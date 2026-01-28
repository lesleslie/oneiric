"""Type definitions for OpenTelemetry telemetry data.

This module defines Pydantic models for type-safe OTel telemetry data structures
used in the observability storage adapter.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TraceData(BaseModel):
    """Distributed trace span data for storage.

    Attributes:
        trace_id: Unique trace identifier (16-byte hex string)
        span_id: Unique span identifier (8-byte hex string)
        parent_span_id: Parent span identifier (8-byte hex string, optional)
        name: Span name (e.g., operation name)
        kind: Span kind (INTERNAL, SERVER, CLIENT, PRODUCER, CONSUMER)
        start_time: Span start timestamp
        end_time: Span end timestamp
        duration_ms: Span duration in milliseconds
        status: Span status (OK, ERROR, UNSET)
        attributes: Span attributes as key-value pairs
        service: Service name for embedding generation
        operation: Operation name for embedding generation
    """

    trace_id: str = Field(..., description="Unique trace identifier (16-byte hex string)")
    span_id: str = Field(..., description="Unique span identifier (8-byte hex string)")
    parent_span_id: str | None = Field(None, description="Parent span identifier (8-byte hex string)")
    name: str = Field(..., description="Span name (e.g., operation name)")
    kind: str = Field(..., description="Span kind (INTERNAL, SERVER, CLIENT, PRODUCER, CONSUMER)")
    start_time: datetime = Field(..., description="Span start timestamp")
    end_time: datetime = Field(..., description="Span end timestamp")
    duration_ms: float = Field(..., description="Span duration in milliseconds")
    status: str = Field(..., description="Span status (OK, ERROR, UNSET)")
    attributes: dict[str, Any] = Field(default_factory=dict, description="Span attributes as key-value pairs")
    service: str = Field(..., description="Service name for embedding generation")
    operation: str = Field(..., description="Operation name for embedding generation")


class MetricData(BaseModel):
    """Metric data point for time-series storage.

    Attributes:
        name: Metric name (e.g., http_requests_total)
        type: Metric type (GAUGE, COUNTER, HISTOGRAM, SUMMARY)
        value: Metric value
        unit: Metric unit (e.g., seconds, bytes, requests)
        labels: Metric labels/dimensions
        timestamp: Metric timestamp
    """

    name: str = Field(..., description="Metric name (e.g., http_requests_total)")
    type: str = Field(..., description="Metric type (GAUGE, COUNTER, HISTOGRAM, SUMMARY)")
    value: float = Field(..., description="Metric value")
    unit: str = Field(..., description="Metric unit (e.g., seconds, bytes, requests)")
    labels: dict[str, str] = Field(default_factory=dict, description="Metric labels/dimensions")
    timestamp: datetime = Field(..., description="Metric timestamp")


class LogEntry(BaseModel):
    """Log entry with trace correlation.

    Attributes:
        timestamp: Log timestamp
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        message: Log message
        trace_id: Associated trace ID (optional, for correlation)
        resource_attributes: Resource attributes (service.name, host.name, etc.)
        span_attributes: Associated span attributes (optional)
    """

    timestamp: datetime = Field(..., description="Log timestamp")
    level: str = Field(..., description="Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)")
    message: str = Field(..., description="Log message")
    trace_id: str | None = Field(None, description="Associated trace ID for correlation")
    resource_attributes: dict[str, Any] = Field(
        default_factory=dict,
        description="Resource attributes (service.name, host.name, etc.)",
    )
    span_attributes: dict[str, Any] = Field(default_factory=dict, description="Associated span attributes")


class TraceResult(BaseModel):
    """Result from trace similarity query.

    Attributes:
        trace_id: Unique trace identifier
        name: Trace/root span name
        service: Service name
        operation: Operation name
        status: Trace status (OK, ERROR, UNSET)
        duration_ms: Trace duration in milliseconds
        attributes: Trace attributes
        similarity: Similarity score (0-1, higher is more similar)
    """

    trace_id: str = Field(..., description="Unique trace identifier")
    name: str = Field(..., description="Trace/root span name")
    service: str = Field(..., description="Service name")
    operation: str = Field(..., description="Operation name")
    status: str = Field(..., description="Trace status (OK, ERROR, UNSET)")
    duration_ms: float = Field(..., description="Trace duration in milliseconds")
    attributes: dict[str, Any] = Field(default_factory=dict, description="Trace attributes")
    similarity: float = Field(..., description="Similarity score (0-1, higher is more similar)")


class MetricPoint(BaseModel):
    """Metric data point from time-series query.

    Attributes:
        name: Metric name
        type: Metric type (GAUGE, COUNTER, HISTOGRAM, SUMMARY)
        value: Metric value
        unit: Metric unit (e.g., seconds, bytes, requests)
        labels: Metric labels/dimensions
        timestamp: Metric timestamp
    """

    name: str = Field(..., description="Metric name")
    type: str = Field(..., description="Metric type (GAUGE, COUNTER, HISTOGRAM, SUMMARY)")
    value: float = Field(..., description="Metric value")
    unit: str = Field(..., description="Metric unit (e.g., seconds, bytes, requests)")
    labels: dict[str, str] = Field(default_factory=dict, description="Metric labels/dimensions")
    timestamp: datetime = Field(..., description="Metric timestamp")


class TraceContext(BaseModel):
    """Complete trace with all related telemetry.

    Attributes:
        trace_id: Unique trace identifier
        spans: List of spans in the trace
        logs: Log entries correlated to this trace
        metrics: Metrics correlated to this trace
    """

    trace_id: str = Field(..., description="Unique trace identifier")
    spans: list[TraceData] = Field(default_factory=list, description="List of spans in the trace")
    logs: list[LogEntry] = Field(default_factory=list, description="Log entries correlated to this trace")
    metrics: list[MetricPoint] = Field(default_factory=list, description="Metrics correlated to this trace")
