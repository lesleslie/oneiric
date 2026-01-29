# Phase 3: QueryService Design

**Date:** 2025-01-27
**Status:** Approved Design
**Implementing:** Vector similarity search and trace correlation queries

______________________________________________________________________

## Executive Summary

Phase 3 implements the QueryService that provides high-level query API for OTel telemetry data using SQLAlchemy ORM + Pgvector for vector similarity search. This completes the core OTel storage functionality - after Phase 3, the system can store traces with embeddings (Phase 1-2) and query them intelligently (Phase 3).

**Key Features:**

- Vector similarity search using Pgvector cosine similarity
- Trace correlation queries (join traces, logs, metrics)
- Time-series metric queries with optional aggregation
- Full-text log search with trace correlation
- Read-only SQL escape hatch for complex queries
- Pydantic models for type-safe results
- Explicit error handling (never silent failures)

**Design Decisions:**

- Error handling: Empty list for no results, exceptions for DB errors
- Return types: Pydantic models (TraceContext, TraceResult, MetricPoint, LogEntry)
- SQL escape hatch: Read-only validation (must start with SELECT/WITH)
- Metric aggregation: Optional `aggregate: str | None` parameter
- Vector search: Cosine similarity without IVFFlat index (deferred to Phase 5)

______________________________________________________________________

## Architecture Overview

**File:** `oneiric/adapters/observability/queries.py`

**Component hierarchy:**

```
OTelStorageAdapter
    ├── EmbeddingService (Phase 2) ✓
    └── QueryService (Phase 3) ← Building this
            ├── Vector similarity search (Pgvector)
            ├── Trace correlation queries (ORM)
            ├── Time-series aggregation (SQL)
            └── SQL escape hatch (raw SQL)
```

**QueryService lifecycle:**

```python
class QueryService:
    def __init__(self, session_factory: async_sessionmaker):
        """Initialize with SQLAlchemy session factory."""
        self._session_factory = session_factory
        self._logger = get_logger("otel.queries")
```

**Key integration:** QueryService doesn't own the database connection - it receives session_factory from OTelStorageAdapter and creates sessions per query. This allows sharing connections and proper lifecycle management.

**Single Responsibility:** QueryService ONLY queries data. Storage, embedding generation, and lifecycle are separate concerns.

______________________________________________________________________

## Query API Design

**File:** `oneiric/adapters/observability/queries.py`

### Method 1: Vector Similarity Search

```python
async def find_similar_traces(
    self,
    embedding: np.ndarray,
    threshold: float = 0.85,
    limit: int = 10
) -> list[TraceResult]:
    """
    Find traces similar to the given embedding.

    Uses Pgvector cosine similarity: distance < 1 - threshold.
    Returns traces with similarity_score in [0, 1].

    Args:
        embedding: 384-dim vector
        threshold: Minimum similarity (0.0-1.0, default 0.85)
        limit: Max results (default 10)

    Returns:
        Empty list if no matches, raises on DB error
    """
```

### Method 2: Error Pattern Search

```python
async def get_traces_by_error(
    self,
    error_pattern: str,
    service: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    limit: int = 100
) -> list[TraceResult]:
    """
    Find traces matching error pattern.

    Searches attributes->>'error.message' using SQL LIKE.
    Supports wildcards: % (any chars), _ (single char).

    Example: error_pattern = "%timeout%" finds "connection timeout"
    """
```

### Method 3: Time-series Metrics

```python
async def get_metrics_by_time_range(
    self,
    metric_name: str,
    start_time: datetime,
    end_time: datetime,
    aggregate: str | None = None  # "1m", "5m", "15m", "1h" or None
) -> list[MetricPoint]:
    """
    Get metric data with optional time-bucket aggregation.

    If aggregate=None: Returns raw data points
    If aggregate="5m": Averages values into 5-minute buckets
    """
```

### Method 4: Log Search

```python
async def search_logs(
    self,
    query: str,
    trace_id: str | None = None,
    level: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    limit: int = 100
) -> list[LogEntry]:
    """
    Full-text search logs with optional trace correlation.

    Searches message column using SQL LIKE.
    If trace_id provided, includes all logs from that trace.
    """
```

### Method 5: Trace Context (Correlation)

```python
async def get_trace_context(
    self,
    trace_id: str
) -> TraceContext:
    """
    Get complete trace context (Pydantic model).

    Returns:
        TraceContext with:
        - trace: TraceResult
        - logs: list[LogEntry]
        - metrics: list[MetricPoint]

    Raises:
        NotFoundError if trace_id doesn't exist
    """
```

### Method 6: SQL Escape Hatch

```python
async def custom_query(
    self,
    sql: str,
    params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """
    Execute raw SQL query (read-only).

    Validates SQL starts with SELECT or WITH.
    Raises ValueError if SQL tries to modify data.
    """
```

______________________________________________________________________

## Data Models

**File:** `oneiric/adapters/observability/types.py` (extend existing file)

### TraceResult

```python
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
```

### LogEntry

```python
class LogEntry(BaseModel):
    """Log entry from query results."""
    id: str
    timestamp: datetime
    level: str
    message: str
    trace_id: str | None = None
    resource_attributes: dict[str, Any] = {}
    span_attributes: dict[str, Any] = {}
```

### MetricPoint

```python
class MetricPoint(BaseModel):
    """Metric data point."""
    name: str
    value: float
    unit: str | None = None
    labels: dict[str, Any] = {}
    timestamp: datetime
```

### TraceContext

```python
class TraceContext(BaseModel):
    """Complete trace context with correlated data."""
    trace: TraceResult
    logs: list[LogEntry] = []
    metrics: list[MetricPoint] = []
```

**Conversion pattern:** ORM → Pydantic

```python
# In QueryService methods
def _orm_to_result(self, orm_model: TraceModel) -> TraceResult:
    """Convert SQLAlchemy model to Pydantic result."""
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

______________________________________________________________________

## Vector Similarity Implementation

**Pgvector cosine similarity:**

```python
# In find_similar_traces()
async def find_similar_traces(
    self,
    embedding: np.ndarray,
    threshold: float = 0.85,
    limit: int = 10
) -> list[TraceResult]:
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

        return results
```

**Key points:**

- `<=>` is Pgvector's cosine distance operator
- Cosine similarity = `1 - cosine_distance`
- Filter: `similarity > threshold` (e.g., 0.85)
- Order by most similar first
- No IVFFlat index yet (deferred to Phase 5)
- Fallback to sequential scan (still works, just slower)

______________________________________________________________________

## Error Handling

**Strategy:** Explicit errors, never silent failures

### Error Types

```python
# In oneiric/adapters/observability/errors.py (extend existing)
class QueryError(OneiricError):
    """Base class for query errors."""
    pass

class TraceNotFoundError(QueryError):
    """Trace ID not found in database."""
    pass

class InvalidSQLError(QueryError):
    """SQL escape hatch validation failed."""
    pass

class InvalidEmbeddingError(QueryError):
    """Embedding dimension mismatch."""
    pass
```

### Error Handling by Method

**find_similar_traces():**

- Invalid embedding dimension → `raise InvalidEmbeddingError`
- Database connection error → `raise` (bubble up)
- No results → Return `[]` (not an error)

**get_traces_by_error():**

- Invalid error_pattern → Return `[]` (SQL LIKE handles it)
- Database error → `raise` (bubble up)
- No matches → Return `[]`

**get_trace_context():**

- Trace ID not found → `raise TraceNotFoundError`
- Database error → `raise` (bubble up)

**custom_query():**

- SQL doesn't start with SELECT/WITH → `raise InvalidSQLError`
- SQL injection attempt (params mismatch) → `raise InvalidSQLError`
- Database error → `raise` (bubble up)

**get_metrics_by_time_range():**

- Invalid aggregate interval → `raise ValueError`
- Database error → `raise` (bubble up)
- No data → Return `[]`

**search_logs():**

- Invalid datetime range → `raise ValueError`
- Database error → `raise` (bubble up)
- No matches → Return `[]`

### Logging

```python
# All query methods log:
self._logger.debug("query-executed", method="find_similar_traces",
                   result_count=len(results))
self._logger.error("query-failed", method="find_similar_traces",
                   error=str(exc))
```

______________________________________________________________________

## Testing Strategy

**File:** `tests/adapters/observability/test_queries.py`

### Unit Tests (Fast, No Database)

**12 tests total:**

1. **ORM conversion** (1 test)

   - `test_orm_to_trace_result_conversion()` - Verify TraceModel → TraceResult

1. **SQL validation** (3 tests)

   - `test_custom_query_select_allowed()` - SELECT passes
   - `test_custom_query_with_allowed()` - WITH passes
   - `test_custom_query_insert_rejected()` - INSERT raises InvalidSQLError

1. **Aggregation parsing** (2 tests)

   - `test_parse_aggregate_interval_valid()` - "5m", "1h" parsed correctly
   - `test_parse_aggregate_interval_invalid()` - "7x" raises ValueError

1. **Error handling** (3 tests)

   - `test_find_similar_traces_invalid_dimension()` - Wrong embedding size raises
   - `test_get_trace_context_not_found()` - Missing trace raises NotFoundError
   - `test_custom_query_injection_attempt()` - Malicious SQL rejected

1. **Query construction** (3 tests)

   - Test WHERE clauses built correctly
   - Test ORDER BY applied
   - Test LIMIT enforced

### Integration Tests (Slow, Requires PostgreSQL)

**8 tests total:**

1. **Vector similarity** (2 tests)

   - `test_find_similar_traces_returns_results()` - Finds similar traces
   - `test_find_similar_traces_threshold_filtering()` - Filters by similarity

1. **Error search** (2 tests)

   - `test_get_traces_by_error_pattern_matching()` - SQL LIKE works
   - `test_get_traces_by_error_with_filters()` - service/time filters work

1. **Time-series metrics** (2 tests)

   - `test_get_metrics_raw_data()` - Returns all points
   - `test_get_metrics_aggregated()` - 5-minute buckets work

1. **Log search** (1 test)

   - `test_search_logs_with_trace_correlation()` - Finds logs by trace_id

1. **Trace context** (1 test)

   - `test_get_trace_context_complete()` - Returns trace + logs + metrics

**Test fixtures:**

```python
@pytest.fixture
async def query_service(test_session_factory):
    """Create QueryService with test database."""
    return QueryService(session_factory=test_session_factory)

@pytest.fixture
async def sample_traces(query_service):
    """Insert sample traces for testing."""
    # Insert 10 traces with embeddings
```

**Coverage goals:**

- Query construction: 100%
- Error handling: 100%
- ORM conversion: 100%
- SQL validation: 100%

______________________________________________________________________

## Performance Considerations

### Current Performance (Phase 3 - No Index)

**Vector similarity search:**

- Sequential scan through all traces
- Complexity: O(n) where n = total traces
- Expected latency:
  - 1K traces: ~50ms
  - 10K traces: ~500ms
  - 100K traces: ~5s (unacceptable)

**Why this is OK for Phase 3:**

- System is new, dataset will be small initially
- Defer optimization until we have real data (Phase 5)
- IVFFlat index requires 1000+ traces to be effective

### Phase 5 Optimization Plan

**IVFFlat index creation:**

```sql
-- Create index after accumulating 1000+ traces
CREATE INDEX otel_traces_embedding_ivfflat
ON otel_traces
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);  -- 100 = sqrt(num_vectors)
```

**Expected post-index performance:**

- Vector similarity: ~10ms (100K traces)
- 50x faster than sequential scan
- Index maintenance overhead: ~5% on writes

### Current Phase Optimizations

**Connection pooling:**

- SQLAlchemy session factory manages connections
- Reuse sessions across queries
- Configurable pool size (default: max_retries from settings)

**Query batching:**

- No N+1 query problems
- Use `selectinload()` for eager loading relationships
- Single query for trace context (join traces + logs + metrics)

**Result limits:**

- Default `limit=10` prevents large result sets
- Max `limit=1000` enforced
- Caller can paginate manually

### Memory Usage

**Per query:**

- Embedding vector: 1.5KB
- TraceResult: ~2KB
- 100 results × 2KB = ~200KB per query

**Session overhead:**

- SQLAlchemy session: ~100KB
- Connection: ~50KB
- **Total per query: ~350KB**

### Monitoring

**Metrics to track:**

```python
self._logger.info("query-executed",
                  method="find_similar_traces",
                  result_count=len(results),
                  duration_ms=elapsed_time)
```

**Performance targets:**

- Vector similarity (no index): \<500ms (up to 10K traces)
- Error pattern search: \<100ms
- Time-series query: \<200ms
- Log search: \<100ms

______________________________________________________________________

## Implementation Plan

### Task Breakdown

1. **Create queries.py** - QueryService class with all methods
1. **Add Pydantic models** - TraceResult, LogEntry, MetricPoint, TraceContext
1. **Implement vector similarity** - Pgvector cosine similarity
1. **Implement trace correlation** - get_trace_context with joins
1. **Implement error search** - SQL LIKE pattern matching
1. **Implement time-series queries** - With aggregation
1. **Implement log search** - Full-text with trace correlation
1. **SQL escape hatch** - Read-only validation
1. **Error handling** - Custom error types
1. **Tests** - Unit + integration tests
1. **Integration** - Connect with OTelStorageAdapter
1. **Documentation** - Docstrings + examples

### Estimated Time

- Implementation: 3 hours
- Testing: 1 hour
- **Total: 4 hours**

______________________________________________________________________

## Success Criteria

### Functional

- ✅ Find similar traces using vector similarity
- ✅ Search traces by error pattern
- ✅ Query metrics with time aggregation
- ✅ Search logs with trace correlation
- ✅ Get complete trace context (trace + logs + metrics)
- ✅ Execute read-only SQL queries safely

### Performance

- ✅ Vector similarity: \<500ms (up to 10K traces)
- ✅ Error search: \<100ms
- ✅ Time-series query: \<200ms
- ✅ Log search: \<100ms

### Quality

- ✅ Type hints on all functions
- ✅ Docstrings on all public methods
- ✅ 100% test coverage (core logic)
- ✅ No suppress(Exception)
- ✅ Comprehensive error handling

______________________________________________________________________

## Next Steps

After design approval:

1. Create git worktree for Phase 3
1. Implement QueryService
1. Create tests (unit + integration)
1. Integrate with OTelStorageAdapter
1. Performance benchmarks
1. Update documentation

______________________________________________________________________

**Status:** Ready for implementation approval
**Estimated Time:** 4 hours
**Complexity:** Medium (ORM queries, vector operations, aggregation)
**Dependencies:** SQLAlchemy, Pgvector, numpy
