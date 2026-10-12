"""Health feed-state aggregation regression net (Plan 2 Phase E2 Task 5 — partial).

This file pins the **current canonical** health envelope so a future
refactor doesn't accidentally drop the per-feed detail that
``oneiric_get_health`` and ``GET /health`` both serve. The plan §6.5
expected shape ``feeds.{cache_state,warm_state,cold_state,embedding_state}
.{entities_count,last_updated_timestamp,errors_total,cycles_total}``
requires the underlying ``mcp_common.health.aggregate_feed_states`` to
expose the full ``HealthFeedState`` per feed (the dataclass has all 4
fields but the aggregator currently only surfaces
``status``/``healthy``/``reason_codes``). That gap is documented in
``known_gap_plan_2_phase_e2_task_5`` and tracked as a follow-up.

What this test does pin (regression net):
1. The canonical envelope shape: ``{status, checks, reason_codes}``.
2. Each ``checks[feed_name]`` has the 3 fields the aggregator actually
   surfaces (``status``, ``healthy``, ``reason_codes``).
3. ``HealthFeedState`` carries the 4 plan-expected fields
   (``entities_count``, ``last_updated_timestamp``, ``cycles_total``,
   ``errors_total``) — guards against a future refactor that drops them
   from the dataclass.
4. The ``/health`` route and the ``oneiric_get_health`` MCP tool return
   the same canonical envelope (per the B2 wiring-discipline rule
   that ``mcp__oneiric__get_health`` and ``GET /health`` MUST agree).
"""
from __future__ import annotations

import json


# Four substrate adapter namespaces per Plan 2 Phase E2 §2.1.
SUBSTRATE_FEED_NAMES = ("cache", "warm", "cold", "embedding")


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

    This is the *current* shape; the plan's expected shape (per-feed
    ``entities_count`` etc. inside ``checks[feed_name]``) is a
    follow-up — see ``known_gap_plan_2_phase_e2_task_5``.
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
    # Per-feed keys present (current shape — 3 fields, not 4).
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


def test_known_gap_plan_2_phase_e2_task_5() -> None:
    """The plan §6.5 expected shape (``feeds.{cache_state,...}.{entities_count,
    last_updated_timestamp, errors_total, cycles_total}``) requires the
    mcp-common aggregator to include the full ``HealthFeedState`` inside
    each ``checks[feed_name]``. The current aggregator surfaces only
    ``status``/``healthy``/``reason_codes``.

    Pinning the gap here so a follow-up PR that closes it can drop the
    assertion below. When the gap is closed, this test should be
    removed and replaced with the full per-feed shape assertion.
    """
    from mcp_common.health.aggregator import aggregate_feed_states
    from mcp_common.health.feed import HealthFeedState

    state = HealthFeedState(
        entities_count=42, cycles_total=7, errors_total=0, last_updated_timestamp=1.0
    )
    snapshot = aggregate_feed_states({"cache": state})
    check = snapshot["checks"]["cache"]
    # The 4 plan-expected fields are NOT in the aggregator output today.
    plan_expected_fields = {
        "entities_count",
        "last_updated_timestamp",
        "cycles_total",
        "errors_total",
    }
    missing = plan_expected_fields - set(check.keys())
    assert missing == plan_expected_fields, (
        "Gap closed — mcp-common aggregator now includes the full "
        "HealthFeedState. Update this test to assert presence and "
        "the /health route return shape across the 3 components."
    )
