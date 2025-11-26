"""Runtime orchestrator wiring bridges, watchers, and remote sync."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Dict, Optional

from oneiric.adapters import AdapterBridge
from oneiric.adapters.watcher import AdapterConfigWatcher
from oneiric.core.config import OneiricSettings, SecretsHook, domain_activity_path
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
from oneiric.runtime.health import RuntimeHealthSnapshot, write_runtime_health

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
        health_path: Optional[str] = None,
    ) -> None:
        self.settings = settings
        self.resolver = resolver
        self.lifecycle = lifecycle
        self.secrets = secrets
        self._health_path = health_path
        self._health = RuntimeHealthSnapshot()
        self._activity_store = DomainActivityStore(domain_activity_path(settings))

        self.adapter_bridge = AdapterBridge(
            resolver,
            lifecycle,
            settings.adapters,
            activity_store=self._activity_store,
        )
        self.service_bridge = ServiceBridge(
            resolver,
            lifecycle,
            settings.services,
            activity_store=self._activity_store,
        )
        self.task_bridge = TaskBridge(
            resolver,
            lifecycle,
            settings.tasks,
            activity_store=self._activity_store,
        )
        self.event_bridge = EventBridge(
            resolver,
            lifecycle,
            settings.events,
            activity_store=self._activity_store,
        )
        self.workflow_bridge = WorkflowBridge(
            resolver,
            lifecycle,
            settings.workflows,
            activity_store=self._activity_store,
        )

        self.bridges: Dict[str, DomainBridge | AdapterBridge] = {
            "adapter": self.adapter_bridge,
            "service": self.service_bridge,
            "task": self.task_bridge,
            "event": self.event_bridge,
            "workflow": self.workflow_bridge,
        }

        self._watchers = [
            AdapterConfigWatcher(self.adapter_bridge),
            ServiceConfigWatcher(self.service_bridge),
            TaskConfigWatcher(self.task_bridge),
            EventConfigWatcher(self.event_bridge),
            WorkflowConfigWatcher(self.workflow_bridge),
        ]
        self._remote_task: Optional[asyncio.Task[None]] = None

    async def sync_remote(self, manifest_url: Optional[str] = None):
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
            )
        return result

    async def start(
        self,
        *,
        manifest_url: Optional[str] = None,
        refresh_interval_override: Optional[float] = None,
        enable_remote: bool = True,
    ) -> None:
        for watcher in self._watchers:
            await watcher.start()
        self._update_health(
            watchers_running=True,
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

    async def stop(self) -> None:
        for watcher in self._watchers:
            await watcher.stop()
        if self._remote_task:
            self._remote_task.cancel()
            await asyncio.gather(self._remote_task, return_exceptions=True)
            self._remote_task = None
        self._update_health(watchers_running=False, remote_enabled=False)

    async def __aenter__(self) -> "RuntimeOrchestrator":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> Optional[bool]:
        await self.stop()
        return None


    async def _remote_loop(self, manifest_url: Optional[str], interval: float) -> None:
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
        watchers_running: Optional[bool] = None,
        remote_enabled: Optional[bool] = None,
        last_remote_sync_at: Optional[str] = None,
        last_remote_error: Optional[str] = None,
        orchestrator_pid: Optional[int] = None,
        last_remote_registered: Optional[int] = None,
        last_remote_per_domain: Optional[Dict[str, int]] = None,
        last_remote_skipped: Optional[int] = None,
    ) -> None:
        if not self._health_path:
            return
        if watchers_running is not None:
            self._health.watchers_running = watchers_running
        if remote_enabled is not None:
            self._health.remote_enabled = remote_enabled
        if last_remote_sync_at is not None:
            self._health.last_remote_sync_at = last_remote_sync_at
        if last_remote_error is not None:
            self._health.last_remote_error = last_remote_error
        if orchestrator_pid is not None:
            self._health.orchestrator_pid = orchestrator_pid
        if last_remote_registered is not None:
            self._health.last_remote_registered = last_remote_registered
        if last_remote_per_domain is not None:
            self._health.last_remote_per_domain = last_remote_per_domain
        if last_remote_skipped is not None:
            self._health.last_remote_skipped = last_remote_skipped
        if self._activity_store:
            snapshot = self._activity_store.snapshot()
            self._health.activity_state = {
                domain: {
                    key: state.as_dict()
                    for key, state in entries.items()
                }
                for domain, entries in snapshot.items()
                if entries
            }
        write_runtime_health(self._health_path, self._health)


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
    return datetime.now(timezone.utc).isoformat()
