"""Workflow bridge."""

from __future__ import annotations

from typing import Optional

from oneiric.core.config import LayerSettings
from oneiric.core.lifecycle import LifecycleManager
from oneiric.core.resolution import Resolver
from oneiric.runtime.activity import DomainActivityStore

from .base import DomainBridge


class WorkflowBridge(DomainBridge):
    def __init__(
        self,
        resolver: Resolver,
        lifecycle: LifecycleManager,
        settings: LayerSettings,
        activity_store: Optional[DomainActivityStore] = None,
    ) -> None:
        super().__init__("workflow", resolver, lifecycle, settings, activity_store=activity_store)
