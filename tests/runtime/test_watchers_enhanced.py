"""Enhanced tests for SelectionWatcher covering uncovered branches."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from oneiric.core.config import LayerSettings, OneiricSettings
from oneiric.core.lifecycle import LifecycleManager
from oneiric.core.resolution import Resolver
from oneiric.domains.base import DomainBridge
from oneiric.runtime.activity import DomainActivity
from oneiric.runtime.watchers import SelectionWatcher


class MockBridge(DomainBridge):
    def __init__(self, resolver, lifecycle, activity_store=None):
        super().__init__(
            domain="test",
            resolver=resolver,
            lifecycle=lifecycle,
            settings={},
            activity_store=activity_store,
        )
        self.update_settings_calls = []
        self.swap_calls = []

    def update_settings(self, layer):
        self.update_settings_calls.append(layer)

    async def use(self, key: str):
        return MagicMock()


def mock_settings_loader() -> OneiricSettings:
    return OneiricSettings()


class TestSelectionWatcherInitStrategy:
    def test_serverless_mode_forces_poll(self):
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = MockBridge(resolver, lifecycle)

        watcher = SelectionWatcher(
            name="test",
            bridge=bridge,
            layer_selector=lambda s: LayerSettings(selections={}),
            settings_loader=mock_settings_loader,
            serverless_mode=True,
            use_watchfiles=True,
        )
        assert watcher._strategy == "poll"

    def test_env_serverless_forces_poll(self):
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = MockBridge(resolver, lifecycle)

        with patch.dict(os.environ, {"ONEIRIC_SERVERLESS": "1"}):
            watcher = SelectionWatcher(
                name="test",
                bridge=bridge,
                layer_selector=lambda s: LayerSettings(selections={}),
                settings_loader=mock_settings_loader,
                serverless_mode=None,
            )
        assert watcher._strategy == "poll"

    def test_use_watchfiles_false_forces_poll(self):
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = MockBridge(resolver, lifecycle)

        watcher = SelectionWatcher(
            name="test",
            bridge=bridge,
            layer_selector=lambda s: LayerSettings(selections={}),
            settings_loader=mock_settings_loader,
            use_watchfiles=False,
        )
        assert watcher._strategy == "poll"

    def test_serverless_overrides_use_watchfiles(self):
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = MockBridge(resolver, lifecycle)

        watcher = SelectionWatcher(
            name="test",
            bridge=bridge,
            layer_selector=lambda s: LayerSettings(selections={}),
            settings_loader=mock_settings_loader,
            serverless_mode=False,
            use_watchfiles=True,
        )
        # watchfiles lib IS available, use_watchfiles=True, no serverless
        # but no watch_path -> still poll
        assert watcher._strategy == "poll"


class TestSelectionWatcherResolveWatchPath:
    def test_explicit_path_exists(self, tmp_path):
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = MockBridge(resolver, lifecycle)

        watcher = SelectionWatcher(
            name="test",
            bridge=bridge,
            layer_selector=lambda s: LayerSettings(selections={}),
            settings_loader=mock_settings_loader,
            watch_path=str(tmp_path),
        )
        assert watcher._watch_path == tmp_path

    def test_env_oneiric_config(self, tmp_path):
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = MockBridge(resolver, lifecycle)
        cfg_file = tmp_path / "oneiric.yaml"
        cfg_file.touch()

        with patch.dict(os.environ, {"ONEIRIC_CONFIG": str(cfg_file)}):
            watcher = SelectionWatcher(
                name="test",
                bridge=bridge,
                layer_selector=lambda s: LayerSettings(selections={}),
                settings_loader=mock_settings_loader,
            )
        assert watcher._watch_path == cfg_file

    def test_parent_fallback(self, tmp_path):
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = MockBridge(resolver, lifecycle)

        with patch.dict(os.environ, {"ONEIRIC_CONFIG": str(tmp_path / "nonexistent.yaml")}):
            watcher = SelectionWatcher(
                name="test",
                bridge=bridge,
                layer_selector=lambda s: LayerSettings(selections={}),
                settings_loader=mock_settings_loader,
            )
        assert watcher._watch_path == tmp_path

    def test_no_path_returns_none(self):
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = MockBridge(resolver, lifecycle)

        with patch.dict(os.environ, {}, clear=True):
            watcher = SelectionWatcher(
                name="test",
                bridge=bridge,
                layer_selector=lambda s: LayerSettings(selections={}),
                settings_loader=mock_settings_loader,
            )
        assert watcher._watch_path is None


class TestSelectionWatcherTick:
    @pytest.mark.asyncio
    async def test_added_key_triggers_swap(self):
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = MockBridge(resolver, lifecycle)
        bridge.lifecycle.swap = AsyncMock()

        call_count = 0
        def layer_selector(settings):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return LayerSettings(selections={})
            return LayerSettings(selections={"cache": "redis"})

        watcher = SelectionWatcher(
            name="test",
            bridge=bridge,
            layer_selector=layer_selector,
            settings_loader=mock_settings_loader,
        )
        # Init reads empty selections
        assert watcher._last == {}

        await watcher.run_once()
        bridge.lifecycle.swap.assert_called_once()

    @pytest.mark.asyncio
    async def test_removed_key_triggers_swap_with_none(self):
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = MockBridge(resolver, lifecycle)
        bridge.lifecycle.swap = AsyncMock()

        call_count = 0
        def layer_selector(settings):
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return LayerSettings(selections={"cache": "redis"})
            return LayerSettings(selections={})

        watcher = SelectionWatcher(
            name="test",
            bridge=bridge,
            layer_selector=layer_selector,
            settings_loader=mock_settings_loader,
        )
        await watcher.run_once()
        bridge.lifecycle.swap.assert_called_once()
        call_args = bridge.lifecycle.swap.call_args
        assert call_args[0][0] == "test"  # domain
        assert call_args[0][1] == "cache"  # key
        assert call_args[1]["provider"] is None

    @pytest.mark.asyncio
    async def test_no_change_no_swap(self):
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = MockBridge(resolver, lifecycle)
        bridge.lifecycle.swap = AsyncMock()

        watcher = SelectionWatcher(
            name="test",
            bridge=bridge,
            layer_selector=lambda s: LayerSettings(selections={"cache": "redis"}),
            settings_loader=mock_settings_loader,
        )
        await watcher.run_once()
        bridge.lifecycle.swap.assert_not_called()

    @pytest.mark.asyncio
    async def test_swap_error_is_caught(self):
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = MockBridge(resolver, lifecycle)
        bridge.lifecycle.swap = AsyncMock(side_effect=RuntimeError("swap fail"))

        call_count = 0
        def layer_selector(settings):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return LayerSettings(selections={})
            return LayerSettings(selections={"cache": "redis"})

        watcher = SelectionWatcher(
            name="test",
            bridge=bridge,
            layer_selector=layer_selector,
            settings_loader=mock_settings_loader,
        )
        # Should not raise
        await watcher.run_once()


class TestSelectionWatcherDrainingAllowsRemoval:
    @pytest.mark.asyncio
    async def test_draining_allows_removal(self, tmp_path):
        """Provider=None (removal) is allowed even when draining."""
        from oneiric.runtime.activity import DomainActivityStore

        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        activity_store = DomainActivityStore(str(tmp_path / "activity.sqlite"))
        bridge = MockBridge(resolver, lifecycle, activity_store=activity_store)
        bridge._activity_store.set("test", "cache", DomainActivity(draining=True))
        bridge.lifecycle.swap = AsyncMock()

        call_count = 0
        def layer_selector(settings):
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return LayerSettings(selections={"cache": "redis"})
            return LayerSettings(selections={})

        watcher = SelectionWatcher(
            name="test",
            bridge=bridge,
            layer_selector=layer_selector,
            settings_loader=mock_settings_loader,
        )

        await watcher.run_once()
        # Removal (provider=None) should still proceed
        bridge.lifecycle.swap.assert_called_once()


class TestSelectionWatcherDomain:
    @pytest.mark.asyncio
    async def test_uses_bridge_domain(self):
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = MockBridge(resolver, lifecycle)
        bridge.lifecycle.swap = AsyncMock()

        call_count = 0
        def layer_selector(settings):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return LayerSettings(selections={})
            return LayerSettings(selections={"key": "val"})

        watcher = SelectionWatcher(
            name="mywatcher",
            bridge=bridge,
            layer_selector=layer_selector,
            settings_loader=mock_settings_loader,
        )
        await watcher.run_once()
        call_args = bridge.lifecycle.swap.call_args
        assert call_args[0][0] == "test"  # bridge.domain


class TestSelectionWatcherRunEventLoopFallback:
    @pytest.mark.asyncio
    async def test_event_loop_falls_back_to_poll(self):
        """If watchfiles not available or no path, event loop falls back to poll."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = MockBridge(resolver, lifecycle)

        watcher = SelectionWatcher(
            name="test",
            bridge=bridge,
            layer_selector=lambda s: LayerSettings(selections={}),
            settings_loader=mock_settings_loader,
        )
        assert watcher._strategy == "poll"

        # Start briefly and stop to test _run_poll_loop
        await watcher.start()
        await asyncio.sleep(0.05)
        await watcher.stop()
