from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TraceData(BaseModel):
    trace_id: str = Field(
        ..., description="Unique trace identifier (16-byte hex string)"
    )
    span_id: str = Field(..., description="Unique span identifier (8-byte hex string)")
    parent_span_id: str | None = Field(
        None, description="Parent span identifier (8-byte hex string)"
    )
    name: str = Field(..., description="Span name (e.g., operation name)")
    kind: str = Field(
        ..., description="Span kind (INTERNAL, SERVER, CLIENT, PRODUCER, CONSUMER)"
    )
    start_time: datetime = Field(..., description="Span start timestamp")
    end_time: datetime = Field(..., description="Span end timestamp")
    duration_ms: float = Field(..., description="Span duration in milliseconds")
    status: str = Field(..., description="Span status (OK, ERROR, UNSET)")
    attributes: dict[str, Any] = Field(
        default_factory=dict, description="Span attributes as key-value pairs"
    )
    service: str = Field(..., description="Service name for embedding generation")
    operation: str = Field(..., description="Operation name for embedding generation")


class MetricData(BaseModel):
    name: str = Field(..., description="Metric name (e.g., http_requests_total)")
    type: str = Field(
        ..., description="Metric type (GAUGE, COUNTER, HISTOGRAM, SUMMARY)"
    )
    value: float = Field(..., description="Metric value")
    unit: str = Field(..., description="Metric unit (e.g., seconds, bytes, requests)")
    labels: dict[str, str] = Field(
        default_factory=dict, description="Metric labels/dimensions"
    )
    timestamp: datetime = Field(..., description="Metric timestamp")


class LogEntry(BaseModel):
    id: str = Field(..., description="Log entry identifier")
    timestamp: datetime = Field(..., description="Log timestamp")
    level: str = Field(
        ..., description="Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    )
    message: str = Field(..., description="Log message")
    trace_id: str | None = Field(
        None, description="Associated trace ID for correlation"
    )
    resource_attributes: dict[str, Any] = Field(
        default_factory=dict,
        description="Resource attributes (service.name, host.name, etc.)",
    )
    span_attributes: dict[str, Any] = Field(
        default_factory=dict, description="Associated span attributes"
    )


class TraceResult(BaseModel):
    trace_id: str = Field(..., description="Unique trace identifier")
    span_id: str | None = Field(None, description="Span identifier")
    name: str = Field(..., description="Trace/root span name")
    service: str = Field(..., description="Service name")
    operation: str | None = Field(None, description="Operation name")
    status: str = Field(..., description="Trace status (OK, ERROR, UNSET)")
    duration_ms: float | None = Field(
        None, description="Trace duration in milliseconds"
    )
    start_time: datetime = Field(..., description="Trace start timestamp")
    end_time: datetime | None = Field(None, description="Trace end timestamp")
    attributes: dict[str, Any] = Field(
        default_factory=dict, description="Trace attributes"
    )
    similarity_score: float | None = Field(
        None, description="Similarity score for vector search"
    )


class MetricPoint(BaseModel):
    name: str = Field(..., description="Metric name")
    value: float = Field(..., description="Metric value")
    unit: str | None = Field(
        None, description="Metric unit (e.g., seconds, bytes, requests)"
    )
    labels: dict[str, Any] = Field(
        default_factory=dict, description="Metric labels/dimensions"
    )
    timestamp: datetime = Field(..., description="Metric timestamp")


class TraceContext(BaseModel):
    trace: TraceResult = Field(..., description="Trace result")
    logs: list[LogEntry] = Field(
        default_factory=list, description="Log entries correlated to this trace"
    )
    metrics: list[MetricPoint] = Field(
        default_factory=list, description="Metrics correlated to this trace"
    )
