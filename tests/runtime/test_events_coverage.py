from __future__ import annotations

import pytest

from oneiric.runtime.events import (
    EventDispatcher,
    EventEnvelope,
    EventFilter,
    EventHandler,
    _resolve_filter_path,
    create_event_envelope,
    parse_event_filters,
)


def test_event_filter_path_resolution_and_matching():
    envelope = EventEnvelope(
        topic="demo.topic",
        payload={"outer": {"inner": "value"}, "status": "ok"},
        headers={"tenant": "alpha"},
    )

    assert _resolve_filter_path(envelope, "topic") == "demo.topic"
    assert _resolve_filter_path(envelope, "payload.outer.inner") == "value"
    assert _resolve_filter_path(envelope, "headers.tenant") == "alpha"
    assert _resolve_filter_path(envelope, "payload.outer.missing") is None

    assert EventFilter(path="payload.outer.inner", exists=True).matches(envelope)
    assert not EventFilter(path="payload.outer.missing", exists=True).matches(envelope)
    assert not EventFilter(path="headers.tenant", exists=False).matches(envelope)
    assert EventFilter(path="payload.status", equals="ok").matches(envelope)
    assert not EventFilter(path="payload.status", equals="missing").matches(envelope)
    assert EventFilter(path="payload.status", any_of=("ok", "pending")).matches(
        envelope
    )
    assert not EventFilter(path="payload.status", any_of=("missing",)).matches(envelope)


def test_parse_event_filters_handles_aliases_and_scalar_membership():
    filters = parse_event_filters(
        [
            {"path": "payload.status", "value": "ok"},
            {"field": "headers.tenant", "in": "alpha"},
            {"path": None},
        ]
    )

    assert len(filters) == 2
    assert filters[0].path == "payload.status"
    assert filters[0].equals == "ok"
    assert filters[1].path == "headers.tenant"
    assert filters[1].any_of == ("alpha",)


@pytest.mark.anyio
async def test_dispatch_returns_empty_for_no_candidates():
    dispatcher = EventDispatcher(
        [
            EventHandler(
                name="scoped",
                callback=lambda event: pytest.fail("should not run"),
                topics=("other.topic",),
            )
        ]
    )

    results = await dispatcher.dispatch(
        EventEnvelope(topic="demo.topic", payload={"value": 1})
    )

    assert results == []


@pytest.mark.anyio
async def test_dispatch_uses_exclusive_handler_and_normalizes_retry_window():
    calls: list[str] = []

    async def handler(event: EventEnvelope) -> str:
        calls.append(event.topic)
        return "ok"

    dispatcher = EventDispatcher(
        [
            EventHandler(
                name="broadcast",
                callback=handler,
                priority=1,
            ),
            EventHandler(
                name="exclusive",
                callback=handler,
                priority=10,
                fanout_policy="exclusive",
                retry_policy={
                    "attempts": 2,
                    "base_delay": 0.05,
                    "max_delay": 0.01,
                    "jitter": 0.0,
                },
            ),
        ]
    )

    results = await dispatcher.dispatch(
        EventEnvelope(topic="demo.topic", payload={"value": 1})
    )

    assert [result.handler for result in results] == ["exclusive"]
    assert results[0].success is True
    assert results[0].attempts == 1
    assert calls == ["demo.topic"]


# ---------------------------------------------------------------------------
# Gap-fill: uncovered branches in runtime/events.py
# ---------------------------------------------------------------------------


def test_create_event_envelope_with_optional_ids_and_headers():
    """create_event_envelope sets correlation_id, causation_id, headers — lines 42, 44, 46."""
    envelope = create_event_envelope(
        "test.topic",
        {"key": "val"},
        source="test-source",
        correlation_id="corr-123",
        causation_id="cause-456",
        headers={"x-tenant": "alpha"},
    )
    assert envelope.headers["correlation_id"] == "corr-123"
    assert envelope.headers["causation_id"] == "cause-456"
    assert envelope.headers["x-tenant"] == "alpha"


def test_resolve_filter_path_bare_key_falls_through_to_payload():
    """_resolve_filter_path else branch uses path as attr directly — lines 65-66."""
    envelope = EventEnvelope(
        topic="t",
        payload={"status": "ok"},
        headers={},
    )
    # A path without "topic", "payload.", or "headers." prefix hits the else branch
    result = _resolve_filter_path(envelope, "status")
    assert result == "ok"  # else branch: target=payload, attr_path="status"


def test_parse_event_filters_scalar_any_of_wrapped_in_tuple():
    """parse_event_filters wraps non-sequence any_of in a tuple — line 109."""
    filters = parse_event_filters(
        [{"path": "payload.status", "any_of": "ok"}]  # string, not a list
    )
    assert len(filters) == 1
    assert filters[0].any_of == ("ok",)


def test_parse_event_filters_sequence_any_of_converted_to_tuple():
    """parse_event_filters converts a list any_of to a tuple — line 109."""
    filters = parse_event_filters(
        [{"path": "payload.status", "any_of": ["ok", "pending"]}]
    )
    assert len(filters) == 1
    assert filters[0].any_of == ("ok", "pending")


def test_event_dispatcher_register_adds_handler_sorted():
    """EventDispatcher.register() appends and re-sorts by priority — lines 163-164."""
    dispatcher = EventDispatcher()

    low_handler = EventHandler(name="low", callback=lambda e: None, priority=1)
    high_handler = EventHandler(name="high", callback=lambda e: None, priority=10)

    dispatcher.register(low_handler)
    dispatcher.register(high_handler)

    ordered = dispatcher.handlers()
    assert ordered[0].name == "high"
    assert ordered[1].name == "low"
