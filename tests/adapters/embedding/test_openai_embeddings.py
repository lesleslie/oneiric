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


# ---------------------------------------------------------------------------
# Tests — init / _ensure_client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_init_success(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = OpenAIEmbeddingAdapter(OpenAIEmbeddingSettings())

    async def fake_ensure_client() -> FakeClient:
        return FakeClient("model")

    async def fake_embed_text(text: str, **kwargs: object) -> list[float]:
        return [0.1, 0.2]

    monkeypatch.setattr(adapter, "_ensure_client", fake_ensure_client)
    monkeypatch.setattr(adapter, "embed_text", fake_embed_text)
    await adapter.init()


@pytest.mark.asyncio
async def test_openai_init_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from oneiric.core.lifecycle import LifecycleError

    adapter = OpenAIEmbeddingAdapter(OpenAIEmbeddingSettings())

    async def bad_ensure_client() -> None:
        raise RuntimeError("connection refused")

    monkeypatch.setattr(adapter, "_ensure_client", bad_ensure_client)
    with pytest.raises(LifecycleError, match="openai-embedding-init-failed"):
        await adapter.init()


@pytest.mark.asyncio
async def test_openai_ensure_client_already_set() -> None:
    adapter = OpenAIEmbeddingAdapter(OpenAIEmbeddingSettings())
    fake_client = FakeClient("model")
    adapter._client = fake_client
    result = await adapter._ensure_client()
    assert result is fake_client


@pytest.mark.asyncio
async def test_openai_ensure_client_import_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    from oneiric.core.lifecycle import LifecycleError

    adapter = OpenAIEmbeddingAdapter(OpenAIEmbeddingSettings())
    monkeypatch.setitem(sys.modules, "openai", None)
    with pytest.raises(LifecycleError, match="openai-import-failed"):
        await adapter._ensure_client()


@pytest.mark.asyncio
async def test_openai_ensure_client_creates_new(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_ensure_client success path logs debug message (line 107)."""
    import sys
    import types

    fake_openai = types.ModuleType("openai")
    created: list[object] = []

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs: object) -> None:
            created.append(self)

    fake_openai.AsyncOpenAI = FakeAsyncOpenAI  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    adapter = OpenAIEmbeddingAdapter(OpenAIEmbeddingSettings())
    result = await adapter._ensure_client()
    assert len(created) == 1
    assert result is created[0]


@pytest.mark.asyncio
async def test_openai_ensure_client_creation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    import types

    from oneiric.core.lifecycle import LifecycleError

    fake_openai = types.ModuleType("openai")

    def bad_constructor(**kwargs: object) -> None:
        raise RuntimeError("ssl error")

    fake_openai.AsyncOpenAI = bad_constructor  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    adapter = OpenAIEmbeddingAdapter(OpenAIEmbeddingSettings())
    with pytest.raises(LifecycleError, match="openai-client-creation-failed"):
        await adapter._ensure_client()


# ---------------------------------------------------------------------------
# Tests — health / cleanup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_health_false_no_client() -> None:
    adapter = OpenAIEmbeddingAdapter(OpenAIEmbeddingSettings())
    assert await adapter.health() is False


@pytest.mark.asyncio
async def test_openai_health_true(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = OpenAIEmbeddingAdapter(OpenAIEmbeddingSettings())
    adapter._client = FakeClient("model")

    async def fake_embed_text(text: str, **kwargs: object) -> list[float]:
        return [0.1]

    monkeypatch.setattr(adapter, "embed_text", fake_embed_text)
    assert await adapter.health() is True


@pytest.mark.asyncio
async def test_openai_health_false_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = OpenAIEmbeddingAdapter(OpenAIEmbeddingSettings())
    adapter._client = FakeClient("model")

    async def bad_embed_text(text: str, **kwargs: object) -> list[float]:
        raise RuntimeError("API error")

    monkeypatch.setattr(adapter, "embed_text", bad_embed_text)
    assert await adapter.health() is False


@pytest.mark.asyncio
async def test_openai_cleanup_with_client() -> None:
    closed: list[bool] = []

    class ClosingClient:
        async def close(self) -> None:
            closed.append(True)

    adapter = OpenAIEmbeddingAdapter(OpenAIEmbeddingSettings())
    adapter._client = ClosingClient()  # type: ignore[assignment]
    await adapter.cleanup()
    assert closed == [True]
    assert adapter._client is None
    assert adapter._model_cache == {}


@pytest.mark.asyncio
async def test_openai_cleanup_no_client() -> None:
    adapter = OpenAIEmbeddingAdapter(OpenAIEmbeddingSettings())
    await adapter.cleanup()  # should not raise


@pytest.mark.asyncio
async def test_openai_cleanup_close_raises_logs_warning() -> None:
    """cleanup() catches and logs when client.close() raises (lines 128-129)."""

    class RaisingClient:
        async def close(self) -> None:
            raise RuntimeError("close failed")

    adapter = OpenAIEmbeddingAdapter(OpenAIEmbeddingSettings())
    adapter._client = RaisingClient()  # type: ignore[assignment]
    await adapter.cleanup()  # must not propagate
    assert adapter._client is None


# ---------------------------------------------------------------------------
# Tests — _embed_texts exception path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_embed_texts_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    from oneiric.core.lifecycle import LifecycleError

    adapter = OpenAIEmbeddingAdapter(OpenAIEmbeddingSettings())

    class FailingEmbeddings:
        async def create(self, **kwargs: object) -> None:
            raise RuntimeError("API down")

    class FailingClient:
        embeddings = FailingEmbeddings()

    async def failing_ensure() -> FailingClient:
        return FailingClient()

    async def noop_rate_limit() -> None:
        pass

    monkeypatch.setattr(adapter, "_ensure_client", failing_ensure)
    monkeypatch.setattr(adapter, "_apply_rate_limit", noop_rate_limit)

    with pytest.raises(LifecycleError, match="openai-embedding-failed"):
        await adapter._embed_texts(["text"], model="model", normalize=False, batch_size=10)


# ---------------------------------------------------------------------------
# Tests — _embed_documents
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_embed_documents(monkeypatch: pytest.MonkeyPatch) -> None:
    from oneiric.adapters.embedding.embedding_interface import EmbeddingBatch, EmbeddingResult

    settings = OpenAIEmbeddingSettings(chunk_size=10, chunk_overlap=2)
    adapter = OpenAIEmbeddingAdapter(settings)

    async def fake_embed_texts(
        texts: list[str], model: str, normalize: bool, batch_size: int, **kwargs: object
    ) -> EmbeddingBatch:
        results = [
            EmbeddingResult(text=t, embedding=[0.1], model=model, dimensions=1)
            for t in texts
        ]
        return EmbeddingBatch(results=results, model=model, batch_size=len(results))

    monkeypatch.setattr(adapter, "_embed_texts", fake_embed_texts)

    batches = await adapter._embed_documents(
        ["hello world test document"],
        chunk_size=10,
        chunk_overlap=2,
        model="model",
    )
    assert len(batches) >= 1
    for batch in batches:
        for result in batch.results:
            assert result.metadata.get("is_chunk") is True


# ---------------------------------------------------------------------------
# Tests — _compute_similarity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_compute_similarity_all_methods() -> None:
    adapter = OpenAIEmbeddingAdapter(OpenAIEmbeddingSettings())
    v1, v2 = [1.0, 0.0], [0.0, 1.0]

    cosine = await adapter._compute_similarity(v1, v2, "cosine")
    assert abs(cosine) < 0.01

    euclidean = await adapter._compute_similarity(v1, v2, "euclidean")
    assert abs(euclidean - 1.4142) < 0.01

    dot = await adapter._compute_similarity(v1, v2, "dot")
    assert dot == 0.0

    manhattan = await adapter._compute_similarity(v1, v2, "manhattan")
    assert manhattan == 2.0

    with pytest.raises(ValueError, match="Unsupported"):
        await adapter._compute_similarity(v1, v2, "unknown")


# ---------------------------------------------------------------------------
# Tests — _get_model_info / _list_models
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_get_model_info_small() -> None:
    adapter = OpenAIEmbeddingAdapter(OpenAIEmbeddingSettings())
    info = await adapter._get_model_info("text-embedding-3-small")
    assert info["max_dimensions"] == 1536


@pytest.mark.asyncio
async def test_openai_get_model_info_large() -> None:
    adapter = OpenAIEmbeddingAdapter(OpenAIEmbeddingSettings())
    info = await adapter._get_model_info("text-embedding-3-large")
    assert info["max_dimensions"] == 3072


@pytest.mark.asyncio
async def test_openai_get_model_info_ada() -> None:
    adapter = OpenAIEmbeddingAdapter(OpenAIEmbeddingSettings())
    info = await adapter._get_model_info("text-embedding-ada-002")
    assert info["max_dimensions"] == 1536


@pytest.mark.asyncio
async def test_openai_get_model_info_unknown() -> None:
    adapter = OpenAIEmbeddingAdapter(OpenAIEmbeddingSettings())
    info = await adapter._get_model_info("some-other-model")
    assert info["name"] == "some-other-model"
    assert "max_dimensions" not in info


@pytest.mark.asyncio
async def test_openai_list_models() -> None:
    adapter = OpenAIEmbeddingAdapter(OpenAIEmbeddingSettings())
    models = await adapter._list_models()
    assert len(models) == 3
    names = {m["name"] for m in models}
    assert "text-embedding-3-small" in names


# ---------------------------------------------------------------------------
# Tests — _apply_rate_limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_apply_rate_limit_sleeps(monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("oneiric.adapters.embedding.openai.asyncio.sleep", fake_sleep)

    adapter = OpenAIEmbeddingAdapter(OpenAIEmbeddingSettings(requests_per_minute=60))
    adapter._last_request_time = time.time()  # "just now"
    await adapter._apply_rate_limit()
    assert len(slept) == 1


@pytest.mark.asyncio
async def test_openai_apply_rate_limit_no_sleep() -> None:
    adapter = OpenAIEmbeddingAdapter(OpenAIEmbeddingSettings(requests_per_minute=60))
    adapter._last_request_time = 0.0  # long ago — no sleep needed
    await adapter._apply_rate_limit()  # should not raise
