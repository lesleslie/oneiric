"""Adapter bridge scaffolding."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Type

from pydantic import BaseModel

from oneiric.core.config import LayerSettings
from oneiric.core.lifecycle import LifecycleError, LifecycleManager
from oneiric.core.logging import get_logger
from oneiric.core.resolution import Candidate, Resolver
from oneiric.runtime.activity import DomainActivity, DomainActivityStore


@dataclass
class AdapterHandle:
    category: str
    provider: str
    instance: Any
    settings: Any
    metadata: Dict[str, Any]


class AdapterBridge:
    """Coordinates adapters via the resolver + lifecycle manager."""

    def __init__(
        self,
        resolver: Resolver,
        lifecycle: LifecycleManager,
        settings: LayerSettings,
        activity_store: Optional[DomainActivityStore] = None,
    ) -> None:
        self.domain = "adapter"
        self.resolver = resolver
        self.lifecycle = lifecycle
        self.settings = settings
        self._logger = get_logger("adapter.bridge")
        self._settings_models: Dict[str, Type[BaseModel]] = {}
        self._settings_cache: Dict[str, Any] = {}
        self._activity_store = activity_store
        self._activity: Dict[str, DomainActivity] = {}
        self._refresh_activity_from_store()

    def register_settings_model(self, provider: str, model: Type[BaseModel]) -> None:
        self._settings_models[provider] = model

    def get_settings(self, provider: str) -> Any:
        if provider in self._settings_cache:
            return self._settings_cache[provider]
        raw = self.settings.provider_settings.get(provider, {})
        model = self._settings_models.get(provider)
        if model:
            parsed = model(**raw)
        else:
            parsed = raw
        self._settings_cache[provider] = parsed
        return parsed

    def update_settings(self, settings: LayerSettings) -> None:
        self.settings = settings
        self._settings_cache.clear()

    def active_candidates(self) -> list[Candidate]:
        return self.resolver.list_active("adapter")

    def shadowed_candidates(self) -> list[Candidate]:
        return self.resolver.list_shadowed("adapter")

    async def use(
        self,
        category: str,
        *,
        provider: Optional[str] = None,
        force_reload: bool = False,
    ) -> AdapterHandle:
        configured_provider = provider or self.settings.selections.get(category)
        candidate = self.resolver.resolve("adapter", category, provider=configured_provider)
        if not candidate:
            raise LifecycleError(f"No adapter candidate found for {category}")
        target_provider = candidate.provider or configured_provider
        if not target_provider:
            raise LifecycleError(f"Adapter candidate missing provider for {category}")

        if force_reload:
            instance = await self.lifecycle.swap("adapter", category, provider=target_provider)
        else:
            instance = self.lifecycle.get_instance("adapter", category)
            if instance is None:
                instance = await self.lifecycle.activate("adapter", category, provider=target_provider)

        handle = AdapterHandle(
            category=category,
            provider=target_provider,
            instance=instance,
            settings=self.get_settings(target_provider),
            metadata=candidate.metadata,
        )
        self._logger.info(
            "adapter-ready",
            category=category,
            provider=handle.provider,
            metadata=handle.metadata,
        )
        return handle

    def explain(self, category: str) -> Dict[str, Any]:
        return self.resolver.explain("adapter", category).as_dict()

    def activity_state(self, key: str) -> DomainActivity:
        if self._activity_store:
            state = self._activity_store.get(self.domain, key)
            self._activity[key] = state
            return state
        return self._activity.setdefault(key, DomainActivity())

    def set_paused(self, key: str, paused: bool, *, note: Optional[str] = None) -> DomainActivity:
        current = self.activity_state(key)
        state = DomainActivity(
            paused=paused,
            draining=current.draining,
            note=note if note is not None else current.note,
        )
        self._persist_activity(key, state)
        self._logger.info(
            "adapter-paused" if paused else "adapter-resumed",
            key=key,
            note=state.note,
        )
        return self.activity_state(key)

    def set_draining(self, key: str, draining: bool, *, note: Optional[str] = None) -> DomainActivity:
        current = self.activity_state(key)
        state = DomainActivity(
            paused=current.paused,
            draining=draining,
            note=note if note is not None else current.note,
        )
        self._persist_activity(key, state)
        self._logger.info(
            "adapter-draining" if draining else "adapter-drain-cleared",
            key=key,
            note=state.note,
        )
        return self.activity_state(key)

    def activity_snapshot(self) -> Dict[str, DomainActivity]:
        self._refresh_activity_from_store()
        return dict(self._activity)

    def _persist_activity(self, key: str, state: DomainActivity) -> None:
        self._activity[key] = state
        if self._activity_store:
            self._activity_store.set(self.domain, key, state)

    def _refresh_activity_from_store(self) -> None:
        if not self._activity_store:
            return
        self._activity = self._activity_store.all_for_domain(self.domain)
