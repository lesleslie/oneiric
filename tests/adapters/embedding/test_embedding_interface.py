"""Tests for EmbeddingBase, EmbeddingUtils, and helpers in embedding_interface.py.

Uses a minimal concrete subclass to exercise all delegation paths without
requiring any external embedding backend.
"""

from __future__ import annotations

from typing import Any

import pytest

from oneiric.adapters.embedding.embedding_interface import (
    EmbeddingBase,
    EmbeddingBaseSettings,
    EmbeddingBatch,
    EmbeddingResult,
    EmbeddingUtils,
)

# ---------------------------------------------------------------------------
# Minimal concrete adapter
# ---------------------------------------------------------------------------


class _DummySettings(EmbeddingBaseSettings):
    pass


class _DummyAdapter(EmbeddingBase):
    async def init(self) -> None:
        pass

    async def health(self) -> bool:
        return True

    async def cleanup(self) -> None:
        pass

    async def _ensure_client(self) -> Any:
        return None

    async def _embed_texts(
        self,
        texts: list[str],
        model: str,
        batch_size: int,
        **kwargs: Any,
    ) -> EmbeddingBatch:
        results = [
            EmbeddingResult(text=t, embedding=[0.5, 0.5], model=model, dimensions=2)
            for t in texts
        ]
        return EmbeddingBatch(results=results, model=model, batch_size=len(results))

    async def _embed_documents(
        self,
        documents: list[str],
        chunk_size: int,
        chunk_overlap: int,
        model: str,
        **kwargs: Any,
    ) -> list[EmbeddingBatch]:
        batches = []
        for doc in documents:
            chunks = self._chunk_text(doc, chunk_size, chunk_overlap)
            batch = await self._embed_texts(
                chunks, model=model, batch_size=32
            )
            batches.append(batch)
        return batches

    async def _compute_similarity(
        self,
        embedding1: list[float],
        embedding2: list[float],
        method: str,
    ) -> float:
        return 0.5

    async def _get_model_info(self, model: str) -> dict[str, Any]:
        return {"name": model, "provider": "dummy"}

    async def _list_models(self) -> list[dict[str, Any]]:
        return [{"name": "dummy"}]


def _make() -> _DummyAdapter:
    return _DummyAdapter(_DummySettings())


# ---------------------------------------------------------------------------
# Tests — properties
# ---------------------------------------------------------------------------


def test_settings_property() -> None:
    adapter = _make()
    assert adapter.settings is adapter._settings


def test_client_property() -> None:
    adapter = _make()
    assert adapter.client is None


# ---------------------------------------------------------------------------
# Tests — _normalize_vector
# ---------------------------------------------------------------------------


def test_normalize_vector_l2() -> None:
    adapter = _make()
    result = adapter._normalize_vector([3.0, 4.0])
    assert abs(result[0] - 0.6) < 1e-6
    assert abs(result[1] - 0.8) < 1e-6


def test_normalize_vector_l2_zero_norm() -> None:
    adapter = _make()
    vec = [0.0, 0.0]
    result = adapter._normalize_vector(vec)
    assert result is vec


def test_normalize_vector_returns_new_list() -> None:
    """L2 normalization always allocates a fresh list — caller mutation
    of the result must not poison the input vector."""
    adapter = _make()
    source = [3.0, 4.0]
    result = adapter._normalize_vector(source)
    assert source == [3.0, 4.0]  # input unchanged
    assert result == [0.6, 0.8]


# ---------------------------------------------------------------------------
# Tests — _chunk_text
# ---------------------------------------------------------------------------


def test_chunk_text_short_text() -> None:
    adapter = _make()
    assert adapter._chunk_text("hi", chunk_size=100) == ["hi"]


def test_chunk_text_exact_size() -> None:
    adapter = _make()
    assert adapter._chunk_text("hello", chunk_size=5) == ["hello"]


def test_chunk_text_no_overlap() -> None:
    adapter = _make()
    result = adapter._chunk_text("abcdefghij", chunk_size=5, overlap=0)
    assert result == ["abcde", "fghij"]


def test_chunk_text_with_overlap() -> None:
    adapter = _make()
    result = adapter._chunk_text("abcdefghij", chunk_size=6, overlap=2)
    assert result[0] == "abcdef"
    assert result[1] == "efghij"


# ---------------------------------------------------------------------------
# Tests — _batch_texts
# ---------------------------------------------------------------------------


def test_batch_texts_even() -> None:
    adapter = _make()
    assert adapter._batch_texts(["a", "b", "c", "d"], batch_size=2) == [
        ["a", "b"],
        ["c", "d"],
    ]


def test_batch_texts_uneven() -> None:
    adapter = _make()
    assert adapter._batch_texts(["a", "b", "c"], batch_size=2) == [["a", "b"], ["c"]]


def test_batch_texts_larger_than_list() -> None:
    adapter = _make()
    assert adapter._batch_texts(["x"], batch_size=10) == [["x"]]


# ---------------------------------------------------------------------------
# Tests — public delegation methods
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embed_text() -> None:
    """The dummy's [0.5, 0.5] is NOT unit-length (norm = sqrt(0.5)).
    The base layer must re-normalize to length 1.0."""
    adapter = _make()
    result = await adapter.embed_text("hello")
    norm = (result[0] ** 2 + result[1] ** 2) ** 0.5
    assert abs(norm - 1.0) < 1e-6
    # Component-wise: 0.5 / sqrt(0.5) = sqrt(0.5)
    expected = 0.5 / (0.5) ** 0.5
    assert abs(result[0] - expected) < 1e-6
    assert abs(result[1] - expected) < 1e-6


@pytest.mark.asyncio
async def test_embed_texts_uses_settings_defaults() -> None:
    adapter = _make()
    batch = await adapter.embed_texts(["a", "b"])
    assert len(batch.results) == 2
    assert batch.model == adapter._settings.model


@pytest.mark.asyncio
async def test_embed_texts_explicit_params() -> None:
    adapter = _make()
    batch = await adapter.embed_texts(["x"], model="custom-model", batch_size=8)
    assert batch.model == "custom-model"


@pytest.mark.asyncio
async def test_embed_documents() -> None:
    adapter = _make()
    batches = await adapter.embed_documents(["a short document"])
    assert len(batches) == 1


@pytest.mark.asyncio
async def test_embed_documents_with_params() -> None:
    adapter = _make()
    batches = await adapter.embed_documents(
        ["a b c d e f g h i j"], chunk_size=5, chunk_overlap=1
    )
    assert len(batches) == 1
    assert len(batches[0].results) >= 2  # split into multiple chunks


@pytest.mark.asyncio
async def test_embed_documents_chunk_overlap_zero_is_honored() -> None:
    """Regression: chunk_overlap=0 must NOT fall through to the settings default.

    Pre-fix the call used `chunk_overlap or self._settings.chunk_overlap`,
    which treats 0 as falsy and silently substituted the default (50) — that
    then made `_chunk_text` loop indefinitely (start went negative, producing
    empty chunks forever). This test pins the explicit `is None` fallback
    that preserves a caller-supplied 0.

    Chunks are character-based. With chunk_size=5 on a 19-char string and
    chunk_overlap=0, the expected output is 4 disjoint chunks of lengths
    [5, 5, 5, 4]. The pre-fix bug would have produced an unbounded number
    of empty chunks (infinite loop) — pytest's 30s per-test timeout would
    catch it as a hang.
    """
    adapter = _make()
    batches = await adapter.embed_documents(
        ["a b c d e f g h i j"], chunk_size=5, chunk_overlap=0
    )
    assert len(batches) == 1
    results = batches[0].results
    # Correct behavior: 4 disjoint chunks of 5,5,5,4 chars.
    assert len(results) == 4
    assert [len(r.text) for r in results] == [5, 5, 5, 4]
    # No chunk should be empty (the pre-fix bug's infinite-loop signature).
    assert all(r.text for r in results)


@pytest.mark.asyncio
async def test_compute_similarity() -> None:
    adapter = _make()
    score = await adapter.compute_similarity([1.0, 0.0], [0.0, 1.0])
    assert score == 0.5


@pytest.mark.asyncio
async def test_get_model_info_default() -> None:
    adapter = _make()
    info = await adapter.get_model_info()
    assert info["provider"] == "dummy"


@pytest.mark.asyncio
async def test_get_model_info_explicit() -> None:
    adapter = _make()
    info = await adapter.get_model_info("my-model")
    assert info["name"] == "my-model"


@pytest.mark.asyncio
async def test_list_models() -> None:
    adapter = _make()
    models = await adapter.list_models()
    assert len(models) == 1


# ---------------------------------------------------------------------------
# Tests — EmbeddingUtils
# ---------------------------------------------------------------------------


def test_cosine_similarity_orthogonal() -> None:
    assert abs(EmbeddingUtils.cosine_similarity([1.0, 0.0], [0.0, 1.0])) < 1e-6


def test_cosine_similarity_parallel() -> None:
    assert abs(EmbeddingUtils.cosine_similarity([1.0, 0.0], [1.0, 0.0]) - 1.0) < 1e-6


def test_cosine_similarity_zero_vector() -> None:
    assert EmbeddingUtils.cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_euclidean_distance() -> None:
    d = EmbeddingUtils.euclidean_distance([0.0, 0.0], [3.0, 4.0])
    assert abs(d - 5.0) < 1e-6


def test_dot_product() -> None:
    assert EmbeddingUtils.dot_product([1.0, 2.0], [3.0, 4.0]) == 11.0


def test_manhattan_distance() -> None:
    assert EmbeddingUtils.manhattan_distance([1.0, 2.0], [4.0, 6.0]) == 7.0


# ---------------------------------------------------------------------------
# Tests — Phase 2: EmbeddingBaseSettings env_prefix=EMBEDDING_ isolation
# ---------------------------------------------------------------------------


def test_embedding_base_settings_defaults() -> None:
    s = EmbeddingBaseSettings()
    assert s.model == "text-embedding-3-small"
    assert s.api_key is None


def test_embedding_base_settings_reads_embedding_env_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EMBEDDING_API_KEY=x flows into EmbeddingBaseSettings.api_key."""
    monkeypatch.setenv("EMBEDDING_API_KEY", "sk-env-emb")
    s = EmbeddingBaseSettings()
    assert s.api_key is not None
    assert s.api_key.get_secret_value() == "sk-env-emb"
