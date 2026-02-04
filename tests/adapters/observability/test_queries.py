"""Tests for QueryService."""

from __future__ import annotations

from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock
import pytest
from oneiric.adapters.observability.queries import QueryService
from oneiric.adapters.observability.models import LogModel, MetricModel, TraceModel
from oneiric.adapters.observability.errors import (
    InvalidSQLError,
    TraceNotFoundError,
)


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
        assert result.similarity is not None
        assert 0.0 <= result.similarity <= 1.0


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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_traces_by_error_basic():
    """Test error pattern search."""
    from sqlalchemy.ext.asyncio import AsyncSession

    # Create mock session
    mock_session = AsyncMock(spec=AsyncSession)

    # Create sample traces with error messages
    sample_traces = [
        TraceModel(
            id=f"error-{i}",
            trace_id=f"trace-error-{i}",
            name=f"Error operation {i}",
            start_time=datetime.now(UTC),
            status="ERROR",
            duration_ms=100.0,
            attributes={
                "error.message": f"Connection timeout error {i}",
                "service": f"service-{i % 2}"
            }
        )
        for i in range(3)
    ]

    # Mock execute to return sample traces
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = sample_traces
    mock_session.execute.return_value = mock_result

    # Mock session factory
    session_factory = MagicMock()
    session_factory.return_value.__aenter__.return_value = mock_session

    query_service = QueryService(session_factory=session_factory)

    results = await query_service.get_traces_by_error(
        error_pattern="%timeout%",
        service="service-0"
    )

    assert len(results) == 3
    assert all(r.status == "ERROR" for r in results)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_traces_by_error_with_time_filters():
    """Test error search with time range filters."""
    from sqlalchemy.ext.asyncio import AsyncSession

    mock_session = AsyncMock(spec=AsyncSession)

    sample_traces = [
        TraceModel(
            id="time-error-1",
            trace_id="trace-time-1",
            name="Timed error",
            start_time=datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC),
            status="ERROR",
            duration_ms=100.0,
            attributes={"error.message": "Timeout error"}
        )
    ]

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = sample_traces
    mock_session.execute.return_value = mock_result

    session_factory = MagicMock()
    session_factory.return_value.__aenter__.return_value = mock_session

    query_service = QueryService(session_factory=session_factory)

    results = await query_service.get_traces_by_error(
        error_pattern="%Timeout%",
        start_time=datetime(2024, 1, 1, tzinfo=UTC),
        end_time=datetime(2026, 1, 1, tzinfo=UTC)
    )

    assert len(results) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_trace_context_success():
    """Test getting complete trace context."""
    from sqlalchemy.ext.asyncio import AsyncSession

    mock_session = AsyncMock(spec=AsyncSession)

    # Mock trace
    trace_model = TraceModel(
        id="ctx-trace-1",
        trace_id="context-trace-1",
        name="Context operation",
        start_time=datetime.now(UTC),
        status="OK",
        duration_ms=150.0,
        attributes={"service": "context-service"}
    )

    # Mock logs
    log_models = [
        LogModel(
            id=f"log-{i}",
            timestamp=datetime.now(UTC),
            level="INFO",
            message=f"Log message {i}",
            trace_id="context-trace-1",
            resource_attributes={"service": "context-service"},
            span_attributes={"key": "value"}
        )
        for i in range(2)
    ]

    # Mock metrics
    metric_models = [
        MetricModel(
            id=f"metric-{i}",
            name=f"metric_{i}",
            type="GAUGE",
            value=float(i * 10),
            unit="ms",
            labels={"trace_id": "context-trace-1"},
            timestamp=datetime.now(UTC)
        )
        for i in range(2)
    ]

    # Set up mock return values for sequential calls
    trace_result = MagicMock()
    trace_result.scalar_one_or_none.return_value = trace_model

    logs_result = MagicMock()
    logs_result.scalars.return_value.all.return_value = log_models

    metrics_result = MagicMock()
    metrics_result.scalars.return_value.all.return_value = metric_models

    # Execute returns different results on sequential calls
    mock_session.execute.side_effect = [trace_result, logs_result, metrics_result]

    session_factory = MagicMock()
    session_factory.return_value.__aenter__.return_value = mock_session

    query_service = QueryService(session_factory=session_factory)

    context = await query_service.get_trace_context("context-trace-1")

    assert context.trace_id == "context-trace-1"
    assert len(context.spans) == 1
    assert len(context.logs) == 2
    assert len(context.metrics) == 2
    assert context.logs[0].message == "Log message 0"
    assert context.metrics[0].name == "metric_0"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_trace_context_not_found():
    """Test TraceNotFoundError when trace doesn't exist."""
    from sqlalchemy.ext.asyncio import AsyncSession

    mock_session = AsyncMock(spec=AsyncSession)

    # Mock no trace found
    trace_result = MagicMock()
    trace_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = trace_result

    session_factory = MagicMock()
    session_factory.return_value.__aenter__.return_value = mock_session

    query_service = QueryService(session_factory=session_factory)

    with pytest.raises(TraceNotFoundError, match="Trace not found"):
        await query_service.get_trace_context("nonexistent-trace")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_custom_query_select():
    """Test custom query with SELECT."""
    from sqlalchemy.ext.asyncio import AsyncSession

    mock_session = AsyncMock(spec=AsyncSession)

    # Mock fetchall result
    mock_row = MagicMock()
    mock_row._mapping = {"trace_id": "trace-1", "status": "OK"}

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [mock_row]
    mock_session.execute.return_value = mock_result

    session_factory = MagicMock()
    session_factory.return_value.__aenter__.return_value = mock_session

    query_service = QueryService(session_factory=session_factory)

    results = await query_service.custom_query(
        "SELECT trace_id, status FROM traces WHERE status = :status",
        {"status": "OK"}
    )

    assert len(results) == 1
    assert results[0]["trace_id"] == "trace-1"
    assert results[0]["status"] == "OK"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_custom_query_with_cte():
    """Test custom query with CTE (WITH clause)."""
    from sqlalchemy.ext.asyncio import AsyncSession

    mock_session = AsyncMock(spec=AsyncSession)

    mock_row = MagicMock()
    mock_row._mapping = {"count": 5}

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [mock_row]
    mock_session.execute.return_value = mock_result

    session_factory = MagicMock()
    session_factory.return_value.__aenter__.return_value = mock_session

    query_service = QueryService(session_factory=session_factory)

    results = await query_service.custom_query(
        "WITH error_traces AS (SELECT * FROM traces WHERE status = 'ERROR') "
        "SELECT COUNT(*) as count FROM error_traces"
    )

    assert len(results) == 1
    assert results[0]["count"] == 5


@pytest.mark.unit
@pytest.mark.asyncio
async def test_custom_query_rejects_delete():
    """Test custom query rejects DELETE statements."""
    query_service = QueryService(session_factory=MagicMock())

    with pytest.raises(InvalidSQLError, match="Only SELECT and WITH queries allowed"):
        await query_service.custom_query("DELETE FROM traces")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_custom_query_rejects_drop():
    """Test custom query rejects dangerous DROP pattern."""
    query_service = QueryService(session_factory=MagicMock())

    with pytest.raises(InvalidSQLError, match="Dangerous SQL pattern detected"):
        await query_service.custom_query("SELECT * FROM traces; DROP TABLE traces")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_custom_query_rejects_insert():
    """Test custom query rejects INSERT statements."""
    query_service = QueryService(session_factory=MagicMock())

    with pytest.raises(InvalidSQLError, match="Only SELECT and WITH queries allowed"):
        await query_service.custom_query("INSERT INTO traces VALUES (...)")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_custom_query_rejects_comment_injection():
    """Test custom query rejects SQL comment injection."""
    query_service = QueryService(session_factory=MagicMock())

    with pytest.raises(InvalidSQLError, match="Dangerous SQL pattern detected"):
        await query_service.custom_query("SELECT * FROM traces -- evil comment")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_custom_query_rejects_block_comment():
    """Test custom query rejects block comment injection."""
    query_service = QueryService(session_factory=MagicMock())

    with pytest.raises(InvalidSQLError, match="Dangerous SQL pattern detected"):
        await query_service.custom_query("SELECT * FROM traces /* evil */")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_custom_query_empty_params():
    """Test custom query with no parameters."""
    from sqlalchemy.ext.asyncio import AsyncSession

    mock_session = AsyncMock(spec=AsyncSession)

    mock_row = MagicMock()
    mock_row._mapping = {"count": 10}

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [mock_row]
    mock_session.execute.return_value = mock_result

    session_factory = MagicMock()
    session_factory.return_value.__aenter__.return_value = mock_session

    query_service = QueryService(session_factory=session_factory)

    results = await query_service.custom_query("SELECT COUNT(*) as count FROM traces")

    assert len(results) == 1
    assert results[0]["count"] == 10
