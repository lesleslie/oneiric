"""Runtime metrics helpers for events and workflow DAGs."""

from __future__ import annotations

from opentelemetry import metrics

_RUNTIME_METER = metrics.get_meter("oneiric.runtime")

_event_duration_hist = _RUNTIME_METER.create_histogram(
    "oneiric_event_handler_duration_ms",
    unit="ms",
    description="Duration of event handler executions.",
)
_event_attempts_hist = _RUNTIME_METER.create_histogram(
    "oneiric_event_handler_attempts",
    unit="1",
    description="Attempt count recorded per event handler invocation.",
)
_event_failure_counter = _RUNTIME_METER.create_counter(
    "oneiric_event_handler_failures_total",
    unit="1",
    description="Number of failed event handler executions.",
)

_workflow_duration_hist = _RUNTIME_METER.create_histogram(
    "oneiric_workflow_node_duration_ms",
    unit="ms",
    description="Duration of workflow DAG node executions.",
)
_workflow_attempts_hist = _RUNTIME_METER.create_histogram(
    "oneiric_workflow_node_attempts",
    unit="1",
    description="Attempt count recorded per workflow DAG node.",
)
_workflow_failure_counter = _RUNTIME_METER.create_counter(
    "oneiric_workflow_node_failures_total",
    unit="1",
    description="Number of workflow DAG node executions that failed.",
)


def record_event_handler_metrics(
    *,
    handler: str,
    topic: str,
    success: bool,
    duration_ms: float,
    attempts: int,
) -> None:
    """Record duration/attempt telemetry for an event handler invocation."""

    attrs: dict[str, str] = {
        "handler": handler,
        "topic": topic,
        "outcome": "success" if success else "failed",
    }
    _event_duration_hist.record(max(duration_ms, 0.0), attributes=attrs)
    _event_attempts_hist.record(float(max(attempts, 0)), attributes=attrs)
    if not success:
        _event_failure_counter.add(1, attributes=attrs)


def record_workflow_node_metrics(
    *,
    workflow: str,
    node: str,
    success: bool,
    duration_ms: float,
    attempts: int,
) -> None:
    """Record duration/attempt telemetry for a workflow DAG node execution."""

    attrs: dict[str, str] = {
        "workflow": workflow,
        "node": node,
        "outcome": "success" if success else "failed",
    }
    _workflow_duration_hist.record(max(duration_ms, 0.0), attributes=attrs)
    _workflow_attempts_hist.record(float(max(attempts, 0)), attributes=attrs)
    if not success:
        _workflow_failure_counter.add(1, attributes=attrs)
