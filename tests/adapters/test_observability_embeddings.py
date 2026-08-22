"""Tests for EmbeddingService public behavior + trace-text helpers.

The hybrid chain itself is exercised in
``tests/adapters/observability/test_hybrid_embeddings.py``; this file
focuses on the legacy surface that ``otel_ingester`` and similar
callers depend on:

- ``_build_text_from_trace`` — still part of the public surface
- ``_generate_cache_key`` — still used by ``embed_trace``
- ``_generate_fallback_embedding`` — the deterministic mock fallback
- ``embed_trace`` — the high-level API callers use

Tests for the removed sentence-transformers internals (``_load_model``,
``_generate_embedding``, ``_embed_cached``) were deleted when the
sentence-transformers backend was replaced by the probe chain —
see ``docs/plans/2026-08-22-hybrid-embeddings-design.md``.
"""

from __future__ import annotations

import numpy as np
import pytest

from oneiric.adapters.observability.embeddings import EmbeddingService

# ---------------------------------------------------------------------------
# Tests — _build_text_from_trace (kept from old suite)
# ---------------------------------------------------------------------------


def test_build_text_from_trace_full() -> None:
    svc = EmbeddingService()
    text = svc._build_text_from_trace(
        {
            "service": "auth",
            "operation": "login",
            "status": "OK",
            "duration_ms": 42,
            "attributes": {"user": "abc", "method": "POST"},
        }
    )
    assert "auth" in text
    assert "login" in text
    assert "42ms" in text
    assert "user=abc" in text


def test_build_text_from_trace_defaults() -> None:
    svc = EmbeddingService()
    text = svc._build_text_from_trace({})
    assert "unknown" in text


# ---------------------------------------------------------------------------
# Tests — _generate_cache_key (kept from old suite)
# ---------------------------------------------------------------------------


def test_generate_cache_key_consistent() -> None:
    svc = EmbeddingService()
    trace = {"a": 1, "b": 2}
    k1 = svc._generate_cache_key(trace)
    k2 = svc._generate_cache_key(trace)
    assert k1 == k2
    assert isinstance(k1, int)


# ---------------------------------------------------------------------------
# Tests — _generate_fallback_embedding (mock fallback)
#
# Note: the new mock uses numpy.random.standard_normal (Gaussian) seeded
# from the trace_id's SHA-256, so values are centered around 0 (not in
# [0,1] as the old byte-shuffling version was). The test asserts the
# new contract: L2-normalized, deterministic, variable per id.
# ---------------------------------------------------------------------------


def test_generate_fallback_embedding_shape() -> None:
    svc = EmbeddingService()
    emb = svc._generate_fallback_embedding("trace-abc")
    assert isinstance(emb, np.ndarray)
    assert emb.shape == (384,)
    # L2-normalized
    assert abs(float(np.linalg.norm(emb)) - 1.0) < 1e-5


def test_generate_fallback_embedding_deterministic() -> None:
    svc = EmbeddingService()
    e1 = svc._generate_fallback_embedding("same-id")
    e2 = svc._generate_fallback_embedding("same-id")
    assert np.array_equal(e1, e2)


def test_generate_fallback_embedding_differs_by_id() -> None:
    svc = EmbeddingService()
    e1 = svc._generate_fallback_embedding("id-a")
    e2 = svc._generate_fallback_embedding("id-b")
    assert not np.array_equal(e1, e2)


# ---------------------------------------------------------------------------
# Tests — embed_trace public API
#
# These rely on the chain auto-falling back to mock (no real backend
# configured). They verify that ``embed_trace`` keeps the same
# outward contract (returns np.ndarray, handles missing trace_id).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embed_trace_returns_ndarray_when_no_backend_available() -> None:
    """Without ``await initialize()`` the chain is uninitialised.

    The test asserts that ``embed_trace`` still returns a valid ndarray
    (the mock fallback) so the legacy trace-ingestion call sites don't
    break when the chain hasn't been awaited yet.
    """
    svc = EmbeddingService()
    result = await svc.embed_trace({"trace_id": "fallback-trace"})
    assert isinstance(result, np.ndarray)
    assert result.shape == (384,)


@pytest.mark.asyncio
async def test_embed_trace_handles_missing_trace_id() -> None:
    svc = EmbeddingService()
    result = await svc.embed_trace({})  # no trace_id key
    assert result.shape == (384,)


# ---------------------------------------------------------------------------
# Tests — observability settings validator (kept from old suite)
# ---------------------------------------------------------------------------


def test_otel_storage_settings_rejects_non_postgresql_scheme() -> None:
    """validate_connection_string raises for non-postgresql:// scheme (line 51 of settings.py)."""
    import pytest

    from oneiric.adapters.observability.settings import OTelStorageSettings

    with pytest.raises(ValueError, match="postgresql://"):
        OTelStorageSettings(connection_string="mysql://user:pass@host/db")
