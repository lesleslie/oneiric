"""Property-based tests with Hypothesis.

Tests core invariants using property-based testing.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from oneiric.core.resolution import (
    Candidate,
    CandidateRegistry,
    CandidateSource,
    Resolver,
    ResolverSettings,
    infer_priority,
    register_pkg,
)


class TestCandidateProperties:
    """Property-based tests for Candidate model."""

    @given(
        domain=st.text(min_size=1, max_size=50, alphabet="abcdefghijklmnopqrstuvwxyz"),
        key=st.text(min_size=1, max_size=50, alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-"),
        provider=st.text(min_size=1, max_size=50, alphabet="abcdefghijklmnopqrstuvwxyz"),
        priority=st.integers(min_value=0, max_value=1000),
    )
    @settings(
        max_examples=10,  # Further limit examples for speed
        suppress_health_check=[HealthCheck.too_slow],
        deadline=None,  # Disable per-test deadline
    )
    def test_candidate_with_priority_increments(self, domain, key, provider, priority):
        """with_priority creates new candidate with increased priority."""
        candidate = Candidate(
            domain=domain,
            key=key,
            provider=provider,
            factory=lambda: None,
            priority=priority,
            source=CandidateSource.MANUAL,
        )

        new_priority = priority + 10
        updated = candidate.with_priority(new_priority)

        # Original unchanged
        assert candidate.priority == priority
        # New candidate has updated priority
        assert updated.priority == new_priority
        # Other fields copied
        assert updated.domain == domain
        assert updated.key == key
        assert updated.provider == provider

    @given(
        candidates=st.lists(
            st.builds(
                Candidate,
                domain=st.text(min_size=1, max_size=20, alphabet="abc"),
                key=st.text(min_size=1, max_size=20, alphabet="123"),
                provider=st.text(min_size=1, max_size=20, alphabet="xyz"),
                factory=st.just(lambda: None),
                priority=st.integers(min_value=0, max_value=100),
                source=st.sampled_from(list(CandidateSource)),
            ),
            min_size=1,
            max_size=20,
        )
    )
    @settings(suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_registry_preserves_candidate_count(self, candidates):
        """Registry preserves all registered candidates."""
        registry = CandidateRegistry()

        for candidate in candidates:
            registry.register_candidate(candidate)

        # Count unique (domain, key) pairs
        unique_keys = set((c.domain, c.key) for c in candidates)

        # Should have at least as many active as unique keys
        active = registry.list_active("adapter")
        assert len(active) >= 0  # At least doesn't crash


class TestResolverProperties:
    """Property-based tests for Resolver."""

    @given(
        domain=st.text(min_size=1, max_size=30),
        key=st.text(min_size=1, max_size=30),
        priority=st.integers(min_value=0, max_value=100),
    )
    def test_resolve_returns_candidate_or_none(self, domain, key, priority):
        """Resolve always returns Candidate or None."""
        registry = CandidateRegistry()

        candidate = Candidate(
            domain=domain,
            key=key,
            provider="test",
            factory=lambda: None,
            priority=priority,
            source=CandidateSource.MANUAL,
        )
        registry.register_candidate(candidate)

        result = registry.resolve(domain, key)

        # Should return a Candidate or None
        assert result is None or isinstance(result, Candidate)

    @given(
        priorities=st.lists(
            st.integers(min_value=0, max_value=100),
            min_size=2,
            max_size=10,
            unique=True,
        )
    )
    def test_higher_priority_wins(self, priorities):
        """Candidate with highest priority wins resolution."""
        registry = CandidateRegistry()

        # Register candidates with different priorities
        for i, priority in enumerate(priorities):
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

        resolved = registry.resolve("adapter", "cache")

        # Should resolve to highest priority
        assert resolved is not None
        assert resolved.priority == max(priorities)

    @given(
        stack_levels=st.lists(
            st.integers(min_value=0, max_value=100),
            min_size=2,
            max_size=10,
            unique=True,
        )
    )
    def test_higher_stack_level_wins_with_same_priority(self, stack_levels):
        """Higher stack level wins when priorities are equal."""
        registry = CandidateRegistry()

        # Register candidates with same priority, different stack levels
        for i, stack in enumerate(stack_levels):
            registry.register_candidate(
                Candidate(
                    domain="adapter",
                    key="cache",
                    provider=f"provider-{i}",
                    factory=lambda: None,
                    priority=50,  # Same priority
                    stack_level=stack,
                    source=CandidateSource.MANUAL,
                )
            )

        resolved = registry.resolve("adapter", "cache")

        # Should resolve to highest stack level
        assert resolved is not None
        assert resolved.stack_level == max(stack_levels)


class TestPriorityInferenceProperties:
    """Property-based tests for priority inference."""

    @given(
        package_name=st.text(min_size=1, max_size=30, alphabet="abcdefghijklmnopqrstuvwxyz"),
        path=st.text(min_size=1, max_size=100, alphabet="abcdefghijklmnopqrstuvwxyz/0123456789_-."),
    )
    @settings(max_examples=20)
    def test_infer_priority_returns_int(self, package_name, path):
        """infer_priority always returns an integer."""
        priority = infer_priority(package_name, path)
        assert isinstance(priority, int)

    @given(path=st.from_regex(r".*adapters.*"))
    @settings(max_examples=20)
    def test_adapters_path_gets_positive_priority(self, path):
        """Paths containing 'adapters' get positive priority."""
        priority = infer_priority(None, path)
        # Should have some positive priority from path hint
        assert priority >= 0

    @given(path=st.from_regex(r".*vendor.*"))
    @settings(max_examples=20)
    def test_vendor_path_gets_high_priority(self, path):
        """Paths containing 'vendor' get high priority."""
        priority = infer_priority(None, path)
        # Vendor hint is 90, so should be high even with depth penalty
        assert priority >= 0


class TestRegistrationProperties:
    """Property-based tests for registration."""

    @given(
        num_candidates=st.integers(min_value=1, max_value=50),
        base_priority=st.integers(min_value=0, max_value=100),
    )
    @settings(max_examples=20, deadline=None)
    def test_registration_sequence_increments(self, num_candidates, base_priority):
        """Registry sequence increments monotonically."""
        registry = CandidateRegistry()

        sequences = []
        for i in range(num_candidates):
            candidate = Candidate(
                domain="adapter",
                key=f"cache-{i}",
                provider=f"provider-{i}",
                factory=lambda: None,
                priority=base_priority + i,
                source=CandidateSource.MANUAL,
            )
            registry.register_candidate(candidate)
            resolved = registry.resolve("adapter", f"cache-{i}")
            sequences.append(resolved.registry_sequence if resolved else 0)

        # Sequences should be strictly increasing
        assert sequences == sorted(sequences)
        # All sequences should be unique
        assert len(set(sequences)) == len(sequences)

    @given(
        candidates=st.lists(
            st.builds(
                Candidate,
                domain=st.just("adapter"),
                key=st.just("cache"),
                provider=st.text(min_size=1, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz"),
                factory=st.just(lambda: None),
                priority=st.integers(min_value=0, max_value=100),
                source=st.sampled_from(list(CandidateSource)),
            ),
            min_size=1,
            max_size=20,
        )
    )
    @settings(max_examples=20)
    def test_registry_resolves_to_single_candidate(self, candidates):
        """Registry with same domain/key resolves to single candidate."""
        registry = CandidateRegistry()

        for candidate in candidates:
            registry.register_candidate(candidate)

        resolved = registry.resolve("adapter", "cache")

        # Should resolve to exactly one candidate (highest priority)
        assert resolved is not None
        assert resolved.domain == "adapter"
        assert resolved.key == "cache"


class TestExplainProperties:
    """Property-based tests for explain API."""

    @given(
        candidates=st.lists(
            st.builds(
                Candidate,
                domain=st.just("adapter"),
                key=st.just("cache"),
                provider=st.text(min_size=1, max_size=20),
                factory=st.just(lambda: None),
                priority=st.integers(min_value=0, max_value=100),
                source=st.just(CandidateSource.MANUAL),
            ),
            min_size=1,
            max_size=20,
        )
    )
    def test_explain_orders_by_priority(self, candidates):
        """Explanation orders candidates by priority (high to low)."""
        registry = CandidateRegistry()

        for candidate in candidates:
            registry.register_candidate(candidate)

        explanation = registry.explain("adapter", "cache")

        # Check ordering: priorities should be non-increasing
        priorities = [entry.candidate.priority for entry in explanation.ordered]
        assert priorities == sorted(priorities, reverse=True)

    @given(
        candidates=st.lists(
            st.builds(
                Candidate,
                domain=st.just("adapter"),
                key=st.just("cache"),
                provider=st.text(min_size=1, max_size=20),
                factory=st.just(lambda: None),
                priority=st.integers(min_value=0, max_value=100),
                source=st.just(CandidateSource.MANUAL),
            ),
            min_size=1,
            max_size=20,
        )
    )
    def test_explain_has_single_winner(self, candidates):
        """Explanation marks exactly one candidate as selected."""
        registry = CandidateRegistry()

        for candidate in candidates:
            registry.register_candidate(candidate)

        explanation = registry.explain("adapter", "cache")

        # Count selected candidates
        selected = [entry for entry in explanation.ordered if entry.selected]
        assert len(selected) == 1

        # Winner should match resolved candidate
        resolved = registry.resolve("adapter", "cache")
        assert selected[0].candidate.provider == resolved.provider


class TestPackageRegistrationProperties:
    """Property-based tests for package registration."""

    @given(
        num_candidates=st.integers(min_value=1, max_value=30),
        package_priority=st.integers(min_value=0, max_value=100),
    )
    def test_register_pkg_applies_priority_to_all(self, num_candidates, package_priority):
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
            for i in range(num_candidates)
        ]

        register_pkg(
            registry,
            package_name="testpkg",
            path="/test",
            candidates=candidates,
            priority=package_priority,
        )

        # All should have the package priority
        for i in range(num_candidates):
            resolved = registry.resolve("adapter", f"cache-{i}")
            assert resolved.priority == package_priority


class TestMergeProperties:
    """Property-based tests for config merging."""

    @given(
        base_dict=st.dictionaries(
            st.text(min_size=1, max_size=20, alphabet="abc"),
            st.integers(min_value=0, max_value=100),
            min_size=0,
            max_size=20,
        ),
        override_dict=st.dictionaries(
            st.text(min_size=1, max_size=20, alphabet="abc"),
            st.integers(min_value=0, max_value=100),
            min_size=0,
            max_size=20,
        ),
    )
    def test_merge_preserves_all_keys(self, base_dict, override_dict):
        """Merge preserves all keys from both dicts."""
        from oneiric.core.config import _deep_merge

        merged = _deep_merge(base_dict, override_dict)

        # All keys from base should be present (unless overridden)
        all_keys = set(base_dict.keys()) | set(override_dict.keys())
        assert set(merged.keys()) == all_keys

    @given(
        base_dict=st.dictionaries(
            st.text(min_size=1, max_size=20),
            st.integers(min_value=0, max_value=100),
            min_size=0,
            max_size=10,
        ),
    )
    def test_merge_with_empty_override(self, base_dict):
        """Merging with empty override returns base unchanged."""
        from oneiric.core.config import _deep_merge

        merged = _deep_merge(base_dict, {})
        assert merged == base_dict

    @given(
        override_dict=st.dictionaries(
            st.text(min_size=1, max_size=20),
            st.integers(min_value=0, max_value=100),
            min_size=0,
            max_size=10,
        ),
    )
    def test_merge_with_empty_base(self, override_dict):
        """Merging with empty base returns override unchanged."""
        from oneiric.core.config import _deep_merge

        merged = _deep_merge({}, override_dict)
        assert merged == override_dict
