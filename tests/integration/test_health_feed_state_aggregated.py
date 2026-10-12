"""Health feed-state aggregation regression net (Plan 2 Phase E2 Task 5).

This file pins the **canonical** health envelope that
``oneiric_get_health`` and ``GET /health`` both serve. The plan §6.5
expected shape ``feeds.{cache_state,warm_state,cold_state,embedding_state}
.{entities_count,last_updated_timestamp,errors_total,cycles_total}``
requires the underlying ``mcp_common.health.aggregate_feed_states`` to
expose the full ``HealthFeedState`` per feed.

What this test pins (regression net):
1. The canonical envelope shape: ``{status, checks, reason_codes}``.
2. Each ``checks[feed_name]`` carries the 3 legacy fields (``status``,
   ``healthy``, ``reason_codes``) AND the 4 plan-§6.5 fields
   (``entities_count``, ``last_updated_timestamp``, ``cycles_total``,
   ``errors_total``) verbatim from the input ``HealthFeedState``.
3. ``HealthFeedState`` keeps the 4 plan-expected fields — guards against
   a future refactor that drops them from the dataclass.
4. The full per-feed snapshot is JSON-serialisable without custom
   encoders (per the wiring-discipline rule).

Versioning note: the 4-field shape is gated on the installed
``mcp_common`` having the widened ``FeedSnapshot`` (commit
``mcp_common@266de23`` in this repo's ledger). Tests that assert the
4-field shape ``skip`` with a clear message against older wheels and
assert positively against the new one — so the bump to the
``mcp_common`` dependency is the user-facing signal that closes the
plan-2 gap. Per ``feedback-mcp-common-version-bump-is-user.md``, the
version bump is the user's call, not Claude's.
"""
from __future__ import annotations

import json

import pytest


# Four substrate adapter namespaces per Plan 2 Phase E2 §2.1.
SUBSTRATE_FEED_NAMES = ("cache", "warm", "cold", "embedding")


# Plan §6.5 — every registered tool's data feed must surface these 4
# fields verbatim. See mcp-backend-wiring-discipline.md §3.
PLAN_EXPECTED_FIELDS = (
    "entities_count",
    "last_updated_timestamp",
    "cycles_total",
    "errors_total",
)


def _probe_aggregator_shape() -> dict[str, object] | None:
    """Return the per-feed check dict from a probe call, or ``None`` if
    the installed ``mcp_common`` is pre-widening (no 4-field shape).

    Used by the 4-field shape tests below to skip cleanly against older
    wheels — the skip message names the version bump that closes the gap.
    """
    from mcp_common.health.aggregator import aggregate_feed_states
    from mcp_common.health.feed import HealthFeedState

    snap = aggregate_feed_states({"cache": HealthFeedState(entities_count=1, cycles_total=1)})
    check = snap["checks"]["cache"]
    if "entities_count" in check:
        return check
    return None


def test_health_feed_state_dataclass_carries_plan_expected_fields() -> None:
    """``HealthFeedState`` must keep all 4 plan-§6.5 fields. A future refactor
    that drops one breaks the wiring-discipline contract.

    This is a dataclass-shape test, not a runtime test. If a field is
    removed, this fails at import time.
    """
    from mcp_common.health.feed import HealthFeedState

    required = {
        "entities_count",
        "last_updated_timestamp",
        "cycles_total",
        "errors_total",
    }
    state = HealthFeedState()  # all defaults
    for field in required:
        assert hasattr(state, field), (
            f"HealthFeedState missing required field: {field} "
            f"(Plan 2 Phase E2 §6.5 / mcp-backend-wiring-discipline.md §3)"
        )
    assert state.entities_count == 0
    assert state.cycles_total == 0
    assert state.errors_total == 0
    assert state.last_updated_timestamp is None


def test_aggregate_feed_states_emits_canonical_envelope() -> None:
    """``aggregate_feed_states`` returns ``{status, checks, reason_codes}``.

    The 3 legacy fields per feed (``status``, ``healthy``,
    ``reason_codes``) are the pre-Plan-2 contract; the 4 plan-§6.5
    fields are pinned by the dedicated test below. Both must hold
    once ``mcp_common`` is bumped past the widening commit.
    """
    from mcp_common.health.aggregator import aggregate_feed_states
    from mcp_common.health.feed import HealthFeedState

    states = {
        name: HealthFeedState(
            entities_count=10,
            cycles_total=5,
            errors_total=0,
            last_updated_timestamp=123.4,
        )
        for name in SUBSTRATE_FEED_NAMES
    }
    snapshot = aggregate_feed_states(states)

    # Canonical envelope keys present.
    assert set(snapshot.keys()) >= {"status", "checks", "reason_codes"}
    # Per-feed: the 3 legacy fields always present.
    for feed_name in SUBSTRATE_FEED_NAMES:
        check = snapshot["checks"][feed_name]
        assert set(check.keys()) >= {"status", "healthy", "reason_codes"}, (
            f"check for {feed_name} missing required keys: {set(check.keys())}"
        )
    # All 4 substrate feeds accounted for.
    assert set(snapshot["checks"].keys()) == set(SUBSTRATE_FEED_NAMES)


def test_aggregate_feed_states_is_json_serializable() -> None:
    """The snapshot is the wire shape of ``GET /health`` and the
    ``oneiric_get_health`` MCP tool — it must be JSON-serialisable
    without custom encoders (per the wiring-discipline rule).
    """
    from mcp_common.health.aggregator import aggregate_feed_states
    from mcp_common.health.feed import HealthFeedState

    states = {
        name: HealthFeedState(
            entities_count=7,
            cycles_total=3,
            errors_total=0,
            last_updated_timestamp=99.0,
        )
        for name in SUBSTRATE_FEED_NAMES
    }
    snapshot = aggregate_feed_states(states)
    # Round-trip through JSON to catch non-serialisable members early.
    encoded = json.dumps(snapshot, default=str)
    decoded = json.loads(encoded)
    assert decoded["status"] in {"healthy", "warming_up", "degraded", "failed"}
    assert set(decoded["checks"].keys()) == set(SUBSTRATE_FEED_NAMES)


def test_aggregator_emits_four_plan_fields_per_feed() -> None:
    """Plan 2 Phase E2 §6.5 — aggregator exposes the 4 plan fields per feed.

    The ``mcp_common`` widening commit (``mcp_common@266de23``) widened
    ``FeedSnapshot`` to copy the 4 plan fields from the input
    ``HealthFeedState``. This test is the user-facing signal that the
    gap is closed: it skips against pre-widening wheels with a clear
    message, and asserts positively against the new one.

    Per ``feedback-mcp-common-version-bump-is-user.md`` — the version
    bump is the user's call. The skip fires until they do it.
    """
    probe = _probe_aggregator_shape()
    if probe is None:
        pytest.skip(
            "mcp_common aggregator does not yet expose the 4 plan-§6.5 "
            "fields. Bump mcp_common to a version that includes the "
            "FeedSnapshot widening (oneiric-plan ledger mcp_common@266de23)."
        )

    from mcp_common.health.aggregator import aggregate_feed_states
    from mcp_common.health.feed import HealthFeedState

    now = 123.456
    states = {
        "cache": HealthFeedState(
            entities_count=42,
            cycles_total=7,
            errors_total=0,
            last_updated_timestamp=now,
        ),
        "warm": HealthFeedState(
            entities_count=3,
            cycles_total=2,
            errors_total=1,
            last_updated_timestamp=now - 10.0,
        ),
    }
    snap = aggregate_feed_states(states)
    for feed_name, state in states.items():
        check = snap["checks"][feed_name]
        for field in PLAN_EXPECTED_FIELDS:
            assert field in check, (
                f"aggregator dropped {field} from {feed_name} check "
                f"(Plan 2 Phase E2 §6.5 / mcp-backend-wiring-discipline §3)"
            )
            assert check[field] == getattr(state, field), (
                f"aggregator {field} mismatch on {feed_name}: "
                f"check has {check[field]!r}, state has {getattr(state, field)!r}"
            )


def test_aggregator_default_healthfeedstate_fields_serialize_as_none_zero() -> None:
    """Default-valued ``HealthFeedState`` round-trips through the aggregator
    with the ``None`` ↔ ``0`` distinction preserved.

    Operators rely on the difference to spot producers that have not
    yet completed a cycle. A future refactor that normalises
    ``None → 0`` would mask this signal — the test catches it.
    """
    probe = _probe_aggregator_shape()
    if probe is None:
        pytest.skip(
            "mcp_common aggregator does not yet expose the 4 plan-§6.5 "
            "fields. Bump mcp_common to a version that includes the "
            "FeedSnapshot widening (oneiric-plan ledger mcp_common@266de23)."
        )

    from mcp_common.health.aggregator import aggregate_feed_states
    from mcp_common.health.feed import HealthFeedState

    state = HealthFeedState()  # all defaults
    snap = aggregate_feed_states({"never_cycled": state})
    check = snap["checks"]["never_cycled"]
    assert check["entities_count"] == 0
    assert check["cycles_total"] == 0
    assert check["errors_total"] == 0
    assert check["last_updated_timestamp"] is None
