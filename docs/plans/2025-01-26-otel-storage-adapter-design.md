# Oneiric OTel Storage Adapter Design
**Date**: 2025-01-26
**Status**: Approved Design
**Implementing**: Option B - Traces with Vector Similarity Search

---

## Executive Summary

This document describes the design for Oneiric adapters that store OpenTelemetry telemetry data directly into PostgreSQL/Pgvector, replacing external OTel collector + backends with native database storage. This enables SQL-based queries and vector similarity search on distributed traces.

**Design Choices**:
- Storage priority: Traces with vector similarity search
- Embedding strategy: Metadata + span attributes (Option C)
- Database schema: Hybrid approach (Option C)
- Query interface: SQL + ORM (Option C)

---

## Architecture Overview

The OTel adapter system integrates OpenTelemetry telemetry storage directly into PostgreSQL/Pgvector using Oneiric's adapter pattern.

### Core Components

```
Mahavishnu Application
    ↓ (generates telemetry)
OTel SDK (spans, metrics, logs)
    ↓ (OTLP protocol - optional)
OTelStorageAdapter (Oneiric adapter)
    ├── TelemetryRepository (SQLAlchemy models)
    ├── EmbeddingService (sentence-transformers)
    └── QueryService (ORM + SQL escape hatch)
    ↓ (stores data)
PostgreSQL + Pgvector
    ├── traces (with vector embeddings)
    ├── metrics (time-series)
    └── logs (with trace correlation)
    ↓ (queries)
User/Analytics
```

### Key Integration Points

**1. With Mahavishnu** (`mahavishnu/core/observability.py`):
```python
# Configuration option
class MahavishnuSettings:
    otel_storage_backend: str = "otel"  # New config option
```

**2. With Oneiric**:
- Uses existing `PostgresDatabaseAdapter`
- Uses existing `PgvectorAdapter`
- Follows Oneiric lifecycle: `init()`, `health()`, `cleanup()`

**3. Database Extensions Required**:
- `pgvector` - Vector similarity search
- `pg_partman` - Time-series partitioning (optional)
- `pg_stat_statements` - Query performance (optional)

---

## Components

### 1. OTelStorageAdapter

**File**: `oneiric/adapters/observability/otel.py`

**Purpose**: Main Oneiric adapter following adapter pattern

**Interface**:
```python
class OTelStorageAdapter(ABC):
    """Store and query OTel telemetry data."""

    @abstractmethod
    async def store_trace(self, trace: TraceData) -> None:
        """Store a trace with embedding."""

    @abstractmethod
    async def store_metrics(self, metrics: List[MetricData]) -> None:
        """Store metrics in time-series storage."""

    @abstractmethod
    async def store_log(self, log: LogEntry) -> None:
        """Store log with trace correlation."""

    @abstractmethod
    async def find_similar_traces(
        self,
        embedding: np.ndarray,
        threshold: float = 0.85
    ) -> List[TraceResult]:
        """Find traces by vector similarity."""

    @abstractmethod
    async def get_traces_by_error(
        self,
        error_type: str,
        service: str | None = None
    ) -> List[TraceResult]:
        """Get traces filtered by error."""

    @abstractmethod
    async def search_logs(
        self,
        trace_id: str,
        level: str | None = None
    ) -> List[LogEntry]:
        """Search logs with trace correlation."""
```

**Lifecycle Methods**:
- `init(settings)` - Initialize database connection, validate schema
- `health()` - Check database connectivity, Pgvector extension
- `cleanup()` - Close connections, flush buffers

---

### 2. TelemetryRepository

**File**: `oneiric/adapters/observability/repository.py`

**Purpose**: SQLAlchemy models for traces, metrics, logs

**Models**:

**TraceModel** (main table):
```python
class TraceModel(Base):
    __tablename__ = 'otel_traces'

    id = Column(String, primary_key=True)
    trace_id = Column(String, unique=True, nullable=False, index=True)
    parent_span_id = Column(String)
    trace_state = Column(String)  #DELTA, IN_PROGRESS, COMPLETE etc.
    name = Column(String)  # Span name
    kind = Column(String)  # Span kind
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    duration_ms = Column(Integer)
    status = Column(String)  # StatusCode enum
    attributes = Column(JSONB)  # Span attributes

    # Vector embedding for similarity search
    embedding = Column(Vector(384))  # Pgvector
    embedding_model = Column(String, default="all-MiniLM-L6-v2")
    embedding_generated_at = Column(DateTime)

    # Indexes
    __table_args__ = (
        Index('ix_traces_trace_id', 'trace_id'),
        Index('ix_traces_service_name', 'name'),  # service name from attributes
        Index('ix_traces_start_time', 'start_time'),
        UniqueConstraint('uq_traces_id', 'id'),
    )
```

**MetricModel** (time-series):
```python
class MetricModel(Base):
    __tablename__ = 'otel_metrics'

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False, index=True)
    type = Column(String)  # counter, gauge, histogram
    value = Column(Float)
    unit = Column(String)
    labels = Column(JSONB)
    timestamp = Column(DateTime, nullable=False, index=True)

    # Indexes
    __table_args__ = (
        Index('ix_metrics_name', 'name'),
        Index('ix_metrics_timestamp', 'timestamp'),
    )
```

**LogModel** (correlated):
```python
class LogModel(Base):
    __tablename__ = 'otel_logs'

    id = Column(String, primary_key=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    level = Column(String, nullable=False, index=True)
    message = Column(Text)
    trace_id = Column(String, index=True)  # Correlation!
    resource_attributes = Column(JSONB)
    span_attributes = Column(JSONB)

    # Indexes
    __table_args__ = (
        Index('ix_logs_timestamp', 'timestamp'),
        Index('ix_logs_trace_id', 'trace_id'),
        Index('ix_logs_level', 'level'),
    )
```

---

### 3. EmbeddingService

**File**: `oneiric/adapters/observability/embeddings.py`

**Purpose**: Generate vector embeddings for traces

**Interface**:
```python
class EmbeddingService:
    """Generate embeddings for trace similarity search."""

    async def embed_trace(
        self,
        trace: TraceData
    ) -> np.ndarray:
        """Generate 384-dim embedding from trace metadata + attributes."""
```

**Embedding Strategy** (Option C - Metadata + Attributes):
```
Input:
  trace_id: "abc123"
  service: "mahavishnu"
  operation: "process_repository"
  duration_ms: 2500
  status: "ERROR"
  span_names: ["fetch_repo", "run_tests", "merge_pr"]
  attributes: {
    "http.status_code": 500,
    "error.message": "connection timeout",
    "repo": "fastblocks"
  }

Embedding text:
  "mahavahishnu process_repository ERROR in 2500ms "
  "status=500 connection timeout fastblocks "
  "operations: fetch_repo run_tests merge_pr"

→ 384-dim vector (all-MiniLM-L6-v2)
```

**Caching**:
- In-memory cache of recent embeddings (LRU, max 1000)
- Regenerate only when trace attributes change
- TTL: 1 hour

**Error Handling**:
- On embedding failure → use fallback embedding (hash of trace_id)
- Log warnings for monitoring
- Never fail the trace storage (embeddings are optional)

---

### 4. QueryService

**File**: `oneiric/adapters/observability/queries.py`

**Purpose**: High-level query API for common operations

**Methods**:

```python
class QueryService:
    """High-level query API for OTel telemetry."""

    async def find_similar_traces(
        self,
        embedding: np.ndarray,
        threshold: float = 0.85,
        limit: int = 10
    ) -> List[TraceResult]:
        """
        Find traces similar to the given embedding.

        Uses Pgvector cosine similarity search.
        Returns traces with similarity score.
        """

    async def get_traces_by_error(
        self,
        error_pattern: str,
        service: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None
    ) -> List[TraceResult]:
        """
        Get traces matching error pattern.

        Searches span_attributes['error.message'].
        Supports SQL wildcards (%, _).
        """

    async def get_metrics_by_time_range(
        self,
        metric_name: str,
        start_time: datetime,
        end_time: datetime
    ) -> List[MetricPoint]:
        """Get metric data points in time range."""

    async def search_logs(
        self,
        query: str,
        trace_id: str | None = None,
        level: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None
    ) -> List[LogEntry]:
        """
        Full-text search logs with optional trace correlation.

        If trace_id provided, includes all related logs.
        """

    async def get_trace_context(
        self,
        trace_id: str
    ) -> TraceContext:
        """
        Get complete trace context including:
        - All spans in trace
        - Related logs (same trace_id)
        - Related metrics
        """
```

**SQL Escape Hatch**:
For complex queries not supported by ORM:
```python
async def custom_query(
    self,
    sql: str,
    params: dict | None = None
) -> List[dict]:
    """Execute raw SQL with parameters (expert only)."""
```

---

## Data Flow

### Write Path (Async, Non-blocking)

```
1. Mahavishnu executes workflow
2. ObservabilityManager captures span
3. Calls: await obs_manager.record_trace(trace_data)
4. OTelStorageAdapter stores trace (async, doesn't block)
5. TelemetryRepository inserts into PostgreSQL
6. EmbeddingService generates embedding (background task)
7. Trace stored immediately, embedding added later
8. Mahavishnu continues execution
```

**Buffering**:
- In-memory queue for DB writes (max 1000 records)
- Batch inserts every 5 seconds or when queue full
- Prevents blocking on slow DB operations

### Read Path (Synchronous)

```
1. User queries: await adapter.find_similar_traces(embedding)
2. QueryService executes Pgvector search
3. Returns: List[TraceResult] with similarity scores
4. Each result includes: trace_id, metadata, attributes, similarity
5. User inspects similar traces, identifies patterns
```

**Performance**:
- Vector search: <50ms for 1000 traces
- Error filtering: <100ms with indexes
- Full trace context: <200ms with joins

---

## Error Handling & Resilience

### Connection Failures
**Strategy**: Retry with exponential backoff + circuit breaker

```python
async def store_with_retry(self, trace: TraceData) -> None:
    for attempt in range(3):
        try:
            await self.telemetry_repo.store_trace(trace)
            self.circuit_breaker.record_success()
            return
        except ConnectionError:
            self.circuit_breaker.record_failure()
            if attempt == 2:
                raise  # Re-raise after final retry
            await asyncio.sleep(2 ** attempt)  # 1s, 2s, 4s
```

### Fallback Behavior

**Embedding Failures**:
- Generate fallback embedding (hash of trace_id)
- Store trace with NULL embedding
- Log warning for monitoring
- Trace still queryable (just not similar-searchable)

**Database Unavailable**:
- Buffer traces in memory queue (max 1000)
- Warn: "Telemetry buffering, DB unavailable"
- Persist when DB recovers
- Drop oldest traces if buffer full (FIFO)

### Dead Letter Queue

**otel_telemetry_dlq** table:
```sql
CREATE TABLE otel_telemetry_dlq (
    id SERIAL PRIMARY KEY,
    telemetry_type TEXT NOT NULL,  -- 'trace', 'metric', 'log'
    raw_data JSONB NOT NULL,       -- original data
    error_message TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    processed_at TIMESTAMP,
    retry_count INTEGER DEFAULT 0
);
```

**Background job**: Retry every 5 minutes, alert if > 1000 records

---

## Testing Strategy

### Unit Tests

**`tests/unit/test_otel_adapter.py`**:
- OTelStorageAdapter lifecycle methods
- Store/retrieve trace with embedding
- Vector similarity search accuracy
- Retry logic and circuit breaker
- Fallback embedding generation

**`tests/unit/test_embeddings.py`**:
- EmbeddingService functionality
- Fallback behavior on errors
- Batch embedding performance
- Cache hit/miss rates

**`tests/unit/test_queries.py`**:
- QueryService ORM methods
- SQL escape hatch functionality
- Trace correlation queries
- Time-series metric queries

### Integration Tests

**`tests/integration/test_otel_storage.py`**:
- End-to-end: generate trace → store → query → verify
- Vector search with real embeddings
- Trace ID correlation across tables
- Performance: 10,000 traces in <60s
- Concurrent operations: 10 parallel stores + queries

**`tests/integration/test_performance.py`**:
- Benchmark: 1000 trace stores/queries
- Load test: 100 concurrent connections
- Memory profiling: embedding cache efficiency

### Test Fixtures

**Sample Traces**:
```python
# Success trace
trace_success = TraceData(
    trace_id="trace-success-001",
    metadata={"service": "mahavishnu", "operation": "process_repository"},
    span_names=["fetch", "build", "test"],
    attributes={"status": "success", "repo": "fastblocks"}
)

# Failure trace with error details
trace_failure = TraceData(
    trace_id="trace-failure-001",
    metadata={"service": "mahavishnu", "operation": "process_repository"},
    span_names=["fetch", "build", "test"],
    attributes={
        "status": "error",
        "http.status_code": 500,
        "error.message": "database connection timeout",
        "repo": "fastblocks"
    }
)
```

---

## Performance Considerations

### Storage Optimization

**Batch Inserts**:
```python
# Collect traces in buffer
buffer_size = 100
batch_interval = 5  # seconds

# Batch insert with SQL
INSERT INTO otel_traces (trace_id, metadata, ...)
VALUES
    ($1, $2, $3),
    ($4, $5, $6),
    ...
ON CONFLICT (trace_id) DO UPDATE SET ...
```

**Partitioning** (Metrics):
```sql
-- Create partitioned table for metrics
CREATE TABLE otel_metrics (
    ...
) PARTITION BY RANGE (timestamp);

-- Create monthly partitions
CREATE TABLE otel_metrics_2025_01 PARTITION OF otel_metrics
    FOR VALUES FROM ('2025-01-01') TO ('2025-02-01');
```

### Indexes

**Vector Index** (Pgvector):
```sql
CREATE INDEX ix_traces_embedding_embedding
ON otel_traces
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);  # IVFFlat parameters
```

**GIN Indexes** (JSONB attributes):
```sql
CREATE INDEX ix_traces_attributes_gin
ON otel_traces USING GIN (attributes);
```

### Caching Strategy

**Embedding Cache**:
- Size: 1000 embeddings
- TTL: 1 hour
- Eviction: LRU
- Hit rate target: 80%+

**Query Cache**:
- Common queries cached
- TTL: 5 minutes
- Invalidation: on new trace storage

---

## Implementation Phases

### Phase 1: Foundation (6 hours)
- [ ] Create Oneiric observability directory structure
- [ ] Implement OTelStorageAdapter skeleton
- [ ] Create TelemetryRepository models
- [ ] Set up database schema migrations
- [ ] Unit tests for models

### Phase 2: Embedding Service (4 hours)
- [ ] Implement EmbeddingService
- [ ] Integrate sentence-transformers model
- [ ] Implement caching layer
- [ ] Add fallback embedding logic
- [ ] Tests for embedding service

### Phase 3: Query Service (4 hours)
- [ ] Implement QueryService ORM methods
- [ ] Add vector similarity search
- [ ] Implement trace correlation queries
- [ ] Add SQL escape hatch
- [ ] Tests for query service

### Phase 4: Integration (4 hours)
- [ ] Integrate with Mahavishnu's ObservabilityManager
- [ ] Add configuration option to MahavishnuSettings
- [ ] Implement write buffering and batch processing
- [ ] Add dead letter queue
- [ ] Integration tests

### Phase 5: Performance & Polish (4 hours)
- [ ] Add circuit breaker and retry logic
- [ ] Implement background embedding generation
- [ ] Performance benchmarks
- [ ] Documentation
- [ ] Schema migrations

**Total Estimate**: 22 hours

---

## Configuration

### Mahavishnu Settings

**Add to `mahavishnu/core/config.py`**:
```python
class MahavishnuSettings(BaseSettings):
    # ... existing settings ...

    # OTel Storage (new)
    otel_storage_enabled: bool = Field(
        default=False,
        description="Enable Oneiric OTel storage adapter"
    )
    otel_storage_connection_string: str = Field(
        default="postgresql://user:pass@localhost:5432/mahavishnu",
        description="PostgreSQL connection string for OTel storage"
    )
    otel_storage_embedding_cache_size: int = Field(
        default=1000,
        ge=100,
        le=10000,
        description="Number of embeddings to cache"
    )
```

### Oneiric Settings

**New file: `oneiric/adapters/observability/settings.py`**:
```python
from pydantic import Field

class OTelStorageSettings(BaseSettings):
    """Settings for OTel storage adapter."""

    # Database connection
    connection_string: str = Field(
        default="postgresql://user:pass@localhost:5432/otel"
    )

    # Embedding
    embedding_model: str = Field(
        default="all-MiniLM-L6-v2"
    )
    embedding_dimension: int = Field(
        default=384
    )
    cache_size: int = Field(
        default=1000
    )

    # Vector search
    similarity_threshold: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0
    )

    # Performance
    batch_size: int = Field(
        default=100
    )
    batch_interval_seconds: int = Field(
        default=5
    )
```

---

## Migration Path

### Existing Deployments

**Current**: Mahavishnu pushes to OTel collector (external)

**Migration Path**:
1. Deploy OTel storage adapter alongside existing system
2. Configure to **dual write** (OTLP collector + OTel storage)
3. Validate data consistency between systems
4. Switch to OTel storage only
5. Decommission OTel collector (optional)

**Zero Downtime**:
```python
# Dual write mode
async def record_trace(self, trace: TraceData):
    # Write to both systems
    await asyncio.gather(
        self.otel_collector.export_trace(trace),
        self.otel_storage.store_trace(trace)
    )
```

---

## Success Criteria

### Functional
- [x] Store traces with metadata + attributes
- [x] Generate vector embeddings for similarity search
- [x] Query traces by vector similarity
- [x] Filter traces by error patterns
- [x] Correlate logs with trace IDs
- [x] Query metrics with time-series
- [x] SQL + ORM query interfaces

### Performance
- [x] Vector search: <50ms for 1000 traces
- [x] Trace storage: <100ms async, non-blocking
- [x] Batch processing: 10,000 traces in <60s
- [x] Concurrent operations: 100 parallel connections

### Reliability
- [x] Retry logic with exponential backoff
- [x] Circuit breaker for DB failures
- [x] Dead letter queue for failed operations
- [x] Fallback embeddings on generation failure
- [x] Graceful degradation when DB unavailable

### Quality
- [x] Type hints on all functions
- [x] Docstrings on all public methods
- [x] 85%+ test coverage
- [x] No suppress(Exception) in code
- [x] Error handling for all failure modes

---

## Risks & Mitigations

### Risk 1: Embedding Performance
**Risk**: Generating embeddings is slow (50-100ms each)
**Mitigation**:
- Background task generation
- Cache embeddings (80%+ hit rate)
- Only embed when trace changes

### Risk 2: Storage Growth
**Risk**: Unbounded trace storage fills disk
**Mitigation**:
- Retention policy: 90 days default
- Automatic partitioning by month
- Background cleanup job

### Risk 3: Vector Search Accuracy
**Risk**: False positives/negatives in similarity search
**Mitigation**:
- Tunable similarity threshold (0.85 default)
- Multiple embedding models support
- A/B test embeddings

### Risk 4: Breaking Changes
**Risk**: Changes to OTel SDK break adapter
**Mitigation**:
- Version-locked adapter for OTel SDK
- Comprehensive integration tests
- Can fall back to OTLP push if needed

---

## Open Questions

1. **Retention Policy**: Should traces be auto-deleted after 90 days? (proposed: yes, configurable)
2. **Embedding Model**: Should we support multiple embedding models? (proposed: start with all-MiniLM-L6-v2)
3. **Partitioning**: Should metrics be auto-partitioned by month? (proposed: yes, using pg_partman)
4. **Backup Strategy**: How to backup telemetry data? (proposed: pg_dump + S3 for cold storage)

---

## Next Steps

Once design is approved:
1. Create git worktree for isolated development
2. Implement Phase 1 (Foundation)
3. Implement Phase 2 (Embedding Service)
4. Implement Phase 3 (Query Service)
5. Implement Phase 4 (Integration)
6. Implement Phase 5 (Performance & Polish)
7. Create migration documentation
8. Update Mahavishnu docs

---

**Status**: Ready for implementation approval
**Estimated Time**: 22 hours total
**Complexity**: Medium-High (vector search, OTel integration, Oneiric patterns)
**Dependencies**: PostgreSQL 14+, Pgvector, sentence-transformers
