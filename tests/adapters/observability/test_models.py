"""Tests for OTel telemetry storage models.

Tests the SQLAlchemy models for traces, metrics, and logs including
vector embeddings and time-series queries.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from oneiric.adapters.observability.models import (
    Base,
    LogModel,
    MetricModel,
    TraceModel,
)


@pytest.fixture
def in_memory_db():
    """Create an in-memory SQLite database for testing.

    Yields:
        Session: SQLAlchemy session bound to in-memory database
    """
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


def test_trace_model_creation(in_memory_db: Session) -> None:
    """Test creating and querying a trace record."""
    # Create a trace
    trace = TraceModel(
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        name="HTTP GET /api/users",
        kind="SPAN_KIND_SERVER",
        start_time=datetime.utcnow(),
        end_time=datetime.utcnow() + timedelta(milliseconds=150),
        duration_ms=150,
        status="STATUS_CODE_OK",
        attributes={
            "http.method": "GET",
            "http.url": "/api/users",
            "http.status_code": 200,
        },
    )
    in_memory_db.add(trace)
    in_memory_db.commit()

    # Query the trace
    queried = in_memory_db.query(TraceModel).filter_by(trace_id="4bf92f3577b34da6a3ce929d0e0e4736").first()

    assert queried is not None
    assert queried.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert queried.name == "HTTP GET /api/users"
    assert queried.kind == "SPAN_KIND_SERVER"
    assert queried.status == "STATUS_CODE_OK"
    assert queried.duration_ms == 150
    assert queried.attributes["http.method"] == "GET"
    assert queried.attributes["http.status_code"] == 200


def test_metric_model_time_series(in_memory_db: Session) -> None:
    """Test creating and querying multiple metric data points."""
    # Create multiple metric points
    base_time = datetime.utcnow()
    metrics = [
        MetricModel(
            name="http_request_duration",
            type="HISTOGRAM",
            value=150.5,
            unit="ms",
            labels={"endpoint": "/api/users", "method": "GET"},
            timestamp=base_time,
        ),
        MetricModel(
            name="http_request_duration",
            type="HISTOGRAM",
            value=230.1,
            unit="ms",
            labels={"endpoint": "/api/users", "method": "GET"},
            timestamp=base_time + timedelta(seconds=1),
        ),
        MetricModel(
            name="http_request_duration",
            type="HISTOGRAM",
            value=89.3,
            unit="ms",
            labels={"endpoint": "/api/users", "method": "GET"},
            timestamp=base_time + timedelta(seconds=2),
        ),
    ]
    in_memory_db.add_all(metrics)
    in_memory_db.commit()

    # Query metrics by name
    queried = (
        in_memory_db.query(MetricModel)
        .filter_by(name="http_request_duration")
        .order_by(MetricModel.timestamp)
        .all()
    )

    assert len(queried) == 3
    assert queried[0].value == 150.5
    assert queried[1].value == 230.1
    assert queried[2].value == 89.3
    assert all(m.type == "HISTOGRAM" for m in queried)
    assert all(m.unit == "ms" for m in queried)


def test_log_model_trace_correlation(in_memory_db: Session) -> None:
    """Test creating log entries correlated with trace IDs."""
    # Create a trace
    trace = TraceModel(
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        name="HTTP POST /api/orders",
        kind="SPAN_KIND_SERVER",
        start_time=datetime.utcnow(),
        status="STATUS_CODE_OK",
        attributes={"http.method": "POST", "http.url": "/api/orders"},
    )
    in_memory_db.add(trace)

    # Create log entries with trace correlation
    logs = [
        LogModel(
            timestamp=datetime.utcnow(),
            level="INFO",
            message="Request received",
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            resource_attributes={"service.name": "order-service"},
            span_attributes={"http.method": "POST"},
        ),
        LogModel(
            timestamp=datetime.utcnow() + timedelta(milliseconds=50),
            level="DEBUG",
            message="Processing order validation",
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            resource_attributes={"service.name": "order-service"},
        ),
        LogModel(
            timestamp=datetime.utcnow() + timedelta(milliseconds=150),
            level="INFO",
            message="Order created successfully",
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            resource_attributes={"service.name": "order-service"},
        ),
    ]
    in_memory_db.add_all(logs)
    in_memory_db.commit()

    # Query logs by trace_id
    queried = (
        in_memory_db.query(LogModel)
        .filter_by(trace_id="4bf92f3577b34da6a3ce929d0e0e4736")
        .order_by(LogModel.timestamp)
        .all()
    )

    assert len(queried) == 3
    assert queried[0].level == "INFO"
    assert queried[0].message == "Request received"
    assert queried[1].level == "DEBUG"
    assert queried[1].message == "Processing order validation"
    assert queried[2].level == "INFO"
    assert queried[2].message == "Order created successfully"
    assert all(log.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736" for log in queried)
    assert all(log.resource_attributes["service.name"] == "order-service" for log in queried)
