"""Tests for QueryService Pydantic models."""

from __future__ import annotations

from datetime import datetime
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
        start_time=datetime.utcnow(),
        end_time=datetime.utcnow(),
        attributes={"key": "value"},
        similarity_score=0.95
    )

    assert trace.trace_id == "trace-001"
    assert trace.similarity_score == 0.95
    assert trace.attributes == {"key": "value"}


def test_log_entry_model_success():
    """Test LogEntry model with valid data."""
    log = LogEntry(
        id="log-001",
        timestamp=datetime.utcnow(),
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
        value=75.5,
        unit="percent",
        labels={"host": "server1"},
        timestamp=datetime.utcnow()
    )

    assert metric.name == "cpu_usage"
    assert metric.value == 75.5
    assert metric.unit == "percent"


def test_trace_context_model_success():
    """Test TraceContext model with nested data."""
    trace = TraceResult(
        trace_id="trace-001",
        name="Test",
        service="test",
        status="OK",
        start_time=datetime.utcnow()
    )
    log = LogEntry(
        id="log-001",
        timestamp=datetime.utcnow(),
        level="INFO",
        message="Test"
    )
    metric = MetricPoint(
        name="metric",
        value=1.0,
        timestamp=datetime.utcnow()
    )

    context = TraceContext(
        trace=trace,
        logs=[log],
        metrics=[metric]
    )

    assert context.trace.trace_id == "trace-001"
    assert len(context.logs) == 1
    assert len(context.metrics) == 1
