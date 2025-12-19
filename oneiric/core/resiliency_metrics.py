"""Metrics helpers for retry/backoff and circuit breaker events."""

from __future__ import annotations

from opentelemetry import metrics

METER_NAME = "oneiric.resiliency"

_meter = metrics.get_meter(METER_NAME)
_retry_counter = _meter.create_counter(
    "oneiric_retry_attempts_total",
    unit="1",
    description="Number of retry attempts executed.",
)
_retry_exhausted_counter = _meter.create_counter(
    "oneiric_retry_exhausted_total",
    unit="1",
    description="Number of operations that exhausted retries.",
)
_retry_success_counter = _meter.create_counter(
    "oneiric_retry_success_total",
    unit="1",
    description="Number of operations that succeeded after retries.",
)
_circuit_open_counter = _meter.create_counter(
    "oneiric_circuit_open_total",
    unit="1",
    description="Number of circuit breaker open events.",
)
_circuit_retry_after_hist = _meter.create_histogram(
    "oneiric_circuit_retry_after_seconds",
    unit="s",
    description="Retry-after duration when circuit breaker is open.",
)


def record_retry_attempt(attributes: dict[str, str]) -> None:
    _retry_counter.add(1, attributes=attributes)


def record_retry_exhausted(attributes: dict[str, str]) -> None:
    _retry_exhausted_counter.add(1, attributes=attributes)


def record_retry_success(attributes: dict[str, str], attempts: int) -> None:
    if attempts > 1:
        _retry_success_counter.add(1, attributes=attributes)


def record_circuit_open(attributes: dict[str, str], retry_after: float) -> None:
    _circuit_open_counter.add(1, attributes=attributes)
    _circuit_retry_after_hist.record(max(retry_after, 0.0), attributes=attributes)
