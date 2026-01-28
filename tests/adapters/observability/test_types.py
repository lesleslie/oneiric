"""Tests for OTel type definitions."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from oneiric.adapters.observability.types import (
    LogEntry,
    MetricData,
    MetricPoint,
    TraceContext,
    TraceData,
    TraceResult,
)


class TestTraceData:
    """Test TraceData validation and serialization."""

    def test_trace_data_validation(self):
        """Test TraceData with all required fields."""
        trace = TraceData(
            trace_id="0123456789abcdef0123456789abcdef",
            span_id="01234567",
            parent_span_id="abcdef01",
            name="HTTP GET /api/users",
            kind="SERVER",
            start_time=datetime.now(UTC),
            end_time=datetime.now(UTC),
            duration_ms=123.45,
            status="OK",
            attributes={"http.method": "GET", "http.status_code": 200},
            service="api-service",
            operation="GET /api/users",
        )

        assert trace.trace_id == "0123456789abcdef0123456789abcdef"
        assert trace.span_id == "01234567"
        assert trace.parent_span_id == "abcdef01"
        assert trace.name == "HTTP GET /api/users"
        assert trace.kind == "SERVER"
        assert trace.status == "OK"
        assert trace.duration_ms == 123.45
        assert trace.attributes == {"http.method": "GET", "http.status_code": 200}
        assert trace.service == "api-service"
        assert trace.operation == "GET /api/users"

    def test_trace_data_missing_required_field(self):
        """Test TraceData validation error for missing required field."""
        with pytest.raises(ValidationError) as exc_info:
            TraceData(
                trace_id="0123456789abcdef0123456789abcdef",
                # Missing: span_id
                name="HTTP GET /api/users",
                kind="SERVER",
                start_time=datetime.now(UTC),
                end_time=datetime.now(UTC),
                duration_ms=123.45,
                status="OK",
                service="api-service",
                operation="GET /api/users",
            )

        errors = exc_info.value.errors()
        assert any(error["loc"] == ("span_id",) and error["type"] == "missing" for error in errors)

    def test_trace_data_optional_parent_span_id(self):
        """Test TraceData with missing optional parent_span_id."""
        trace = TraceData(
            trace_id="0123456789abcdef0123456789abcdef",
            span_id="01234567",
            name="HTTP GET /api/users",
            kind="SERVER",
            start_time=datetime.now(UTC),
            end_time=datetime.now(UTC),
            duration_ms=123.45,
            status="OK",
            service="api-service",
            operation="GET /api/users",
        )

        assert trace.parent_span_id is None

    def test_trace_data_default_attributes(self):
        """Test TraceData with default empty attributes dict."""
        trace = TraceData(
            trace_id="0123456789abcdef0123456789abcdef",
            span_id="01234567",
            name="HTTP GET /api/users",
            kind="SERVER",
            start_time=datetime.now(UTC),
            end_time=datetime.now(UTC),
            duration_ms=123.45,
            status="OK",
            service="api-service",
            operation="GET /api/users",
        )

        assert trace.attributes == {}


class TestMetricData:
    """Test MetricData validation and serialization."""

    def test_metric_data_validation(self):
        """Test MetricData with all required fields."""
        metric = MetricData(
            name="http_requests_total",
            type="COUNTER",
            value=1234.0,
            unit="requests",
            labels={"method": "GET", "endpoint": "/api/users"},
            timestamp=datetime.now(UTC),
        )

        assert metric.name == "http_requests_total"
        assert metric.type == "COUNTER"
        assert metric.value == 1234.0
        assert metric.unit == "requests"
        assert metric.labels == {"method": "GET", "endpoint": "/api/users"}

    def test_metric_data_default_labels(self):
        """Test MetricData with default empty labels dict."""
        metric = MetricData(
            name="http_requests_total",
            type="COUNTER",
            value=1234.0,
            unit="requests",
            timestamp=datetime.now(UTC),
        )

        assert metric.labels == {}


class TestLogEntry:
    """Test LogEntry validation and serialization."""

    def test_log_entry_trace_correlation(self):
        """Test LogEntry with trace ID correlation."""
        log = LogEntry(
            timestamp=datetime.now(UTC),
            level="INFO",
            message="Request processed successfully",
            trace_id="0123456789abcdef0123456789abcdef",
            resource_attributes={"service.name": "api-service"},
            span_attributes={"http.method": "GET", "http.status_code": 200},
        )

        assert log.trace_id == "0123456789abcdef0123456789abcdef"
        assert log.resource_attributes == {"service.name": "api-service"}
        assert log.span_attributes == {"http.method": "GET", "http.status_code": 200}

    def test_log_entry_without_trace_correlation(self):
        """Test LogEntry without trace ID (optional field)."""
        log = LogEntry(
            timestamp=datetime.now(UTC),
            level="ERROR",
            message="Database connection failed",
            resource_attributes={"service.name": "db-service"},
        )

        assert log.trace_id is None
        assert log.span_attributes == {}

    def test_log_entry_default_resource_attributes(self):
        """Test LogEntry with default empty resource_attributes."""
        log = LogEntry(
            timestamp=datetime.now(UTC),
            level="DEBUG",
            message="Debug message",
        )

        assert log.resource_attributes == {}
        assert log.span_attributes == {}


class TestTraceResult:
    """Test TraceResult validation and serialization."""

    def test_trace_result_with_similarity(self):
        """Test TraceResult with similarity score."""
        result = TraceResult(
            trace_id="0123456789abcdef0123456789abcdef",
            name="HTTP GET /api/users",
            service="api-service",
            operation="GET /api/users",
            status="OK",
            duration_ms=123.45,
            attributes={"http.method": "GET"},
            similarity=0.95,
        )

        assert result.trace_id == "0123456789abcdef0123456789abcdef"
        assert result.similarity == 0.95
        assert result.service == "api-service"

    def test_trace_result_similarity_range(self):
        """Test TraceResult similarity scores in valid range."""
        # Test low similarity
        result_low = TraceResult(
            trace_id="0123456789abcdef0123456789abcdef",
            name="Trace A",
            service="service-a",
            operation="operation-a",
            status="OK",
            duration_ms=100.0,
            similarity=0.0,
        )
        assert result_low.similarity == 0.0

        # Test high similarity
        result_high = TraceResult(
            trace_id="abcdef0123456789abcdef0123456789",
            name="Trace B",
            service="service-b",
            operation="operation-b",
            status="OK",
            duration_ms=200.0,
            similarity=1.0,
        )
        assert result_high.similarity == 1.0


class TestMetricPoint:
    """Test MetricPoint validation and serialization."""

    def test_metric_point_structure(self):
        """Test MetricPoint structure."""
        point = MetricPoint(
            name="cpu_usage",
            type="GAUGE",
            value=75.5,
            unit="percent",
            labels={"host": "server-1"},
            timestamp=datetime.now(UTC),
        )

        assert point.name == "cpu_usage"
        assert point.type == "GAUGE"
        assert point.value == 75.5
        assert point.unit == "percent"
        assert point.labels == {"host": "server-1"}

    def test_metric_point_default_labels(self):
        """Test MetricPoint with default empty labels."""
        point = MetricPoint(
            name="memory_usage",
            type="GAUGE",
            value=1024.0,
            unit="bytes",
            timestamp=datetime.now(UTC),
        )

        assert point.labels == {}


class TestTraceContext:
    """Test TraceContext validation and serialization."""

    def test_trace_context_with_all_telemetry(self):
        """Test TraceContext with spans, logs, and metrics."""
        trace_id = "0123456789abcdef0123456789abcdef"
        now = datetime.now(UTC)

        spans = [
            TraceData(
                trace_id=trace_id,
                span_id="01234567",
                name="HTTP GET /api/users",
                kind="SERVER",
                start_time=now,
                end_time=now,
                duration_ms=100.0,
                status="OK",
                service="api-service",
                operation="GET /api/users",
            )
        ]

        logs = [
            LogEntry(
                timestamp=now,
                level="INFO",
                message="Request received",
                trace_id=trace_id,
            )
        ]

        metrics = [
            MetricPoint(
                name="http_requests_total",
                type="COUNTER",
                value=1.0,
                unit="requests",
                timestamp=now,
            )
        ]

        context = TraceContext(
            trace_id=trace_id,
            spans=spans,
            logs=logs,
            metrics=metrics,
        )

        assert context.trace_id == trace_id
        assert len(context.spans) == 1
        assert len(context.logs) == 1
        assert len(context.metrics) == 1

    def test_trace_context_empty_collections(self):
        """Test TraceContext with default empty collections."""
        context = TraceContext(
            trace_id="0123456789abcdef0123456789abcdef",
        )

        assert context.spans == []
        assert context.logs == []
        assert context.metrics == []
