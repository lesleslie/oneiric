"""Public-behavior tests for EmbeddingService trace helpers.

The hybrid chain itself is exercised in
``tests/adapters/observability/test_hybrid_embeddings.py``. This file
focuses on the trace-text construction helpers (``_build_text_from_trace``,
``_generate_cache_key``) and the deterministic mock fallback contract.

The old sentence-transformers integration tests are gone — the model
loader was replaced by the probe chain. Real-backend tests live in
``test_hybrid_embeddings.py`` against ``httpx.MockTransport``.
"""

from __future__ import annotations

import numpy as np
import pytest

from oneiric.adapters.observability.embeddings import EmbeddingService


@pytest.fixture
def embedding_service() -> EmbeddingService:
    """Create EmbeddingService instance."""
    return EmbeddingService()


# ---------------------------------------------------------------------------
# _build_text_from_trace
# ---------------------------------------------------------------------------


def test_text_construction_success(embedding_service: EmbeddingService) -> None:
    """Test building text from trace dict."""
    trace = {
        "service": "mahavishnu",
        "operation": "process_repository",
        "status": "ERROR",
        "duration_ms": 2500,
        "attributes": {"http.status_code": 500, "error.message": "timeout"},
    }

    text = embedding_service._build_text_from_trace(trace)

    assert "mahavishnu" in text
    assert "process_repository" in text
    assert "ERROR" in text
    assert "2500ms" in text
    assert "http.status_code=500" in text


def test_text_construction_empty_attributes(embedding_service: EmbeddingService) -> None:
    """Test building text with no attributes."""
    trace = {
        "service": "test",
        "operation": "op",
        "status": "OK",
        "duration_ms": 100,
        "attributes": {},
    }

    text = embedding_service._build_text_from_trace(trace)

    assert "test op OK in 100ms" in text
    assert "attributes:" in text


# ---------------------------------------------------------------------------
# _generate_cache_key
# ---------------------------------------------------------------------------


def test_cache_key_generation(embedding_service: EmbeddingService) -> None:
    """Test cache key is deterministic."""
    trace1 = {"trace_id": "abc", "service": "test"}
    trace2 = {"trace_id": "abc", "service": "test"}
    trace3 = {"trace_id": "abc", "service": "different"}

    key1 = embedding_service._generate_cache_key(trace1)
    key2 = embedding_service._generate_cache_key(trace2)
    key3 = embedding_service._generate_cache_key(trace3)

    assert key1 == key2  # Same trace = same key
    assert key1 != key3  # Different trace = different key


# ---------------------------------------------------------------------------
# _generate_fallback_embedding (mock contract)
#
# New contract: L2-normalized Gaussian seeded from SHA-256(trace_id).
# Values are no longer constrained to [0, 1] (Gaussian distribution).
# ---------------------------------------------------------------------------


def test_fallback_embedding_deterministic(embedding_service: EmbeddingService) -> None:
    """Test fallback embedding is deterministic."""
    trace_id = "trace-123"

    emb1 = embedding_service._generate_fallback_embedding(trace_id)
    emb2 = embedding_service._generate_fallback_embedding(trace_id)

    assert np.array_equal(emb1, emb2)


def test_fallback_embedding_dimension(embedding_service: EmbeddingService) -> None:
    """Test fallback embedding has correct dimension."""
    embedding = embedding_service._generate_fallback_embedding("any-id")

    assert embedding.shape == (384,)
    assert embedding.dtype == np.float32


def test_fallback_embedding_is_l2_normalized(
    embedding_service: EmbeddingService,
) -> None:
    """The mock fallback vector is L2-normalized to unit norm."""
    embedding = embedding_service._generate_fallback_embedding("test-id")

    norm = float(np.linalg.norm(embedding))
    assert abs(norm - 1.0) < 1e-5
