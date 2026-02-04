from __future__ import annotations

from contextlib import contextmanager

import httpx
import pytest

from oneiric.core.http_instrumentation import observed_http_request


class DummySpan:
    def __init__(self) -> None:
        self.exceptions: list[Exception] = []
        self.attributes: list[dict[str, object]] = []

    def record_exception(self, exc: Exception) -> None:
        self.exceptions.append(exc)

    def set_attributes(self, attrs: dict[str, object]) -> None:
        self.attributes.append(dict(attrs))


def _patch_observed_span(monkeypatch: pytest.MonkeyPatch) -> dict[str, DummySpan]:
    holder: dict[str, DummySpan] = {}

    @contextmanager
    def _observed_span(*args, **kwargs):  # type: ignore[no-untyped-def]
        span = DummySpan()
        holder["span"] = span
        yield span

    monkeypatch.setattr("oneiric.core.http_instrumentation.observed_span", _observed_span)
    return holder


@pytest.mark.asyncio
async def test_observed_http_request_records_success_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    holder = _patch_observed_span(monkeypatch)
    calls: list[dict[str, object]] = []

    def _record_metrics(**kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(
        "oneiric.adapters.metrics.record_adapter_request_metrics", _record_metrics
    )

    async def _send() -> httpx.Response:
        return httpx.Response(204, request=httpx.Request("GET", "https://example.com"))

    response = await observed_http_request(
        domain="adapter",
        key="alpha",
        adapter="http",
        provider="test",
        operation="GET",
        url="https://example.com",
        component="test",
        span_name="http.request",
        send=_send,
    )

    assert response.status_code == 204
    assert len(calls) == 1
    call = calls[0]
    assert call["domain"] == "adapter"
    assert call["adapter"] == "http"
    assert call["provider"] == "test"
    assert call["operation"] == "GET"
    assert call["success"] is True
    assert call["timeout"] is False
    assert call["duration_ms"] >= 0
    span = holder["span"]
    assert any(attrs.get("http.status_code") == 204 for attrs in span.attributes)


@pytest.mark.asyncio
async def test_observed_http_request_records_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    holder = _patch_observed_span(monkeypatch)
    calls: list[dict[str, object]] = []

    def _record_metrics(**kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(
        "oneiric.adapters.metrics.record_adapter_request_metrics", _record_metrics
    )

    async def _send() -> httpx.Response:
        raise httpx.TimeoutException("boom")

    with pytest.raises(httpx.TimeoutException):
        await observed_http_request(
            domain="adapter",
            key="alpha",
            adapter="http",
            provider="test",
            operation="GET",
            url="https://example.com",
            component="test",
            span_name="http.request",
            send=_send,
        )

    assert calls[0]["success"] is False
    assert calls[0]["timeout"] is True
    span = holder["span"]
    assert len(span.exceptions) == 1
    assert any(attrs.get("http.timeout") is True for attrs in span.attributes)


@pytest.mark.asyncio
async def test_observed_http_request_records_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    holder = _patch_observed_span(monkeypatch)
    calls: list[dict[str, object]] = []

    def _record_metrics(**kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(
        "oneiric.adapters.metrics.record_adapter_request_metrics", _record_metrics
    )

    async def _send() -> httpx.Response:
        raise httpx.HTTPError("boom")

    with pytest.raises(httpx.HTTPError):
        await observed_http_request(
            domain="adapter",
            key="alpha",
            adapter="http",
            provider="test",
            operation="GET",
            url="https://example.com",
            component="test",
            span_name="http.request",
            send=_send,
        )

    assert calls[0]["success"] is False
    assert calls[0]["timeout"] is False
    span = holder["span"]
    assert len(span.exceptions) == 1
    assert any(attrs.get("oneiric.success") is False for attrs in span.attributes)
