"""Comprehensive tests for oneiric.domains.base.

Covers the full surface of the base domain bridge: the DomainHandle dataclass,
DomainBridge construction with optional activity_store and supervisor, settings
registration and caching, the async ``use`` flow (happy path, force_reload,
missing candidate, missing provider, capabilities, require_all), candidate
listing helpers, the explain pass-through, should_accept_work for both
supervisor and in-memory paths, set_paused and set_draining with metric
recording, activity_snapshot merging, supervisor listener wiring and domain
filtering, and the activity-allowed guard. The property test asserts that
the settings cache is idempotent for repeated reads.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from hypothesis import HealthCheck, given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st
from pydantic import BaseModel

from oneiric.core.config import LayerSettings
from oneiric.core.lifecycle import LifecycleError, LifecycleManager
from oneiric.core.resolution import Candidate, CandidateSource, Resolver
from oneiric.domains.base import DomainBridge, DomainHandle
from oneiric.runtime.activity import DomainActivity, DomainActivityStore
from oneiric.runtime.supervisor import ServiceSupervisor

# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------


class _StubInstance:
    """Simple object returned by factory callables in tests."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.cleaned_up = False

    async def cleanup(self) -> None:  # pragma: no cover - optional cleanup
        self.cleaned_up = True


class _ProviderSettings(BaseModel):
    """Pydantic settings model used by register_settings_model tests."""

    host: str = "localhost"
    port: int = 8080
    timeout: int = 30


def _activity_store(tmp_path: Any) -> DomainActivityStore:
    """Build a DomainActivityStore backed by a per-test sqlite file.

    The shared ``bridge_activity_store`` fixture passes no path to
    ``DomainActivityStore.__init__`` (which requires one), so we construct
    our own store with a fresh tmp_path for each test that needs it.
    """
    return DomainActivityStore(tmp_path / "activity.sqlite")


def _make_bridge(
    resolver: Resolver,
    lifecycle: LifecycleManager,
    settings: LayerSettings | None = None,
    activity_store: Any = None,
    supervisor: ServiceSupervisor | None = None,
    *,
    domain: str = "service",
) -> DomainBridge:
    return DomainBridge(
        domain,
        resolver,
        lifecycle,
        settings if settings is not None else LayerSettings(),
        activity_store=activity_store,
        supervisor=supervisor,
    )


def _register_factory(
    resolver: Resolver,
    *,
    domain: str = "service",
    key: str = "api",
    provider: str = "fastapi",
    factory: Any = None,
    priority: int = 10,
    metadata: dict[str, Any] | None = None,
) -> None:
    resolver.register(
        Candidate(
            domain=domain,
            key=key,
            provider=provider,
            factory=factory
            if factory is not None
            else (lambda: _StubInstance(provider)),
            priority=priority,
            source=CandidateSource.MANUAL,
            metadata=metadata if metadata is not None else {"version": "1.0"},
        )
    )


# ---------------------------------------------------------------------------
# DomainHandle dataclass
# ---------------------------------------------------------------------------


class TestDomainHandle:
    def test_minimal_construction(self) -> None:
        handle = DomainHandle(
            domain="adapter",
            key="cache",
            provider="redis",
            instance=object(),
            metadata={},
            settings=None,
        )
        assert handle.domain == "adapter"
        assert handle.key == "cache"
        assert handle.provider == "redis"
        assert handle.metadata == {}
        assert handle.settings is None

    def test_holds_arbitrary_instance(self) -> None:
        sentinel = object()
        handle = DomainHandle(
            domain="adapter",
            key="cache",
            provider="redis",
            instance=sentinel,
            metadata={},
            settings=None,
        )
        assert handle.instance is sentinel

    def test_metadata_is_mutable(self) -> None:
        handle = DomainHandle(
            domain="service",
            key="api",
            provider="fastapi",
            instance=object(),
            metadata={"version": "1.0"},
            settings=None,
        )
        handle.metadata["owner"] = "platform"
        assert handle.metadata == {"version": "1.0", "owner": "platform"}

    def test_settings_can_be_model_or_dict(self) -> None:
        model_settings = _ProviderSettings(host="h", port=1, timeout=2)
        raw_settings = {"host": "h"}
        m = DomainHandle(
            domain="d",
            key="k",
            provider="p",
            instance=object(),
            metadata={},
            settings=model_settings,
        )
        r = DomainHandle(
            domain="d",
            key="k",
            provider="p",
            instance=object(),
            metadata={},
            settings=raw_settings,
        )
        assert m.settings is model_settings
        assert r.settings is raw_settings


# ---------------------------------------------------------------------------
# DomainBridge construction
# ---------------------------------------------------------------------------


class TestDomainBridgeInit:
    def test_stores_domain_resolver_lifecycle_settings(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
    ) -> None:
        bridge = _make_bridge(
            resolver, lifecycle_manager, settings=layer_settings, domain="service"
        )
        assert bridge.domain == "service"
        assert bridge.resolver is resolver
        assert bridge.lifecycle is lifecycle_manager
        assert bridge.settings is layer_settings
        assert bridge._settings_models == {}
        assert bridge._settings_cache == {}
        assert bridge._activity == {}

    def test_optional_activity_store_accepted(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
        tmp_path: Any,
    ) -> None:
        store = _activity_store(tmp_path)
        bridge = _make_bridge(
            resolver,
            lifecycle_manager,
            settings=layer_settings,
            activity_store=store,
        )
        assert bridge._activity_store is store

    def test_optional_supervisor_registers_listener(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
        tmp_path: Any,
    ) -> None:
        store = _activity_store(tmp_path)
        supervisor = ServiceSupervisor(store)
        bridge = _make_bridge(
            resolver,
            lifecycle_manager,
            settings=layer_settings,
            supervisor=supervisor,
        )
        # The bridge must have stored the unsubscriber and wired the listener.
        assert bridge._supervisor is supervisor
        assert bridge._supervisor_unsubscribe is not None
        assert callable(bridge._supervisor_unsubscribe)
        bridge._supervisor_unsubscribe()

    def test_no_supervisor_leaves_listener_unset(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
    ) -> None:
        bridge = _make_bridge(resolver, lifecycle_manager, settings=layer_settings)
        assert bridge._supervisor is None
        assert bridge._supervisor_unsubscribe is None


# ---------------------------------------------------------------------------
# Settings registration and caching
# ---------------------------------------------------------------------------


class TestDomainBridgeSettings:
    def test_register_settings_model_stores_provider(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
    ) -> None:
        bridge = _make_bridge(resolver, lifecycle_manager, settings=layer_settings)
        bridge.register_settings_model("fastapi", _ProviderSettings)
        assert bridge._settings_models["fastapi"] is _ProviderSettings

    def test_get_settings_returns_parsed_model(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
    ) -> None:
        layer = LayerSettings(
            provider_settings={
                "fastapi": {"host": "api.example.com", "port": 443, "timeout": 60}
            }
        )
        bridge = _make_bridge(
            resolver, lifecycle_manager, settings=layer, domain="service"
        )
        bridge.register_settings_model("fastapi", _ProviderSettings)

        parsed = bridge.get_settings("fastapi")
        assert isinstance(parsed, _ProviderSettings)
        assert parsed.host == "api.example.com"
        assert parsed.port == 443
        assert parsed.timeout == 60

    def test_get_settings_returns_raw_dict_when_no_model(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
    ) -> None:
        layer = LayerSettings(
            provider_settings={"redis": {"host": "cache", "port": 6379}}
        )
        bridge = _make_bridge(
            resolver, lifecycle_manager, settings=layer, domain="adapter"
        )
        raw = bridge.get_settings("redis")
        assert raw == {"host": "cache", "port": 6379}
        assert isinstance(raw, dict)

    def test_cache_hit_returns_same_instance(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
    ) -> None:
        layer = LayerSettings(provider_settings={"fastapi": {"host": "h"}})
        bridge = _make_bridge(resolver, lifecycle_manager, settings=layer)
        bridge.register_settings_model("fastapi", _ProviderSettings)
        first = bridge.get_settings("fastapi")
        second = bridge.get_settings("fastapi")
        assert first is second

    def test_update_settings_clears_cache(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
    ) -> None:
        layer_one = LayerSettings(
            provider_settings={"fastapi": {"host": "old", "port": 1, "timeout": 1}}
        )
        bridge = _make_bridge(resolver, lifecycle_manager, settings=layer_one)
        bridge.register_settings_model("fastapi", _ProviderSettings)
        old = bridge.get_settings("fastapi")
        assert old.host == "old"

        layer_two = LayerSettings(
            provider_settings={"fastapi": {"host": "new", "port": 2, "timeout": 2}}
        )
        bridge.update_settings(layer_two)
        new = bridge.get_settings("fastapi")
        assert new.host == "new"
        assert new is not old


# ---------------------------------------------------------------------------
# use() — async flow
# ---------------------------------------------------------------------------


class TestUse:
    async def test_happy_path_returns_handle(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
    ) -> None:
        bridge = _make_bridge(
            resolver, lifecycle_manager, settings=layer_settings, domain="service"
        )
        _register_factory(resolver, domain="service", key="api", provider="fastapi")

        handle = await bridge.use("api")

        assert isinstance(handle, DomainHandle)
        assert handle.domain == "service"
        assert handle.key == "api"
        assert handle.provider == "fastapi"
        assert isinstance(handle.instance, _StubInstance)
        assert handle.metadata == {"version": "1.0"}

    async def test_force_reload_calls_lifecycle_swap(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
        monkeypatch: Any,
    ) -> None:
        bridge = _make_bridge(
            resolver, lifecycle_manager, settings=layer_settings, domain="service"
        )
        _register_factory(resolver, domain="service", key="api", provider="fastapi")

        call_log: list[str] = []
        original_swap = lifecycle_manager.swap
        original_activate = lifecycle_manager.activate

        async def fake_swap(
            domain: str,
            key: str,
            provider: str | None = None,
            *,
            force: bool = False,
        ) -> Any:
            call_log.append(f"swap:{domain}:{key}:{provider}")
            return await original_swap(domain, key, provider=provider, force=force)

        async def fake_activate(
            domain: str,
            key: str,
            provider: str | None = None,
            *,
            force: bool = False,
        ) -> Any:
            call_log.append(f"activate:{domain}:{key}:{provider}")
            return await original_activate(domain, key, provider=provider, force=force)

        monkeypatch.setattr(lifecycle_manager, "swap", fake_swap)
        monkeypatch.setattr(lifecycle_manager, "activate", fake_activate)

        await bridge.use("api")  # initial activation (cached path)
        await bridge.use("api", force_reload=True)  # force swap

        swap_calls = [entry for entry in call_log if entry.startswith("swap:")]
        assert swap_calls, f"expected at least one swap call, got {call_log!r}"
        # The second use must route through lifecycle.swap with the right provider.
        assert any("service:api:fastapi" in entry for entry in swap_calls)

    async def test_missing_candidate_raises_with_no_candidate_message(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
    ) -> None:
        bridge = _make_bridge(
            resolver, lifecycle_manager, settings=layer_settings, domain="service"
        )
        with __import__("pytest").raises(
            LifecycleError, match="No candidate found for service:missing"
        ):
            await bridge.use("missing")

    async def test_missing_provider_raises(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
    ) -> None:
        bridge = _make_bridge(
            resolver, lifecycle_manager, settings=layer_settings, domain="service"
        )
        resolver.register(
            Candidate(
                domain="service",
                key="api",
                provider=None,
                factory=lambda: _StubInstance("no-provider"),
                source=CandidateSource.MANUAL,
            )
        )
        with __import__("pytest").raises(
            LifecycleError, match="Candidate missing provider for service:api"
        ):
            await bridge.use("api")

    async def test_capabilities_route_to_capable_candidate(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
    ) -> None:
        bridge = _make_bridge(
            resolver, lifecycle_manager, settings=layer_settings, domain="service"
        )
        resolver.register(
            Candidate(
                domain="service",
                key="api",
                provider="alpha",
                factory=lambda: _StubInstance("alpha"),
                source=CandidateSource.MANUAL,
                priority=10,
                metadata={"capabilities": ["fast"]},
            )
        )
        resolver.register(
            Candidate(
                domain="service",
                key="api",
                provider="beta",
                factory=lambda: _StubInstance("beta"),
                source=CandidateSource.MANUAL,
                priority=20,
                metadata={"capabilities": ["slow"]},
            )
        )

        # ``beta`` has higher priority but doesn't expose "fast".  With
        # capabilities=["fast"], the resolver should select ``alpha``.
        handle = await bridge.use("api", capabilities=["fast"], require_all=True)
        assert handle.provider == "alpha"
        assert handle.instance.name == "alpha"

    async def test_require_all_false_picks_any_matching_candidate(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
    ) -> None:
        bridge = _make_bridge(
            resolver, lifecycle_manager, settings=layer_settings, domain="service"
        )
        resolver.register(
            Candidate(
                domain="service",
                key="api",
                provider="alpha",
                factory=lambda: _StubInstance("alpha"),
                source=CandidateSource.MANUAL,
                priority=10,
                metadata={"capabilities": ["fast"]},
            )
        )
        resolver.register(
            Candidate(
                domain="service",
                key="api",
                provider="beta",
                factory=lambda: _StubInstance("beta"),
                source=CandidateSource.MANUAL,
                priority=20,
                metadata={"capabilities": ["slow"]},
            )
        )

        # require_all=False with capability "fast" should still pick ``alpha``
        # (the only one that has it) over higher-priority ``beta``.
        handle = await bridge.use("api", capabilities=["fast"], require_all=False)
        assert handle.provider == "alpha"


# ---------------------------------------------------------------------------
# Candidate listing helpers
# ---------------------------------------------------------------------------


class TestActiveAndShadowedCandidates:
    def test_active_candidates_passes_through(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
    ) -> None:
        bridge = _make_bridge(
            resolver, lifecycle_manager, settings=layer_settings, domain="service"
        )
        _register_factory(resolver, domain="service", key="api", provider="alpha")
        _register_factory(resolver, domain="adapter", key="cache", provider="redis")

        active = bridge.active_candidates()
        domains = {candidate.domain for candidate in active}
        assert "service" in domains
        assert "adapter" not in domains

    def test_shadowed_candidates_passes_through(self, temp_dir: Any) -> None:
        # The bridge delegates to resolver.list_shadowed(domain).  Shadowed
        # candidates are produced when the resolver has a selection override
        # in ResolverSettings (note: distinct from LayerSettings.selections).
        from oneiric.core.resolution import ResolverSettings

        shadow_resolver = Resolver(
            ResolverSettings(selections={"service": {"api": "alpha"}})
        )
        lifecycle = LifecycleManager(
            shadow_resolver, status_snapshot_path=str(temp_dir / "lifecycle.json")
        )
        bridge = _make_bridge(
            shadow_resolver, lifecycle, settings=LayerSettings(), domain="service"
        )
        _register_factory(
            shadow_resolver, domain="service", key="api", provider="alpha", priority=10
        )
        _register_factory(
            shadow_resolver, domain="service", key="api", provider="beta", priority=20
        )
        _register_factory(
            shadow_resolver, domain="adapter", key="cache", provider="redis"
        )

        shadowed = bridge.shadowed_candidates()
        providers = {candidate.provider for candidate in shadowed}
        domains = {candidate.domain for candidate in shadowed}
        assert "beta" in providers
        assert domains == {"service"}


# ---------------------------------------------------------------------------
# explain()
# ---------------------------------------------------------------------------


class TestExplain:
    def test_returns_dict_form(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
    ) -> None:
        bridge = _make_bridge(
            resolver, lifecycle_manager, settings=layer_settings, domain="service"
        )
        _register_factory(resolver, domain="service", key="api", provider="alpha")

        result = bridge.explain("api")
        assert isinstance(result, dict)
        assert result["domain"] == "service"
        assert result["key"] == "api"
        assert result["ordered"], "expected at least one ordered entry"
        first = result["ordered"][0]
        assert first["provider"] == "alpha"
        assert first["selected"] is True

    def test_capabilities_passed_through(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
    ) -> None:
        bridge = _make_bridge(
            resolver, lifecycle_manager, settings=layer_settings, domain="service"
        )
        _register_factory(resolver, domain="service", key="api", provider="alpha")
        result = bridge.explain("api", capabilities=["x"], require_all=False)
        assert isinstance(result, dict)
        assert result["key"] == "api"


# ---------------------------------------------------------------------------
# should_accept_work
# ---------------------------------------------------------------------------


class TestShouldAcceptWork:
    def test_default_passes_when_no_store(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
    ) -> None:
        bridge = _make_bridge(
            resolver, lifecycle_manager, settings=layer_settings, domain="service"
        )
        assert bridge.should_accept_work("api") is True

    def test_paused_blocks_work(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
    ) -> None:
        bridge = _make_bridge(
            resolver, lifecycle_manager, settings=layer_settings, domain="service"
        )
        bridge.set_paused("api", True)
        assert bridge.should_accept_work("api") is False

    def test_draining_blocks_work(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
    ) -> None:
        bridge = _make_bridge(
            resolver, lifecycle_manager, settings=layer_settings, domain="service"
        )
        bridge.set_draining("api", True)
        assert bridge.should_accept_work("api") is False

    def test_supervisor_overrides(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
        tmp_path: Any,
    ) -> None:
        store = _activity_store(tmp_path)
        supervisor = ServiceSupervisor(store)
        bridge = _make_bridge(
            resolver,
            lifecycle_manager,
            settings=layer_settings,
            activity_store=store,
            supervisor=supervisor,
        )
        # Activity store has no entry, supervisor state has no entry either.
        assert bridge.should_accept_work("api") is True


# ---------------------------------------------------------------------------
# set_paused / set_draining
# ---------------------------------------------------------------------------


class TestSetPaused:
    def test_set_paused_updates_activity_state(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
    ) -> None:
        bridge = _make_bridge(
            resolver, lifecycle_manager, settings=layer_settings, domain="service"
        )
        state = bridge.set_paused("api", True, note="maint")
        assert state.paused is True
        assert state.note == "maint"
        # In-memory activity reflects the change.
        cached = bridge.activity_state("api")
        assert cached.paused is True
        assert cached.note == "maint"

    def test_set_paused_records_metric(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
        monkeypatch: Any,
    ) -> None:
        bridge = _make_bridge(
            resolver, lifecycle_manager, settings=layer_settings, domain="service"
        )
        calls: list[tuple[str, bool]] = []
        monkeypatch.setattr(
            "oneiric.domains.base.record_pause_state",
            lambda domain, paused: calls.append((domain, paused)),
        )
        bridge.set_paused("api", True)
        bridge.set_paused("api", False)
        assert calls == [("service", True), ("service", False)]

    def test_set_paused_emits_log_line(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
    ) -> None:
        bridge = _make_bridge(
            resolver, lifecycle_manager, settings=layer_settings, domain="service"
        )
        info_calls: list[tuple[str, dict[str, Any]]] = []
        bridge._logger.info = (  # type: ignore[method-assign]
            lambda event, **kw: info_calls.append((event, kw))
        )
        bridge.set_paused("api", True, note="maint")
        bridge.set_paused("api", False)
        events = [entry[0] for entry in info_calls]
        assert "domain-paused" in events
        assert "domain-resumed" in events

    def test_set_paused_resume_returns_to_default(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
    ) -> None:
        bridge = _make_bridge(
            resolver, lifecycle_manager, settings=layer_settings, domain="service"
        )
        bridge.set_paused("api", True, note="maint")
        state = bridge.set_paused("api", False)
        # Resuming keeps the note but clears paused.
        assert state.paused is False
        assert state.note == "maint"


class TestSetDraining:
    def test_set_draining_updates_activity_state(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
    ) -> None:
        bridge = _make_bridge(
            resolver, lifecycle_manager, settings=layer_settings, domain="service"
        )
        state = bridge.set_draining("api", True, note="draining queue")
        assert state.draining is True
        assert state.note == "draining queue"
        cached = bridge.activity_state("api")
        assert cached.draining is True
        assert cached.note == "draining queue"

    def test_set_draining_records_metric(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
        monkeypatch: Any,
    ) -> None:
        bridge = _make_bridge(
            resolver, lifecycle_manager, settings=layer_settings, domain="service"
        )
        calls: list[tuple[str, bool]] = []
        monkeypatch.setattr(
            "oneiric.domains.base.record_drain_state",
            lambda domain, draining: calls.append((domain, draining)),
        )
        bridge.set_draining("api", True)
        bridge.set_draining("api", False)
        assert calls == [("service", True), ("service", False)]

    def test_set_draining_emits_log_line(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
    ) -> None:
        bridge = _make_bridge(
            resolver, lifecycle_manager, settings=layer_settings, domain="service"
        )
        info_calls: list[tuple[str, dict[str, Any]]] = []
        bridge._logger.info = (  # type: ignore[method-assign]
            lambda event, **kw: info_calls.append((event, kw))
        )
        bridge.set_draining("api", True, note="drain")
        bridge.set_draining("api", False)
        events = [entry[0] for entry in info_calls]
        assert "domain-draining" in events
        assert "domain-drain-cleared" in events

    def test_set_draining_clear_returns_to_default(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
    ) -> None:
        bridge = _make_bridge(
            resolver, lifecycle_manager, settings=layer_settings, domain="service"
        )
        bridge.set_draining("api", True, note="drain")
        state = bridge.set_draining("api", False)
        assert state.draining is False
        assert state.note == "drain"


# ---------------------------------------------------------------------------
# activity_snapshot
# ---------------------------------------------------------------------------


class TestActivitySnapshot:
    def test_in_memory_only(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
    ) -> None:
        bridge = _make_bridge(
            resolver, lifecycle_manager, settings=layer_settings, domain="service"
        )
        bridge.set_paused("api", True)
        bridge.set_draining("worker", True)

        snapshot = bridge.activity_snapshot()
        assert set(snapshot.keys()) == {"api", "worker"}
        assert snapshot["api"].paused is True
        assert snapshot["worker"].draining is True

    def test_merges_store_and_in_memory(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
        tmp_path: Any,
    ) -> None:
        # Pre-populate the activity store with one key.
        store = _activity_store(tmp_path)
        store.set("service", "persisted", DomainActivity(paused=True, note="persisted"))
        bridge = _make_bridge(
            resolver,
            lifecycle_manager,
            settings=layer_settings,
            activity_store=store,
        )
        # Set an in-memory key (note: without a store, this still updates
        # the in-memory dict that activity_snapshot returns).
        bridge.set_draining("transient", True, note="runtime")

        snapshot = bridge.activity_snapshot()
        assert "persisted" in snapshot
        assert snapshot["persisted"].paused is True
        assert snapshot["persisted"].note == "persisted"
        assert "transient" in snapshot
        assert snapshot["transient"].draining is True


# ---------------------------------------------------------------------------
# Supervisor listener
# ---------------------------------------------------------------------------


class TestSupervisorListener:
    def test_listener_invoked_for_matching_domain(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
        tmp_path: Any,
    ) -> None:
        store = _activity_store(tmp_path)
        supervisor = ServiceSupervisor(store)
        bridge = _make_bridge(
            resolver,
            lifecycle_manager,
            settings=layer_settings,
            activity_store=None,
            supervisor=supervisor,
        )

        store.set("service", "api", DomainActivity(paused=True, note="maint"))
        supervisor.refresh()

        cached = bridge._activity.get("api")
        assert cached is not None
        assert cached.paused is True
        assert cached.note == "maint"

    def test_listener_ignored_for_other_domain(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
        tmp_path: Any,
    ) -> None:
        store = _activity_store(tmp_path)
        supervisor = ServiceSupervisor(store)
        bridge = _make_bridge(
            resolver,
            lifecycle_manager,
            settings=layer_settings,
            activity_store=None,
            supervisor=supervisor,
        )

        store.set("other", "api", DomainActivity(paused=True, note="other"))
        supervisor.refresh()

        assert "api" not in bridge._activity

    def test_default_state_pops_entry(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
        tmp_path: Any,
    ) -> None:
        store = _activity_store(tmp_path)
        supervisor = ServiceSupervisor(store)
        bridge = _make_bridge(
            resolver,
            lifecycle_manager,
            settings=layer_settings,
            activity_store=None,
            supervisor=supervisor,
        )

        store.set("service", "api", DomainActivity(paused=True))
        supervisor.refresh()
        assert "api" in bridge._activity

        # Clear in the store; refresh; bridge should drop the key.
        store.set("service", "api", DomainActivity())
        supervisor.refresh()
        assert "api" not in bridge._activity


# ---------------------------------------------------------------------------
# _ensure_activity_allowed
# ---------------------------------------------------------------------------


class TestEnsureActivityAllowed:
    async def test_use_raises_when_paused(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
    ) -> None:
        bridge = _make_bridge(
            resolver, lifecycle_manager, settings=layer_settings, domain="service"
        )
        _register_factory(resolver, domain="service", key="api", provider="alpha")
        bridge.set_paused("api", True, note="maint")

        with __import__("pytest").raises(LifecycleError, match="service:api is paused"):
            await bridge.use("api")

    async def test_use_raises_when_draining(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
    ) -> None:
        bridge = _make_bridge(
            resolver, lifecycle_manager, settings=layer_settings, domain="service"
        )
        _register_factory(resolver, domain="service", key="api", provider="alpha")
        bridge.set_draining("api", True, note="drain")

        with __import__("pytest").raises(
            LifecycleError, match="service:api is draining"
        ):
            await bridge.use("api")

    async def test_use_raises_when_both_paused_and_draining(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
    ) -> None:
        bridge = _make_bridge(
            resolver, lifecycle_manager, settings=layer_settings, domain="service"
        )
        _register_factory(resolver, domain="service", key="api", provider="alpha")
        bridge.set_paused("api", True, note="maint")
        bridge.set_draining("api", True, note="drain")

        with __import__("pytest").raises(
            LifecycleError, match=r"service:api is paused & draining"
        ):
            await bridge.use("api")

    async def test_use_passes_when_activity_default(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
    ) -> None:
        bridge = _make_bridge(
            resolver, lifecycle_manager, settings=layer_settings, domain="service"
        )
        _register_factory(resolver, domain="service", key="api", provider="alpha")
        handle = await bridge.use("api")
        assert handle.provider == "alpha"


# ---------------------------------------------------------------------------
# Property-based test
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Helpers used by the property test
# ---------------------------------------------------------------------------


_provider_names = st.sampled_from(["alpha", "beta", "gamma", "delta"])
_call_counts = st.integers(min_value=1, max_value=25)


@st.composite
def _provider_payload(draw: Any) -> dict[str, Any]:
    return {
        "host": draw(st.text(min_size=1, max_size=12)),
        "port": draw(st.integers(min_value=1, max_value=65535)),
        "timeout": draw(st.integers(min_value=1, max_value=600)),
    }


@hyp_settings(max_examples=25, suppress_health_check=[HealthCheck.too_slow])
@given(
    provider=_provider_names,
    payload=_provider_payload(),
    call_count=_call_counts,
)
def test_settings_cache_idempotent(
    provider: str,
    payload: dict[str, Any],
    call_count: int,
) -> None:
    """Repeated get_settings() calls return the same object instance."""
    resolver = Resolver()
    lifecycle = LifecycleManager(resolver)
    layer = LayerSettings(provider_settings={provider: payload})
    bridge = DomainBridge("service", resolver, lifecycle, layer)
    bridge.register_settings_model(provider, _ProviderSettings)

    instances = [bridge.get_settings(provider) for _ in range(call_count)]
    first = instances[0]
    for other in instances[1:]:
        assert other is first


# ---------------------------------------------------------------------------
# Integration scenarios
# ---------------------------------------------------------------------------


class TestIntegration:
    async def test_full_use_lifecycle_returns_factory_result(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
    ) -> None:
        bridge = _make_bridge(
            resolver, lifecycle_manager, settings=layer_settings, domain="service"
        )

        def factory() -> _StubInstance:
            return _StubInstance("real-component")

        _register_factory(
            resolver,
            domain="service",
            key="api",
            provider="fastapi",
            factory=factory,
        )

        handle = await bridge.use("api")
        assert isinstance(handle.instance, _StubInstance)
        assert handle.instance.name == "real-component"

    async def test_paused_message_starts_with_domain_key(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
    ) -> None:
        bridge = _make_bridge(
            resolver, lifecycle_manager, settings=layer_settings, domain="adapter"
        )
        _register_factory(resolver, domain="adapter", key="cache", provider="redis")
        bridge.set_paused("cache", True, note="freeze")

        with __import__("pytest").raises(
            LifecycleError, match="^adapter:cache is paused"
        ):
            await bridge.use("cache")

    def test_supervisor_authoritative_over_in_memory(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
        tmp_path: Any,
    ) -> None:
        # With a supervisor wired, should_accept_work delegates to it and
        # ignores the in-memory activity dict (since the supervisor is
        # authoritative for this bridge).
        store = _activity_store(tmp_path)
        supervisor = ServiceSupervisor(store)
        bridge = _make_bridge(
            resolver,
            lifecycle_manager,
            settings=layer_settings,
            activity_store=store,
            supervisor=supervisor,
        )
        # In-memory set_paused should not change supervisor's view.
        bridge.set_paused("api", True)
        # Supervisor state has no entry, so it still accepts work.
        assert bridge.should_accept_work("api") is True

    def test_activity_state_reads_from_store_when_available(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
        tmp_path: Any,
    ) -> None:
        store = _activity_store(tmp_path)
        store.set("service", "api", DomainActivity(paused=True, note="from-store"))
        bridge = _make_bridge(
            resolver,
            lifecycle_manager,
            settings=layer_settings,
            activity_store=store,
        )
        state = bridge.activity_state("api")
        assert state.paused is True
        assert state.note == "from-store"

    def test_activity_state_default_in_memory(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
    ) -> None:
        bridge = _make_bridge(
            resolver, lifecycle_manager, settings=layer_settings, domain="service"
        )
        state = bridge.activity_state("never-seen")
        assert state == DomainActivity()


# ---------------------------------------------------------------------------
# Thread safety smoke test
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_set_paused_consistent(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
    ) -> None:
        bridge = _make_bridge(
            resolver, lifecycle_manager, settings=layer_settings, domain="service"
        )

        def toggle(value: bool) -> None:
            for _ in range(20):
                bridge.set_paused("api", value)

        threads = [threading.Thread(target=toggle, args=(v,)) for v in (True, False)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        final = bridge.activity_state("api")
        assert isinstance(final, DomainActivity)

    def test_concurrent_get_settings_idempotent(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings: LayerSettings,
    ) -> None:
        layer = LayerSettings(
            provider_settings={"fastapi": {"host": "h", "port": 1, "timeout": 1}}
        )
        bridge = _make_bridge(resolver, lifecycle_manager, settings=layer)
        bridge.register_settings_model("fastapi", _ProviderSettings)

        observed: list[Any] = []
        lock = threading.Lock()

        def worker() -> None:
            for _ in range(20):
                instance = bridge.get_settings("fastapi")
                with lock:
                    observed.append(instance)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        first = observed[0]
        for instance in observed[1:]:
            assert instance is first


# ---------------------------------------------------------------------------
# Async sanity check
# ---------------------------------------------------------------------------


class TestAsyncSanity:
    async def test_run_in_event_loop(self) -> None:
        # Sanity: a trivial async test runs under asyncio_mode=auto.
        await asyncio.sleep(0)
        assert True
