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
