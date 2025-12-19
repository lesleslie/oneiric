"""Runtime orchestrator wiring bridges, watchers, and remote sync."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from oneiric import plugins
from oneiric.adapters import AdapterBridge
from oneiric.adapters.watcher import AdapterConfigWatcher
from oneiric.core.config import (
    OneiricSettings,
    SecretsHook,
    domain_activity_path,
    runtime_observability_path,
)
from oneiric.core.config import (
    workflow_checkpoint_path as resolve_workflow_checkpoint_path,
)
from oneiric.core.lifecycle import LifecycleManager
from oneiric.core.logging import get_logger
from oneiric.core.resolution import Resolver
from oneiric.domains import (
    DomainBridge,
    EventBridge,
    EventConfigWatcher,
    ServiceBridge,
    ServiceConfigWatcher,
    TaskBridge,
    TaskConfigWatcher,
    WorkflowBridge,
    WorkflowConfigWatcher,
)
from oneiric.remote import sync_remote_manifest
from oneiric.runtime.activity import DomainActivityStore
from oneiric.runtime.checkpoints import WorkflowCheckpointStore
from oneiric.runtime.durable import WorkflowExecutionStore
from oneiric.runtime.health import RuntimeHealthSnapshot, write_runtime_health
from oneiric.runtime.supervisor import ServiceSupervisor
from oneiric.runtime.telemetry import RuntimeTelemetryRecorder

logger = get_logger("runtime.orchestrator")


class RuntimeOrchestrator:
    """Manages domain bridges, selection watchers, and remote sync loops."""

    def __init__(
        self,
        settings: OneiricSettings,
        resolver: Resolver,
        lifecycle: LifecycleManager,
        secrets: SecretsHook,
        *,
        health_path: str | None = None,
        workflow_checkpoint_path: str | None = None,
        enable_workflow_checkpoints: bool | None = None,
    ) -> None:
        self.settings = settings
        self.resolver = resolver
        self.lifecycle = lifecycle
        self.secrets = secrets
        plugins.register_entrypoint_plugins(resolver, settings.plugins)
        self._health_path = health_path
        self._health = RuntimeHealthSnapshot()
        self._activity_store = DomainActivityStore(domain_activity_path(settings))
        self._telemetry = RuntimeTelemetryRecorder(runtime_observability_path(settings))
        supervisor_cfg = getattr(settings, "runtime_supervisor", None)
        self._supervisor_enabled = bool(
            getattr(settings.profile, "supervisor_enabled", True)
            and (getattr(supervisor_cfg, "enabled", True))
        )
        poll_interval = (
            getattr(supervisor_cfg, "poll_interval", 2.0) if supervisor_cfg else 2.0
        )
        self._supervisor = (
            ServiceSupervisor(self._activity_store, poll_interval=poll_interval)
            if self._supervisor_enabled
            else None
        )
        resolved_checkpoint_path = (
            Path(workflow_checkpoint_path)
            if workflow_checkpoint_path
            else resolve_workflow_checkpoint_path(settings)
        )
        checkpoints_enabled = (
            settings.runtime_paths.workflow_checkpoints_enabled
            if enable_workflow_checkpoints is None
            else enable_workflow_checkpoints
        )
        self._checkpoint_store = (
            WorkflowCheckpointStore(resolved_checkpoint_path)
            if checkpoints_enabled and resolved_checkpoint_path
            else None
        )
        self._execution_store = (
            WorkflowExecutionStore(resolved_checkpoint_path)
            if checkpoints_enabled and resolved_checkpoint_path
            else None
        )

        self.adapter_bridge = AdapterBridge(
            resolver,
            lifecycle,
            settings.adapters,
            activity_store=self._activity_store,
            supervisor=self._supervisor,
        )
        self.service_bridge = ServiceBridge(
            resolver,
            lifecycle,
            settings.services,
            activity_store=self._activity_store,
            supervisor=self._supervisor,
        )
        self.task_bridge = TaskBridge(
            resolver,
            lifecycle,
            settings.tasks,
            activity_store=self._activity_store,
            supervisor=self._supervisor,
        )
        self.event_bridge = EventBridge(
            resolver,
            lifecycle,
            settings.events,
            activity_store=self._activity_store,
            supervisor=self._supervisor,
            telemetry=self._telemetry,
        )
        self.workflow_bridge = WorkflowBridge(
            resolver,
            lifecycle,
            settings.workflows,
            activity_store=self._activity_store,
            task_bridge=self.task_bridge,
            checkpoint_store=self._checkpoint_store,
            execution_store=self._execution_store,
            queue_bridge=self.adapter_bridge,
            supervisor=self._supervisor,
            telemetry=self._telemetry,
        )

        self.bridges: dict[str, DomainBridge | AdapterBridge] = {
            "adapter": self.adapter_bridge,
            "service": self.service_bridge,
            "task": self.task_bridge,
            "event": self.event_bridge,
            "workflow": self.workflow_bridge,
        }

        self._watchers_enabled = getattr(settings.profile, "watchers_enabled", True)
        self._watchers = (
            [
                AdapterConfigWatcher(self.adapter_bridge),
                ServiceConfigWatcher(self.service_bridge),
                TaskConfigWatcher(self.task_bridge),
                EventConfigWatcher(self.event_bridge),
                WorkflowConfigWatcher(self.workflow_bridge),
            ]
            if self._watchers_enabled
            else []
        )
        self._remote_task: asyncio.Task[None] | None = None
        self._secrets_task: asyncio.Task[None] | None = None

    async def sync_remote(self, manifest_url: str | None = None):
        """Run a single remote sync and refresh runtime health metadata."""

        try:
            result = await sync_remote_manifest(
                self.resolver,
                self.settings.remote,
                secrets=self.secrets,
                manifest_url=manifest_url,
            )
        except Exception as exc:
            self._update_health(last_remote_error=str(exc))
            raise
        if result:
            self._update_health(
                last_remote_sync_at=_timestamp(),
                last_remote_error=None,
                last_remote_registered=result.registered,
                last_remote_per_domain=result.per_domain,
                last_remote_skipped=result.skipped,
                last_remote_duration_ms=result.duration_ms,
            )
            self.event_bridge.refresh_dispatcher()
            self.workflow_bridge.refresh_dags()
        return result

    async def start(
        self,
        *,
        manifest_url: str | None = None,
        refresh_interval_override: float | None = None,
        enable_remote: bool = True,
    ) -> None:
        """Start config watchers and (optionally) the remote refresh loop."""

        if self._watchers_enabled:
            for watcher in self._watchers:
                await watcher.start()
        try:
            await self.secrets.prefetch()
        except Exception as exc:  # pragma: no cover - defensive log
            logger.warning("secrets-prefetch-failed", error=str(exc))
        if self._supervisor:
            await self._supervisor.start()
        self._update_health(
            watchers_running=self._watchers_enabled,
            remote_enabled=enable_remote,
            orchestrator_pid=os.getpid(),
        )
        if enable_remote:
            await self.sync_remote(manifest_url=manifest_url)
            interval = (
                refresh_interval_override
                if refresh_interval_override is not None
                else self.settings.remote.refresh_interval
            )
            if interval:
                target_url = manifest_url or self.settings.remote.manifest_url
                self._remote_task = asyncio.create_task(
                    self._remote_loop(target_url, interval),
                    name="remote.sync.loop",
                )
        secrets_interval = self.settings.secrets.refresh_interval
        if secrets_interval:
            self._secrets_task = asyncio.create_task(
                self._secrets_loop(secrets_interval),
                name="secrets.refresh.loop",
            )

    async def stop(self) -> None:
        """Stop config watchers and cancel any running remote loop."""

        if self._watchers_enabled:
            for watcher in self._watchers:
                await watcher.stop()
        if self._supervisor:
            await self._supervisor.stop()
        if self._remote_task:
            self._remote_task.cancel()
            await asyncio.gather(self._remote_task, return_exceptions=True)
            self._remote_task = None
        if self._secrets_task:
            self._secrets_task.cancel()
            await asyncio.gather(self._secrets_task, return_exceptions=True)
            self._secrets_task = None
        self._update_health(watchers_running=False, remote_enabled=False)

    async def _secrets_loop(self, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)
            try:
                await self.secrets.rotate(include_provider_cache=True)
                logger.info("secrets-rotation-complete", interval=interval)
            except Exception as exc:  # pragma: no cover - background loop
                logger.warning("secrets-rotation-failed", error=str(exc))

    async def __aenter__(self) -> RuntimeOrchestrator:
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool | None:
        await self.stop()
        return None

    async def _remote_loop(self, manifest_url: str | None, interval: float) -> None:
        """Background task that periodically refreshes the remote manifest."""

        if not manifest_url:
            logger.info("remote-refresh-skip", reason="no-manifest-url")
            return
        while True:
            await asyncio.sleep(interval)
            try:
                await self.sync_remote(manifest_url=manifest_url)
            except Exception as exc:  # pragma: no cover - logged upstream
                logger.error(
                    "remote-refresh-error",
                    url=manifest_url,
                    error=str(exc),
                )

    def _update_health(
        self,
        *,
        watchers_running: bool | None = None,
        remote_enabled: bool | None = None,
        last_remote_sync_at: str | None = None,
        last_remote_error: str | None = None,
        orchestrator_pid: int | None = None,
        last_remote_registered: int | None = None,
        last_remote_per_domain: dict[str, int] | None = None,
        last_remote_skipped: int | None = None,
        last_remote_duration_ms: float | None = None,
    ) -> None:
        """Persist runtime health snapshot updates to disk."""
        if not self._health_path:
            return

        self._apply_health_updates(
            watchers_running,
            remote_enabled,
            last_remote_sync_at,
            last_remote_error,
            orchestrator_pid,
            last_remote_registered,
            last_remote_per_domain,
            last_remote_skipped,
            last_remote_duration_ms,
        )
        self._update_activity_state()
        self._update_lifecycle_state()
        write_runtime_health(self._health_path, self._health)

    def _apply_health_updates(
        self,
        watchers_running: bool | None,
        remote_enabled: bool | None,
        last_remote_sync_at: str | None,
        last_remote_error: str | None,
        orchestrator_pid: int | None,
        last_remote_registered: int | None,
        last_remote_per_domain: dict[str, int] | None,
        last_remote_skipped: int | None,
        last_remote_duration_ms: float | None,
    ) -> None:
        """Apply individual health field updates."""
        updates = [
            ("watchers_running", watchers_running),
            ("remote_enabled", remote_enabled),
            ("last_remote_sync_at", last_remote_sync_at),
            ("last_remote_error", last_remote_error),
            ("orchestrator_pid", orchestrator_pid),
            ("last_remote_registered", last_remote_registered),
            ("last_remote_per_domain", last_remote_per_domain),
            ("last_remote_skipped", last_remote_skipped),
            ("last_remote_duration_ms", last_remote_duration_ms),
        ]
        for field_name, value in updates:
            if value is not None:
                setattr(self._health, field_name, value)

    def _update_activity_state(self) -> None:
        """Update activity state from activity store."""
        snapshot = None
        if self._supervisor:
            snapshot = self._supervisor.snapshot()
        elif self._activity_store:
            snapshot = self._activity_store.snapshot()
        if snapshot is None:
            return
        self._health.activity_state = {
            domain: {key: state.as_dict() for key, state in entries.items()}
            for domain, entries in snapshot.items()
            if entries
        }

    def _update_lifecycle_state(self) -> None:
        """Record lifecycle manager status entries."""
        statuses = self.lifecycle.all_statuses()
        if not statuses:
            self._health.lifecycle_state = {}
            return
        lifecycle_map: dict[str, dict[str, Any]] = {}
        for status in statuses:
            domain_entries = lifecycle_map.setdefault(status.domain, {})
            domain_entries[status.key] = status.as_dict()
        self._health.lifecycle_state = lifecycle_map


@asynccontextmanager
async def orchestrated_runtime(
    settings: OneiricSettings,
    resolver: Resolver,
    lifecycle: LifecycleManager,
    secrets: SecretsHook,
):
    orchestrator = RuntimeOrchestrator(settings, resolver, lifecycle, secrets)
    async with orchestrator as runtime:
        yield runtime


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()
