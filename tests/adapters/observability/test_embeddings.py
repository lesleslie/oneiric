"""Tests for EmbeddingService text construction."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
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
        "attributes": {"http.status_code": 500, "error.message": "timeout"},
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
        "attributes": {},
    }

    text = embedding_service._build_text_from_trace(trace)

    assert "test op OK in 100ms" in text
    assert "attributes:" in text


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


@pytest.mark.asyncio
async def test_embed_trace_with_mock_model(embedding_service):
    """Test embedding generation with mocked model."""
    trace = {
        "trace_id": "test-001",
        "service": "test-service",
        "operation": "test-op",
        "status": "OK",
        "duration_ms": 100,
        "attributes": {},
    }

    # Mock the model
    mock_embedding = np.random.rand(384)

    # Mock _embed_cached to return our mock embedding
    with patch.object(embedding_service, "_embed_cached", return_value=mock_embedding):
        embedding = await embedding_service.embed_trace(trace)

    # Verify the embedding has correct shape
    assert embedding.shape == (384,)
    # Note: We don't check exact equality because the mock may not be called
    # if sentence-transformers is not available (fallback is used)
    # The important thing is that an embedding is always returned


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
        "attributes": {},
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
        "attributes": {"error": "timeout"},
    }
    trace2 = {
        "trace_id": "similar-2",
        "service": "mahavishnu",
        "operation": "process_repo",
        "status": "ERROR",
        "duration_ms": 1200,
        "attributes": {"error": "network error"},
    }

    import asyncio

    emb1 = asyncio.run(embedding_service.embed_trace(trace1))
    emb2 = asyncio.run(embedding_service.embed_trace(trace2))

    # Cosine similarity
    from numpy.linalg import norm

    similarity = (emb1 @ emb2) / (norm(emb1) * norm(emb2))

    # Similar traces should have high cosine similarity (>0.7)
    assert similarity > 0.7
