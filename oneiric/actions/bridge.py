"""Domain bridge for resolver-managed actions."""

from __future__ import annotations

from oneiric.core.config import LayerSettings
from oneiric.core.lifecycle import LifecycleManager
from oneiric.core.resolution import Resolver
from oneiric.domains.base import DomainBridge
from oneiric.runtime.activity import DomainActivityStore
from oneiric.runtime.supervisor import ServiceSupervisor


class ActionBridge(DomainBridge):
    """Thin wrapper for the shared DomainBridge wired to the 'action' domain."""

    def __init__(
        self,
        resolver: Resolver,
        lifecycle: LifecycleManager,
        settings: LayerSettings,
        *,
        activity_store: DomainActivityStore | None = None,
        supervisor: ServiceSupervisor | None = None,
    ) -> None:
        super().__init__(
            domain="action",
            resolver=resolver,
            lifecycle=lifecycle,
            settings=settings,
            activity_store=activity_store,
            supervisor=supervisor,
        )
