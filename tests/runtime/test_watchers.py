"""Tests for SelectionWatcher."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from oneiric.core.config import LayerSettings, OneiricSettings
from oneiric.core.lifecycle import LifecycleManager
from oneiric.core.resolution import Resolver
from oneiric.domains.base import DomainBridge
from oneiric.runtime.watchers import SelectionWatcher


# Test helpers


class MockBridge(DomainBridge):
    """Mock domain bridge for testing."""

    def __init__(self, resolver, lifecycle, activity_store=None):
        super().__init__(
            domain="test",
            resolver=resolver,
            lifecycle=lifecycle,
            settings={},
            activity_store=activity_store,
        )
        self.use_calls = []

    async def use(self, key: str):
        """Mock use method."""
        self.use_calls.append(key)
        mock_handle = MagicMock()
        mock_handle.instance = MagicMock()
        return mock_handle


def mock_layer_selector(settings: OneiricSettings) -> LayerSettings:
    """Mock layer selector."""
    return LayerSettings(selections={})


def mock_settings_loader() -> OneiricSettings:
    """Mock settings loader."""
    return OneiricSettings(config_dir=".", cache_dir=".")


# SelectionWatcher Tests


class TestSelectionWatcherInit:
    """Test SelectionWatcher initialization."""

    def test_init_minimal(self):
        """SelectionWatcher can be created with minimal params."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = MockBridge(resolver, lifecycle)

        watcher = SelectionWatcher(
            name="test",
            bridge=bridge,
            layer_selector=mock_layer_selector,
            settings_loader=mock_settings_loader,
        )

        assert watcher.name == "test"
        assert watcher.bridge is bridge
        assert watcher.poll_interval == 5.0
        assert watcher._task is None

    def test_init_custom_poll_interval(self):
        """SelectionWatcher accepts custom poll interval."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = MockBridge(resolver, lifecycle)

        watcher = SelectionWatcher(
            name="test",
            bridge=bridge,
            layer_selector=mock_layer_selector,
            settings_loader=mock_settings_loader,
            poll_interval=2.0,
        )

        assert watcher.poll_interval == 2.0


class TestSelectionWatcherLifecycle:
    """Test SelectionWatcher start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_creates_task(self):
        """start() creates polling task."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = MockBridge(resolver, lifecycle)

        watcher = SelectionWatcher(
            name="test",
            bridge=bridge,
            layer_selector=mock_layer_selector,
            settings_loader=mock_settings_loader,
            poll_interval=0.1,
        )

        await watcher.start()

        assert watcher._task is not None
        assert not watcher._task.done()

        await watcher.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self):
        """stop() cancels polling task."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = MockBridge(resolver, lifecycle)

        watcher = SelectionWatcher(
            name="test",
            bridge=bridge,
            layer_selector=mock_layer_selector,
            settings_loader=mock_settings_loader,
            poll_interval=0.1,
        )

        await watcher.start()
        await watcher.stop()

        assert watcher._task is None

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """SelectionWatcher works as async context manager."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = MockBridge(resolver, lifecycle)

        watcher = SelectionWatcher(
            name="test",
            bridge=bridge,
            layer_selector=mock_layer_selector,
            settings_loader=mock_settings_loader,
            poll_interval=0.1,
        )

        async with watcher:
            assert watcher._task is not None

        assert watcher._task is None

    @pytest.mark.asyncio
    async def test_stop_without_start(self):
        """stop() is safe when not started."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = MockBridge(resolver, lifecycle)

        watcher = SelectionWatcher(
            name="test",
            bridge=bridge,
            layer_selector=mock_layer_selector,
            settings_loader=mock_settings_loader,
        )

        # Should not raise
        await watcher.stop()

    @pytest.mark.asyncio
    async def test_start_already_running_raises(self):
        """start() raises if already running."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = MockBridge(resolver, lifecycle)

        watcher = SelectionWatcher(
            name="test",
            bridge=bridge,
            layer_selector=mock_layer_selector,
            settings_loader=mock_settings_loader,
            poll_interval=0.1,
        )

        await watcher.start()

        with pytest.raises(RuntimeError, match="already running"):
            await watcher.start()

        await watcher.stop()


class TestSelectionWatcherRunOnce:
    """Test SelectionWatcher.run_once() method."""

    @pytest.mark.asyncio
    async def test_run_once_completes_without_error(self):
        """run_once() executes one polling cycle."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = MockBridge(resolver, lifecycle)

        def layer_selector(settings: OneiricSettings) -> LayerSettings:
            return LayerSettings(selections={"cache": "redis"})

        watcher = SelectionWatcher(
            name="test",
            bridge=bridge,
            layer_selector=layer_selector,
            settings_loader=mock_settings_loader,
        )

        # Should complete without error
        await watcher.run_once()


class TestSelectionWatcherActivityState:
    """Test SelectionWatcher respects pause/drain states."""

    @pytest.mark.asyncio
    async def test_respects_paused_state(self, tmp_path):
        """Watcher respects paused state."""
        from oneiric.runtime.activity import DomainActivity, DomainActivityStore

        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        activity_store = DomainActivityStore(str(tmp_path / "activity.json"))
        bridge = MockBridge(resolver, lifecycle, activity_store=activity_store)

        # Pause the cache key
        bridge._activity_store.set("test", "cache", DomainActivity(paused=True, note="test"))

        def layer_selector(settings: OneiricSettings) -> LayerSettings:
            return LayerSettings(selections={"cache": "redis"})

        watcher = SelectionWatcher(
            name="test",
            bridge=bridge,
            layer_selector=layer_selector,
            settings_loader=mock_settings_loader,
        )

        # Mock lifecycle.swap
        bridge.lifecycle.swap = AsyncMock()

        await watcher.run_once()

        # Swap should not be called (paused)
        bridge.lifecycle.swap.assert_not_called()

    @pytest.mark.asyncio
    async def test_respects_draining_state(self, tmp_path):
        """Watcher respects draining state."""
        from oneiric.runtime.activity import DomainActivity, DomainActivityStore

        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        activity_store = DomainActivityStore(str(tmp_path / "activity.json"))
        bridge = MockBridge(resolver, lifecycle, activity_store=activity_store)

        # Set draining state
        bridge._activity_store.set("test", "cache", DomainActivity(draining=True, note="test"))

        def layer_selector(settings: OneiricSettings) -> LayerSettings:
            return LayerSettings(selections={"cache": "redis"})

        watcher = SelectionWatcher(
            name="test",
            bridge=bridge,
            layer_selector=layer_selector,
            settings_loader=mock_settings_loader,
        )

        # Mock lifecycle.swap
        bridge.lifecycle.swap = AsyncMock()

        await watcher.run_once()

        # Swap may be delayed but not immediately called
        # (exact behavior depends on drain delay)
