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
    VectorNormalization,
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
        normalize: bool,
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
                chunks, model=model, normalize=False, batch_size=32
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


def test_normalize_vector_none_method() -> None:
    adapter = _make()
    vec = [1.0, 2.0, 3.0]
    result = adapter._normalize_vector(vec, VectorNormalization.NONE)
    assert result is vec


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


def test_normalize_vector_l1() -> None:
    adapter = _make()
    result = adapter._normalize_vector([1.0, 3.0], VectorNormalization.L1)
    assert abs(result[0] - 0.25) < 1e-6
    assert abs(result[1] - 0.75) < 1e-6


def test_normalize_vector_l1_zero_norm() -> None:
    adapter = _make()
    vec = [0.0, 0.0]
    result = adapter._normalize_vector(vec, VectorNormalization.L1)
    assert result is vec


def test_normalize_vector_unknown_method_returns_vector() -> None:
    """Fallback return on line 241 — reached when method is not NONE/L2/L1."""
    adapter = _make()
    vec = [1.0, 2.0]
    result = adapter._normalize_vector(vec, "custom")  # type: ignore[arg-type]
    assert result is vec


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
    adapter = _make()
    result = await adapter.embed_text("hello")
    assert result == [0.5, 0.5]


@pytest.mark.asyncio
async def test_embed_texts_uses_settings_defaults() -> None:
    adapter = _make()
    batch = await adapter.embed_texts(["a", "b"])
    assert len(batch.results) == 2
    assert batch.model == adapter._settings.model


@pytest.mark.asyncio
async def test_embed_texts_explicit_params() -> None:
    adapter = _make()
    batch = await adapter.embed_texts(
        ["x"], model="custom-model", normalize=True, batch_size=8
    )
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
