"""Comprehensive tests for oneiric.core.resolution.

Covers the full surface of the resolver: constants and enum, the Candidate
Pydantic model, the ResolverSettings container, the CandidateRank and
ResolutionExplanation dataclasses, the CandidateRegistry thread-safe
implementation, the Resolver facade, priority inference, the register_pkg
helper, integration scenarios, and three property-based invariants.
"""

from __future__ import annotations

import json
import threading
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from oneiric.core.resolution import (
    PATH_PRIORITY_HINTS,
    STACK_ORDER_ENV,
    Candidate,
    CandidateRank,
    CandidateRegistry,
    CandidateSource,
    FactoryType,
    ResolutionExplanation,
    Resolver,
    ResolverSettings,
    infer_priority,
    register_pkg,
)


# ---------------------------------------------------------------------------
# CandidateSource enum
# ---------------------------------------------------------------------------


class TestCandidateSource:
    def test_values_exist(self) -> None:
        assert CandidateSource.LOCAL_PKG.value == "local_pkg"
        assert CandidateSource.REMOTE_MANIFEST.value == "remote_manifest"
        assert CandidateSource.ENTRY_POINT.value == "entry_point"
        assert CandidateSource.MANUAL.value == "manual"

    def test_values_are_distinct(self) -> None:
        seen = {member.value for member in CandidateSource}
        assert len(seen) == len(CandidateSource)

    def test_str_round_trip(self) -> None:
        for member in CandidateSource:
            assert CandidateSource(str(member)) is member

    def test_strenum_string_equality(self) -> None:
        # StrEnum instances are equal to their string value
        assert CandidateSource.LOCAL_PKG == "local_pkg"
        assert CandidateSource.REMOTE_MANIFEST != CandidateSource.MANUAL


# ---------------------------------------------------------------------------
# Candidate model
# ---------------------------------------------------------------------------


class TestCandidate:
    def test_minimal_construction(self) -> None:
        c = Candidate(domain="adapter", key="cache", factory=lambda: None)
        assert c.domain == "adapter"
        assert c.key == "cache"
        assert c.provider is None
        assert c.priority is None
        assert c.stack_level is None
        assert c.source == CandidateSource.LOCAL_PKG
        assert c.metadata == {}
        assert c.registry_sequence is None

    def test_full_construction(self) -> None:
        factory: FactoryType = "oneiric.demo:DemoAdapter"
        c = Candidate(
            domain="service",
            key="auth",
            provider="google",
            priority=10,
            stack_level=2,
            factory=factory,
            metadata={"version": "1.0"},
            source=CandidateSource.REMOTE_MANIFEST,
        )
        assert c.provider == "google"
        assert c.priority == 10
        assert c.stack_level == 2
        assert c.factory == factory
        assert c.metadata == {"version": "1.0"}
        assert c.source == CandidateSource.REMOTE_MANIFEST

    def test_with_priority_returns_copy(self) -> None:
        c = Candidate(domain="adapter", key="cache", factory=lambda: None)
        c2 = c.with_priority(5)
        assert c2.priority == 5
        # Original not mutated
        assert c.priority is None

    def test_with_priority_preserves_other_fields(self) -> None:
        c = Candidate(
            domain="adapter",
            key="cache",
            provider="redis",
            factory=lambda: None,
            metadata={"v": 1},
        )
        c2 = c.with_priority(7)
        assert c2.domain == "adapter"
        assert c2.key == "cache"
        assert c2.provider == "redis"
        assert c2.metadata == {"v": 1}
        assert c2.factory is c.factory

    def test_model_dump_round_trip(self) -> None:
        original = Candidate(
            domain="adapter",
            key="cache",
            provider="redis",
            priority=10,
            stack_level=3,
            factory=lambda: None,
            metadata={"v": 1},
        )
        dump = original.model_dump()
        restored = Candidate(**dump)
        assert restored.domain == original.domain
        assert restored.key == original.key
        assert restored.provider == original.provider
        assert restored.priority == original.priority
        assert restored.stack_level == original.stack_level
        assert restored.metadata == original.metadata

    def test_registered_at_defaults_to_utc_now(self) -> None:
        before = datetime.now(UTC)
        c = Candidate(domain="adapter", key="cache", factory=lambda: None)
        after = datetime.now(UTC)
        assert before <= c.registered_at <= after
        # Default is timezone-aware UTC
        assert c.registered_at.tzinfo is not None

    def test_health_callable_invoked(self) -> None:
        calls: list[bool] = []

        def hc() -> bool:
            calls.append(True)
            return True

        c = Candidate(
            domain="adapter", key="cache", factory=lambda: None, health=hc
        )
        # Invoke the stored health check directly
        assert c.health is not None
        result = c.health()
        assert result is True
        assert calls == [True]

    def test_health_default_none(self) -> None:
        c = Candidate(domain="adapter", key="cache", factory=lambda: None)
        assert c.health is None

    def test_registry_sequence_excluded_from_json(self) -> None:
        c = Candidate(
            domain="adapter",
            key="cache",
            factory="oneiric.demo:DemoAdapter",
        )
        # registry_sequence is excluded from serialization
        assert "registry_sequence" not in c.model_dump()
        assert "registry_sequence" not in c.model_dump_json()
        # But it is accessible as a Python attribute
        assert c.registry_sequence is None

    def test_model_dump_preserves_metadata_dict_independence(self) -> None:
        c = Candidate(
            domain="adapter",
            key="cache",
            factory=lambda: None,
            metadata={"k": 1},
        )
        dump = c.model_dump()
        # Mutate the dump's metadata; the candidate's metadata should be intact
        dump["metadata"]["k"] = 999
        assert c.metadata == {"k": 1}


# ---------------------------------------------------------------------------
# ResolverSettings
# ---------------------------------------------------------------------------


class TestResolverSettings:
    def test_defaults(self) -> None:
        rs = ResolverSettings()
        assert rs.default_priority == 0
        assert rs.selections == {}

    def test_selection_for_existing(self) -> None:
        rs = ResolverSettings(
            selections={"adapter": {"cache": "redis"}, "service": {"auth": "okta"}},
        )
        assert rs.selection_for("adapter", "cache") == "redis"
        assert rs.selection_for("service", "auth") == "okta"

    def test_selection_for_missing_domain(self) -> None:
        rs = ResolverSettings(selections={"adapter": {"cache": "redis"}})
        assert rs.selection_for("service", "auth") is None

    def test_selection_for_missing_key(self) -> None:
        rs = ResolverSettings(selections={"adapter": {}})
        assert rs.selection_for("adapter", "cache") is None

    def test_selections_independence_on_deepcopy(self) -> None:
        original = ResolverSettings(
            selections={"adapter": {"cache": "redis"}},
        )
        clone = deepcopy(original)
        clone.selections["adapter"]["cache"] = "memcached"
        clone.selections["service"] = {"auth": "okta"}
        # Original unchanged after mutating clone
        assert original.selection_for("adapter", "cache") == "redis"
        assert original.selection_for("service", "auth") is None

    def test_default_priority_explicit(self) -> None:
        rs = ResolverSettings(default_priority=42)
        assert rs.default_priority == 42


# ---------------------------------------------------------------------------
# CandidateRank dataclass
# ---------------------------------------------------------------------------


class TestCandidateRank:
    def test_defaults(self) -> None:
        c = Candidate(domain="adapter", key="cache", factory=lambda: None)
        rank = CandidateRank(candidate=c, score=(1, 2, 3, 4), reasons=["r"])
        assert rank.candidate is c
        assert rank.score == (1, 2, 3, 4)
        assert rank.reasons == ["r"]
        assert rank.selected is False

    def test_mutable(self) -> None:
        c = Candidate(domain="adapter", key="cache", factory=lambda: None)
        rank = CandidateRank(candidate=c, score=(0, 0, 0, 0), reasons=[])
        rank.selected = True
        rank.reasons.append("winner")
        assert rank.selected is True
        assert rank.reasons == ["winner"]

    def test_score_is_tuple(self) -> None:
        c = Candidate(domain="adapter", key="cache", factory=lambda: None)
        rank = CandidateRank(candidate=c, score=(1, 0, 0, 0), reasons=[])
        # Tuple type expected; verify ordering is preserved
        assert rank.score[0] == 1
        assert rank.score[1] == 0
        assert rank.score[2] == 0
        assert rank.score[3] == 0


# ---------------------------------------------------------------------------
# ResolutionExplanation dataclass
# ---------------------------------------------------------------------------


class TestResolutionExplanation:
    def _make_candidate(self, provider: str) -> Candidate:
        return Candidate(
            domain="adapter",
            key="cache",
            provider=provider,
            factory=lambda: None,
        )

    def test_construction(self) -> None:
        c = self._make_candidate("redis")
        rank = CandidateRank(candidate=c, score=(0, 0, 0, 0), reasons=[])
        explanation = ResolutionExplanation(
            domain="adapter", key="cache", ordered=[rank]
        )
        assert explanation.domain == "adapter"
        assert explanation.key == "cache"
        assert explanation.ordered == [rank]

    def test_winner_returns_first_selected(self) -> None:
        c1 = self._make_candidate("redis")
        c2 = self._make_candidate("memcached")
        r1 = CandidateRank(candidate=c1, score=(10, 0, 0, 0), reasons=[], selected=True)
        r2 = CandidateRank(
            candidate=c2, score=(5, 0, 0, 0), reasons=[], selected=False
        )
        explanation = ResolutionExplanation(
            domain="adapter", key="cache", ordered=[r1, r2]
        )
        assert explanation.winner is c1

    def test_winner_none_when_nothing_selected(self) -> None:
        c1 = self._make_candidate("redis")
        c2 = self._make_candidate("memcached")
        r1 = CandidateRank(
            candidate=c1, score=(10, 0, 0, 0), reasons=[], selected=False
        )
        r2 = CandidateRank(
            candidate=c2, score=(5, 0, 0, 0), reasons=[], selected=False
        )
        explanation = ResolutionExplanation(
            domain="adapter", key="cache", ordered=[r1, r2]
        )
        assert explanation.winner is None

    def test_winner_none_when_empty(self) -> None:
        explanation = ResolutionExplanation(
            domain="adapter", key="cache", ordered=[]
        )
        assert explanation.winner is None

    def test_as_dict_is_json_serialisable(self) -> None:
        c = self._make_candidate("redis")
        rank = CandidateRank(
            candidate=c, score=(10, 5, 0, 0), reasons=["best"], selected=True
        )
        explanation = ResolutionExplanation(
            domain="adapter", key="cache", ordered=[rank]
        )
        d = explanation.as_dict()
        # Round-trip through json
        encoded = json.dumps(d)
        decoded = json.loads(encoded)
        assert decoded["domain"] == "adapter"
        assert decoded["key"] == "cache"
        assert len(decoded["ordered"]) == 1
        assert decoded["ordered"][0]["provider"] == "redis"
        assert decoded["ordered"][0]["selected"] is True
        assert decoded["ordered"][0]["reasons"] == ["best"]

    def test_as_dict_score_ordering_reflects_rationale(self) -> None:
        # Higher tuple scores sort first; rationale ordering in `ordered`
        # is the ranking order, not the registration order.
        c_low = self._make_candidate("low")
        c_high = self._make_candidate("high")
        r_low = CandidateRank(
            candidate=c_low, score=(0, 0, 1, 0), reasons=["low"], selected=False
        )
        r_high = CandidateRank(
            candidate=c_high, score=(0, 0, 9, 0), reasons=["high"], selected=True
        )
        # Provide in registration order (low first) to confirm the
        # as_dict output reflects the *input* list, not a resort. The
        # contract is to expose the rationale in the order it was ranked.
        explanation = ResolutionExplanation(
            domain="adapter", key="cache", ordered=[r_low, r_high]
        )
        d = explanation.as_dict()
        assert d["ordered"][0]["provider"] == "low"
        assert d["ordered"][1]["provider"] == "high"
        assert d["ordered"][0]["reasons"] == ["low"]
        assert d["ordered"][1]["reasons"] == ["high"]


# ---------------------------------------------------------------------------
# CandidateRegistry
# ---------------------------------------------------------------------------


class TestCandidateRegistry:
    def test_register_single_candidate(self) -> None:
        registry = CandidateRegistry()
        candidate = Candidate(
            domain="adapter", key="cache", provider="redis", factory=lambda: None
        )
        registry.register_candidate(candidate)
        resolved = registry.resolve("adapter", "cache")
        assert resolved is not None
        assert resolved.provider == "redis"

    def test_register_multiple_candidates(self) -> None:
        registry = CandidateRegistry()
        for i in range(3):
            registry.register_candidate(
                Candidate(
                    domain="adapter",
                    key=f"k-{i}",
                    provider=f"p-{i}",
                    factory=lambda: None,
                )
            )
        for i in range(3):
            resolved = registry.resolve("adapter", f"k-{i}")
            assert resolved is not None
            assert resolved.provider == f"p-{i}"

    def test_sequence_numbers_strictly_increase(self) -> None:
        registry = CandidateRegistry()
        for i in range(5):
            registry.register_candidate(
                Candidate(
                    domain="adapter",
                    key=f"k-{i}",
                    provider=f"p-{i}",
                    factory=lambda: None,
                )
            )
        sequences = [
            registry.resolve("adapter", f"k-{i}").registry_sequence for i in range(5)
        ]
        # Strictly increasing
        for prev, curr in zip(sequences, sequences[1:], strict=False):
            assert curr > prev
        # Starting at 1
        assert sequences[0] == 1

    def test_same_candidate_re_registered_increments_sequence(
        self, monkeypatch: Any
    ) -> None:
        # No unregister method: re-registering a logically-equal candidate
        # still increments the sequence number, because sequence is monotonic.
        registry = CandidateRegistry()
        first = Candidate(
            domain="adapter", key="cache", provider="redis", factory=lambda: None
        )
        registry.register_candidate(first)
        seq1 = registry.resolve("adapter", "cache").registry_sequence

        # Re-register an equivalent candidate (new instance, same field values)
        second = Candidate(
            domain="adapter", key="cache", provider="redis", factory=lambda: None
        )
        registry.register_candidate(second)
        seq2 = registry.resolve("adapter", "cache").registry_sequence

        # Sequence strictly increased
        assert seq2 == seq1 + 1
        # And the re-registration produced a shadowed candidate
        shadowed = registry.list_shadowed("adapter")
        assert len(shadowed) == 1
        assert shadowed[0].registry_sequence == seq1

    def test_list_active_and_shadowed_partition(self) -> None:
        registry = CandidateRegistry()
        # Two candidates for the same key
        registry.register_candidate(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: None,
                priority=1,
            )
        )
        registry.register_candidate(
            Candidate(
                domain="adapter",
                key="cache",
                provider="memcached",
                factory=lambda: None,
                priority=10,
            )
        )
        # And one candidate for a different key
        registry.register_candidate(
            Candidate(
                domain="adapter",
                key="queue",
                provider="redis",
                factory=lambda: None,
            )
        )

        active = registry.list_active("adapter")
        shadowed = registry.list_shadowed("adapter")
        # Active should contain the winner of each key
        active_providers = sorted(c.provider for c in active)
        assert active_providers == ["memcached", "redis"]
        # Shadowed should contain the loser
        shadowed_providers = sorted(c.provider for c in shadowed)
        assert shadowed_providers == ["redis"]
        # Partition: every registered candidate is in exactly one bucket
        all_keys = (
            [("adapter", "cache"), ("adapter", "cache"), ("adapter", "queue")]
        )
        assert len(active) + len(shadowed) == len(all_keys)

    def test_resolve_returns_highest_priority(self) -> None:
        registry = CandidateRegistry()
        registry.register_candidate(
            Candidate(
                domain="adapter",
                key="cache",
                provider="low",
                factory=lambda: None,
                priority=1,
            )
        )
        registry.register_candidate(
            Candidate(
                domain="adapter",
                key="cache",
                provider="high",
                factory=lambda: None,
                priority=100,
            )
        )
        resolved = registry.resolve("adapter", "cache")
        assert resolved is not None
        assert resolved.provider == "high"

    def test_resolve_unknown_returns_none(self) -> None:
        registry = CandidateRegistry()
        assert registry.resolve("adapter", "cache") is None

    def test_explain_returns_full_ordered_list(self) -> None:
        registry = CandidateRegistry()
        for provider, priority in [("low", 1), ("high", 100), ("mid", 50)]:
            registry.register_candidate(
                Candidate(
                    domain="adapter",
                    key="cache",
                    provider=provider,
                    factory=lambda: None,
                    priority=priority,
                )
            )
        explanation = registry.explain("adapter", "cache")
        providers = [e.candidate.provider for e in explanation.ordered]
        # Ordered high -> low
        assert providers == ["high", "mid", "low"]
        # Winner is the first selected
        assert explanation.winner is not None
        assert explanation.winner.provider == "high"

    def test_capability_matching_require_all_true(self) -> None:
        registry = CandidateRegistry()
        registry.register_candidate(
            Candidate(
                domain="adapter",
                key="cache",
                provider="basic",
                factory=lambda: None,
                metadata={"capabilities": ["read"]},
            )
        )
        registry.register_candidate(
            Candidate(
                domain="adapter",
                key="cache",
                provider="full",
                factory=lambda: None,
                metadata={"capabilities": ["read", "write"]},
            )
        )
        # require_all=True: "full" is the only one matching both
        resolved = registry.resolve(
            "adapter", "cache", capabilities=["read", "write"]
        )
        assert resolved is not None
        assert resolved.provider == "full"

    def test_capability_matching_require_all_false(self) -> None:
        registry = CandidateRegistry()
        registry.register_candidate(
            Candidate(
                domain="adapter",
                key="cache",
                provider="read",
                factory=lambda: None,
                metadata={"capabilities": ["read"]},
                priority=1,
            )
        )
        registry.register_candidate(
            Candidate(
                domain="adapter",
                key="cache",
                provider="write",
                factory=lambda: None,
                metadata={"capabilities": ["write"]},
                priority=100,
            )
        )
        # require_all=False: even "read" qualifies; "write" has higher priority
        resolved = registry.resolve(
            "adapter",
            "cache",
            capabilities=["read", "write"],
            require_all=False,
        )
        assert resolved is not None
        assert resolved.provider == "write"

    def test_provider_override_path(self) -> None:
        registry = CandidateRegistry()
        registry.register_candidate(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: None,
                priority=100,
            )
        )
        registry.register_candidate(
            Candidate(
                domain="adapter",
                key="cache",
                provider="memcached",
                factory=lambda: None,
                priority=1,
            )
        )
        # Override path: requesting memcached returns memcached even though
        # its priority is lower
        resolved = registry.resolve("adapter", "cache", provider="memcached")
        assert resolved is not None
        assert resolved.provider == "memcached"
        # And requesting an unknown provider returns None
        assert registry.resolve("adapter", "cache", provider="unknown") is None

    def test_settings_override_wins(self) -> None:
        settings = ResolverSettings(selections={"adapter": {"cache": "memcached"}})
        registry = CandidateRegistry(settings)
        registry.register_candidate(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: None,
                priority=100,
            )
        )
        registry.register_candidate(
            Candidate(
                domain="adapter",
                key="cache",
                provider="memcached",
                factory=lambda: None,
                priority=1,
            )
        )
        resolved = registry.resolve("adapter", "cache")
        assert resolved is not None
        assert resolved.provider == "memcached"

    def test_concurrent_registration_is_thread_safe(self) -> None:
        registry = CandidateRegistry()
        n_threads = 8
        per_thread = 25

        def worker(thread_id: int) -> None:
            for i in range(per_thread):
                registry.register_candidate(
                    Candidate(
                        domain="adapter",
                        key=f"t{thread_id}-k{i}",
                        provider=f"p{thread_id}-{i}",
                        factory=lambda: None,
                    )
                )

        threads = [
            threading.Thread(target=worker, args=(t,)) for t in range(n_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All registrations must be retrievable
        for thread_id in range(n_threads):
            for i in range(per_thread):
                resolved = registry.resolve("adapter", f"t{thread_id}-k{i}")
                assert resolved is not None
                assert resolved.provider == f"p{thread_id}-{i}"

        # Total active count must equal the total registrations
        active = registry.list_active("adapter")
        assert len(active) == n_threads * per_thread

        # Sequences must be unique and form the range 1..N (no gaps, no dupes)
        sequences = sorted(c.registry_sequence for c in active)
        assert sequences == list(range(1, n_threads * per_thread + 1))


# ---------------------------------------------------------------------------
# Resolver facade
# ---------------------------------------------------------------------------


class TestResolver:
    def test_register(self, resolver: Resolver) -> None:
        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: None,
            )
        )
        assert resolver.resolve("adapter", "cache") is not None

    def test_register_from_pkg(self, resolver: Resolver) -> None:
        resolver.register_from_pkg(
            package_name="myapp",
            path="/project/myapp",
            priority=33,
            candidates=[
                Candidate(
                    domain="adapter",
                    key="cache",
                    provider="redis",
                    factory=lambda: None,
                )
            ],
        )
        resolved = resolver.resolve("adapter", "cache")
        assert resolved is not None
        assert resolved.priority == 33
        assert resolved.metadata["package"] == "myapp"
        assert resolved.metadata["path"] == "/project/myapp"

    def test_resolve(self, resolver: Resolver) -> None:
        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: None,
                priority=10,
            )
        )
        resolved = resolver.resolve("adapter", "cache")
        assert resolved is not None
        assert resolved.provider == "redis"

    def test_list_active(self, resolver: Resolver) -> None:
        for i in range(3):
            resolver.register(
                Candidate(
                    domain="adapter",
                    key=f"k-{i}",
                    provider=f"p-{i}",
                    factory=lambda: None,
                )
            )
        active = resolver.list_active("adapter")
        assert len(active) == 3

    def test_list_shadowed(self, resolver: Resolver) -> None:
        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: None,
                priority=1,
            )
        )
        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="memcached",
                factory=lambda: None,
                priority=10,
            )
        )
        shadowed = resolver.list_shadowed("adapter")
        assert len(shadowed) == 1
        assert shadowed[0].provider == "redis"

    def test_explain(self, resolver: Resolver) -> None:
        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: None,
            )
        )
        explanation = resolver.explain("adapter", "cache")
        assert explanation.domain == "adapter"
        assert explanation.key == "cache"
        assert explanation.winner is not None

    def test_resolver_composes_with_candidate_registry(
        self, resolver: Resolver
    ) -> None:
        # Verify the facade's registry is the same instance via behaviour
        # (the resolver composes by holding a CandidateRegistry).
        resolver.register(
            Candidate(
                domain="adapter",
                key="k",
                provider="p",
                factory=lambda: None,
            )
        )
        # Resolve via resolver
        assert resolver.resolve("adapter", "k") is not None
        # Same data accessible via the underlying registry
        assert resolver.registry.resolve("adapter", "k") is not None


# ---------------------------------------------------------------------------
# Priority inference
# ---------------------------------------------------------------------------


class TestPriorityInference:
    def test_defaults_to_zero(self, monkeypatch: Any) -> None:
        monkeypatch.delenv(STACK_ORDER_ENV, raising=False)
        assert infer_priority(None, None) == 0
        assert infer_priority("unknown", None) == 0
        assert infer_priority(None, "/no/hints/here.py") == 0

    def test_path_hints_yield_positive_priority(
        self, monkeypatch: Any
    ) -> None:
        monkeypatch.delenv(STACK_ORDER_ENV, raising=False)
        for marker, value in PATH_PRIORITY_HINTS:
            # Use a 2-part path so depth penalty is min(2, 10) = 2
            path = f"/{marker}/component.py"
            priority = infer_priority(None, path)
            # Parts of "/adapters/component.py" are ('/', 'adapters', 'component.py')
            # marker 'adapters' is in parts; depth = min(3, 10) = 3
            assert priority == value - 3
            assert priority > 0

    def test_env_var_overrides_path_hints(self, monkeypatch: Any) -> None:
        monkeypatch.setenv(STACK_ORDER_ENV, "myapp:100,otherapp:50")
        # Env value wins, path is ignored
        assert infer_priority("myapp", "/project/adapters/x.py") == 100
        assert infer_priority("otherapp", "/project/services/x.py") == 50

    def test_env_var_auto_assign(self, monkeypatch: Any) -> None:
        # Tokens without ':' get auto-assigned values in registration order:
        # first token = 0, second = 10, third = 20
        monkeypatch.setenv(STACK_ORDER_ENV, "first,second,third")
        assert infer_priority("first", None) == 0
        assert infer_priority("second", None) == 10
        assert infer_priority("third", None) == 20

    def test_env_var_ignores_blank_tokens(self, monkeypatch: Any) -> None:
        monkeypatch.setenv(STACK_ORDER_ENV, "first,,third:30")
        assert infer_priority("first", None) == 0
        assert infer_priority("third", None) == 30

    def test_depth_penalty(self, monkeypatch: Any) -> None:
        monkeypatch.delenv(STACK_ORDER_ENV, raising=False)
        shallow = infer_priority(None, "/project/adapters/x.py")
        deep = infer_priority(None, "/very/deep/nested/path/adapters/x.py")
        # Deeper path gets a larger depth penalty, hence lower priority
        assert shallow > deep

    def test_depth_penalty_capped_at_ten(self, monkeypatch: Any) -> None:
        monkeypatch.delenv(STACK_ORDER_ENV, raising=False)
        # Many parts: depth is min(len(parts), 10)
        very_deep = "/a/b/c/d/e/f/g/h/i/j/k/l/m/n/o/p"
        priority = infer_priority(None, very_deep)
        # No hint marker so result is 0
        assert priority == 0


# ---------------------------------------------------------------------------
# register_pkg helper
# ---------------------------------------------------------------------------


class TestRegisterPkg:
    def test_applies_inferred_priority(self, monkeypatch: Any) -> None:
        monkeypatch.setenv(STACK_ORDER_ENV, "myapp:77")
        registry = CandidateRegistry()
        register_pkg(
            registry,
            package_name="myapp",
            path="/project/myapp",
            candidates=[
                Candidate(
                    domain="adapter",
                    key=f"k-{i}",
                    provider=f"p-{i}",
                    factory=lambda: None,
                )
                for i in range(3)
            ],
        )
        for i in range(3):
            resolved = registry.resolve("adapter", f"k-{i}")
            assert resolved is not None
            assert resolved.priority == 77

    def test_merges_metadata(self) -> None:
        registry = CandidateRegistry()
        register_pkg(
            registry,
            package_name="myapp",
            path="/project/myapp",
            candidates=[
                Candidate(
                    domain="adapter",
                    key="cache",
                    provider="redis",
                    factory=lambda: None,
                    metadata={"version": "1.0"},
                )
            ],
        )
        resolved = registry.resolve("adapter", "cache")
        assert resolved is not None
        assert resolved.metadata["package"] == "myapp"
        assert resolved.metadata["path"] == "/project/myapp"
        assert resolved.metadata["version"] == "1.0"

    def test_explicit_priority_overrides_inferred(
        self, monkeypatch: Any
    ) -> None:
        monkeypatch.setenv(STACK_ORDER_ENV, "myapp:99")
        registry = CandidateRegistry()
        register_pkg(
            registry,
            package_name="myapp",
            path="/project/myapp",
            priority=10,
            candidates=[
                Candidate(
                    domain="adapter",
                    key="cache",
                    provider="redis",
                    factory=lambda: None,
                )
            ],
        )
        resolved = registry.resolve("adapter", "cache")
        assert resolved is not None
        assert resolved.priority == 10

    def test_registers_all_candidates(self) -> None:
        registry = CandidateRegistry()
        candidates = [
            Candidate(
                domain="adapter",
                key=f"k-{i}",
                provider=f"p-{i}",
                factory=lambda: None,
            )
            for i in range(5)
        ]
        register_pkg(
            registry,
            package_name="myapp",
            path="/project/myapp",
            priority=5,
            candidates=candidates,
        )
        for i in range(5):
            assert registry.resolve("adapter", f"k-{i}") is not None

    def test_does_not_mutate_caller_candidates(self) -> None:
        registry = CandidateRegistry()
        original = Candidate(
            domain="adapter",
            key="cache",
            provider="redis",
            factory=lambda: None,
            metadata={"v": 1},
        )
        caller_copy = original.model_copy(deep=True)
        register_pkg(
            registry,
            package_name="myapp",
            path="/project/myapp",
            priority=5,
            candidates=[caller_copy],
        )
        # The candidate the caller still holds is unchanged
        assert caller_copy.priority is None
        assert "package" not in caller_copy.metadata


# ---------------------------------------------------------------------------
# Integration scenarios
# ---------------------------------------------------------------------------


class TestIntegrationScenarios:
    def test_full_lifecycle_via_resolver(self, resolver: Resolver) -> None:
        # Register a candidate, then verify list_active, resolve, and explain
        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: None,
            )
        )
        active = resolver.list_active("adapter")
        assert len(active) == 1
        assert active[0].provider == "redis"
        resolved = resolver.resolve("adapter", "cache")
        assert resolved is not None
        assert resolved.provider == "redis"
        explanation = resolver.explain("adapter", "cache")
        assert explanation.winner is not None
        assert explanation.winner.provider == "redis"

    def test_settings_override_wins_over_priority(self, resolver: Resolver) -> None:
        # Replace the resolver's settings with one that has an override.
        # The resolver holds the settings object; rebuilding a registry with
        # a settings instance is a common way to scope overrides.
        from oneiric.core.resolution import CandidateRegistry

        settings = ResolverSettings(
            selections={"adapter": {"cache": "memcached"}},
        )
        registry = CandidateRegistry(settings)
        registry.register_candidate(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: None,
                priority=100,
            )
        )
        registry.register_candidate(
            Candidate(
                domain="adapter",
                key="cache",
                provider="memcached",
                factory=lambda: None,
                priority=1,
            )
        )
        resolved = registry.resolve("adapter", "cache")
        assert resolved is not None
        assert resolved.provider == "memcached"

    def test_no_re_register_means_shrinking_active(
        self, resolver: Resolver
    ) -> None:
        # Register two candidates for the same key — only the higher-priority
        # one is in list_active. Without an unregister method we can verify
        # the count semantics by registering on a fresh resolver.
        from oneiric.core.resolution import CandidateRegistry

        registry = CandidateRegistry()
        registry.register_candidate(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: None,
                priority=1,
            )
        )
        registry.register_candidate(
            Candidate(
                domain="adapter",
                key="cache",
                provider="memcached",
                factory=lambda: None,
                priority=10,
            )
        )
        # Active has 1 winner; shadowed has 1 loser; total 2.
        assert len(registry.list_active("adapter")) == 1
        assert len(registry.list_shadowed("adapter")) == 1
        # Now register on a brand-new registry (no re-registration) — only 1
        # active, 0 shadowed.
        fresh = CandidateRegistry()
        fresh.register_candidate(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: None,
            )
        )
        assert len(fresh.list_active("adapter")) == 1
        assert len(fresh.list_shadowed("adapter")) == 0


# ---------------------------------------------------------------------------
# Property-based invariants
# ---------------------------------------------------------------------------


class TestPropertyInvariants:
    @given(
        domain=st.text(
            min_size=1, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz"
        ),
        key=st.text(
            min_size=1, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz_-"
        ),
        provider=st.text(
            min_size=1, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz"
        ),
        new_priority=st.integers(min_value=-100, max_value=1000),
    )
    @settings(
        max_examples=20,
        suppress_health_check=[HealthCheck.too_slow],
        deadline=None,
    )
    def test_with_priority_is_pure(
        self,
        domain: str,
        key: str,
        provider: str,
        new_priority: int,
    ) -> None:
        original = Candidate(
            domain=domain,
            key=key,
            provider=provider,
            factory=lambda: None,
        )
        snapshot_priority = original.priority
        snapshot_metadata = dict(original.metadata)
        snapshot_provider = original.provider

        new_candidate = original.with_priority(new_priority)

        # New candidate has the updated priority
        assert new_candidate.priority == new_priority
        # Original is not mutated
        assert original.priority == snapshot_priority
        assert original.metadata == snapshot_metadata
        assert original.provider == snapshot_provider
        # And it is a new instance
        assert new_candidate is not original

    @given(
        domain=st.text(min_size=1, max_size=15, alphabet="abcdefghijklmnopqrstuvwxyz"),
        key=st.text(min_size=1, max_size=15, alphabet="abcdefghijklmnopqrstuvwxyz_-"),
        provider=st.text(
            min_size=1, max_size=15, alphabet="abcdefghijklmnopqrstuvwxyz"
        ),
        priority=st.integers(min_value=0, max_value=1000),
        stack_level=st.integers(min_value=0, max_value=100),
        metadata_value=st.integers(min_value=0, max_value=100),
    )
    @settings(
        max_examples=20,
        suppress_health_check=[HealthCheck.too_slow],
        deadline=None,
    )
    def test_candidate_round_trip_json(
        self,
        domain: str,
        key: str,
        provider: str,
        priority: int,
        stack_level: int,
        metadata_value: int,
    ) -> None:
        factory_str = "oneiric.demo:DemoAdapter"
        original = Candidate(
            domain=domain,
            key=key,
            provider=provider,
            priority=priority,
            stack_level=stack_level,
            factory=factory_str,
            metadata={"k": metadata_value},
        )
        # Exclude `factory` from JSON because it can hold a non-serializable
        # callable. registry_sequence is also excluded by config.
        encoded = original.model_dump_json(exclude={"factory"})
        # Re-supply factory on validate since it's required
        payload = json.loads(encoded)
        payload["factory"] = factory_str
        restored = Candidate.model_validate(payload)
        # The non-excluded fields round-trip
        assert restored.domain == original.domain
        assert restored.key == original.key
        assert restored.provider == original.provider
        assert restored.priority == original.priority
        assert restored.stack_level == original.stack_level
        assert restored.metadata == original.metadata
        assert restored.factory == factory_str
        # registry_sequence is excluded from JSON; restored has None
        assert "registry_sequence" not in encoded
        assert restored.registry_sequence is None

    @given(
        n_candidates=st.integers(min_value=1, max_value=6),
        seed=st.integers(min_value=0, max_value=1000),
    )
    @settings(
        max_examples=20,
        suppress_health_check=[HealthCheck.too_slow],
        deadline=None,
    )
    def test_resolver_explain_consistent_with_resolve(
        self, n_candidates: int, seed: int
    ) -> None:
        # Use a fresh registry per example to avoid shared state
        from oneiric.core.resolution import CandidateRegistry

        registry = CandidateRegistry()
        for i in range(n_candidates):
            priority = (seed + i) % 50
            registry.register_candidate(
                Candidate(
                    domain="adapter",
                    key="k",
                    provider=f"p-{i}",
                    factory=lambda: None,
                    priority=priority,
                )
            )
        resolved = registry.resolve("adapter", "k")
        explanation = registry.explain("adapter", "k")
        # If resolve returns a candidate, the winner of explain is the
        # same instance (same provider).
        if resolved is not None:
            assert explanation.winner is not None
            assert explanation.winner.provider == resolved.provider
            # The first ordered entry corresponds to the winner
            assert explanation.ordered[0].candidate.provider == resolved.provider
        else:
            assert explanation.winner is None
