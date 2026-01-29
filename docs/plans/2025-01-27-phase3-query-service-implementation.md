# Phase 3: QueryService Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build QueryService that provides high-level query API for OTel telemetry using SQLAlchemy ORM + Pgvector for vector similarity search.

**Architecture:** QueryService provides 6 query methods (vector similarity, error search, time-series metrics, log search, trace context, SQL escape hatch). Uses Pydantic models for type-safe results, explicit error handling (exceptions for DB errors, empty lists for no results).

**Tech Stack:** SQLAlchemy (async ORM), Pgvector (cosine similarity), Pydantic (result models), numpy (vector operations)

______________________________________________________________________

## Task 1: Create Pydantic result models

**Files:**

- Modify: `oneiric/adapters/observability/types.py`

**Step 1: Write tests for Pydantic models**

Create test file: `tests/adapters/observability/test_query_models.py`

```python
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
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/adapters/observability/test_query_models.py -v
```

Expected: FAIL - TraceResult, LogEntry, MetricPoint, TraceContext don't exist yet

**Step 3: Implement Pydantic models**

Add to `oneiric/adapters/observability/types.py`:

```python
"""Query result models for OTel telemetry."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class TraceResult(BaseModel):
    """Trace data from query results."""

    trace_id: str
    span_id: str | None = None
    name: str
    service: str
    operation: str | None = None
    status: str
    duration_ms: float | None = None
    start_time: datetime
    end_time: datetime | None = None
    attributes: dict[str, Any] = {}
    similarity_score: float | None = None  # Only for vector search


class LogEntry(BaseModel):
    """Log entry from query results."""

    id: str
    timestamp: datetime
    level: str
    message: str
    trace_id: str | None = None
    resource_attributes: dict[str, Any] = {}
    span_attributes: dict[str, Any] = {}


class MetricPoint(BaseModel):
    """Metric data point."""

    name: str
    value: float
    unit: str | None = None
    labels: dict[str, Any] = {}
    timestamp: datetime


class TraceContext(BaseModel):
    """Complete trace context with correlated data."""

    trace: TraceResult
    logs: list[LogEntry] = []
    metrics: list[MetricPoint] = []
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/adapters/observability/test_query_models.py -v
```

Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add oneiric/adapters/observability/types.py tests/adapters/observability/test_query_models.py
git commit -m "feat(otel): Add Pydantic result models for QueryService

Add TraceResult, LogEntry, MetricPoint, TraceContext models:
- TraceResult: Trace data with optional similarity_score
- LogEntry: Log data with trace correlation
- MetricPoint: Metric data point with labels
- TraceContext: Complete context (trace + logs + metrics)

All models use Pydantic for validation and type safety.

Tests cover model creation with valid data.
"
```

______________________________________________________________________

## Task 2: Create QueryService class with ORM conversion

**Files:**

- Create: `oneiric/adapters/observability/queries.py`
- Create: `tests/adapters/observability/test_queries.py`

**Step 1: Write test for ORM conversion**

```python
"""Tests for QueryService."""

from __future__ import annotations

from datetime import datetime
import pytest
import pytest_asyncio
from oneiric.adapters.observability.queries import QueryService
from oneiric.adapters.observability.models import TraceModel


@pytest.fixture
def query_service(test_session_factory):
    """Create QueryService for testing."""
    return QueryService(session_factory=test_session_factory)


def test_orm_to_trace_result_conversion(query_service):
    """Test converting TraceModel to TraceResult."""
    orm_model = TraceModel(
        id="span-001",
        trace_id="trace-001",
        name="Test operation",
        start_time=datetime.utcnow(),
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
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/adapters/observability/test_queries.py::test_orm_to_trace_result_conversion -v
```

Expected: FAIL - QueryService doesn't exist yet

**Step 3: Implement QueryService with ORM conversion**

Create `oneiric/adapters/observability/queries.py`:

```python
"""Query service for OTel telemetry."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from numpy import ndarray
from sqlalchemy.ext.asyncio import async_sessionmaker
from structlog.stdlib import BoundLogger

from oneiric.core.lifecycle import get_logger
from oneiric.adapters.observability.models import TraceModel, LogModel, MetricModel
from oneiric.adapters.observability.types import TraceResult, LogEntry, MetricPoint


class QueryService:
    """High-level query API for OTel telemetry."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        """Initialize with SQLAlchemy session factory.

        Args:
            session_factory: Async session factory for queries
        """
        self._session_factory = session_factory
        self._logger: BoundLogger = get_logger("otel.queries")

    def _orm_to_result(self, orm_model: TraceModel) -> TraceResult:
        """Convert TraceModel to TraceResult.

        Args:
            orm_model: SQLAlchemy TraceModel instance

        Returns:
            TraceResult Pydantic model
        """
        return TraceResult(
            trace_id=orm_model.trace_id,
            span_id=orm_model.id,
            name=orm_model.name,
            service=orm_model.attributes.get("service", "unknown"),
            operation=orm_model.attributes.get("operation"),
            status=orm_model.status,
            duration_ms=orm_model.duration_ms,
            start_time=orm_model.start_time,
            end_time=orm_model.end_time,
            attributes=orm_model.attributes or {}
        )
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/adapters/observability/test_queries.py::test_orm_to_trace_result_conversion -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add oneiric/adapters/observability/queries.py tests/adapters/observability/test_queries.py
git commit -m "feat(otel): Create QueryService with ORM conversion

Implement QueryService class:
- Initialize with SQLAlchemy session factory
- _orm_to_result() method: TraceModel → TraceResult conversion
- Extracts service/operation from attributes
- Handles missing fields with defaults

Tests cover ORM → Pydantic conversion.
"
```

______________________________________________________________________

## Task 3: Implement vector similarity search

**Files:**

- Modify: `oneiric/adapters/observability/queries.py`
- Modify: `tests/adapters/observability/test_queries.py`

**Step 1: Write test for vector similarity**

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_find_similar_traces_returns_results(query_service, sample_traces_with_embeddings):
    """Test vector similarity search returns similar traces."""
    import numpy as np

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
def test_find_similar_traces_invalid_dimension(query_service):
    """Test invalid embedding dimension raises error."""
    import numpy as np
    from oneiric.adapters.observability.errors import InvalidEmbeddingError
    import pytest

    bad_embedding = np.random.rand(128)  # Wrong dimension

    with pytest.raises(InvalidEmbeddingError):
        await query_service.find_similar_traces(
            embedding=bad_embedding,
            threshold=0.85,
            limit=10
        )
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/adapters/observability/test_queries.py -k "find_similar_traces" -v
```

Expected: FAIL - Method not implemented

**Step 3: Implement vector similarity search**

Add to `oneiric/adapters/observability/queries.py`:

```python
import numpy as np
from sqlalchemy import select
from oneiric.adapters.observability.errors import InvalidEmbeddingError

# In QueryService class

async def find_similar_traces(
    self,
    embedding: ndarray,
    threshold: float = 0.85,
    limit: int = 10
) -> list[TraceResult]:
    """Find traces similar to the given embedding.

    Uses Pgvector cosine similarity search.

    Args:
        embedding: 384-dim vector
        threshold: Minimum similarity (0.0-1.0, default 0.85)
        limit: Max results (default 10)

    Returns:
        List of TraceResult with similarity scores

    Raises:
        InvalidEmbeddingError: If embedding dimension != 384
    """
    # Validate embedding dimension
    if embedding.shape != (384,):
        raise InvalidEmbeddingError(
            f"Invalid embedding dimension: {embedding.shape}, expected (384,)"
        )

    async with self._session_factory() as session:
        # Cosine distance: 0 = identical, 2 = opposite
        # Cosine similarity: 1 - cosine_distance
        query = (
            select(TraceModel)
            .where(
                (1 - (TraceModel.embedding <=> embedding)) > threshold
            )
            .order_by(TraceModel.embedding <=> embedding)
            .limit(limit)
        )

        result = await session.execute(query)
        orm_models = result.scalars().all()

        # Convert ORM → Pydantic with similarity scores
        results = []
        for model in orm_models:
            trace_result = self._orm_to_result(model)
            # Calculate similarity score
            similarity = 1 - float(np.dot(
                model.embedding, embedding
            ) / (
                np.linalg.norm(model.embedding) *
                np.linalg.norm(embedding)
            ))
            trace_result.similarity_score = similarity
            results.append(trace_result)

        self._logger.debug(
            "query-executed",
            method="find_similar_traces",
            result_count=len(results)
        )

        return results
```

Also add to `oneiric/adapters/observability/errors.py`:

```python
class InvalidEmbeddingError(QueryError):
    """Embedding dimension mismatch."""
    pass
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/adapters/observability/test_queries.py -k "find_similar_traces" -v
```

Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add oneiric/adapters/observability/queries.py tests/adapters/observability/test_queries.py oneiric/adapters/observability/errors.py
git commit -m "feat(otel): Implement vector similarity search

Implement QueryService.find_similar_traces():
- Validates embedding dimension (384)
- Uses Pgvector <=> operator for cosine similarity
- Filters by threshold, orders by similarity
- Calculates similarity_score for each result
- Returns list[TraceResult]

Error handling:
- InvalidEmbeddingError for wrong dimension
- Empty list for no results
- DB errors bubble up

Tests cover valid queries and dimension validation.
"
```

______________________________________________________________________

## Task 4: Implement error pattern search

**Files:**

- Modify: `oneiric/adapters/observability/queries.py`
- Modify: `tests/adapters/observability/test_queries.py`

**Step 1: Write test for error search**

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_traces_by_error_pattern_matching(query_service, sample_error_traces):
    """Test searching traces by error pattern."""
    results = await query_service.get_traces_by_error(
        error_pattern="%timeout%",
        limit=10
    )

    assert len(results) > 0
    # Verify all results have timeout in error message
    for result in results:
        assert "timeout" in result.attributes.get("error.message", "").lower()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_traces_by_error_with_filters(query_service, sample_error_traces):
    """Test error search with service and time filters."""
    from datetime import datetime, timedelta

    start_time = datetime.utcnow() - timedelta(hours=1)
    end_time = datetime.utcnow()

    results = await query_service.get_traces_by_error(
        error_pattern="%error%",
        service="test-service",
        start_time=start_time,
        end_time=end_time,
        limit=10
    )

    # Verify service filter applied
    for result in results:
        assert result.service == "test-service"
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/adapters/observability/test_queries.py -k "get_traces_by_error" -v
```

Expected: FAIL - Method not implemented

**Step 3: Implement error pattern search**

Add to QueryService class:

```python
async def get_traces_by_error(
    self,
    error_pattern: str,
    service: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    limit: int = 100
) -> list[TraceResult]:
    """Find traces matching error pattern.

    Searches attributes->>'error.message' using SQL LIKE.
    Supports wildcards: % (any chars), _ (single char).

    Args:
        error_pattern: SQL LIKE pattern (e.g., "%timeout%")
        service: Optional service name filter
        start_time: Optional start time filter
        end_time: Optional end time filter
        limit: Max results (default 100)

    Returns:
        List of TraceResult matching error pattern
    """
    async with self._session_factory() as session:
        query = select(TraceModel).where(
            TraceModel.attributes["error.message"].astext.like(error_pattern)
        )

        # Apply optional filters
        if service:
            query = query.where(
                TraceModel.attributes["service"].astext == service
            )

        if start_time:
            query = query.where(TraceModel.start_time >= start_time)

        if end_time:
            query = query.where(TraceModel.start_time <= end_time)

        query = query.limit(limit)

        result = await session.execute(query)
        orm_models = result.scalars().all()

        # Convert ORM → Pydantic
        results = [self._orm_to_result(model) for model in orm_models]

        self._logger.debug(
            "query-executed",
            method="get_traces_by_error",
            result_count=len(results)
        )

        return results
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/adapters/observability/test_queries.py -k "get_traces_by_error" -v
```

Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add oneiric/adapters/observability/queries.py tests/adapters/observability/test_queries.py
git commit -m "feat(otel): Implement error pattern search

Implement QueryService.get_traces_by_error():
- Searches error.message using SQL LIKE
- Supports wildcards: % (any), _ (single)
- Optional filters: service, start_time, end_time
- Returns list[TraceResult]

Usage:
- error_pattern='%timeout%' finds 'connection timeout'
- service='mahavishnu' filters by service
- start_time/end_time filters by time range

Tests cover pattern matching and filter application.
"
```

______________________________________________________________________

## Task 5: Implement trace context (correlation query)

**Files:**

- Modify: `oneiric/adapters/observability/queries.py`
- Modify: `tests/adapters/observability/test_queries.py`

**Step 1: Write test for trace context**

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_trace_context_complete(query_service, sample_trace_with_logs_and_metrics):
    """Test getting complete trace context."""
    context = await query_service.get_trace_context(trace_id="test-trace-001")

    assert context.trace.trace_id == "test-trace-001"
    assert len(context.logs) > 0
    assert len(context.metrics) > 0

    # Verify logs are correlated
    for log in context.logs:
        assert log.trace_id == "test-trace-001"


@pytest.mark.unit
def test_get_trace_context_not_found(query_service):
    """Test missing trace raises NotFoundError."""
    from oneiric.adapters.observability.errors import TraceNotFoundError
    import pytest

    with pytest.raises(TraceNotFoundError):
        await query_service.get_trace_context(trace_id="nonexistent")
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/adapters/observability/test_queries.py -k "get_trace_context" -v
```

Expected: FAIL - Method not implemented

**Step 3: Implement trace context query**

Add to `oneiric/adapters/observability/errors.py`:

```python
class TraceNotFoundError(QueryError):
    """Trace ID not found in database."""
    pass
```

Add to QueryService class:

```python
async def get_trace_context(
    self,
    trace_id: str
) -> TraceContext:
    """Get complete trace context with correlated logs and metrics.

    Args:
        trace_id: Trace identifier

    Returns:
        TraceContext with trace + logs + metrics

    Raises:
        TraceNotFoundError: If trace_id doesn't exist
    """
    async with self._session_factory() as session:
        # Get trace
        trace_query = select(TraceModel).where(
            TraceModel.trace_id == trace_id
        )
        trace_result = await session.execute(trace_query)
        trace_model = trace_result.scalar_one_or_none()

        if not trace_model:
            raise TraceNotFoundError(f"Trace not found: {trace_id}")

        trace_pydantic = self._orm_to_result(trace_model)

        # Get correlated logs
        logs_query = select(LogModel).where(
            LogModel.trace_id == trace_id
        ).order_by(LogModel.timestamp)
        logs_result = await session.execute(logs_query)
        log_models = logs_result.scalars().all()

        logs = [
            LogEntry(
                id=log.id,
                timestamp=log.timestamp,
                level=log.level,
                message=log.message,
                trace_id=log.trace_id,
                resource_attributes=log.resource_attributes or {},
                span_attributes=log.span_attributes or {}
            )
            for log in log_models
        ]

        # Get correlated metrics (same service, same time range)
        metrics_query = select(MetricModel).where(
            MetricModel.labels["trace_id"].astext == trace_id
        )
        metrics_result = await session.execute(metrics_query)
        metric_models = metrics_result.scalars().all()

        metrics = [
            MetricPoint(
                name=metric.name,
                value=metric.value,
                unit=metric.unit,
                labels=metric.labels or {},
                timestamp=metric.timestamp
            )
            for metric in metric_models
        ]

        context = TraceContext(
            trace=trace_pydantic,
            logs=logs,
            metrics=metrics
        )

        self._logger.debug(
            "query-executed",
            method="get_trace_context",
            trace_id=trace_id,
            logs_count=len(logs),
            metrics_count=len(metrics)
        )

        return context
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/adapters/observability/test_queries.py -k "get_trace_context" -v
```

Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add oneiric/adapters/observability/queries.py oneiric/adapters/observability/errors.py tests/adapters/observability/test_queries.py
git commit -m "feat(otel): Implement trace context correlation

Implement QueryService.get_trace_context():
- Fetches trace by trace_id
- Correlates logs with same trace_id
- Correlates metrics with same trace_id
- Returns TraceContext Pydantic model

Error handling:
- TraceNotFoundError if trace_id missing
- DB errors bubble up

Returns complete context for distributed trace analysis.

Tests cover complete context and missing trace error.
"
```

______________________________________________________________________

## Task 6: Implement SQL escape hatch

**Files:**

- Modify: `oneiric/adapters/observability/queries.py`
- Modify: `tests/adapters/observability/test_queries.py`

**Step 1: Write test for SQL escape hatch**

```python
@pytest.mark.unit
def test_custom_query_select_allowed(query_service):
    """Test SELECT queries are allowed."""
    result = await query_service.custom_query(
        "SELECT * FROM otel_traces LIMIT 1"
    )

    assert isinstance(result, list)


@pytest.mark.unit
def test_custom_query_with_allowed(query_service):
    """Test WITH (CTE) queries are allowed."""
    result = await query_service.custom_query(
        "WITH ranked AS (SELECT *, ROW_NUMBER() OVER () AS rn FROM otel_traces) SELECT * FROM ranked LIMIT 1"
    )

    assert isinstance(result, list)


@pytest.mark.unit
def test_custom_query_insert_rejected(query_service):
    """Test INSERT queries are rejected."""
    from oneiric.adapters.observability.errors import InvalidSQLError
    import pytest

    with pytest.raises(InvalidSQLError):
        await query_service.custom_query(
            "INSERT INTO otel_traces (trace_id) VALUES ('test')"
        )


@pytest.mark.unit
def test_custom_query_injection_attempt(query_service):
    """Test SQL injection attempts are rejected."""
    from oneiric.adapters.observability.errors import InvalidSQLError
    import pytest

    malicious = "SELECT * FROM otel_traces; DROP TABLE otel_traces;"

    with pytest.raises(InvalidSQLError):
        await query_service.custom_query(malicious)
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/adapters/observability/test_queries.py -k "custom_query" -v
```

Expected: FAIL - Method not implemented

**Step 3: Implement SQL escape hatch**

Add to `oneiric/adapters/observability/errors.py`:

```python
class InvalidSQLError(QueryError):
    """SQL escape hatch validation failed."""
    pass
```

Add to QueryService class:

```python
async def custom_query(
    self,
    sql: str,
    params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Execute raw SQL query (read-only).

    Validates SQL starts with SELECT or WITH.
    Rejects INSERT, UPDATE, DELETE, DROP, etc.

    Args:
        sql: SQL query string
        params: Optional query parameters

    Returns:
        List of dictionaries (rows)

    Raises:
        InvalidSQLError: If SQL tries to modify data or has injection attempt
    """
    # Trim and normalize
    sql_stripped = sql.strip().upper()

    # Validate: Must start with SELECT or WITH
    if not (sql_stripped.startswith("SELECT") or sql_stripped.startswith("WITH")):
        raise InvalidSQLError(
            f"Only SELECT and WITH queries allowed. Query starts with: {sql_stripped[:20]}"
        )

    # Check for common injection patterns
    dangerous_patterns = ["; DROP", "; DELETE", "; INSERT", "; UPDATE", "--", "/*"]
    sql_upper = sql.upper()
    for pattern in dangerous_patterns:
        if pattern in sql_upper:
            raise InvalidSQLError(
                f"Potentially dangerous SQL pattern detected: {pattern}"
            )

    try:
        async with self._session_factory() as session:
            result = await session.execute(sql, params or {})
            rows = result.fetchall()

            # Convert to list of dicts
            return [dict(row._mapping) for row in rows]

    except Exception as exc:
        self._logger.error("custom-query-failed", error=str(exc))
        raise
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/adapters/observability/test_queries.py -k "custom_query" -v
```

Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add oneiric/adapters/observability/queries.py oneiric/adapters/observability/errors.py tests/adapters/observability/test_queries.py
git commit -m "feat(otel): Implement SQL escape hatch

Implement QueryService.custom_query():
- Validates SQL starts with SELECT or WITH
- Rejects INSERT, UPDATE, DELETE, DROP
- Checks for injection patterns (; DROP, --, etc.)
- Executes raw SQL with parameters
- Returns list[dict] (rows)

Safety:
- Read-only validation
- Injection detection
- Parameterized queries supported

Use case: Complex queries not supported by ORM.

Tests cover allowed queries and dangerous pattern rejection.
"
```

______________________________________________________________________

## Task 7: Integrate QueryService with OTelStorageAdapter

**Files:**

- Modify: `oneiric/adapters/observability/otel.py`
- Modify: `tests/adapters/observability/test_otel_adapter.py`

**Step 1: Write integration test**

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_query_service_integration(otel_adapter, sample_traces_with_embeddings):
    """Test QueryService is accessible through OTelStorageAdapter."""
    import numpy as np

    # Access query service
    query_service = otel_adapter._query_service
    assert query_service is not None

    # Test vector similarity search
    query_embedding = np.random.rand(384)
    results = await query_service.find_similar_traces(
        embedding=query_embedding,
        threshold=0.0,
        limit=5
    )

    assert isinstance(results, list)
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/adapters/observability/test_otel_adapter.py::test_query_service_integration -v
```

Expected: FAIL - \_query_service doesn't exist

**Step 3: Integrate QueryService into OTelStorageAdapter**

Modify `oneiric/adapters/observability/otel.py`:

```python
from oneiric.adapters.observability.queries import QueryService

# In OTelStorageAdapter.__init__

self._query_service = QueryService(
    session_factory=self._session_factory
)
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/adapters/observability/test_otel_adapter.py::test_query_service_integration -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add oneiric/adapters/observability/otel.py tests/adapters/observability/test_otel_adapter.py
git commit -m "feat(otel): Integrate QueryService with OTelStorageAdapter

Integration changes:
- Import QueryService in otel.py
- Create QueryService instance in __init__
- Pass session_factory for query operations
- QueryService accessible via _query_service

OTelStorageAdapter now provides:
- Trace storage with embeddings (Phase 2)
- Query API for similarity search (Phase 3)

Integration test verifies QueryService is accessible.
"
```

______________________________________________________________________

## Summary

This plan provides:

✅ **Bite-sized tasks** - Each step is 2-5 minutes
✅ **Exact file paths** - All files specified
✅ **Complete code** - Full implementations in plan
✅ **TDD workflow** - Test first, then implement
✅ **Frequent commits** - Commit after each task
✅ **Type hints** - Full type annotations
✅ **Error handling** - Custom error types
✅ **Integration tests** - Database tests (marked)

**Total breakdown:**

- **Task 1:** Pydantic result models (4 tests)
- **Task 2:** QueryService class with ORM conversion (1 test)
- **Task 3:** Vector similarity search (2 tests)
- **Task 4:** Error pattern search (2 tests)
- **Task 5:** Trace context correlation (2 tests)
- **Task 6:** SQL escape hatch (4 tests)
- **Task 7:** Integration with OTelStorageAdapter (1 test)

**Estimated completion:** 4 hours
**Complexity:** Medium (ORM queries, vector operations, aggregation)
**Dependencies:** SQLAlchemy, Pgvector, numpy, Pydantic
