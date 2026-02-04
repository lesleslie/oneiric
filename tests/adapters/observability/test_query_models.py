"""Tests for QueryService Pydantic models.

These tests validate the result models used by QueryService for returning
OTel telemetry data. This is separate from the storage models (TraceData,
MetricData) which are tested in test_types.py.

QueryService models:
- TraceResult: Trace data with optional similarity
- LogEntry: Log entry with trace correlation
- MetricPoint: Metric data point with labels
- TraceContext: Complete context (trace_id + spans + logs + metrics)
"""

from __future__ import annotations

from datetime import datetime, UTC
import pytest
from oneiric.adapters.observability.types import TraceResult, LogEntry, MetricPoint, TraceContext


def test_trace_result_model_success():
    """Test TraceResult model with valid data."""
    trace = TraceResult(
        trace_id="trace-001",
        span_id="span-001",
        name="Test operation",
        service="test-service",
        operation="test_op",
        status="OK",
        duration_ms=100.0,
        start_time=datetime.now(UTC),
        end_time=datetime.now(UTC),
        attributes={"key": "value"},
        similarity=0.95
    )

    assert trace.trace_id == "trace-001"
    assert trace.similarity == 0.95
    assert trace.attributes == {"key": "value"}


def test_log_entry_model_success():
    """Test LogEntry model with valid data."""
    log = LogEntry(
        id="log-001",
        timestamp=datetime.now(UTC),
        level="INFO",
        message="Test message",
        trace_id="trace-001",
        resource_attributes={"service": "test"},
        span_attributes={"key": "value"}
    )

    assert log.id == "log-001"
    assert log.level == "INFO"
    assert log.trace_id == "trace-001"


def test_metric_point_model_success():
    """Test MetricPoint model with valid data."""
    metric = MetricPoint(
        name="cpu_usage",
        type="GAUGE",
        value=75.5,
        unit="percent",
        labels={"host": "server1"},
        timestamp=datetime.now(UTC)
    )

    assert metric.name == "cpu_usage"
    assert metric.value == 75.5
    assert metric.unit == "percent"
    assert metric.type == "GAUGE"


def test_trace_context_model_success():
    """Test TraceContext model with nested data."""
    from oneiric.adapters.observability.types import TraceData

    now = datetime.now(UTC)
    trace = TraceData(
        trace_id="trace-001",
        span_id="span-001",
        name="Test",
        kind="INTERNAL",
        start_time=now,
        end_time=now,
        duration_ms=100.0,
        status="OK",
        service="test",
        operation="test_op",
    )
    log = LogEntry(
        id="log-001",
        timestamp=now,
        level="INFO",
        message="Test"
    )
    metric = MetricPoint(
        name="metric",
        type="COUNTER",
        value=1.0,
        timestamp=now
    )

    context = TraceContext(
        trace_id="trace-001",
        spans=[trace],
        logs=[log],
        metrics=[metric]
    )

    assert context.trace_id == "trace-001"
    assert len(context.spans) == 1
    assert len(context.logs) == 1
    assert len(context.metrics) == 1
