"""Domain bridge for resolver-managed actions."""

from __future__ import annotations

from typing import Optional

from oneiric.core.config import LayerSettings
from oneiric.core.lifecycle import LifecycleManager
from oneiric.core.resolution import Resolver
from oneiric.domains.base import DomainBridge
from oneiric.runtime.activity import DomainActivityStore


class ActionBridge(DomainBridge):
    """Thin wrapper for the shared DomainBridge wired to the 'action' domain."""

    def __init__(
        self,
        resolver: Resolver,
        lifecycle: LifecycleManager,
        settings: LayerSettings,
        *,
        activity_store: Optional[DomainActivityStore] = None,
    ) -> None:
        super().__init__(
            domain="action",
            resolver=resolver,
            lifecycle=lifecycle,
            settings=settings,
            activity_store=activity_store,
        )
