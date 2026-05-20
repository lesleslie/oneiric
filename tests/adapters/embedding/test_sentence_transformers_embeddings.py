from __future__ import annotations

import pytest

from oneiric.adapters.embedding.embedding_interface import (
    EmbeddingBatch,
    EmbeddingResult,
)
from oneiric.adapters.embedding.sentence_transformers import (
    SentenceTransformersAdapter,
    SentenceTransformersSettings,
)


class FakeModel:
    max_seq_length = 128
    tokenizer = object()

    def encode(self, texts, **_kwargs):  # type: ignore[no-untyped-def]
        return [[float(len(text))] for text in texts]

    def similarity(self, _query, docs):  # type: ignore[no-untyped-def]
        return [[float(vec[0]) for vec in docs]]

    def half(self) -> None:
        pass

    def get_sentence_embedding_dimension(self) -> int:
        return 1


def _make() -> SentenceTransformersAdapter:
    adapter = SentenceTransformersAdapter(SentenceTransformersSettings())
    adapter._model = FakeModel()
    adapter._device = "cpu"
    return adapter


# ---------------------------------------------------------------------------
# Tests — _embed_texts (original tests kept)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sentence_transformers_embed_texts() -> None:
    adapter = _make()
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
    adapter = _make()

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


# ---------------------------------------------------------------------------
# Tests — init
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_init_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    from oneiric.core.lifecycle import LifecycleError

    monkeypatch.setattr(
        "oneiric.adapters.embedding.sentence_transformers._sentence_transformers_available",
        False,
    )
    adapter = SentenceTransformersAdapter(SentenceTransformersSettings())
    with pytest.raises(LifecycleError, match="sentence-transformers-import-failed"):
        await adapter.init()


@pytest.mark.asyncio
async def test_init_success(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = SentenceTransformersAdapter(SentenceTransformersSettings())

    async def fake_load_model() -> None:
        adapter._model = FakeModel()
        adapter._device = "cpu"

    async def fake_embed_text(text: str, **_kwargs: object) -> list[float]:
        return [0.1]

    monkeypatch.setattr(adapter, "_load_model", fake_load_model)
    monkeypatch.setattr(adapter, "embed_text", fake_embed_text)
    monkeypatch.setattr(
        "oneiric.adapters.embedding.sentence_transformers._sentence_transformers_available",
        True,
    )
    await adapter.init()


@pytest.mark.asyncio
async def test_init_failure_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    from oneiric.core.lifecycle import LifecycleError

    monkeypatch.setattr(
        "oneiric.adapters.embedding.sentence_transformers._sentence_transformers_available",
        True,
    )

    async def bad_load() -> None:
        raise RuntimeError("disk full")

    adapter = SentenceTransformersAdapter(SentenceTransformersSettings())
    monkeypatch.setattr(adapter, "_load_model", bad_load)
    with pytest.raises(LifecycleError, match="sentence-transformers-init-failed"):
        await adapter.init()


# ---------------------------------------------------------------------------
# Tests — _load_model
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_model_success(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import types

    fake_torch = types.ModuleType("torch")
    fake_cuda = types.SimpleNamespace(is_available=lambda: False)
    fake_torch.cuda = fake_cuda  # type: ignore[attr-defined]

    loaded: list[str] = []

    class FakeST:
        def __init__(self, model_name: str, **_kwargs: object) -> None:
            loaded.append(model_name)

    fake_st_mod = types.ModuleType("sentence_transformers")
    fake_st_mod.SentenceTransformer = FakeST  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_st_mod)

    adapter = SentenceTransformersAdapter(SentenceTransformersSettings())
    await adapter._load_model()

    assert adapter._device == "cpu"
    assert len(loaded) == 1


@pytest.mark.asyncio
async def test_load_model_cuda_auto(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import types

    fake_torch = types.ModuleType("torch")
    fake_cuda = types.SimpleNamespace(is_available=lambda: True)
    fake_torch.cuda = fake_cuda  # type: ignore[attr-defined]

    class FakeST:
        def __init__(self, *_a: object, **_kw: object) -> None:
            pass

        def half(self) -> None:
            pass

    fake_st_mod = types.ModuleType("sentence_transformers")
    fake_st_mod.SentenceTransformer = FakeST  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_st_mod)

    settings = SentenceTransformersSettings(precision="float16")
    adapter = SentenceTransformersAdapter(settings)
    await adapter._load_model()
    assert adapter._device == "cuda"


@pytest.mark.asyncio
async def test_load_model_explicit_device(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import types

    fake_torch = types.ModuleType("torch")
    fake_cuda = types.SimpleNamespace(is_available=lambda: False)
    fake_torch.cuda = fake_cuda  # type: ignore[attr-defined]

    class FakeST:
        def __init__(self, *_a: object, **_kw: object) -> None:
            pass

    fake_st_mod = types.ModuleType("sentence_transformers")
    fake_st_mod.SentenceTransformer = FakeST  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_st_mod)

    settings = SentenceTransformersSettings(device="mps")
    adapter = SentenceTransformersAdapter(settings)
    await adapter._load_model()
    assert adapter._device == "mps"


@pytest.mark.asyncio
async def test_load_model_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import types
    from oneiric.core.lifecycle import LifecycleError

    fake_torch = types.ModuleType("torch")
    fake_cuda = types.SimpleNamespace(is_available=lambda: False)
    fake_torch.cuda = fake_cuda  # type: ignore[attr-defined]

    class BadST:
        def __init__(self, *_a: object, **_kw: object) -> None:
            raise RuntimeError("network error")

    fake_st_mod = types.ModuleType("sentence_transformers")
    fake_st_mod.SentenceTransformer = BadST  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_st_mod)

    adapter = SentenceTransformersAdapter(SentenceTransformersSettings())
    with pytest.raises(LifecycleError, match="model-load-failed"):
        await adapter._load_model()


# ---------------------------------------------------------------------------
# Tests — _ensure_client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_client_returns_model() -> None:
    adapter = _make()
    result = await adapter._ensure_client()
    assert result is adapter._model


@pytest.mark.asyncio
async def test_ensure_client_loads_when_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = SentenceTransformersAdapter(SentenceTransformersSettings())

    async def fake_load() -> None:
        adapter._model = FakeModel()

    monkeypatch.setattr(adapter, "_load_model", fake_load)
    result = await adapter._ensure_client()
    assert isinstance(result, FakeModel)


# ---------------------------------------------------------------------------
# Tests — health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_no_model() -> None:
    adapter = SentenceTransformersAdapter(SentenceTransformersSettings())
    assert await adapter.health() is False


@pytest.mark.asyncio
async def test_health_success(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _make()

    async def ok_embed(text: str, **_kw: object) -> list[float]:
        return [0.1]

    monkeypatch.setattr(adapter, "embed_text", ok_embed)
    assert await adapter.health() is True


@pytest.mark.asyncio
async def test_health_error(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _make()

    async def bad_embed(text: str, **_kw: object) -> list[float]:
        raise RuntimeError("OOM")

    monkeypatch.setattr(adapter, "embed_text", bad_embed)
    assert await adapter.health() is False


# ---------------------------------------------------------------------------
# Tests — cleanup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_clears_model() -> None:
    adapter = _make()
    await adapter.cleanup()
    assert adapter._model is None


@pytest.mark.asyncio
async def test_cleanup_no_model() -> None:
    adapter = SentenceTransformersAdapter(SentenceTransformersSettings())
    await adapter.cleanup()  # should not raise


@pytest.mark.asyncio
async def test_cleanup_del_model_raises_logs_warning() -> None:
    """cleanup() catches exception when del self._model raises (lines 196-197)."""

    class FailDelAdapter(SentenceTransformersAdapter):
        def __delattr__(self, name: str) -> None:
            if name == "_model":
                raise RuntimeError("cannot delete model")
            super().__delattr__(name)

    adapter = FailDelAdapter(SentenceTransformersSettings())
    adapter._model = FakeModel()
    adapter._device = "cpu"
    await adapter.cleanup()  # must not propagate
    assert adapter._model_cache == {}


@pytest.mark.asyncio
async def test_cleanup_with_cuda_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import types

    cache_cleared: list[bool] = []
    fake_torch = types.ModuleType("torch")
    fake_cuda = types.SimpleNamespace(
        is_available=lambda: True,
        empty_cache=lambda: cache_cleared.append(True),
    )
    fake_torch.cuda = fake_cuda  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    adapter = _make()
    await adapter.cleanup()
    assert adapter._model is None


# ---------------------------------------------------------------------------
# Tests — _embed_texts numpy tolist branch (line 229)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embed_texts_numpy_tolist_branch() -> None:
    """When encode() returns numpy array, embeddings.tolist() branch fires (line 229)."""
    import numpy as np

    class NumpyModel:
        max_seq_length = 128
        tokenizer = object()

        def encode(self, texts: list[str], **_kwargs: object) -> object:
            return np.array([[float(len(t))] for t in texts])

    adapter = SentenceTransformersAdapter(SentenceTransformersSettings())
    adapter._model = NumpyModel()  # type: ignore[assignment]
    adapter._device = "cpu"

    batch = await adapter._embed_texts(["hi", "hello"], model="m", normalize=False, batch_size=2)
    assert len(batch.results) == 2
    assert batch.results[0].embedding == [2.0]


# ---------------------------------------------------------------------------
# Tests — _embed_texts exception path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embed_texts_exception() -> None:
    from oneiric.core.lifecycle import LifecycleError

    class BoomModel:
        def encode(self, *_a: object, **_kw: object) -> None:
            raise RuntimeError("GPU error")

    adapter = SentenceTransformersAdapter(SentenceTransformersSettings())
    adapter._model = BoomModel()
    adapter._device = "cpu"

    with pytest.raises(LifecycleError, match="sentence-transformers-embedding-failed"):
        await adapter._embed_texts(["text"], model="model", normalize=False, batch_size=1)


# ---------------------------------------------------------------------------
# Tests — _embed_documents
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embed_documents_marks_chunks() -> None:
    adapter = _make()
    batches = await adapter._embed_documents(
        ["a short document"],
        chunk_size=100,
        chunk_overlap=0,
        model="model",
    )
    assert len(batches) == 1
    for result in batches[0].results:
        assert result.metadata.get("is_chunk") is True


@pytest.mark.asyncio
async def test_embed_documents_multiple() -> None:
    adapter = _make()
    batches = await adapter._embed_documents(
        ["doc one", "doc two"],
        chunk_size=100,
        chunk_overlap=0,
        model="model",
    )
    assert len(batches) == 2


# ---------------------------------------------------------------------------
# Tests — _compute_similarity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compute_similarity_all_methods() -> None:
    adapter = _make()
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
async def test_get_model_info_with_model() -> None:
    adapter = _make()
    info = await adapter._get_model_info("all-MiniLM-L6-v2")
    assert info["provider"] == "sentence_transformers"
    assert info["local"] is True
    assert "max_seq_length" in info


@pytest.mark.asyncio
async def test_get_model_info_no_model() -> None:
    adapter = SentenceTransformersAdapter(SentenceTransformersSettings())
    info = await adapter._get_model_info("some-model")
    assert info["name"] == "some-model"
    assert info["device"] is None


@pytest.mark.asyncio
async def test_list_models() -> None:
    adapter = _make()
    models = await adapter._list_models()
    assert len(models) == 5
    names = {m["name"] for m in models}
    assert "all-MiniLM-L6-v2" in names
    assert all(m["local"] is True for m in models)


# ---------------------------------------------------------------------------
# Tests — similarity_search tolist branch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_similarity_search_numpy_tolist_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When model.similarity() returns numpy array, .tolist()[0] branch fires (line 349)."""
    import numpy as np

    class NumpySimModel:
        def similarity(self, _q: object, docs: list[object]) -> object:
            return np.array([[float(i + 1) for i in range(len(docs))]])

    adapter = SentenceTransformersAdapter(SentenceTransformersSettings())
    adapter._model = NumpySimModel()  # type: ignore[assignment]
    adapter._device = "cpu"

    async def fake_embed_text(text: str, **_kw: object) -> list[float]:
        return [0.0]

    async def fake_embed_texts(docs: list[str], **_kw: object) -> EmbeddingBatch:
        return EmbeddingBatch(
            results=[
                EmbeddingResult(text=d, embedding=[0.0], model="m", dimensions=1)
                for d in docs
            ],
            model="m",
            batch_size=len(docs),
        )

    monkeypatch.setattr(adapter, "embed_text", fake_embed_text)
    monkeypatch.setattr(adapter, "embed_texts", fake_embed_texts)

    results = await adapter.similarity_search("q", ["a", "b", "c"], top_k=2)
    assert len(results) == 2


@pytest.mark.asyncio
async def test_similarity_search_list_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ListModel:
        def similarity(self, _q: object, docs: list[object]) -> list[list[float]]:
            return [[float(i + 1) for i in range(len(docs))]]

    adapter = SentenceTransformersAdapter(SentenceTransformersSettings())
    adapter._model = ListModel()
    adapter._device = "cpu"

    async def fake_embed_text(text: str, **_kw: object) -> list[float]:
        return [0.0]

    async def fake_embed_texts(docs: list[str], **_kw: object) -> EmbeddingBatch:
        return EmbeddingBatch(
            results=[
                EmbeddingResult(text=d, embedding=[0.0], model="m", dimensions=1)
                for d in docs
            ],
            model="m",
            batch_size=len(docs),
        )

    monkeypatch.setattr(adapter, "embed_text", fake_embed_text)
    monkeypatch.setattr(adapter, "embed_texts", fake_embed_texts)

    results = await adapter.similarity_search("q", ["a", "b", "c"], top_k=2)
    assert len(results) == 2
