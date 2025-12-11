"""Task bridge."""

from __future__ import annotations

from oneiric.core.config import LayerSettings
from oneiric.core.lifecycle import LifecycleManager
from oneiric.core.resolution import Resolver
from oneiric.runtime.activity import DomainActivityStore
from oneiric.runtime.supervisor import ServiceSupervisor

from .base import DomainBridge


class TaskBridge(DomainBridge):
    def __init__(
        self,
        resolver: Resolver,
        lifecycle: LifecycleManager,
        settings: LayerSettings,
        activity_store: DomainActivityStore | None = None,
        supervisor: ServiceSupervisor | None = None,
    ) -> None:
        super().__init__(
            "task",
            resolver,
            lifecycle,
            settings,
            activity_store=activity_store,
            supervisor=supervisor,
        )
