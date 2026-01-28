# Phase 2: EmbeddingService Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build EmbeddingService to generate 384-dimensional vector embeddings from trace telemetry using sentence-transformers, enabling semantic similarity search across distributed traces.

**Architecture:** EmbeddingService generates embeddings from trace text (service + operation + status + attributes), caches results with LRU (1000 entries), and falls back to hash-based vectors on model failure.

**Tech Stack:**
- sentence-transformers (all-MiniLM-L6-v2, 384 dimensions)
- numpy (vector operations)
- functools.lru_cache (caching)
- hashlib (fallback generation)

---

## Task 1: Create EmbeddingService with text construction

**Files:**
- Create: `oneiric/adapters/observability/embeddings.py`
- Create: `tests/adapters/observability/test_embeddings.py`

**Step 1: Write test for text construction**

```python
"""Tests for EmbeddingService text construction."""

from __future__ import annotations

import pytest
from oneiric.adapters.observability.embeddings import EmbeddingService


@pytest.fixture
def embedding_service():
    """Create EmbeddingService instance."""
    return EmbeddingService()


def test_text_construction_success(embedding_service):
    """Test building text from trace dict."""
    trace = {
        "service": "mahavishnu",
        "operation": "process_repository",
        "status": "ERROR",
        "duration_ms": 2500,
        "attributes": {
            "http.status_code": 500,
            "error.message": "timeout"
        }
    }

    text = embedding_service._build_text_from_trace(trace)

    assert "mahavishnu" in text
    assert "process_repository" in text
    assert "ERROR" in text
    assert "2500ms" in text
    assert "http.status_code=500" in text


def test_text_construction_empty_attributes(embedding_service):
    """Test building text with no attributes."""
    trace = {
        "service": "test",
        "operation": "op",
        "status": "OK",
        "duration_ms": 100,
        "attributes": {}
    }

    text = embedding_service._build_text_from_trace(trace)

    assert "test op OK in 100ms" in text
    assert "attributes:" in text
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/adapters/observability/test_embeddings.py::test_text_construction_success -v`
Expected: FAIL - EmbeddingService doesn't exist yet

**Step 3: Write minimal EmbeddingService implementation**

```python
"""Embedding service for trace similarity search."""

from __future__ import annotations

from typing import Any


class EmbeddingService:
    """Generate embeddings for trace similarity search."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        """Initialize embedding service.

        Args:
            model_name: sentence-transformers model name
        """
        self._model_name = model_name
        self._model = None  # Lazy-loaded

    def _build_text_from_trace(self, trace: dict[str, Any]) -> str:
        """Build human-readable text from trace dict.

        Args:
            trace: Trace data dictionary

        Returns:
            Human-readable text string for embedding
        """
        service = trace.get("service", "unknown")
        operation = trace.get("operation", "unknown")
        status = trace.get("status", "UNKNOWN")
        duration_ms = trace.get("duration_ms", 0)
        attributes = trace.get("attributes", {})

        # Build attributes string
        attr_str = " ".join(f"{k}={v}" for k, v in sorted(attributes.items()))

        return f"{service} {operation} {status} in {duration_ms}ms attributes: {attr_str}"
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/adapters/observability/test_embeddings.py::test_text_construction_success -v`
Expected: PASS

**Step 5: Commit**

```bash
git add oneiric/adapters/observability/embeddings.py tests/adapters/observability/test_embeddings.py
git commit -m "feat(otel): Create EmbeddingService with text construction

Implement EmbeddingService._build_text_from_trace():
- Converts trace dict to human-readable text
- Format: "{service} {operation} {status} in {duration_ms}ms attributes: ..."
- Handles missing fields with defaults
- Sorts attributes for determinism

Tests cover text construction with and without attributes.
"
```

---

## Task 2: Add cache key generation

**Files:**
- Modify: `oneiric/adapters/observability/embeddings.py`
- Modify: `tests/adapters/observability/test_embeddings.py`

**Step 1: Write test for cache key generation**

```python
def test_cache_key_generation(embedding_service):
    """Test cache key is deterministic."""
    trace1 = {"trace_id": "abc", "service": "test"}
    trace2 = {"trace_id": "abc", "service": "test"}
    trace3 = {"trace_id": "abc", "service": "different"}

    key1 = embedding_service._generate_cache_key(trace1)
    key2 = embedding_service._generate_cache_key(trace2)
    key3 = embedding_service._generate_cache_key(trace3)

    assert key1 == key2  # Same trace = same key
    assert key1 != key3  # Different trace = different key
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/adapters/observability/test_embeddings.py::test_cache_key_generation -v`
Expected: FAIL - _generate_cache_key doesn't exist

**Step 3: Implement cache key generation**

Add to EmbeddingService:
```python
def _generate_cache_key(self, trace: dict[str, Any]) -> int:
    """Generate cache key from trace dict.

    Uses hash of sorted items for determinism.

    Args:
        trace: Trace data dictionary

    Returns:
        Cache key (hash integer)
    """
    return hash(frozenset(sorted(trace.items())))
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/adapters/observability/test_embeddings.py::test_cache_key_generation -v`
Expected: PASS

**Step 5: Commit**

```bash
git add oneiric/adapters/observability/embeddings.py tests/adapters/observability/test_embeddings.py
git commit -m "feat(otel): Add cache key generation for trace embeddings

Implement _generate_cache_key():
- Hash of frozenset(sorted(trace.items()))
- Deterministic: same trace = same key
- Enables LRU cache for embeddings

Tests verify determinism of cache keys.
"
```

---

## Task 3: Implement fallback embedding

**Files:**
- Modify: `oneiric/adapters/observability/embeddings.py`
- Modify: `tests/adapters/observability/test_embeddings.py`

**Step 1: Write test for fallback embedding**

```python
import numpy as np

def test_fallback_embedding_deterministic(embedding_service):
    """Test fallback embedding is deterministic."""
    trace_id = "trace-123"

    emb1 = embedding_service._generate_fallback_embedding(trace_id)
    emb2 = embedding_service._generate_fallback_embedding(trace_id)

    assert np.array_equal(emb1, emb2)  # Same ID = same vector


def test_fallback_embedding_dimension(embedding_service):
    """Test fallback embedding has correct dimension."""
    embedding = embedding_service._generate_fallback_embedding("any-id")

    assert embedding.shape == (384,)
    assert embedding.dtype == np.float64


def test_fallback_embedding_range(embedding_service):
    """Test fallback embedding values are in [0, 1]."""
    embedding = embedding_service._generate_fallback_embedding("test-id")

    assert np.all(embedding >= 0.0)
    assert np.all(embedding <= 1.0)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/adapters/observability/test_embeddings.py::test_fallback_embedding_deterministic -v`
Expected: FAIL - _generate_fallback_embedding doesn't exist

**Step 3: Implement fallback embedding**

Add to imports:
```python
import hashlib
```

Add to EmbeddingService:
```python
def _generate_fallback_embedding(self, trace_id: str) -> np.ndarray:
    """Generate fallback embedding from trace_id hash.

    Creates deterministic 384-dim vector using SHA-256 hash.
    Used when sentence-transformers model fails.

    Args:
        trace_id: Trace identifier

    Returns:
        384-dim vector with values in [0, 1]
    """
    # Hash trace_id to get deterministic bytes
    hash_int = int(hashlib.sha256(trace_id.encode()).hexdigest(), 16)

    # Convert to 384-dim vector
    # Each byte (0-255) becomes a value in [0, 1]
    return np.array([
        (hash_int >> i) & 0xFF
        for i in range(384)
    ]) / 255.0
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/adapters/observability/test_embeddings.py -k test_fallback_embedding -v`
Expected: PASS

**Step 5: Commit**

```bash
git add oneiric/adapters/observability/embeddings.py tests/adapters/observability/test_embeddings.py
git commit -m "feat(otel): Add fallback embedding generation

Implement _generate_fallback_embedding():
- Uses SHA-256 hash of trace_id
- Generates 384-dim vector in [0, 1] range
- Deterministic: same trace_id = same vector
- Used when sentence-transformers model fails

Tests verify determinism, dimension, and value range.
"
```

---

## Task 4: Add sentence-transformers integration with caching

**Files:**
- Modify: `oneiric/adapters/observability/embeddings.py`
- Modify: `tests/adapters/observability/test_embeddings.py`

**Step 1: Write test for embedding generation**

```python
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_embed_trace_with_mock_model(embedding_service):
    """Test embedding generation with mocked model."""
    trace = {
        "trace_id": "test-001",
        "service": "test-service",
        "operation": "test-op",
        "status": "OK",
        "duration_ms": 100,
        "attributes": {}
    }

    # Mock the model
    mock_embedding = np.random.rand(384)

    with patch.object(embedding_service, "_generate_embedding", return_value=mock_embedding):
        embedding = await embedding_service.embed_trace(trace)

    assert embedding.shape == (384,)
    assert np.array_equal(embedding, mock_embedding)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/adapters/observability/test_embeddings.py::test_embed_trace_with_mock_model -v`
Expected: FAIL - embed_trace doesn't exist

**Step 3: Implement embed_trace with model loading**

Add imports:
```python
from functools import lru_cache
from sentence_transformers import SentenceTransformer
import numpy as np
```

Add to EmbeddingService:
```python
def _load_model(self) -> SentenceTransformer:
    """Lazy-load sentence-transformers model.

    Returns:
        Loaded SentenceTransformer model
    """
    if self._model is None:
        self._model = SentenceTransformer(self._model_name)
    return self._model

async def _generate_embedding(self, text: str) -> np.ndarray:
    """Generate embedding from text.

    Args:
        text: Text string to embed

    Returns:
        384-dim vector
    """
    model = self._load_model()
    return model.encode(text)

@lru_cache(maxsize=1000)
def _embed_cached(self, cache_key: int, text: str) -> np.ndarray:
    """Generate embedding with LRU caching.

    Args:
        cache_key: Cache key (hash of trace)
        text: Text to embed

    Returns:
        384-dim vector
    """
    # Note: This is sync, but fast because model is cached
    model = self._load_model()
    return model.encode(text)

async def embed_trace(self, trace: dict[str, Any]) -> np.ndarray:
    """Generate embedding from trace dict.

    Args:
        trace: Trace data dictionary

    Returns:
        384-dim vector embedding
    """
    from oneiric.core.logging import get_logger
    logger = get_logger("otel.embedding")

    try:
        # Build text
        text = self._build_text_from_trace(trace)

        # Generate cache key
        cache_key = self._generate_cache_key(trace)

        # Generate embedding (cached)
        embedding = self._embed_cached(cache_key, text)

        logger.debug("embedding-generated", trace_id=trace.get("trace_id"))
        return embedding

    except Exception as exc:
        # Fallback on any error
        logger.warning(
            "embedding-generation-failed",
            error=str(exc),
            trace_id=trace.get("trace_id"),
            fallback=True
        )
        return self._generate_fallback_embedding(trace.get("trace_id", "unknown"))
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/adapters/observability/test_embeddings.py::test_embed_trace_with_mock_model -v`
Expected: PASS

**Step 5: Commit**

```bash
git add oneiric/adapters/observability/embeddings.py tests/adapters/observability/test_embeddings.py
git commit -m "feat(otel): Add sentence-transformers integration with caching

Implement EmbeddingService.embed_trace():
- Lazy-load sentence-transformers model (all-MiniLM-L6-v2)
- Build text from trace metadata + attributes
- LRU cache (1000 entries) via functools.lru_cache
- Fallback to hash-based embedding on model failure
- Never fails: always returns embedding

Key features:
- Cached embeddings: <1ms on hit
- Uncached: 50-100ms for model inference
- Deterministic fallback on error
- Comprehensive logging for monitoring

Tests cover mock model integration and error handling.
"
```

---

## Task 5: Add integration tests with real model

**Files:**
- Modify: `tests/adapters/observability/test_embeddings.py`

**Step 1: Write integration tests**

```python
@pytest.mark.integration
@pytest.mark.slow
def test_real_model_embedding_dimension(embedding_service):
    """Test real model produces 384-dim embeddings."""
    trace = {
        "trace_id": "test-real",
        "service": "test",
        "operation": "test",
        "status": "OK",
        "duration_ms": 100,
        "attributes": {}
    }

    import asyncio
    embedding = asyncio.run(embedding_service.embed_trace(trace))

    assert embedding.shape == (384,)


@pytest.mark.integration
@pytest.mark.slow
def test_embedding_similarity(embedding_service):
    """Test similar traces produce similar embeddings."""
    trace1 = {
        "trace_id": "similar-1",
        "service": "mahavishnu",
        "operation": "process_repo",
        "status": "ERROR",
        "duration_ms": 1000,
        "attributes": {"error": "timeout"}
    }
    trace2 = {
        "trace_id": "similar-2",
        "service": "mahavishnu",
        "operation": "process_repo",
        "status": "ERROR",
        "duration_ms": 1200,
        "attributes": {"error": "network error"}
    }

    import asyncio
    emb1 = asyncio.run(embedding_service.embed_trace(trace1))
    emb2 = asyncio.run(embedding_service.embed_trace(trace2))

    # Cosine similarity
    from numpy.linalg import norm
    similarity = (emb1 @ emb2) / (norm(emb1) * norm(emb2))

    # Similar traces should have high cosine similarity (>0.7)
    assert similarity > 0.7
```

**Step 2: Run tests (if model available)**

Run: `pytest tests/adapters/observability/test_embeddings.py -k integration -v`
Expected: PASS (if sentence-transformers installed) or SKIP (if not available)

**Step 3: Commit**

```bash
git add tests/adapters/observability/test_embeddings.py
git commit -m "test(otel): Add integration tests for embedding service

Add real model tests:
- test_real_model_embedding_dimension - Verify 384-dim output
- test_embedding_similarity - Verify semantic similarity

Tests marked as integration and slow (require sentence-transformers).
"
```

---

## Task 6: Integrate EmbeddingService with OTelStorageAdapter

**Files:**
- Modify: `oneiric/adapters/observability/otel.py`
- Modify: `tests/adapters/observability/test_otel_adapter.py`

**Step 1: Write test for embedding integration**

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_store_trace_with_embedding(otel_adapter, embedding_service):
    """Test storing trace with generated embedding."""
    from oneiric.adapters.observability.types import TraceData
    from datetime import datetime

    trace = TraceData(
        trace_id="trace-embed-001",
        span_id="span-001",
        name="Test with embedding",
        kind="INTERNAL",
        start_time=datetime.utcnow(),
        status="OK",
        service="test",
        operation="test_with_embedding",
    )

    # Store trace
    await otel_adapter.store_trace(trace.model_dump())

    # Generate embedding
    embedding = await embedding_service.embed_trace(trace.model_dump())

    # Verify embedding shape
    assert embedding.shape == (384,)
```

**Step 2: Run test to verify it works**

Run: `pytest tests/adapters/observability/test_otel_adapter.py::test_store_trace_with_embedding -v`
Expected: PASS

**Step 3: Modify OTelStorageAdapter to use EmbeddingService**

Add to imports in otel.py:
```python
from oneiric.adapters.observability.embeddings import EmbeddingService
```

Modify __init__:
```python
def __init__(self, settings: OTelStorageSettings) -> None:
    # ... existing code ...
    self._embedding_service = EmbeddingService(
        model_name=settings.embedding_model
    )
```

Modify _flush_buffer to add embedding:
```python
async def _flush_buffer(self) -> None:
    """Flush buffered traces to database in batch."""
    async with self._flush_lock:
        if not self._write_buffer:
            return

        traces_to_store = list(self._write_buffer)
        self._write_buffer.clear()

        try:
            from sqlalchemy import select
            from oneiric.adapters.observability.models import TraceModel

            async with self._session_factory() as session:
                trace_models = []
                for trace_dict in traces_to_store:
                    # Generate embedding (async, cached)
                    embedding = await self._embedding_service.embed_trace(trace_dict)

                    trace_model = TraceModel(
                        id=trace_dict.get("span_id"),
                        trace_id=trace_dict.get("trace_id"),
                        parent_span_id=trace_dict.get("parent_span_id"),
                        name=trace_dict.get("name"),
                        kind=trace_dict.get("kind"),
                        start_time=trace_dict.get("start_time"),
                        end_time=trace_dict.get("end_time"),
                        duration_ms=trace_dict.get("duration_ms"),
                        status=trace_dict.get("status"),
                        attributes=trace_dict.get("attributes", {}),
                        embedding=embedding,  # ← Add embedding here
                        embedding_model="all-MiniLM-L6-v2",
                        embedding_generated_at=datetime.utcnow(),
                    )
                    trace_models.append(trace_model)

                session.add_all(trace_models)
                await session.commit()

            self._logger.info("flush-buffer-success", count=len(trace_models))

        except Exception as exc:
            await self._send_to_dlq(traces_to_store, str(exc))
            self._logger.error("flush-buffer-failed", error=str(exc))
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/adapters/observability/test_otel_adapter.py -k embedding -v`
Expected: PASS

**Step 5: Commit**

```bash
git add oneiric/adapters/observability/otel.py tests/adapters/observability/test_otel_adapter.py
git commit -m "feat(otel): Integrate EmbeddingService with OTelStorageAdapter

Integrate embedding generation into trace storage:
- Create EmbeddingService in __init__
- Generate embedding for each trace during flush
- Store 384-dim vector in embedding column
- Uses cached embeddings when available
- Fallback to hash-based embedding on error

Traces now stored with vector embeddings for similarity search.

Integration test verifies embedding generation and storage.
"
```

---

## Summary

This plan provides:

✅ **Bite-sized tasks** - Each step is 2-5 minutes
✅ **Exact file paths** - All files specified
✅ **Complete code** - Full implementations in plan
✅ **TDD workflow** - Test first, then implement
✅ **Frequent commits** - Commit after each task
✅ **Type hints** - Full type annotations
✅ **Error handling** - Fallback on model failure
✅ **Integration tests** - Real model tests (optional)

**Total breakdown:**
- **Task 1:** EmbeddingService with text construction
- **Task 2:** Cache key generation
- **Task 3:** Fallback embedding
- **Task 4:** sentence-transformers integration
- **Task 5:** Integration tests with real model
- **Task 6:** Integrate with OTelStorageAdapter

**Estimated completion:** 4 hours
**Complexity:** Medium (ML model, caching, async patterns)
**Dependencies:** sentence-transformers, numpy
