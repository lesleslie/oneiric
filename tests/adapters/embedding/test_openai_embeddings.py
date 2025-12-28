from __future__ import annotations

import pytest

from oneiric.adapters.embedding.openai import (
    OpenAIEmbeddingAdapter,
    OpenAIEmbeddingSettings,
)


class FakeEmbeddingData:
    def __init__(self, embedding: list[float], index: int) -> None:
        self.embedding = embedding
        self.index = index
        self.object = "embedding"


class FakeUsage:
    def __init__(self, total_tokens: int) -> None:
        self.total_tokens = total_tokens


class FakeResponse:
    def __init__(self, data: list[FakeEmbeddingData], model: str, tokens: int) -> None:
        self.data = data
        self.model = model
        self.usage = FakeUsage(tokens)


class FakeEmbeddings:
    def __init__(self, model: str) -> None:
        self._model = model
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs: object) -> FakeResponse:
        self.calls.append(kwargs)
        inputs = kwargs["input"]
        data = [FakeEmbeddingData([0.1 + idx], idx) for idx, _ in enumerate(inputs)]
        return FakeResponse(data, self._model, tokens=len(inputs))


class FakeClient:
    def __init__(self, model: str) -> None:
        self.embeddings = FakeEmbeddings(model)


@pytest.mark.asyncio
async def test_openai_prepare_and_extract(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = OpenAIEmbeddingSettings(dimensions=256)
    adapter = OpenAIEmbeddingAdapter(settings)
    params = adapter._prepare_request_params(["a"], "text-embedding-3-small")
    assert params["dimensions"] == 256

    response = FakeResponse([FakeEmbeddingData([0.1, 0.2], 0)], "model", tokens=3)
    normalize_calls: list[list[float]] = []

    def _normalize(vector: list[float], _method) -> list[float]:
        normalize_calls.append(vector)
        return [0.0, 0.0]

    monkeypatch.setattr(adapter, "_normalize_vector", _normalize)
    results = adapter._extract_embedding_results(response, ["hello"], normalize=True)
    assert results[0].embedding == [0.0, 0.0]
    assert normalize_calls == [[0.1, 0.2]]


@pytest.mark.asyncio
async def test_openai_embed_texts_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = OpenAIEmbeddingSettings(batch_size=2)
    adapter = OpenAIEmbeddingAdapter(settings)
    client = FakeClient("model")

    async def _ensure_client() -> FakeClient:
        return client

    calls: list[str] = []

    async def _apply_rate_limit() -> None:
        calls.append("tick")

    monkeypatch.setattr(adapter, "_ensure_client", _ensure_client)
    monkeypatch.setattr(adapter, "_apply_rate_limit", _apply_rate_limit)

    batch = await adapter._embed_texts(
        ["a", "b", "c"],
        model="model",
        normalize=False,
        batch_size=2,
    )

    assert len(batch.results) == 3
    assert len(calls) == 2
    assert client.embeddings.calls[0]["input"] == ["a", "b"]
