"""Tests for QueryService."""

from __future__ import annotations

from datetime import datetime, UTC
import pytest
from oneiric.adapters.observability.queries import QueryService
from oneiric.adapters.observability.models import TraceModel


@pytest.fixture
def query_service():
    """Create QueryService for testing.

    Note: _orm_to_result doesn't need a session, so we pass None.
    """
    return QueryService(session_factory=None)


def test_orm_to_trace_result_conversion(query_service):
    """Test converting TraceModel to TraceResult."""
    orm_model = TraceModel(
        id="span-001",
        trace_id="trace-001",
        name="Test operation",
        start_time=datetime.now(UTC),
        status="OK",
        duration_ms=100.0,
        attributes={"service": "test-service", "operation": "test_op"}
    )

    result = query_service._orm_to_result(orm_model)

    assert result.trace_id == "trace-001"
    assert result.span_id == "span-001"
    assert result.name == "Test operation"
    assert result.service == "test-service"
    assert result.operation == "test_op"
    assert result.status == "OK"
    assert result.duration_ms == 100.0
