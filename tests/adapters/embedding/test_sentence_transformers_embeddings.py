from __future__ import annotations

import pytest

from oneiric.adapters.embedding.embedding_interface import EmbeddingBatch, EmbeddingResult
from oneiric.adapters.embedding.sentence_transformers import (
    SentenceTransformersAdapter,
    SentenceTransformersSettings,
)


class FakeModel:
    def encode(self, texts, **_kwargs):  # type: ignore[no-untyped-def]
        return [[float(len(text))] for text in texts]

    def similarity(self, _query, docs):  # type: ignore[no-untyped-def]
        return [[float(vec[0]) for vec in docs]]


@pytest.mark.asyncio
async def test_sentence_transformers_embed_texts() -> None:
    adapter = SentenceTransformersAdapter(SentenceTransformersSettings())
    adapter._model = FakeModel()
    adapter._device = "cpu"

    batch = await adapter._embed_texts(
        ["hi", "hello"],
        model="model",
        normalize=True,
        batch_size=2,
    )

    assert isinstance(batch, EmbeddingBatch)
    assert batch.results[0].embedding == [2.0]
    assert batch.results[0].metadata["device"] == "cpu"


@pytest.mark.asyncio
async def test_sentence_transformers_similarity_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = SentenceTransformersAdapter(SentenceTransformersSettings())
    adapter._model = FakeModel()

    async def _embed_text(_query: str) -> list[float]:
        return [0.5]

    async def _embed_texts(docs: list[str]) -> EmbeddingBatch:
        return EmbeddingBatch(
            results=[
                EmbeddingResult(
                    text=doc,
                    embedding=[float(idx + 1)],
                    model="model",
                    dimensions=1,
                )
                for idx, doc in enumerate(docs)
            ],
            model="model",
            batch_size=len(docs),
        )

    monkeypatch.setattr(adapter, "embed_text", _embed_text)
    monkeypatch.setattr(adapter, "embed_texts", _embed_texts)

    results = await adapter.similarity_search(
        "query",
        ["a", "bb", "ccc"],
        top_k=2,
    )
    assert results[0][0] == "ccc"
