"""OpenTelemetry metrics helpers for core lifecycle + activity events."""

from __future__ import annotations

from opentelemetry import metrics

METER = metrics.get_meter("oneiric.core")

_pause_counter = METER.create_counter(
    "oneiric_activity_pause_events_total",
    unit="1",
    description="Number of pause/resume events per domain.",
)

_drain_counter = METER.create_counter(
    "oneiric_activity_drain_events_total",
    unit="1",
    description="Number of drain/clear events per domain.",
)

_swap_histogram = METER.create_histogram(
    "oneiric_lifecycle_swap_duration_ms",
    unit="ms",
    description="Lifecycle swap/activation duration in milliseconds.",
)


def record_pause_state(domain: str, paused: bool) -> None:
    """Record a pause/resume operation for the given domain."""

    _pause_counter.add(
        1, attributes={"domain": domain, "state": "paused" if paused else "resumed"}
    )


def record_drain_state(domain: str, draining: bool) -> None:
    """Record a drain/clear operation for the given domain."""

    _drain_counter.add(
        1, attributes={"domain": domain, "state": "draining" if draining else "cleared"}
    )


def record_swap_duration(
    domain: str,
    key: str,
    provider: str | None,
    duration_ms: float,
    *,
    success: bool,
) -> None:
    """Record the elapsed time for a lifecycle activation/swap."""

    attrs = {
        "domain": domain,
        "key": key,
        "provider": provider or "unknown",
        "outcome": "success" if success else "failed",
    }
    _swap_histogram.record(max(duration_ms, 0.0), attributes=attrs)
