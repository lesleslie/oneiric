"""Adapter-level metrics helpers."""

from __future__ import annotations

from typing import Any

from opentelemetry import metrics

METER_NAME = "oneiric.adapters"

_meter = metrics.get_meter(METER_NAME)
_duration_hist = _meter.create_histogram(
    "oneiric_adapter_request_duration_ms",
    unit="ms",
    description="Duration of adapter operations in milliseconds.",
)
_error_counter = _meter.create_counter(
    "oneiric_adapter_request_errors_total",
    unit="1",
    description="Total adapter operation errors.",
)
_timeout_counter = _meter.create_counter(
    "oneiric_adapter_request_timeouts_total",
    unit="1",
    description="Total adapter operation timeouts.",
)
_pool_hist = _meter.create_histogram(
    "oneiric_adapter_pool_size",
    unit="1",
    description="Observed adapter connection/pool size.",
)
_queue_hist = _meter.create_histogram(
    "oneiric_adapter_queue_depth",
    unit="1",
    description="Observed adapter queue/backlog depth.",
)


def record_adapter_request_metrics(
    *,
    domain: str,
    adapter: str,
    provider: str,
    operation: str,
    duration_ms: float,
    success: bool,
    timeout: bool = False,
) -> None:
    attrs = {
        "domain": domain,
        "adapter": adapter,
        "provider": provider,
        "operation": operation,
        "outcome": "success" if success else "failed",
    }
    _duration_hist.record(max(duration_ms, 0.0), attributes=attrs)
    if not success:
        _error_counter.add(1, attributes=attrs)
    if timeout:
        _timeout_counter.add(1, attributes=attrs)


def record_adapter_pool_size(
    *,
    domain: str,
    adapter: str,
    provider: str,
    size: float,
) -> None:
    attrs = {"domain": domain, "adapter": adapter, "provider": provider}
    _pool_hist.record(max(size, 0.0), attributes=attrs)


def record_adapter_queue_depth(
    *,
    domain: str,
    adapter: str,
    provider: str,
    depth: float,
) -> None:
    attrs = {"domain": domain, "adapter": adapter, "provider": provider}
    _queue_hist.record(max(depth, 0.0), attributes=attrs)


def capture_adapter_state_metrics(
    instance: Any, *, category: str, provider: str
) -> None:
    """Attempt to capture pool/queue metrics from adapter instances."""

    pool_size = _extract_numeric(
        instance,
        ("pool_size", "connections", "active_connections", "max_connections"),
    )
    if pool_size is not None:
        record_adapter_pool_size(
            domain="adapter",
            adapter=category,
            provider=provider,
            size=pool_size,
        )

    queue_depth = _extract_numeric(
        instance,
        ("queue_depth", "queue_size", "backlog", "pending", "pending_count"),
    )
    if queue_depth is not None:
        record_adapter_queue_depth(
            domain="adapter",
            adapter=category,
            provider=provider,
            depth=queue_depth,
        )


def _extract_numeric(instance: Any, names: tuple[str, ...]) -> float | None:
    for name in names:
        value = _read_value(instance, name)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _read_value(instance: Any, name: str) -> Any:
    value = getattr(instance, name, None)
    if callable(value):
        try:
            return value()
        except Exception:
            return None
    return value
