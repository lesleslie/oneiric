"""Adapter bridge scaffolding."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from oneiric.adapters.metrics import capture_adapter_state_metrics
from oneiric.core.config import LayerSettings
from oneiric.core.lifecycle import LifecycleError, LifecycleManager
from oneiric.core.resolution import Candidate, Resolver
from oneiric.domains.base import DomainBridge, DomainHandle
from oneiric.runtime.activity import DomainActivityStore
from oneiric.runtime.supervisor import ServiceSupervisor


@dataclass
class AdapterHandle:
    category: str
    provider: str
    instance: Any
    settings: Any
    metadata: dict[str, Any]


class AdapterBridge(DomainBridge):
    """Coordinates adapters via the resolver + lifecycle manager."""

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
            domain="adapter",
            resolver=resolver,
            lifecycle=lifecycle,
            settings=settings,
            activity_store=activity_store,
            supervisor=supervisor,
        )

    async def use(
        self,
        category: str,
        *,
        provider: str | None = None,
        capabilities: Sequence[str] | None = None,
        require_all: bool = True,
        force_reload: bool = False,
    ) -> AdapterHandle:
        handle = await super().use(
            category,
            provider=provider,
            capabilities=capabilities,
            require_all=require_all,
            force_reload=force_reload,
        )
        return AdapterHandle(
            category=handle.key,
            provider=handle.provider,
            instance=handle.instance,
            settings=handle.settings,
            metadata=handle.metadata,
        )

    def _after_handle(self, handle: DomainHandle, candidate: Candidate) -> None:
        try:
            capture_adapter_state_metrics(
                handle.instance, category=handle.key, provider=handle.provider
            )
        except Exception:  # pragma: no cover - defensive metric sampling
            pass
        self._logger.info(
            "adapter-ready",
            category=handle.key,
            provider=handle.provider,
            metadata=handle.metadata,
        )

    def _missing_candidate_error(self, key: str) -> LifecycleError:
        return LifecycleError(f"No adapter candidate found for {key}")
