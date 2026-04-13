"""Tests for oneiric.core.resolution data structures and pure logic."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from oneiric.core.resolution import (
    Candidate,
    CandidateRank,
    CandidateSource,
    ResolutionExplanation,
    ResolverSettings,
)


# ---------------------------------------------------------------------------
# CandidateSource enum
# ---------------------------------------------------------------------------

class TestCandidateSource:
    def test_values(self) -> None:
        assert CandidateSource.LOCAL_PKG == "local_pkg"
        assert CandidateSource.REMOTE_MANIFEST == "remote_manifest"
        assert CandidateSource.ENTRY_POINT == "entry_point"
        assert CandidateSource.MANUAL == "manual"


# ---------------------------------------------------------------------------
# Candidate
# ---------------------------------------------------------------------------

class TestCandidate:
    def test_minimal(self) -> None:
        c = Candidate(domain="adapter", key="cache", factory=lambda: None)
        assert c.domain == "adapter"
        assert c.key == "cache"
        assert c.provider is None
        assert c.priority is None
        assert c.source == CandidateSource.LOCAL_PKG
        assert c.metadata == {}

    def test_full(self) -> None:
        c = Candidate(
            domain="service", key="auth", provider="google",
            priority=10, stack_level=2, factory=lambda: None,
            source=CandidateSource.REMOTE_MANIFEST,
            metadata={"version": "1.0"},
        )
        assert c.provider == "google"
        assert c.priority == 10
        assert c.metadata == {"version": "1.0"}

    def test_with_priority(self) -> None:
        c = Candidate(domain="adapter", key="cache", factory=lambda: None)
        c2 = c.with_priority(5)
        assert c2.priority == 5
        assert c.priority is None  # original unchanged

    def test_registered_at_defaults_to_now(self) -> None:
        before = datetime.now(UTC)
        c = Candidate(domain="adapter", key="cache", factory=lambda: None)
        after = datetime.now(UTC)
        assert before <= c.registered_at <= after

    def test_model_copy_deep(self) -> None:
        c = Candidate(
            domain="adapter", key="cache", factory=lambda: None,
            metadata={"a": 1},
        )
        c2 = c.model_copy(deep=True)
        c2.metadata["a"] = 2
        assert c.metadata["a"] == 1


# ---------------------------------------------------------------------------
# ResolverSettings
# ---------------------------------------------------------------------------

class TestResolverSettings:
    def test_defaults(self) -> None:
        rs = ResolverSettings()
        assert rs.default_priority == 0
        assert rs.selections == {}

    def test_selection_for(self) -> None:
        rs = ResolverSettings(
            selections={"adapter": {"cache": "redis"}},
        )
        assert rs.selection_for("adapter", "cache") == "redis"

    def test_selection_for_missing_domain(self) -> None:
        rs = ResolverSettings()
        assert rs.selection_for("service", "auth") is None

    def test_selection_for_missing_key(self) -> None:
        rs = ResolverSettings(selections={"adapter": {}})
        assert rs.selection_for("adapter", "cache") is None


# ---------------------------------------------------------------------------
# CandidateRank
# ---------------------------------------------------------------------------

class TestCandidateRank:
    def test_defaults(self) -> None:
        c = Candidate(domain="adapter", key="cache", factory=lambda: None)
        rank = CandidateRank(candidate=c, score=(10, 5, 2, 1), reasons=["high priority"])
        assert rank.candidate is c
        assert rank.score == (10, 5, 2, 1)
        assert rank.reasons == ["high priority"]
        assert rank.selected is False


# ---------------------------------------------------------------------------
# ResolutionExplanation
# ---------------------------------------------------------------------------

class TestResolutionExplanation:
    def _make_candidate(self, provider: str) -> Candidate:
        return Candidate(
            domain="adapter", key="cache", provider=provider, factory=lambda: None,
        )

    def test_winner_none_when_no_selections(self) -> None:
        c1 = self._make_candidate("redis")
        c2 = self._make_candidate("memcached")
        r1 = CandidateRank(candidate=c1, score=(10, 0, 0, 0), reasons=[], selected=False)
        r2 = CandidateRank(candidate=c2, score=(5, 0, 0, 0), reasons=[], selected=False)
        explanation = ResolutionExplanation(domain="adapter", key="cache", ordered=[r1, r2])
        assert explanation.winner is None

    def test_winner_returns_selected(self) -> None:
        c1 = self._make_candidate("redis")
        c2 = self._make_candidate("memcached")
        r1 = CandidateRank(candidate=c1, score=(10, 0, 0, 0), reasons=[], selected=True)
        r2 = CandidateRank(candidate=c2, score=(5, 0, 0, 0), reasons=[], selected=False)
        explanation = ResolutionExplanation(domain="adapter", key="cache", ordered=[r1, r2])
        assert explanation.winner is c1

    def test_as_dict(self) -> None:
        c = self._make_candidate("redis")
        rank = CandidateRank(candidate=c, score=(10, 5, 0, 0), reasons=["best"], selected=True)
        explanation = ResolutionExplanation(domain="adapter", key="cache", ordered=[rank])
        d = explanation.as_dict()
        assert d["domain"] == "adapter"
        assert d["key"] == "cache"
        assert len(d["ordered"]) == 1
        assert d["ordered"][0]["provider"] == "redis"
        assert d["ordered"][0]["score"] == (10, 5, 0, 0)
        assert d["ordered"][0]["selected"] is True

    def test_winner_none_when_empty(self) -> None:
        explanation = ResolutionExplanation(domain="adapter", key="cache", ordered=[])
        assert explanation.winner is None
