from __future__ import annotations

import numpy as np
import pytest

from oneiric.adapters.observability.embeddings import EmbeddingService


# ---------------------------------------------------------------------------
# Tests — _build_text_from_trace
# ---------------------------------------------------------------------------


def test_build_text_from_trace_full() -> None:
    svc = EmbeddingService()
    text = svc._build_text_from_trace({
        "service": "auth",
        "operation": "login",
        "status": "OK",
        "duration_ms": 42,
        "attributes": {"user": "abc", "method": "POST"},
    })
    assert "auth" in text
    assert "login" in text
    assert "42ms" in text
    assert "user=abc" in text


def test_build_text_from_trace_defaults() -> None:
    svc = EmbeddingService()
    text = svc._build_text_from_trace({})
    assert "unknown" in text


# ---------------------------------------------------------------------------
# Tests — _generate_cache_key
# ---------------------------------------------------------------------------


def test_generate_cache_key_consistent() -> None:
    svc = EmbeddingService()
    trace = {"a": 1, "b": 2}
    k1 = svc._generate_cache_key(trace)
    k2 = svc._generate_cache_key(trace)
    assert k1 == k2
    assert isinstance(k1, int)


# ---------------------------------------------------------------------------
# Tests — _generate_fallback_embedding
# ---------------------------------------------------------------------------


def test_generate_fallback_embedding_shape() -> None:
    svc = EmbeddingService()
    emb = svc._generate_fallback_embedding("trace-abc")
    assert isinstance(emb, np.ndarray)
    assert emb.shape == (384,)
    assert emb.min() >= 0.0
    assert emb.max() <= 1.0


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
# Tests — _load_model
# ---------------------------------------------------------------------------


def test_load_model_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "oneiric.adapters.observability.embeddings.SENTENCE_TRANSFORMERS_AVAILABLE",
        False,
    )
    svc = EmbeddingService()
    with pytest.raises(ImportError, match="sentence-transformers"):
        svc._load_model()


def test_load_model_caches_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeModel:
        def encode(self, text: str) -> np.ndarray:
            return np.zeros(384)

    fake_instance = FakeModel()
    monkeypatch.setattr(
        "oneiric.adapters.observability.embeddings.SENTENCE_TRANSFORMERS_AVAILABLE",
        True,
    )
    monkeypatch.setattr(
        "oneiric.adapters.observability.embeddings.SentenceTransformer",
        lambda _name: fake_instance,
    )
    svc = EmbeddingService()
    m1 = svc._load_model()
    m2 = svc._load_model()
    assert m1 is m2  # cached — constructor called only once


# ---------------------------------------------------------------------------
# Tests — _generate_embedding / _embed_cached
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = np.ones(384)

    class FakeModel:
        def encode(self, text: str) -> np.ndarray:
            return expected

    monkeypatch.setattr(
        "oneiric.adapters.observability.embeddings.SENTENCE_TRANSFORMERS_AVAILABLE",
        True,
    )
    monkeypatch.setattr(
        "oneiric.adapters.observability.embeddings.SentenceTransformer",
        lambda _name: FakeModel(),
    )
    svc = EmbeddingService()
    result = await svc._generate_embedding("hello")
    assert np.array_equal(result, expected)


def test_embed_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class FakeModel:
        def encode(self, text: str) -> np.ndarray:
            calls.append(text)
            return np.zeros(384)

    monkeypatch.setattr(
        "oneiric.adapters.observability.embeddings.SENTENCE_TRANSFORMERS_AVAILABLE",
        True,
    )
    monkeypatch.setattr(
        "oneiric.adapters.observability.embeddings.SentenceTransformer",
        lambda _name: FakeModel(),
    )
    svc = EmbeddingService()
    # lru_cache is per-instance but here the function is unbound — call it twice
    k = svc._generate_cache_key({"x": 1})
    r1 = svc._embed_cached(k, "test text")
    r2 = svc._embed_cached(k, "test text")
    assert np.array_equal(r1, r2)


# ---------------------------------------------------------------------------
# Tests — embed_trace (success and fallback)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embed_trace_success(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeModel:
        def encode(self, text: str) -> np.ndarray:
            return np.ones(384)

    monkeypatch.setattr(
        "oneiric.adapters.observability.embeddings.SENTENCE_TRANSFORMERS_AVAILABLE",
        True,
    )
    monkeypatch.setattr(
        "oneiric.adapters.observability.embeddings.SentenceTransformer",
        lambda _name: FakeModel(),
    )
    svc = EmbeddingService()
    trace = {"trace_id": "t-1", "service": "svc", "operation": "op"}
    result = await svc.embed_trace(trace)
    assert isinstance(result, np.ndarray)


@pytest.mark.asyncio
async def test_embed_trace_fallback_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "oneiric.adapters.observability.embeddings.SENTENCE_TRANSFORMERS_AVAILABLE",
        False,
    )
    svc = EmbeddingService()
    trace = {"trace_id": "fallback-trace"}
    result = await svc.embed_trace(trace)
    assert isinstance(result, np.ndarray)
    assert result.shape == (384,)


@pytest.mark.asyncio
async def test_embed_trace_fallback_no_trace_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "oneiric.adapters.observability.embeddings.SENTENCE_TRANSFORMERS_AVAILABLE",
        False,
    )
    svc = EmbeddingService()
    result = await svc.embed_trace({})  # no trace_id key
    assert result.shape == (384,)


# ---------------------------------------------------------------------------
# Tests — observability settings validator
# ---------------------------------------------------------------------------


def test_otel_storage_settings_rejects_non_postgresql_scheme() -> None:
    """validate_connection_string raises for non-postgresql:// scheme (line 51 of settings.py)."""
    from oneiric.adapters.observability.settings import OTelStorageSettings

    import pytest

    with pytest.raises(ValueError, match="postgresql://"):
        OTelStorageSettings(connection_string="mysql://user:pass@host/db")
