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
    return QueryService(session_factory=None)  # type: ignore[assignment]


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


def test_orm_to_result_missing_service_attribute(query_service):
    """Test conversion with missing service attribute uses 'unknown' fallback."""
    orm_model = TraceModel(
        id="span-002",
        trace_id="trace-002",
        name="Operation without service",
        start_time=datetime.now(UTC),
        status="OK",
        duration_ms=50.0,
        attributes={"operation": "some_op"}
    )

    result = query_service._orm_to_result(orm_model)

    assert result.service == "unknown"
    assert result.operation == "some_op"


def test_orm_to_result_missing_operation_attribute(query_service):
    """Test conversion with missing operation attribute returns None."""
    orm_model = TraceModel(
        id="span-003",
        trace_id="trace-003",
        name="Operation without operation field",
        start_time=datetime.now(UTC),
        status="ERROR",
        duration_ms=200.0,
        attributes={"service": "my-service"}
    )

    result = query_service._orm_to_result(orm_model)

    assert result.service == "my-service"
    assert result.operation is None


def test_orm_to_result_empty_attributes(query_service):
    """Test conversion with empty attributes dict."""
    orm_model = TraceModel(
        id="span-004",
        trace_id="trace-004",
        name="Operation with no attributes",
        start_time=datetime.now(UTC),
        status="OK",
        duration_ms=75.0,
        attributes={}
    )

    result = query_service._orm_to_result(orm_model)

    assert result.service == "unknown"
    assert result.operation is None
    assert result.attributes == {}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_find_similar_traces_returns_results(sample_traces_with_embeddings):
    """Test vector similarity search returns similar traces."""
    from oneiric.adapters.observability.queries import QueryService
    import numpy as np

    # Create QueryService with the sample session factory
    query_service = QueryService(session_factory=sample_traces_with_embeddings)

    # Use embedding from first trace
    query_embedding = np.random.rand(384)

    results = await query_service.find_similar_traces(
        embedding=query_embedding,
        threshold=0.0,  # Low threshold to get results
        limit=5
    )

    assert len(results) <= 5
    # Verify all results have similarity scores
    for result in results:
        assert result.similarity_score is not None
        assert 0.0 <= result.similarity_score <= 1.0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_find_similar_traces_invalid_dimension(query_service):
    """Test invalid embedding dimension raises error."""
    from oneiric.adapters.observability.errors import InvalidEmbeddingError
    import numpy as np
    import pytest

    bad_embedding = np.random.rand(128)  # Wrong dimension

    with pytest.raises(InvalidEmbeddingError):
        await query_service.find_similar_traces(
            embedding=bad_embedding,
            threshold=0.85,
            limit=10
        )

