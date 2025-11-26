"""Generic resolver-backed domain bridge."""

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
class DomainHandle:
    domain: str
    key: str
    provider: str
    instance: Any
    metadata: Dict[str, Any]
    settings: Any


class DomainBridge:
    """Reusable bridge for resolver-backed domains."""

    def __init__(
        self,
        domain: str,
        resolver: Resolver,
        lifecycle: LifecycleManager,
        settings: LayerSettings,
        activity_store: Optional[DomainActivityStore] = None,
    ) -> None:
        self.domain = domain
        self.resolver = resolver
        self.lifecycle = lifecycle
        self.settings = settings
        self._logger = get_logger(f"{domain}.bridge")
        self._settings_models: Dict[str, Type[BaseModel]] = {}
        self._settings_cache: Dict[str, Any] = {}
        self._activity_store = activity_store
        self._activity: Dict[str, DomainActivity] = {}
        self._refresh_activity_from_store()

    def register_settings_model(self, provider: str, model: Type[BaseModel]) -> None:
        self._settings_models[provider] = model

    def update_settings(self, settings: LayerSettings) -> None:
        self.settings = settings
        self._settings_cache.clear()

    def get_settings(self, provider: str) -> Any:
        if provider in self._settings_cache:
            return self._settings_cache[provider]
        raw = self.settings.provider_settings.get(provider, {})
        model = self._settings_models.get(provider)
        parsed = model(**raw) if model else raw
        self._settings_cache[provider] = parsed
        return parsed

    async def use(
        self,
        key: str,
        *,
        provider: Optional[str] = None,
        force_reload: bool = False,
    ) -> DomainHandle:
        configured_provider = provider or self.settings.selections.get(key)
        candidate = self.resolver.resolve(self.domain, key, provider=configured_provider)
        if not candidate:
            raise LifecycleError(f"No candidate found for {self.domain}:{key}")
        target_provider = candidate.provider or configured_provider
        if not target_provider:
            raise LifecycleError(f"Candidate missing provider for {self.domain}:{key}")

        if force_reload:
            instance = await self.lifecycle.swap(self.domain, key, provider=target_provider)
        else:
            instance = self.lifecycle.get_instance(self.domain, key)
            if instance is None:
                instance = await self.lifecycle.activate(self.domain, key, provider=target_provider)

        handle = DomainHandle(
            domain=self.domain,
            key=key,
            provider=target_provider,
            instance=instance,
            metadata=candidate.metadata,
            settings=self.get_settings(target_provider),
        )
        self._logger.info(
            "domain-ready",
            domain=self.domain,
            key=key,
            provider=handle.provider,
            metadata=handle.metadata,
        )
        return handle

    def active_candidates(self) -> list[Candidate]:
        return self.resolver.list_active(self.domain)

    def shadowed_candidates(self) -> list[Candidate]:
        return self.resolver.list_shadowed(self.domain)

    def explain(self, key: str) -> Dict[str, Any]:
        return self.resolver.explain(self.domain, key).as_dict()

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
            "domain-paused" if paused else "domain-resumed",
            domain=self.domain,
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
            "domain-draining" if draining else "domain-drain-cleared",
            domain=self.domain,
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
