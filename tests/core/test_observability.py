from __future__ import annotations

import builtins
from contextlib import contextmanager

import pytest

from oneiric.core.observability import (
    DecisionEvent,
    ObservabilityConfig,
    configure_observability,
    get_tracer,
    inject_trace_context,
    observed_span,
    traced_decision,
)


class _DummySpan:
    def __init__(self) -> None:
        self.attributes: dict[str, object] = {}
        self.exceptions: list[BaseException] = []

    def set_attributes(self, attributes: dict[str, object]) -> None:
        self.attributes.update(attributes)

    def record_exception(self, exc: BaseException) -> None:
        self.exceptions.append(exc)


class _DummyTracer:
    def __init__(self, span: _DummySpan) -> None:
        self.span = span
        self.names: list[str] = []

    @contextmanager
    def start_as_current_span(self, name: str):
        self.names.append(name)
        yield self.span


def test_configure_observability_updates_default_scope(monkeypatch: pytest.MonkeyPatch):
    captured: list[str] = []

    def fake_get_tracer(scope: str):
        captured.append(scope)
        return object()

    monkeypatch.setattr("oneiric.core.observability.trace.get_tracer", fake_get_tracer)

    configure_observability(
        ObservabilityConfig(service_name="demo", instrumentation_scope="demo.scope")
    )

    get_tracer()
    get_tracer("explicit.scope")

    assert captured == ["demo.scope", "explicit.scope"]


def test_inject_trace_context_returns_headers_when_import_fails():
    headers = {"traceparent": "abc"}
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "opentelemetry.propagate":
            raise ImportError("boom")
        return real_import(name, globals, locals, fromlist, level)

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("builtins.__import__", fake_import)
        assert inject_trace_context(headers) is headers


def test_observed_span_sets_attributes_and_uses_log_context(
    monkeypatch: pytest.MonkeyPatch,
):
    span = _DummySpan()
    tracer = _DummyTracer(span)
    log_contexts: list[dict[str, object]] = []

    @contextmanager
    def fake_scoped_log_context(**kwargs):
        log_contexts.append(kwargs)
        yield

    monkeypatch.setattr("oneiric.core.observability.trace.get_tracer", lambda _: tracer)
    monkeypatch.setattr(
        "oneiric.core.observability.scoped_log_context", fake_scoped_log_context
    )

    with observed_span(
        "demo.span",
        component="demo.component",
        attributes={"alpha": 1},
        log_context={"request_id": "req-1"},
    ) as observed:
        assert observed is span

    assert tracer.names == ["demo.span"]
    assert span.attributes == {"alpha": 1}
    assert log_contexts == [{"request_id": "req-1"}]


def test_traced_decision_uses_event_details(monkeypatch: pytest.MonkeyPatch):
    span = _DummySpan()
    tracer = _DummyTracer(span)

    @contextmanager
    def fake_scoped_log_context(**kwargs):
        yield

    monkeypatch.setattr("oneiric.core.observability.trace.get_tracer", lambda _: tracer)
    monkeypatch.setattr(
        "oneiric.core.observability.scoped_log_context", fake_scoped_log_context
    )

    event = DecisionEvent(
        domain="adapter",
        key="cache",
        provider=None,
        decision="selected",
        details={"reason": "preferred"},
    )

    with traced_decision(event) as observed:
        assert observed is span

    assert span.attributes["provider"] == "unknown"
    assert span.attributes["reason"] == "preferred"
