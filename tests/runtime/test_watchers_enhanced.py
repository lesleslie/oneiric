"""Enhanced tests for SelectionWatcher covering uncovered branches."""

from __future__ import annotations

import asyncio
import os
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

        with patch.dict(
            os.environ, {"ONEIRIC_CONFIG": str(tmp_path / "nonexistent.yaml")}
        ):
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

    def test_missing_path_and_parent_returns_none(self, tmp_path):
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = MockBridge(resolver, lifecycle)

        watcher = SelectionWatcher(
            name="test",
            bridge=bridge,
            layer_selector=lambda s: LayerSettings(selections={}),
            settings_loader=mock_settings_loader,
            watch_path=tmp_path / "missing" / "oneiric.yaml",
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

    @pytest.mark.asyncio
    async def test_async_context_manager_starts_and_stops(self):
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = MockBridge(resolver, lifecycle)
        watcher = SelectionWatcher(
            name="test",
            bridge=bridge,
            layer_selector=lambda s: LayerSettings(selections={}),
            settings_loader=mock_settings_loader,
        )

        assert watcher._task is None
        async with watcher as active:
            assert active is watcher
            assert watcher._task is not None
        assert watcher._task is None

    @pytest.mark.asyncio
    async def test_start_and_stop_are_idempotent(self):
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = MockBridge(resolver, lifecycle)
        watcher = SelectionWatcher(
            name="test",
            bridge=bridge,
            layer_selector=lambda s: LayerSettings(selections={}),
            settings_loader=mock_settings_loader,
        )

        await watcher.stop()
        await watcher.start()
        with pytest.raises(RuntimeError, match="already running"):
            await watcher.start()
        await watcher.stop()
        await watcher.stop()


class TestSelectionWatcherAdditionalBranches:
    @pytest.mark.asyncio
    async def test_refresh_on_every_tick_updates_without_diff(self):
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = MockBridge(resolver, lifecycle)

        watcher = SelectionWatcher(
            name="test",
            bridge=bridge,
            layer_selector=lambda s: LayerSettings(selections={"cache": "redis"}),
            settings_loader=mock_settings_loader,
            refresh_on_every_tick=True,
        )

        await watcher.run_once()

        assert bridge.update_settings_calls

    @pytest.mark.asyncio
    async def test_paused_swap_is_skipped(self):
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = MockBridge(resolver, lifecycle)
        bridge.lifecycle.swap = AsyncMock()
        bridge.activity_state = lambda key: DomainActivity(paused=True)

        watcher = SelectionWatcher(
            name="test",
            bridge=bridge,
            layer_selector=lambda s: LayerSettings(selections={}),
            settings_loader=mock_settings_loader,
        )

        await watcher._trigger_swap("cache", "redis")

        bridge.lifecycle.swap.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_draining_swap_is_deferred(self):
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = MockBridge(resolver, lifecycle)
        bridge.lifecycle.swap = AsyncMock()
        bridge.activity_state = lambda key: DomainActivity(draining=True)

        watcher = SelectionWatcher(
            name="test",
            bridge=bridge,
            layer_selector=lambda s: LayerSettings(selections={}),
            settings_loader=mock_settings_loader,
        )

        await watcher._trigger_swap("cache", "redis")

        bridge.lifecycle.swap.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_poll_loop_timeout_branch(self):
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = MockBridge(resolver, lifecycle)
        watcher = SelectionWatcher(
            name="test",
            bridge=bridge,
            layer_selector=lambda s: LayerSettings(selections={}),
            settings_loader=mock_settings_loader,
            poll_interval=0.01,
        )

        tick_count = 0

        async def tick_once():
            nonlocal tick_count
            tick_count += 1
            watcher._stop_event.set()

        watcher._tick = tick_once  # type: ignore[assignment]

        with patch("oneiric.runtime.watchers.asyncio.wait_for", side_effect=TimeoutError):
            await watcher._run_poll_loop()

        assert tick_count == 1

    @pytest.mark.asyncio
    async def test_event_loop_branch_runs_awatch(self, tmp_path):
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = MockBridge(resolver, lifecycle)
        watcher = SelectionWatcher(
            name="test",
            bridge=bridge,
            layer_selector=lambda s: LayerSettings(selections={}),
            settings_loader=mock_settings_loader,
            watch_path=str(tmp_path),
            use_watchfiles=True,
        )

        changes_seen: list[str] = []

        async def fake_awatch(path, stop_event=None):
            changes_seen.append(str(path))
            yield ("changed",)

        with (
            patch("oneiric.runtime.watchers.WATCHFILES_AVAILABLE", True),
            patch("oneiric.runtime.watchers.awatch", fake_awatch),
            patch.object(watcher, "_tick", AsyncMock()),
        ):
            await watcher._run_event_loop()

        assert changes_seen == [str(tmp_path)]

    @pytest.mark.asyncio
    async def test_run_dispatches_to_event_loop(self, tmp_path):
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = MockBridge(resolver, lifecycle)
        watcher = SelectionWatcher(
            name="test",
            bridge=bridge,
            layer_selector=lambda s: LayerSettings(selections={}),
            settings_loader=mock_settings_loader,
            watch_path=str(tmp_path),
            use_watchfiles=True,
        )
        watcher._strategy = "events"

        with (
            patch.object(watcher, "_run_event_loop", AsyncMock()) as mock_events,
            patch.object(watcher, "_run_poll_loop", AsyncMock()) as mock_poll,
        ):
            await watcher._run()

        mock_events.assert_awaited_once()
        mock_poll.assert_not_called()

    @pytest.mark.asyncio
    async def test_event_loop_breaks_when_stop_event_set(self, tmp_path):
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = MockBridge(resolver, lifecycle)
        watcher = SelectionWatcher(
            name="test",
            bridge=bridge,
            layer_selector=lambda s: LayerSettings(selections={}),
            settings_loader=mock_settings_loader,
            watch_path=str(tmp_path),
            use_watchfiles=True,
        )

        async def fake_awatch(path, stop_event=None):
            yield ("changed",)
            if stop_event is not None:
                stop_event.set()
            yield ("ignored",)

        with (
            patch("oneiric.runtime.watchers.WATCHFILES_AVAILABLE", True),
            patch("oneiric.runtime.watchers.awatch", fake_awatch),
            patch.object(watcher, "_tick", AsyncMock()),
        ):
            await watcher._run_event_loop()

        assert watcher._stop_event.is_set()

    @pytest.mark.asyncio
    async def test_event_loop_falls_back_when_no_watch_path(self):
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = MockBridge(resolver, lifecycle)
        watcher = SelectionWatcher(
            name="test",
            bridge=bridge,
            layer_selector=lambda s: LayerSettings(selections={}),
            settings_loader=mock_settings_loader,
        )

        with patch.object(watcher, "_run_poll_loop", AsyncMock()) as mock_poll:
            await watcher._run_event_loop()

        mock_poll.assert_awaited_once()
