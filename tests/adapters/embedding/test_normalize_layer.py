"""Enforcement tests for the L2-normalization layer in ``EmbeddingBase``.

The base class guarantees every vector that comes out of
``embed_text`` / ``embed_texts`` / ``embed_documents`` has L2 norm == 1
(unit-length). Subclasses do not need to (and should not) apply their
own normalization — the base re-normalizes whatever the subclass
hands back. These tests exercise that contract from the public API,
independent of any provider implementation.
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from oneiric.adapters.embedding.embedding_interface import (
    EmbeddingBase,
    EmbeddingBaseSettings,
    EmbeddingBatch,
    EmbeddingResult,
)


# ---------------------------------------------------------------------------
# Test adapters — three subclasses that hand back deliberately un-normalized
# vectors so we can prove the base layer always re-normalizes.
# ---------------------------------------------------------------------------


class _Settings(EmbeddingBaseSettings):
    pass


class _UnnormalizedAdapter(EmbeddingBase):
    """Subclass that returns vectors of arbitrary magnitude — the base
    MUST re-normalize every output regardless."""

    def __init__(self, settings: EmbeddingBaseSettings, raw_vectors: list[list[float]]) -> None:
        super().__init__(settings)
        self._raw_vectors = raw_vectors

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
            EmbeddingResult(
                text=t,
                embedding=list(self._raw_vectors[i]),
                model=model,
                dimensions=len(self._raw_vectors[i]),
            )
            for i, t in enumerate(texts)
        ]
        return EmbeddingBatch(
            results=results, model=model, batch_size=len(results)
        )

    async def _embed_documents(
        self,
        documents: list[str],
        chunk_size: int,
        chunk_overlap: int,
        model: str,
        **kwargs: Any,
    ) -> list[EmbeddingBatch]:
        batches: list[EmbeddingBatch] = []
        idx = 0
        for document in documents:
            chunks = self._chunk_text(document, chunk_size, chunk_overlap)
            chunk_results = [
                EmbeddingResult(
                    text=chunk,
                    embedding=list(self._raw_vectors[idx + i]),
                    model=model,
                    dimensions=len(self._raw_vectors[idx + i]),
                )
                for i, chunk in enumerate(chunks)
            ]
            batches.append(
                EmbeddingBatch(
                    results=chunk_results,
                    model=model,
                    batch_size=len(chunk_results),
                )
            )
            idx += len(chunks)
        return batches

    async def _compute_similarity(
        self,
        embedding1: list[float],
        embedding2: list[float],
        method: str,
    ) -> float:
        return 0.0

    async def _get_model_info(self, model: str) -> dict[str, Any]:
        return {"name": model, "provider": "unnormalized"}

    async def _list_models(self) -> list[dict[str, Any]]:
        return [{"name": "unnormalized"}]


def _make_adapter(
    raw_vectors: list[list[float]],
) -> _UnnormalizedAdapter:
    return _UnnormalizedAdapter(_Settings(), raw_vectors)


def _norm(vector: list[float]) -> float:
    return math.sqrt(sum(component * component for component in vector))


# ---------------------------------------------------------------------------
# embed_text — always unit-length
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embed_text_returns_unit_length_vector() -> None:
    """Even when the subclass returns [3, 4] (norm = 5), the public
    embed_text must hand back [0.6, 0.8] (norm = 1)."""
    adapter = _make_adapter([[3.0, 4.0]])
    result = await adapter.embed_text("hello")
    assert abs(_norm(result) - 1.0) < 1e-6


@pytest.mark.asyncio
async def test_embed_text_unit_length_for_arbitrary_inputs() -> None:
    """Sweep a handful of magnitudes — every output must be unit-length."""
    cases = [
        [1.0, 0.0],
        [1.0, 1.0, 1.0, 1.0],
        [0.1, 0.2, 0.3, 0.4, 0.5],
        [10.0, -5.0, 3.0],
        [0.001, 0.001],
    ]
    for raw in cases:
        adapter = _make_adapter([raw])
        result = await adapter.embed_text("x")
        assert abs(_norm(result) - 1.0) < 1e-6, (
            f"Non-unit-length for input {raw}: got {result}, norm {_norm(result)}"
        )


# ---------------------------------------------------------------------------
# embed_texts — every result is unit-length
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embed_texts_returns_unit_length_vectors() -> None:
    """Mixed magnitudes across the batch — every result must be unit-length."""
    raw = [[3.0, 4.0], [1.0, 0.0], [5.0, -5.0, 5.0], [0.5, 0.5]]
    adapter = _make_adapter(raw)
    batch = await adapter.embed_texts([f"text-{i}" for i in range(len(raw))])
    assert len(batch.results) == len(raw)
    for result in batch.results:
        assert abs(_norm(result.embedding) - 1.0) < 1e-6, (
            f"Non-unit-length for text {result.text!r}: {result.embedding}"
        )


@pytest.mark.asyncio
async def test_embed_texts_preserves_text_and_dimensions() -> None:
    """L2 normalization must NOT change the text/dimensions metadata."""
    raw = [[3.0, 4.0]]
    adapter = _make_adapter(raw)
    batch = await adapter.embed_texts(["hello"])
    assert batch.results[0].text == "hello"
    assert batch.results[0].dimensions == 2
    assert len(batch.results[0].embedding) == 2


@pytest.mark.asyncio
async def test_embed_texts_unit_length_components_sum_to_one_squared() -> None:
    """For a vector normalized from [a, b, ...], the squared sum of the
    output components must equal 1 exactly (within float epsilon)."""
    raw = [[2.0, 3.0, 6.0]]  # norm = sqrt(4 + 9 + 36) = sqrt(49) = 7
    adapter = _make_adapter(raw)
    batch = await adapter.embed_texts(["x"])
    emb = batch.results[0].embedding
    squared_sum = sum(c * c for c in emb)
    assert abs(squared_sum - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# embed_documents — every result is unit-length
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embed_documents_returns_unit_length_vectors() -> None:
    """Chunked document embedding must also normalize every result."""
    # Two documents: first gets 2 chunks, second gets 1 chunk.
    raw = [[3.0, 4.0], [1.0, 1.0], [5.0, -5.0]]
    adapter = _make_adapter(raw)
    batches = await adapter.embed_documents(
        ["ab cd", "ef"],
        chunk_size=3,
        chunk_overlap=1,
    )
    assert len(batches) == 2
    assert len(batches[0].results) == 2
    assert len(batches[1].results) == 1
    for batch in batches:
        for result in batch.results:
            assert abs(_norm(result.embedding) - 1.0) < 1e-6, (
                f"Non-unit-length for text {result.text!r}: {result.embedding}"
            )


# ---------------------------------------------------------------------------
# Base layer is the source of truth — subclass opt-out still produces
# unit-length output.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_base_normalizes_even_when_subclass_returns_unit_vector() -> None:
    """Idempotency check: a subclass that already returns unit-length
    vectors must still come back unit-length (the base re-normalizes)."""
    raw = [[0.6, 0.8]]  # norm = 1
    adapter = _make_adapter(raw)
    result = await adapter.embed_text("x")
    assert abs(_norm(result) - 1.0) < 1e-6
    assert abs(result[0] - 0.6) < 1e-6
    assert abs(result[1] - 0.8) < 1e-6


@pytest.mark.asyncio
async def test_base_normalizes_arbitrary_magnitude() -> None:
    """High-magnitude raw vectors get re-normalized without precision loss."""
    raw = [[100.0, 200.0, 300.0]]
    adapter = _make_adapter(raw)
    result = await adapter.embed_text("x")
    assert abs(_norm(result) - 1.0) < 1e-6
    # 100/sqrt(140000) = 100/374.1657... ≈ 0.26726...
    expected = 100.0 / math.sqrt(10000 + 40000 + 90000)
    assert abs(result[0] - expected) < 1e-6


# ---------------------------------------------------------------------------
# Direction preservation — the normalized output must point in the same
# direction as the input (cosine similarity == 1.0).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_normalization_preserves_direction() -> None:
    """L2 normalization is a scaling operation — direction is preserved."""
    raw = [[2.0, -3.0, 4.0]]
    adapter = _make_adapter(raw)
    normalized = await adapter.embed_text("x")
    raw_norm = _norm(raw[0])
    cosine = (
        sum(raw[0][i] * normalized[i] for i in range(len(raw[0]))) / raw_norm
    )
    assert abs(cosine - 1.0) < 1e-6
