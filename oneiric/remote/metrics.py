"""Remote manifest metrics helpers."""

from __future__ import annotations

from opentelemetry import metrics

METER_NAME = "oneiric.remote"

_meter = metrics.get_meter(METER_NAME)
_success_counter = _meter.create_counter(
    "oneiric_remote_sync_success_total",
    unit="1",
    description="Number of successful remote manifest syncs.",
)
_registered_counter = _meter.create_counter(
    "oneiric_remote_candidates_registered_total",
    unit="1",
    description="Total candidates registered during remote syncs.",
)
_failure_counter = _meter.create_counter(
    "oneiric_remote_sync_failure_total",
    unit="1",
    description="Number of failed remote manifest syncs.",
)
_duration_histogram = _meter.create_histogram(
    "oneiric_remote_sync_duration_ms",
    unit="ms",
    description="Duration of remote manifest syncs in milliseconds.",
)
_digest_counter = _meter.create_counter(
    "oneiric_remote_digest_checks_total",
    unit="1",
    description="Number of digest verifications performed during remote syncs.",
)


def record_remote_success_metric(*, source: str, url: str, registered: int) -> None:
    attrs = _success_attributes(source, url)
    _success_counter.add(1, attributes=attrs)
    if registered:
        _registered_counter.add(registered, attributes=attrs)


def record_remote_failure_metric(*, url: str, error: str) -> None:
    attrs = {"url": url, "error": _truncate(error)}
    _failure_counter.add(1, attributes=attrs)


def record_remote_duration_metric(*, url: str, source: str, duration_ms: float) -> None:
    attrs = _success_attributes(source, url)
    _duration_histogram.record(duration_ms, attributes=attrs)


def record_digest_checks_metric(*, url: str, count: int) -> None:
    if count <= 0:
        return
    _digest_counter.add(count, attributes={"url": url})


def _success_attributes(source: str, url: str) -> dict[str, str]:
    return {"source": source or "unknown", "url": url}


def _truncate(value: str, *, limit: int = 128) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."
