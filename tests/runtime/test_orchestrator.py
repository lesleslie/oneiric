"""Tests for RuntimeOrchestrator."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from oneiric.core.config import (
    OneiricSettings,
    RemoteSourceConfig,
    RuntimeProfileConfig,
    RuntimeSupervisorConfig,
)
from oneiric.core.lifecycle import LifecycleManager, LifecycleStatus
from oneiric.core.resolution import Resolver
from oneiric.runtime.activity import DomainActivity
from oneiric.runtime.orchestrator import RuntimeOrchestrator

# Test helpers


class MockSecrets:
    """Mock secrets manager."""

    async def get_secret(self, key: str) -> str:
        return f"mock-secret-{key}"


# RuntimeOrchestrator Tests


class TestRuntimeOrchestratorInit:
    """Test RuntimeOrchestrator initialization."""

    def test_init_creates_five_bridges(self, tmp_path):
        """RuntimeOrchestrator creates 5 domain bridges."""
        settings = OneiricSettings(
            config_dir=str(tmp_path / "settings"),
            cache_dir=str(tmp_path / "cache"),
        )
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        secrets = MockSecrets()

        orchestrator = RuntimeOrchestrator(settings, resolver, lifecycle, secrets)

        assert orchestrator.adapter_bridge is not None
        assert orchestrator.service_bridge is not None
        assert orchestrator.task_bridge is not None
        assert orchestrator.event_bridge is not None
        assert orchestrator.workflow_bridge is not None

    def test_init_creates_shared_activity_store(self, tmp_path):
        """RuntimeOrchestrator creates shared activity store."""
        settings = OneiricSettings(
            config_dir=str(tmp_path / "settings"),
            cache_dir=str(tmp_path / "cache"),
        )
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        secrets = MockSecrets()

        orchestrator = RuntimeOrchestrator(settings, resolver, lifecycle, secrets)

        # All bridges share same activity store (via private _activity_store)
        assert (
            orchestrator.adapter_bridge._activity_store is orchestrator._activity_store
        )
        assert (
            orchestrator.service_bridge._activity_store is orchestrator._activity_store
        )
        assert orchestrator.task_bridge._activity_store is orchestrator._activity_store
        assert orchestrator.event_bridge._activity_store is orchestrator._activity_store
        assert (
            orchestrator.workflow_bridge._activity_store is orchestrator._activity_store
        )

    def test_init_creates_five_watchers(self, tmp_path):
        """RuntimeOrchestrator creates 5 selection watchers."""
        settings = OneiricSettings(
            config_dir=str(tmp_path / "settings"),
            cache_dir=str(tmp_path / "cache"),
        )
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        secrets = MockSecrets()

        orchestrator = RuntimeOrchestrator(settings, resolver, lifecycle, secrets)

        assert len(orchestrator._watchers) == 5
        watcher_names = {w.name for w in orchestrator._watchers}
        assert watcher_names == {"adapter", "service", "task", "event", "workflow"}

    def test_init_custom_health_path(self, tmp_path):
        """RuntimeOrchestrator accepts custom health path."""
        settings = OneiricSettings(
            config_dir=str(tmp_path / "settings"),
            cache_dir=str(tmp_path / "cache"),
        )
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        secrets = MockSecrets()
        health_path = tmp_path / "custom_health.json"

        orchestrator = RuntimeOrchestrator(
            settings, resolver, lifecycle, secrets, health_path=str(health_path)
        )

        assert orchestrator._health_path == str(health_path)

    def test_workflow_bridge_uses_adapter_queue_bridge(self, tmp_path):
        """WorkflowBridge reuses AdapterBridge for queue operations."""
        settings = OneiricSettings(
            config_dir=str(tmp_path / "settings"),
            cache_dir=str(tmp_path / "cache"),
        )
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        secrets = MockSecrets()

        orchestrator = RuntimeOrchestrator(settings, resolver, lifecycle, secrets)

        assert orchestrator.workflow_bridge._queue_bridge is orchestrator.adapter_bridge

    def test_supervisor_disabled_via_profile(self, tmp_path):
        """Profile toggle can disable the supervisor entirely."""

        settings = OneiricSettings(
            remote=RemoteSourceConfig(cache_dir=str(tmp_path / "cache")),
            profile=RuntimeProfileConfig(
                name="default",
                watchers_enabled=True,
                remote_enabled=True,
                supervisor_enabled=False,
            ),
        )
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        secrets = MockSecrets()

        orchestrator = RuntimeOrchestrator(settings, resolver, lifecycle, secrets)

        assert orchestrator._supervisor is None
        assert orchestrator._supervisor_enabled is False
        assert all(
            getattr(bridge, "_supervisor", None) is None
            for bridge in orchestrator.bridges.values()
        )

    def test_supervisor_disabled_via_runtime_config(self, tmp_path):
        """RuntimeSupervisorConfig overrides the profile toggle."""

        settings = OneiricSettings(
            remote=RemoteSourceConfig(cache_dir=str(tmp_path / "cache")),
            profile=RuntimeProfileConfig(
                name="default",
                watchers_enabled=True,
                remote_enabled=True,
                supervisor_enabled=True,
            ),
            runtime_supervisor=RuntimeSupervisorConfig(
                enabled=False, poll_interval=1.0
            ),
        )
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        secrets = MockSecrets()

        orchestrator = RuntimeOrchestrator(settings, resolver, lifecycle, secrets)

        assert orchestrator._supervisor is None
        assert orchestrator._supervisor_enabled is False


class TestRuntimeOrchestratorStartStop:
    """Test RuntimeOrchestrator start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_without_remote(self, tmp_path):
        """RuntimeOrchestrator.start() works without remote manifest."""
        settings = OneiricSettings(
            config_dir=str(tmp_path / "settings"),
            cache_dir=str(tmp_path / "cache"),
        )
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        secrets = MockSecrets()

        orchestrator = RuntimeOrchestrator(settings, resolver, lifecycle, secrets)

        # Mock watcher start
        for watcher in orchestrator._watchers:
            watcher.start = AsyncMock()

        await orchestrator.start(enable_remote=False)

        # All watchers started
        for watcher in orchestrator._watchers:
            watcher.start.assert_called_once()

        # No remote sync task
        assert orchestrator._remote_task is None

        await orchestrator.stop()

    @pytest.mark.asyncio
    async def test_start_with_manifest_url(self, tmp_path):
        """RuntimeOrchestrator.start() syncs remote manifest."""
        settings = OneiricSettings(
            config_dir=str(tmp_path / "settings"),
            cache_dir=str(tmp_path / "cache"),
        )
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        secrets = MockSecrets()

        orchestrator = RuntimeOrchestrator(settings, resolver, lifecycle, secrets)

        # Mock watcher start
        for watcher in orchestrator._watchers:
            watcher.start = AsyncMock()

        # Mock sync_remote
        orchestrator.sync_remote = AsyncMock()

        manifest_url = "https://example.com/manifest.yaml"
        await orchestrator.start(manifest_url=manifest_url, enable_remote=True)

        # Initial sync called
        orchestrator.sync_remote.assert_called_once_with(manifest_url=manifest_url)

        await orchestrator.stop()

    @pytest.mark.asyncio
    async def test_start_with_refresh_interval(self, tmp_path):
        """RuntimeOrchestrator.start() starts remote sync loop."""
        settings = OneiricSettings(
            config_dir=str(tmp_path / "settings"),
            cache_dir=str(tmp_path / "cache"),
        )
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        secrets = MockSecrets()

        orchestrator = RuntimeOrchestrator(settings, resolver, lifecycle, secrets)

        # Mock watcher start
        for watcher in orchestrator._watchers:
            watcher.start = AsyncMock()

        # Mock sync_remote
        orchestrator.sync_remote = AsyncMock()

        manifest_url = "https://example.com/manifest.yaml"
        await orchestrator.start(
            manifest_url=manifest_url,
            refresh_interval_override=1.0,  # 1 second for test
            enable_remote=True,
        )

        # Remote sync task created
        assert orchestrator._remote_task is not None
        assert not orchestrator._remote_task.done()

        await orchestrator.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_watchers(self, tmp_path):
        """RuntimeOrchestrator.stop() cancels all watchers."""
        settings = OneiricSettings(
            config_dir=str(tmp_path / "settings"),
            cache_dir=str(tmp_path / "cache"),
        )
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        secrets = MockSecrets()

        orchestrator = RuntimeOrchestrator(settings, resolver, lifecycle, secrets)

        # Mock watcher start/stop
        for watcher in orchestrator._watchers:
            watcher.start = AsyncMock()
            watcher.stop = AsyncMock()

        await orchestrator.start(enable_remote=False)
        await orchestrator.stop()

        # All watchers stopped
        for watcher in orchestrator._watchers:
            watcher.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_cancels_remote_sync_task(self, tmp_path):
        """RuntimeOrchestrator.stop() cancels remote sync task."""
        settings = OneiricSettings(
            config_dir=str(tmp_path / "settings"),
            cache_dir=str(tmp_path / "cache"),
        )
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        secrets = MockSecrets()

        orchestrator = RuntimeOrchestrator(settings, resolver, lifecycle, secrets)

        # Mock watcher start/stop
        for watcher in orchestrator._watchers:
            watcher.start = AsyncMock()
            watcher.stop = AsyncMock()

        # Mock sync_remote
        orchestrator.sync_remote = AsyncMock()

        manifest_url = "https://example.com/manifest.yaml"
        await orchestrator.start(
            manifest_url=manifest_url,
            refresh_interval_override=1.0,
            enable_remote=True,
        )

        assert orchestrator._remote_task is not None

        await orchestrator.stop()

        # Remote sync task cancelled (check if None after stop or if still exists and is cancelled)
        assert (
            orchestrator._remote_task is None or orchestrator._remote_task.cancelled()
        )


class TestRuntimeOrchestratorContext:
    """Test RuntimeOrchestrator async context manager."""

    @pytest.mark.asyncio
    async def test_context_manager_starts_and_stops(self, tmp_path):
        """RuntimeOrchestrator works as async context manager."""
        settings = OneiricSettings(
            config_dir=str(tmp_path / "settings"),
            cache_dir=str(tmp_path / "cache"),
        )
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        secrets = MockSecrets()

        orchestrator = RuntimeOrchestrator(settings, resolver, lifecycle, secrets)

        # Mock watcher start/stop
        for watcher in orchestrator._watchers:
            watcher.start = AsyncMock()
            watcher.stop = AsyncMock()

        async with orchestrator:
            # Watchers started
            for watcher in orchestrator._watchers:
                watcher.start.assert_called_once()

        # Watchers stopped
        for watcher in orchestrator._watchers:
            watcher.stop.assert_called_once()


class TestRuntimeOrchestratorSyncRemote:
    """Test RuntimeOrchestrator.sync_remote() method."""

    @pytest.mark.asyncio
    async def test_sync_remote_calls_loader(self, tmp_path):
        """sync_remote() calls sync_remote_manifest."""
        settings = OneiricSettings(
            config_dir=str(tmp_path / "settings"),
            cache_dir=str(tmp_path / "cache"),
        )
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        secrets = MockSecrets()

        orchestrator = RuntimeOrchestrator(settings, resolver, lifecycle, secrets)

        manifest_url = "https://example.com/manifest.yaml"

        # Mock sync_remote_manifest
        with patch("oneiric.runtime.orchestrator.sync_remote_manifest") as mock_sync:
            mock_sync.return_value = None

            await orchestrator.sync_remote(manifest_url)

            mock_sync.assert_called_once()
            call_args = mock_sync.call_args
            assert call_args[0][0] is resolver  # First positional arg

    @pytest.mark.asyncio
    async def test_sync_remote_updates_health_on_success(self, tmp_path):
        """sync_remote() updates health snapshot on success."""
        settings = OneiricSettings(
            config_dir=str(tmp_path / "settings"),
            cache_dir=str(tmp_path / "cache"),
        )
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        secrets = MockSecrets()
        health_path = tmp_path / "health.json"

        orchestrator = RuntimeOrchestrator(
            settings, resolver, lifecycle, secrets, health_path=str(health_path)
        )

        manifest_url = "https://example.com/manifest.yaml"

        # Mock sync_remote_manifest
        from oneiric.remote.loader import RemoteSyncResult
        from oneiric.remote.models import RemoteManifest

        mock_result = RemoteSyncResult(
            manifest=RemoteManifest(source="test"),
            registered=5,
            duration_ms=100.0,  # Required field
            per_domain={"adapter": 3, "service": 2},
            skipped=0,
        )

        with patch(
            "oneiric.runtime.orchestrator.sync_remote_manifest",
            return_value=mock_result,
        ):
            await orchestrator.sync_remote(manifest_url)

        # Health snapshot updated
        assert health_path.exists()
        health_data = json.loads(health_path.read_text())
        assert health_data["last_remote_sync_at"] is not None
        assert health_data["last_remote_registered"] == 5
        assert health_data["last_remote_per_domain"] == {"adapter": 3, "service": 2}
        assert health_data["last_remote_skipped"] == 0

    @pytest.mark.asyncio
    async def test_sync_remote_updates_health_on_error(self, tmp_path):
        """sync_remote() updates health snapshot on error."""
        settings = OneiricSettings(
            config_dir=str(tmp_path / "settings"),
            cache_dir=str(tmp_path / "cache"),
        )
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        secrets = MockSecrets()
        health_path = tmp_path / "health.json"

        orchestrator = RuntimeOrchestrator(
            settings, resolver, lifecycle, secrets, health_path=str(health_path)
        )

        manifest_url = "https://example.com/manifest.yaml"

        # Mock sync_remote_manifest to raise error
        with patch(
            "oneiric.runtime.orchestrator.sync_remote_manifest",
            side_effect=ValueError("Test error"),
        ):
            try:
                await orchestrator.sync_remote(manifest_url)
            except ValueError:
                pass  # Expected

        # Health snapshot updated with error
        assert health_path.exists()
        health_data = json.loads(health_path.read_text())
        assert health_data["last_remote_error"] is not None
        assert "Test error" in health_data["last_remote_error"]


class TestRuntimeOrchestratorHealthSnapshot:
    """Test RuntimeOrchestrator health snapshot updates."""

    @pytest.mark.asyncio
    async def test_health_snapshot_created_on_start(self, tmp_path):
        """Health snapshot created when orchestrator starts."""
        settings = OneiricSettings(
            config_dir=str(tmp_path / "settings"),
            cache_dir=str(tmp_path / "cache"),
        )
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        secrets = MockSecrets()
        health_path = tmp_path / "health.json"

        orchestrator = RuntimeOrchestrator(
            settings, resolver, lifecycle, secrets, health_path=str(health_path)
        )

        # Mock watcher start
        for watcher in orchestrator._watchers:
            watcher.start = AsyncMock()

        await orchestrator.start(enable_remote=False)

        # Health snapshot exists
        assert health_path.exists()
        health_data = json.loads(health_path.read_text())
        assert health_data["watchers_running"] is True
        assert health_data["remote_enabled"] is False

        await orchestrator.stop()

    @pytest.mark.asyncio
    async def test_health_snapshot_updated_on_stop(self, tmp_path):
        """Health snapshot updated when orchestrator stops."""
        settings = OneiricSettings(
            config_dir=str(tmp_path / "settings"),
            cache_dir=str(tmp_path / "cache"),
        )
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        secrets = MockSecrets()
        health_path = tmp_path / "health.json"

        orchestrator = RuntimeOrchestrator(
            settings, resolver, lifecycle, secrets, health_path=str(health_path)
        )

        # Mock watcher start/stop
        for watcher in orchestrator._watchers:
            watcher.start = AsyncMock()
            watcher.stop = AsyncMock()

        await orchestrator.start(enable_remote=False)
        await orchestrator.stop()

        # Health snapshot shows stopped
        health_data = json.loads(health_path.read_text())
        assert health_data["watchers_running"] is False

    @pytest.mark.asyncio
    async def test_health_snapshot_includes_lifecycle_state(self, tmp_path):
        """Health snapshot records lifecycle status entries."""
        settings = OneiricSettings(
            config_dir=str(tmp_path / "settings"),
            cache_dir=str(tmp_path / "cache"),
        )
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        secrets = MockSecrets()
        health_path = tmp_path / "health.json"

        status = LifecycleStatus(domain="adapter", key="cache", state="ready")
        lifecycle._status[(status.domain, status.key)] = status  # type: ignore[attr-defined]

        orchestrator = RuntimeOrchestrator(
            settings, resolver, lifecycle, secrets, health_path=str(health_path)
        )

        for watcher in orchestrator._watchers:
            watcher.start = AsyncMock()
            watcher.stop = AsyncMock()

        await orchestrator.start(enable_remote=False)
        await orchestrator.stop()

        health_data = json.loads(health_path.read_text())
        lifecycle_state = health_data.get("lifecycle_state") or {}
        assert lifecycle_state["adapter"]["cache"]["state"] == "ready"

    def test_health_snapshot_includes_activity_state(self, tmp_path):
        """Health snapshot records supervisor activity entries."""

        settings = OneiricSettings(
            remote=RemoteSourceConfig(cache_dir=str(tmp_path / "cache"))
        )
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        secrets = MockSecrets()
        health_path = tmp_path / "health.json"

        orchestrator = RuntimeOrchestrator(
            settings, resolver, lifecycle, secrets, health_path=str(health_path)
        )

        orchestrator._activity_store.set(
            "service", "api", DomainActivity(paused=True, note="maint")
        )
        if orchestrator._supervisor:
            orchestrator._supervisor.refresh()

        orchestrator._update_health(watchers_running=True, remote_enabled=False)

        health_data = json.loads(health_path.read_text())
        activity_state = health_data.get("activity_state") or {}
        assert activity_state["service"]["api"]["paused"] is True
        assert activity_state["service"]["api"]["note"] == "maint"
