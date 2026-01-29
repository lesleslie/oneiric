# Phase 2: EmbeddingService Design

**Date:** 2025-01-27
**Status:** Approved Design
**Implementing:** Vector embeddings for trace similarity search

______________________________________________________________________

## Executive Summary

Phase 2 implements the EmbeddingService that generates 384-dimensional vector embeddings from trace telemetry using sentence-transformers (all-MiniLM-L6-v2 model). These embeddings enable semantic similarity search - finding traces that are "similar" even without exact keyword matches.

**Key Features:**

- sentence-transformers integration (all-MiniLM-L6-v2, 384 dimensions)
- LRU caching (1000 entries, ~1.5MB memory)
- Fallback embeddings on model failure
- Async generation (non-blocking)
- Comprehensive testing with mocks

______________________________________________________________________

## Architecture Overview

```
Trace Data (dict)
    ↓
EmbeddingService.embed_trace(trace)
    ├── Check cache (hash of trace)
    │   ├─ Hit → Return cached (<1ms)
    │   └─ Miss → Continue
    ↓
Text Construction
    ├── "{service} {operation} {status} in {duration_ms}ms"
    ├── "attributes: {key}={value} ..."
    └─ Result: Human-readable text
    ↓
sentence-transformers Model
    ├── all-MiniLM-L6-v2 (23MB)
    ├── Input: Text string
    └─ Output: np.ndarray (384,)
    ↓
Cache (lru_cache, max 1000)
    └─ Store for next lookup
    ↓
Return np.ndarray (384,)
```

**Single Responsibility:** EmbeddingService ONLY generates embeddings. Storage, querying, and lifecycle are separate concerns.

______________________________________________________________________

## Components

### 1. EmbeddingService

**File:** `oneiric/adapters/observability/embeddings.py`

**Interface:**

```python
class EmbeddingService:
    """Generate embeddings for trace similarity search."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        """Initialize sentence-transformers model."""
        self._model = None  # Lazy-loaded
        self._model_name = model_name

    async def embed_trace(
        self,
        trace: dict[str, Any],
        cache_key: str | None = None
    ) -> np.ndarray:
        """
        Generate 384-dim embedding from trace metadata + attributes.

        Args:
            trace: Trace data dictionary
            cache_key: Optional cache key (hash of trace)

        Returns:
            np.ndarray: 384-dimensional vector
        """
```

**Responsibilities:**

- Lazy-load sentence-transformers model on first use
- Generate human-readable text from trace
- Encode text to vector
- Cache results (LRU, 1000 entries)
- Fallback to hash-based vector on failure

______________________________________________________________________

### 2. Text Construction

**Strategy:** Convert trace dict → human-readable text

**Template:**

```python
text = (
    f"{service} {operation} {status} in {duration_ms}ms "
    f"attributes: "
    f"{' '.join(f'{k}={v}' for k, v in attributes.items())}"
)
```

**Example:**

```python
Input:
{
    "service": "mahavishnu",
    "operation": "process_repository",
    "status": "ERROR",
    "duration_ms": 2500,
    "attributes": {
        "http.status_code": 500,
        "error.message": "connection timeout",
        "repo": "fastblocks"
    }
}

Output:
"mahavishnu process_repository ERROR in 2500ms "
"http.status_code=500 error.message=connection timeout repo=fastblocks"
```

**Why this works:**

- sentence-transformers understands semantic meaning
- "connection timeout" ≈ "network error" (cosine similarity >0.8)
- HTTP status codes capture error types
- Service/operation provide context

______________________________________________________________________

### 3. Caching Layer

**Implementation:** `functools.lru_cache(maxsize=1000)`

**Cache key generation:**

```python
cache_key = hash(frozenset(sorted(trace.items())))
```

**Behavior:**

- **Hit:** Return cached embedding immediately (\<1ms)
- **Miss:** Generate embedding (50-100ms), cache it
- **Eviction:** LRU removes oldest when cache >1000

**Memory:**

- Each embedding: 384 × 4 bytes = ~1.5KB
- 1000 embeddings: ~1.5MB total
- Configurable via `settings.cache_size`

**Cache effectiveness:**

- Expected hit rate: 60-80% (repeated traces)
- Same trace attributes = same embedding
- Cache key changes if attributes change

______________________________________________________________________

### 4. Fallback Logic

**Purpose:** Generate embeddings when model fails

**Implementation:**

```python
def _generate_fallback_embedding(trace_id: str) -> np.ndarray:
    """Generate deterministic vector from trace_id hash."""
    hash_int = int(
        hashlib.sha256(trace_id.encode()).hexdigest(), 16
    )
    # Convert hash to 384-dim vector [0, 1]
    return np.array([
        (hash_int >> i) & 0xFF
        for i in range(384)
    ]) / 255.0
```

**Properties:**

- Deterministic: same trace_id = same vector
- Fast: \<1ms (no ML model)
- Enables similarity search (same traces cluster)
- No external dependencies

**When to use:**

- Model not installed
- Model download fails
- Model inference OOM error
- Model timeout
- Invalid trace data

**Monitoring:**

```python
logger.warning(
    "embedding-generation-failed",
    error=str(exc),
    trace_id=trace["trace_id"],
    fallback=True
)
```

______________________________________________________________________

## Data Flow

### Synchronous Flow (for testing)

```
1. EmbeddingService.embed_trace(trace_dict)
    ↓
2. Check cache (by trace hash)
    ├─ Hit → Return cached (<1ms)
    └─ Miss → Continue
    ↓
3. Build text from trace
    ↓
4. model.encode(text) [50-100ms]
    ↓
5. Cache result
    ↓
6. Return np.ndarray (384,)
```

### Async Flow (production)

```
1. OTelStorageAdapter.store_trace(trace_dict)
    ├─ Store trace immediately (no embedding yet)
    └─ Schedule background embedding task
    ↓
2. Background task: EmbeddingService.embed_trace(trace_dict)
    ↓
3. Generate embedding (cached or fresh)
    ↓
4. Update trace in DB with embedding column
    ↓
5. Trace now searchable by similarity
```

**Why async in production:**

- Embedding takes 50-100ms
- Would block Mahavishnu if synchronous
- Better to store trace fast, embed later
- Fallback embedding enables immediate search

______________________________________________________________________

## Error Handling

### Failure Scenarios

1. **Model not installed**

   - First download attempt fails
   - Network error
   - **Action:** Use fallback, log warning

1. **Model corrupted**

   - Downloaded file broken
   - Incompatible version
   - **Action:** Use fallback, log error

1. **OOM error**

   - Not enough RAM for 23MB model
   - **Action:** Use fallback, log critical error

1. **Invalid trace data**

   - Missing required fields
   - Wrong data types
   - **Action:** Use fallback, log warning

1. **Model timeout**

   - Inference takes too long
   - **Action:** Use fallback, log warning

### Error Handling Pattern

```python
try:
    embedding = await self._generate_embedding(trace)
except Exception as exc:
    logger.warning(
        "embedding-generation-failed",
        error=str(exc),
        trace_id=trace.get("trace_id"),
        fallback=True
    )
    embedding = self._generate_fallback_embedding(
        trace.get("trace_id", "unknown")
    )
# Never fails - always returns embedding
```

**Benefits:**

- ✅ Trace storage never fails
- ✅ Deterministic fallback
- ✅ Monitoring via logs
- ✅ Can re-embed later

______________________________________________________________________

## Testing Strategy

### Unit Tests (fast, no model)

**File:** `tests/adapters/observability/test_embeddings.py`

**Tests:**

1. `test_text_construction_success()` - Build text from trace
1. `test_text_construction_empty_attributes()` - Handle missing attributes
1. `test_cache_key_generation()` - Deterministic cache keys
1. `test_fallback_embedding_deterministic()` - Same ID = same vector
1. `test_fallback_embedding_dimension()` - 384 dimensions
1. `test_cache_hit_miss()` - LRU behavior
1. `test_model_failure_fallback()` - Exception handling

**Fixtures:**

```python
@pytest.fixture
def sample_trace_dict():
    return {
        "trace_id": "trace-001",
        "span_id": "span-001",
        "name": "Test operation",
        "service": "test-service",
        "operation": "test_op",
        "status": "OK",
        "duration_ms": 100,
        "attributes": {"key": "value"}
    }

@pytest.fixture
def mock_sentence_transformer(monkeypatch):
    # Mock SentenceTransformer
    pass
```

### Integration Tests (slow, requires model)

**Tests:**

1. `test_real_model_embedding_dimension()` - Output shape (384,)
1. `test_embedding_similarity()` - Same trace = same embedding
1. `test_embedding_uniqueness()` - Different traces = different embeddings
1. `test_cache_behavior_real_model()` - Cache hit/miss with real model
1. `test_model_download()` - First download works

**Markers:** `@pytest.mark.integration`, `@pytest.mark.slow`

### Test Coverage Goals

- Text construction: 100%
- Cache logic: 100%
- Fallback logic: 100%
- Error handling: 100%

______________________________________________________________________

## Performance Considerations

### Model Loading

- **First call:** ~2-5 seconds (download + load)
- **Subsequent calls:** \<100ms (already loaded)
- **Lazy loading:** Load on first `embed_trace()` call

### Embedding Generation

- **Cached:** \<1ms (hash lookup)
- **Uncached:** 50-100ms (model inference)
- **Target hit rate:** 60-80%

### Memory

- **Model size:** 23MB (all-MiniLM-L6-v2)
- **Cache size:** 1.5MB (1000 embeddings × 1.5KB)
- **Total:** ~25MB per process

### Optimization Opportunities

- Background model loading (preload on adapter init)
- Batch embedding (multiple traces at once)
- Model quantization (INT8 vs FP32)
- Larger cache (10,000 entries = 15MB)

______________________________________________________________________

## Configuration

**Add to `OTelStorageSettings`:**

```python
class OTelStorageSettings(BaseSettings):
    # ... existing fields ...

    # Embedding (already exists)
    embedding_model: str = Field(
        default="all-MiniLM-L6-v2"
    )
    embedding_dimension: int = Field(
        default=384
    )
    cache_size: int = Field(
        default=1000,
        ge=100,
        le=10000
    )
```

**No new config needed** - reusing existing fields.

______________________________________________________________________

## Implementation Plan

### Task Breakdown

1. **Create embeddings.py** - EmbeddingService class
1. **Text construction** - Build text from trace dict
1. **Cache integration** - lru_cache with cache key
1. **Fallback logic** - Hash-based embedding
1. **Error handling** - Try/except with logging
1. **Tests** - Unit + integration tests
1. **Integration** - Connect with OTelStorageAdapter
1. **Documentation** - Docstrings + examples

### Estimated Time

- Implementation: 2-3 hours
- Testing: 1 hour
- Integration: 1 hour
- **Total: 4 hours**

______________________________________________________________________

## Success Criteria

### Functional

- ✅ Generate 384-dim embeddings from traces
- ✅ LRU cache (1000 entries) working
- ✅ Fallback embedding on model failure
- ✅ Same trace = same embedding (deterministic)
- ✅ Different traces = different embeddings

### Performance

- ✅ Cached embedding: \<1ms
- ✅ Uncached embedding: \<100ms
- ✅ Memory: \<25MB total

### Quality

- ✅ Type hints on all functions
- ✅ Docstrings on all public methods
- ✅ 100% test coverage (core logic)
- ✅ No suppress(Exception)
- ✅ Comprehensive error handling

______________________________________________________________________

## Next Steps

After design approval:

1. Create git worktree for Phase 2
1. Implement EmbeddingService
1. Create tests (unit + integration)
1. Integrate with OTelStorageAdapter
1. Performance benchmarks
1. Update documentation

______________________________________________________________________

**Status:** Ready for implementation approval
**Estimated Time:** 4 hours
**Complexity:** Medium (ML model integration, caching, async patterns)
**Dependencies:** sentence-transformers, numpy
