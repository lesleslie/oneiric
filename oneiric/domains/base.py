"""Generic resolver-backed domain bridge."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from oneiric.core.config import LayerSettings
from oneiric.core.lifecycle import LifecycleError, LifecycleManager
from oneiric.core.logging import get_logger
from oneiric.core.metrics import record_drain_state, record_pause_state
from oneiric.core.resolution import Candidate, Resolver
from oneiric.runtime.activity import DomainActivity
from oneiric.runtime.protocols import ActivityStoreProtocol
from oneiric.runtime.supervisor import ServiceSupervisor


@dataclass
class DomainHandle:
    domain: str
    key: str
    provider: str
    instance: Any
    metadata: dict[str, Any]
    settings: Any


class DomainBridge:
    """Reusable bridge for resolver-backed domains."""

    def __init__(
        self,
        domain: str,
        resolver: Resolver,
        lifecycle: LifecycleManager,
        settings: LayerSettings,
        activity_store: ActivityStoreProtocol | None = None,
        supervisor: ServiceSupervisor | None = None,
    ) -> None:
        self.domain = domain
        self.resolver = resolver
        self.lifecycle = lifecycle
        self.settings = settings
        self._logger = get_logger(f"{domain}.bridge")
        self._settings_models: dict[str, type[BaseModel]] = {}
        self._settings_cache: dict[str, Any] = {}
        self._activity_store = activity_store
        self._activity: dict[str, DomainActivity] = {}
        self._supervisor = supervisor
        self._supervisor_unsubscribe: Callable[[], None] | None = None
        if self._supervisor:
            self._supervisor_unsubscribe = self._supervisor.add_listener(
                self._handle_supervisor_update,
                domain=self.domain,
                fire_immediately=True,
            )
        self._refresh_activity_from_store()

    def register_settings_model(self, provider: str, model: type[BaseModel]) -> None:
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
        provider: str | None = None,
        capabilities: Sequence[str] | None = None,
        require_all: bool = True,
        force_reload: bool = False,
    ) -> DomainHandle:
        configured_provider = provider or self.settings.selections.get(key)
        self._ensure_activity_allowed(key)
        candidate = self.resolver.resolve(
            self.domain,
            key,
            provider=configured_provider,
            capabilities=capabilities,
            require_all=require_all,
        )
        if not candidate:
            raise self._missing_candidate_error(key)
        target_provider = candidate.provider or configured_provider
        if not target_provider:
            raise LifecycleError(f"Candidate missing provider for {self.domain}:{key}")

        if force_reload:
            instance = await self.lifecycle.swap(
                self.domain, key, provider=target_provider
            )
        else:
            instance = self.lifecycle.get_instance(self.domain, key)
            if instance is None:
                instance = await self.lifecycle.activate(
                    self.domain, key, provider=target_provider
                )

        handle = self._build_handle(
            key=key,
            provider=target_provider,
            instance=instance,
            candidate=candidate,
        )
        self._after_handle(handle, candidate)
        return handle

    def active_candidates(self) -> list[Candidate]:
        return self.resolver.list_active(self.domain)

    def shadowed_candidates(self) -> list[Candidate]:
        return self.resolver.list_shadowed(self.domain)

    def explain(
        self,
        key: str,
        *,
        capabilities: Sequence[str] | None = None,
        require_all: bool = True,
    ) -> dict[str, Any]:
        return self.resolver.explain(
            self.domain,
            key,
            capabilities=capabilities,
            require_all=require_all,
        ).as_dict()

    def should_accept_work(self, key: str) -> bool:
        """Return True when the domain/key is not paused or draining."""

        if self._supervisor:
            return self._supervisor.should_accept_work(self.domain, key)
        state = self.activity_state(key)
        return not state.paused and not state.draining

    def activity_state(self, key: str) -> DomainActivity:
        if self._activity_store:
            state = self._activity_store.get(self.domain, key)
            self._activity[key] = state
            return state
        return self._activity.setdefault(key, DomainActivity())

    def set_paused(
        self, key: str, paused: bool, *, note: str | None = None
    ) -> DomainActivity:
        current = self.activity_state(key)
        state = DomainActivity(
            paused=paused,
            draining=current.draining,
            note=note if note is not None else current.note,
        )
        self._persist_activity(key, state)
        record_pause_state(self.domain, paused)
        self._logger.info(
            "domain-paused" if paused else "domain-resumed",
            domain=self.domain,
            key=key,
            note=state.note,
        )
        return self.activity_state(key)

    def set_draining(
        self, key: str, draining: bool, *, note: str | None = None
    ) -> DomainActivity:
        current = self.activity_state(key)
        state = DomainActivity(
            paused=current.paused,
            draining=draining,
            note=note if note is not None else current.note,
        )
        self._persist_activity(key, state)
        record_drain_state(self.domain, draining)
        self._logger.info(
            "domain-draining" if draining else "domain-drain-cleared",
            domain=self.domain,
            key=key,
            note=state.note,
        )
        return self.activity_state(key)

    def activity_snapshot(self) -> dict[str, DomainActivity]:
        self._refresh_activity_from_store()
        return self._activity.copy()

    def _persist_activity(self, key: str, state: DomainActivity) -> None:
        self._activity[key] = state
        if self._activity_store:
            self._activity_store.set(self.domain, key, state)

    def _refresh_activity_from_store(self) -> None:
        if not self._activity_store:
            return
        self._activity = self._activity_store.all_for_domain(self.domain)

    def _ensure_activity_allowed(self, key: str) -> None:
        if self.should_accept_work(key):
            return
        state = self.activity_state(key)
        reason = _activity_block_reason(state)
        self._logger.warning(
            "domain-activity-blocked",
            domain=self.domain,
            key=key,
            reason=reason,
        )
        raise LifecycleError(f"{self.domain}:{key} is {reason}")

    def _build_handle(
        self, *, key: str, provider: str, instance: Any, candidate: Candidate
    ) -> DomainHandle:
        return DomainHandle(
            domain=self.domain,
            key=key,
            provider=provider,
            instance=instance,
            metadata=candidate.metadata,
            settings=self.get_settings(provider),
        )

    def _after_handle(self, handle: DomainHandle, candidate: Candidate) -> None:
        self._logger.info(
            "domain-ready",
            domain=self.domain,
            key=handle.key,
            provider=handle.provider,
            metadata=handle.metadata,
        )

    def _missing_candidate_error(self, key: str) -> LifecycleError:
        return LifecycleError(f"No candidate found for {self.domain}:{key}")

    def _handle_supervisor_update(
        self, domain: str, key: str, state: DomainActivity
    ) -> None:
        """Sync internal cache when supervisor broadcasts updates."""

        if domain != self.domain:
            return
        if state.is_default():
            self._activity.pop(key, None)
        else:
            self._activity[key] = state


def _activity_block_reason(state: DomainActivity) -> str:
    flags: list[str] = []
    if state.paused:
        flags.append("paused")
    if state.draining:
        flags.append("draining")
    if not flags:
        flags.append("unavailable")
    return " & ".join(flags)
