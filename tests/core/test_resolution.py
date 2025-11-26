"""Core resolution system tests.

These tests verify the 4-tier precedence system, active/shadowed tracking,
explain API, and priority inference logic.
"""

from __future__ import annotations

import os
from typing import Optional

import pytest

from oneiric.core.resolution import (
    Candidate,
    CandidateRegistry,
    CandidateSource,
    ResolutionExplanation,
    Resolver,
    ResolverSettings,
    infer_priority,
    register_pkg,
)


class TestCandidateModel:
    """Test Candidate model behavior."""

    def test_candidate_with_priority(self):
        """with_priority creates new candidate with updated priority."""
        candidate = Candidate(
            domain="adapter",
            key="cache",
            provider="redis",
            factory=lambda: None,
            priority=5,
            source=CandidateSource.MANUAL,
        )

        updated = candidate.with_priority(10)

        # Original unchanged
        assert candidate.priority == 5
        # New candidate has updated priority
        assert updated.priority == 10
        # Other fields copied
        assert updated.domain == "adapter"
        assert updated.key == "cache"
        assert updated.provider == "redis"


class TestCandidateRegistry:
    """Test CandidateRegistry core functionality."""

    def test_empty_registry_returns_none(self):
        """Resolving from empty registry returns None."""
        registry = CandidateRegistry()
        result = registry.resolve("adapter", "cache")
        assert result is None

    def test_single_candidate_registration(self):
        """Single candidate can be registered and resolved."""
        registry = CandidateRegistry()

        candidate = Candidate(
            domain="adapter",
            key="cache",
            provider="redis",
            factory=lambda: None,
            source=CandidateSource.MANUAL,
        )
        registry.register_candidate(candidate)

        resolved = registry.resolve("adapter", "cache")
        assert resolved is not None
        assert resolved.provider == "redis"

    def test_candidate_deep_copied_on_registration(self):
        """Registered candidates are deep copied (mutations don't affect registry)."""
        registry = CandidateRegistry()

        candidate = Candidate(
            domain="adapter",
            key="cache",
            provider="redis",
            factory=lambda: None,
            metadata={"version": "1.0"},
            source=CandidateSource.MANUAL,
        )
        registry.register_candidate(candidate)

        # Mutate original
        candidate.metadata["version"] = "2.0"

        # Resolved candidate should have original value
        resolved = registry.resolve("adapter", "cache")
        assert resolved.metadata["version"] == "1.0"

    def test_sequence_increments_on_registration(self):
        """Registry sequence increments for each registration."""
        registry = CandidateRegistry()

        candidates = [
            Candidate(
                domain="adapter",
                key=f"cache-{i}",
                provider=f"provider-{i}",
                factory=lambda: None,
                source=CandidateSource.MANUAL,
            )
            for i in range(5)
        ]

        for candidate in candidates:
            registry.register_candidate(candidate)

        # Check sequence values
        for i in range(5):
            resolved = registry.resolve("adapter", f"cache-{i}")
            assert resolved.registry_sequence == i + 1

    def test_resolve_by_provider(self):
        """Resolve can filter by provider."""
        registry = CandidateRegistry()

        # Register two providers for same key
        candidate1 = Candidate(
            domain="adapter",
            key="cache",
            provider="redis",
            factory=lambda: None,
            priority=5,
            source=CandidateSource.MANUAL,
        )
        candidate2 = Candidate(
            domain="adapter",
            key="cache",
            provider="memcached",
            factory=lambda: None,
            priority=10,
            source=CandidateSource.MANUAL,
        )

        registry.register_candidate(candidate1)
        registry.register_candidate(candidate2)

        # Resolve without provider (highest priority wins)
        active = registry.resolve("adapter", "cache")
        assert active.provider == "memcached"  # Higher priority

        # Resolve by specific provider
        redis = registry.resolve("adapter", "cache", provider="redis")
        assert redis.provider == "redis"

        memcached = registry.resolve("adapter", "cache", provider="memcached")
        assert memcached.provider == "memcached"

    def test_list_active_returns_only_active_candidates(self):
        """list_active returns only active candidates for domain."""
        registry = CandidateRegistry()

        # Register multiple adapters
        for i in range(3):
            registry.register_candidate(
                Candidate(
                    domain="adapter",
                    key=f"cache-{i}",
                    provider=f"provider-{i}",
                    factory=lambda: None,
                    source=CandidateSource.MANUAL,
                )
            )

        # Register multiple services
        for i in range(2):
            registry.register_candidate(
                Candidate(
                    domain="service",
                    key=f"worker-{i}",
                    provider=f"provider-{i}",
                    factory=lambda: None,
                    source=CandidateSource.MANUAL,
                )
            )

        # List active adapters
        adapters = registry.list_active("adapter")
        assert len(adapters) == 3
        assert all(c.domain == "adapter" for c in adapters)

        # List active services
        services = registry.list_active("service")
        assert len(services) == 2
        assert all(c.domain == "service" for c in services)

    def test_list_shadowed_returns_only_shadowed_candidates(self):
        """list_shadowed returns candidates that were shadowed by higher priority."""
        registry = CandidateRegistry()

        # Register two candidates for same key (different priorities)
        candidate1 = Candidate(
            domain="adapter",
            key="cache",
            provider="redis",
            factory=lambda: None,
            priority=5,
            source=CandidateSource.MANUAL,
        )
        candidate2 = Candidate(
            domain="adapter",
            key="cache",
            provider="memcached",
            factory=lambda: None,
            priority=10,  # Higher priority
            source=CandidateSource.MANUAL,
        )

        registry.register_candidate(candidate1)
        registry.register_candidate(candidate2)

        # Check active
        active = registry.list_active("adapter")
        assert len(active) == 1
        assert active[0].provider == "memcached"

        # Check shadowed
        shadowed = registry.list_shadowed("adapter")
        assert len(shadowed) == 1
        assert shadowed[0].provider == "redis"


class TestResolutionPrecedence:
    """Test 4-tier precedence: override > priority > stack > sequence."""

    def test_tier1_explicit_override_wins(self):
        """Tier 1: Explicit selection override beats all other factors."""
        settings = ResolverSettings(
            selections={
                "adapter": {"cache": "memcached"}  # Explicit override
            }
        )
        registry = CandidateRegistry(settings)

        # Register redis with higher priority
        registry.register_candidate(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: None,
                priority=100,  # Higher priority
                stack_level=50,  # Higher stack
                source=CandidateSource.MANUAL,
            )
        )

        # Register memcached with lower priority
        registry.register_candidate(
            Candidate(
                domain="adapter",
                key="cache",
                provider="memcached",
                factory=lambda: None,
                priority=1,  # Lower priority
                stack_level=1,  # Lower stack
                source=CandidateSource.MANUAL,
            )
        )

        # Override should win despite lower priority/stack
        resolved = registry.resolve("adapter", "cache")
        assert resolved.provider == "memcached"

    def test_tier2_priority_beats_stack_and_sequence(self):
        """Tier 2: Priority beats stack level and registration order."""
        registry = CandidateRegistry()

        # Register in order: low priority first, high priority last
        registry.register_candidate(
            Candidate(
                domain="adapter",
                key="cache",
                provider="first",
                factory=lambda: None,
                priority=1,  # Low priority
                stack_level=100,  # High stack (should be ignored)
                source=CandidateSource.MANUAL,
            )
        )

        registry.register_candidate(
            Candidate(
                domain="adapter",
                key="cache",
                provider="second",
                factory=lambda: None,
                priority=50,  # High priority
                stack_level=1,  # Low stack
                source=CandidateSource.MANUAL,
            )
        )

        # High priority should win
        resolved = registry.resolve("adapter", "cache")
        assert resolved.provider == "second"

    def test_tier3_stack_level_beats_registration_order(self):
        """Tier 3: Stack level beats registration order when priority is equal."""
        registry = CandidateRegistry()

        # Register in order: high stack first, low stack last
        registry.register_candidate(
            Candidate(
                domain="adapter",
                key="cache",
                provider="first",
                factory=lambda: None,
                priority=5,  # Same priority
                stack_level=100,  # High stack
                source=CandidateSource.MANUAL,
            )
        )

        registry.register_candidate(
            Candidate(
                domain="adapter",
                key="cache",
                provider="second",
                factory=lambda: None,
                priority=5,  # Same priority
                stack_level=1,  # Low stack
                source=CandidateSource.MANUAL,
            )
        )

        # Higher stack should win
        resolved = registry.resolve("adapter", "cache")
        assert resolved.provider == "first"

    def test_tier4_registration_order_is_tiebreaker(self):
        """Tier 4: Last registered wins when priority and stack are equal."""
        registry = CandidateRegistry()

        # Register two candidates with identical priority and stack
        registry.register_candidate(
            Candidate(
                domain="adapter",
                key="cache",
                provider="first",
                factory=lambda: None,
                priority=5,
                stack_level=10,
                source=CandidateSource.MANUAL,
            )
        )

        registry.register_candidate(
            Candidate(
                domain="adapter",
                key="cache",
                provider="second",
                factory=lambda: None,
                priority=5,  # Same priority
                stack_level=10,  # Same stack
                source=CandidateSource.MANUAL,
            )
        )

        # Last registered should win
        resolved = registry.resolve("adapter", "cache")
        assert resolved.provider == "second"

    def test_default_priority_applied_when_none(self):
        """Default priority is applied when candidate has no priority."""
        settings = ResolverSettings(default_priority=42)
        registry = CandidateRegistry(settings)

        candidate = Candidate(
            domain="adapter",
            key="cache",
            provider="redis",
            factory=lambda: None,
            priority=None,  # No priority specified
            source=CandidateSource.MANUAL,
        )
        registry.register_candidate(candidate)

        resolved = registry.resolve("adapter", "cache")
        assert resolved.priority == 42


class TestExplainAPI:
    """Test resolution explanation API."""

    def test_explain_empty_registry(self):
        """Explain for non-existent key returns empty explanation."""
        registry = CandidateRegistry()
        explanation = registry.explain("adapter", "cache")

        assert explanation.domain == "adapter"
        assert explanation.key == "cache"
        assert len(explanation.ordered) == 0
        assert explanation.winner is None

    def test_explain_shows_all_candidates_ordered(self):
        """Explain shows all candidates in precedence order."""
        registry = CandidateRegistry()

        # Register 3 candidates with different priorities
        candidates = [
            ("low", 1),
            ("high", 100),
            ("medium", 50),
        ]

        for provider, priority in candidates:
            registry.register_candidate(
                Candidate(
                    domain="adapter",
                    key="cache",
                    provider=provider,
                    factory=lambda: None,
                    priority=priority,
                    source=CandidateSource.MANUAL,
                )
            )

        explanation = registry.explain("adapter", "cache")

        # Should have 3 entries
        assert len(explanation.ordered) == 3

        # Should be ordered by priority (high to low)
        assert explanation.ordered[0].candidate.provider == "high"
        assert explanation.ordered[1].candidate.provider == "medium"
        assert explanation.ordered[2].candidate.provider == "low"

    def test_explain_marks_winner_as_selected(self):
        """Explain marks the winning candidate as selected."""
        registry = CandidateRegistry()

        # Register multiple candidates
        for i, priority in enumerate([1, 50, 100]):
            registry.register_candidate(
                Candidate(
                    domain="adapter",
                    key="cache",
                    provider=f"provider-{i}",
                    factory=lambda: None,
                    priority=priority,
                    source=CandidateSource.MANUAL,
                )
            )

        explanation = registry.explain("adapter", "cache")

        # Only the winner should be selected
        selected = [entry for entry in explanation.ordered if entry.selected]
        assert len(selected) == 1
        assert selected[0].candidate.provider == "provider-2"  # Highest priority

    def test_explain_includes_reasons(self):
        """Explain includes reasons for each candidate's score."""
        registry = CandidateRegistry()

        candidate = Candidate(
            domain="adapter",
            key="cache",
            provider="redis",
            factory=lambda: None,
            priority=42,
            stack_level=7,
            source=CandidateSource.MANUAL,
        )
        registry.register_candidate(candidate)

        explanation = registry.explain("adapter", "cache")

        # Check reasons for the candidate
        entry = explanation.ordered[0]
        reasons = entry.reasons

        assert any("priority=42" in r for r in reasons)
        assert any("stack_level=7" in r for r in reasons)
        assert any("registration_order=1" in r for r in reasons)

    def test_explain_shows_selection_override_reason(self):
        """Explain shows when explicit selection override is used."""
        settings = ResolverSettings(
            selections={"adapter": {"cache": "redis"}}
        )
        registry = CandidateRegistry(settings)

        # Register two candidates
        registry.register_candidate(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: None,
                priority=1,
                source=CandidateSource.MANUAL,
            )
        )
        registry.register_candidate(
            Candidate(
                domain="adapter",
                key="cache",
                provider="memcached",
                factory=lambda: None,
                priority=100,
                source=CandidateSource.MANUAL,
            )
        )

        explanation = registry.explain("adapter", "cache")

        # Redis should be selected despite lower priority
        winner = explanation.winner
        assert winner.provider == "redis"

        # Should have reason about override
        redis_entry = [e for e in explanation.ordered if e.candidate.provider == "redis"][0]
        assert any("matched selection override" in r for r in redis_entry.reasons)

    def test_explain_as_dict_serializable(self):
        """Explanation as_dict returns JSON-serializable structure."""
        registry = CandidateRegistry()

        registry.register_candidate(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: None,
                priority=5,
                source=CandidateSource.MANUAL,
            )
        )

        explanation = registry.explain("adapter", "cache")
        data = explanation.as_dict()

        assert data["domain"] == "adapter"
        assert data["key"] == "cache"
        assert len(data["ordered"]) == 1
        assert data["ordered"][0]["provider"] == "redis"
        assert data["ordered"][0]["selected"] is True
        assert "score" in data["ordered"][0]
        assert "reasons" in data["ordered"][0]


class TestPriorityInference:
    """Test priority inference from environment and path hints."""

    def test_infer_priority_from_env_exact_match(self):
        """Priority inferred from ONEIRIC_STACK_ORDER exact match."""
        os.environ["ONEIRIC_STACK_ORDER"] = "myapp:100,otherapp:50"

        priority = infer_priority("myapp", None)
        assert priority == 100

        priority = infer_priority("otherapp", None)
        assert priority == 50

        # Cleanup
        del os.environ["ONEIRIC_STACK_ORDER"]

    def test_infer_priority_from_env_auto_assign(self):
        """Priority auto-assigned from comma-separated list."""
        os.environ["ONEIRIC_STACK_ORDER"] = "first,second,third"

        priority = infer_priority("first", None)
        assert priority == 0

        priority = infer_priority("second", None)
        assert priority == 10

        priority = infer_priority("third", None)
        assert priority == 20

        # Cleanup
        del os.environ["ONEIRIC_STACK_ORDER"]

    def test_infer_priority_from_path_hints(self):
        """Priority inferred from path markers (adapters, services, etc)."""
        # Adapters path hint
        priority = infer_priority(None, "/project/adapters/cache.py")
        assert priority > 0  # Should get adapters hint (80 - depth)

        # Services path hint
        priority = infer_priority(None, "/project/services/worker.py")
        assert priority > 0  # Should get services hint (70 - depth)

        # Vendor path hint (highest)
        priority = infer_priority(None, "/project/vendor/plugin.py")
        assert priority > 0  # Should get vendor hint (90 - depth)

    def test_infer_priority_depth_penalty(self):
        """Deeper paths get lower priority."""
        shallow = infer_priority(None, "/project/adapters/cache.py")
        deep = infer_priority(None, "/project/deep/nested/path/adapters/cache.py")

        # Deeper path should have lower priority
        assert shallow > deep

    def test_infer_priority_defaults_to_zero(self):
        """Priority defaults to 0 when no env or path hints."""
        priority = infer_priority(None, None)
        assert priority == 0

        priority = infer_priority("unknown", None)
        assert priority == 0

        priority = infer_priority(None, "/random/path/file.py")
        assert priority == 0


class TestPackageRegistration:
    """Test register_pkg helper function."""

    def test_register_pkg_applies_priority(self):
        """register_pkg applies priority to all candidates."""
        registry = CandidateRegistry()

        candidates = [
            Candidate(
                domain="adapter",
                key=f"cache-{i}",
                provider=f"provider-{i}",
                factory=lambda: None,
                source=CandidateSource.LOCAL_PKG,
            )
            for i in range(3)
        ]

        register_pkg(
            registry,
            package_name="myapp",
            path="/project/myapp",
            candidates=candidates,
            priority=42,
        )

        # All candidates should have priority 42
        for i in range(3):
            resolved = registry.resolve("adapter", f"cache-{i}")
            assert resolved.priority == 42

    def test_register_pkg_adds_metadata(self):
        """register_pkg adds package and path to metadata."""
        registry = CandidateRegistry()

        candidate = Candidate(
            domain="adapter",
            key="cache",
            provider="redis",
            factory=lambda: None,
            metadata={"version": "1.0"},
            source=CandidateSource.LOCAL_PKG,
        )

        register_pkg(
            registry,
            package_name="myapp",
            path="/project/myapp/adapters",
            candidates=[candidate],
        )

        resolved = registry.resolve("adapter", "cache")
        assert resolved.metadata["package"] == "myapp"
        assert resolved.metadata["path"] == "/project/myapp/adapters"
        assert resolved.metadata["version"] == "1.0"  # Original metadata preserved

    def test_register_pkg_infers_priority_when_none(self):
        """register_pkg infers priority from package name and path."""
        registry = CandidateRegistry()

        os.environ["ONEIRIC_STACK_ORDER"] = "myapp:100"

        candidate = Candidate(
            domain="adapter",
            key="cache",
            provider="redis",
            factory=lambda: None,
            source=CandidateSource.LOCAL_PKG,
        )

        register_pkg(
            registry,
            package_name="myapp",
            path="/project/myapp",
            candidates=[candidate],
        )

        resolved = registry.resolve("adapter", "cache")
        assert resolved.priority == 100

        # Cleanup
        del os.environ["ONEIRIC_STACK_ORDER"]


class TestResolverFacade:
    """Test Resolver high-level facade."""

    def test_resolver_wraps_registry(self):
        """Resolver provides facade over CandidateRegistry."""
        resolver = Resolver()

        candidate = Candidate(
            domain="adapter",
            key="cache",
            provider="redis",
            factory=lambda: None,
            source=CandidateSource.MANUAL,
        )

        resolver.register(candidate)

        resolved = resolver.resolve("adapter", "cache")
        assert resolved is not None
        assert resolved.provider == "redis"

    def test_resolver_list_active(self):
        """Resolver list_active delegates to registry."""
        resolver = Resolver()

        for i in range(3):
            resolver.register(
                Candidate(
                    domain="adapter",
                    key=f"cache-{i}",
                    provider=f"provider-{i}",
                    factory=lambda: None,
                    source=CandidateSource.MANUAL,
                )
            )

        active = resolver.list_active("adapter")
        assert len(active) == 3

    def test_resolver_list_shadowed(self):
        """Resolver list_shadowed delegates to registry."""
        resolver = Resolver()

        # Register two candidates for same key
        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                priority=1,
                factory=lambda: None,
                source=CandidateSource.MANUAL,
            )
        )
        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="memcached",
                priority=10,
                factory=lambda: None,
                source=CandidateSource.MANUAL,
            )
        )

        shadowed = resolver.list_shadowed("adapter")
        assert len(shadowed) == 1
        assert shadowed[0].provider == "redis"

    def test_resolver_explain(self):
        """Resolver explain delegates to registry."""
        resolver = Resolver()

        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: None,
                source=CandidateSource.MANUAL,
            )
        )

        explanation = resolver.explain("adapter", "cache")
        assert explanation.domain == "adapter"
        assert explanation.key == "cache"
        assert explanation.winner is not None

    def test_resolver_register_from_pkg(self):
        """Resolver register_from_pkg delegates to register_pkg."""
        resolver = Resolver()

        candidates = [
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: None,
                source=CandidateSource.LOCAL_PKG,
            )
        ]

        resolver.register_from_pkg(
            package_name="myapp",
            path="/project/myapp",
            candidates=candidates,
            priority=42,
        )

        resolved = resolver.resolve("adapter", "cache")
        assert resolved.priority == 42
        assert resolved.metadata["package"] == "myapp"
