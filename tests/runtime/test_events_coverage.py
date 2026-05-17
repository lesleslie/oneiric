from __future__ import annotations

import pytest

from oneiric.runtime.events import (
    EventDispatcher,
    EventEnvelope,
    EventFilter,
    EventHandler,
    _resolve_filter_path,
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
    assert not EventFilter(path="payload.status", any_of=("missing",)).matches(
        envelope
    )


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
