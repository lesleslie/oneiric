from __future__ import annotations

import numpy as np
import pytest

from oneiric.adapters.embedding.embedding_interface import PoolingStrategy
from oneiric.adapters.embedding.onnx import ONNXEmbeddingAdapter, ONNXEmbeddingSettings


def _make_adapter() -> ONNXEmbeddingAdapter:
    settings = ONNXEmbeddingSettings(model_path="model.onnx")
    return ONNXEmbeddingAdapter(settings)


def test_prepare_onnx_inputs() -> None:
    adapter = _make_adapter()
    adapter._input_names = ["input_ids", "attention_mask", "token_type_ids"]
    tokenized = {
        "input_ids": np.array([[1, 2]]),
        "attention_mask": np.array([[1, 1]]),
    }

    onnx_inputs = adapter._prepare_onnx_inputs(tokenized)
    assert "input_ids" in onnx_inputs
    assert "attention_mask" in onnx_inputs
    assert "token_type_ids" not in onnx_inputs


@pytest.mark.asyncio
async def test_onnx_pooling_and_normalization() -> None:
    adapter = _make_adapter()
    token_embeddings = np.array([[[1.0, 0.0], [0.0, 1.0]]])
    attention_mask = np.array([[1, 1]])

    mean = await adapter._apply_pooling(
        token_embeddings, attention_mask, PoolingStrategy.MEAN
    )
    assert mean.tolist() == [[0.5, 0.5]]

    max_pool = await adapter._apply_pooling(
        token_embeddings, attention_mask, PoolingStrategy.MAX
    )
    assert max_pool.tolist() == [[1.0, 1.0]]

    cls = await adapter._apply_pooling(
        token_embeddings, attention_mask, PoolingStrategy.CLS
    )
    assert cls.tolist() == [[1.0, 0.0]]

    weighted = await adapter._apply_pooling(
        token_embeddings, attention_mask, PoolingStrategy.WEIGHTED_MEAN
    )
    assert weighted.tolist() == [[0.5, 0.5]]

    normalized = adapter._normalize_embeddings(np.array([[3.0, 4.0]]))
    assert normalized.tolist() == [[0.6, 0.8]]


def test_onnx_count_tokens_safe() -> None:
    adapter = _make_adapter()

    class Tokenizer:
        def encode(self, text: str) -> list[int]:
            return list(range(len(text)))

    assert adapter._count_tokens_safe("abc", Tokenizer()) == 3
    assert adapter._count_tokens_safe("abc", object()) is None


def test_onnx_count_tokens_safe_encode_raises_returns_none() -> None:
    """_count_tokens_safe returns None when encode() raises (line 311)."""
    adapter = _make_adapter()

    class FailTokenizer:
        def encode(self, text: str) -> list[int]:
            raise ValueError("tokenization failed")

    result = adapter._count_tokens_safe("abc", FailTokenizer())
    assert result is None


# ---------------------------------------------------------------------------
# Mock session / tokenizer helpers
# ---------------------------------------------------------------------------


class MockSession:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def get_providers(self) -> list[str]:
        return ["CPUExecutionProvider"]

    def get_inputs(self) -> list:
        return []

    def get_outputs(self) -> list:
        return []

    def run(self, output_names: list, inputs: dict) -> list:
        if inputs:
            first = next(iter(inputs.values()))
            batch_size = first.shape[0]
            seq_len = first.shape[1] if len(first.shape) > 1 else 4
        else:
            batch_size, seq_len = 1, 4
        out = np.zeros((batch_size, seq_len, 4), dtype=np.float32)
        return [out]

    def end_profiling(self) -> str:
        return "profile.json"


class MockTokenizer:
    def __call__(
        self,
        texts: list[str],
        padding: bool = True,
        truncation: bool = True,
        max_length: int = 512,
        return_tensors: str = "np",
    ) -> dict:
        n = len(texts)
        return {
            "input_ids": np.ones((n, 4), dtype=np.int64),
            "attention_mask": np.ones((n, 4), dtype=np.int64),
        }

    def encode(self, text: str) -> list[int]:
        return list(range(len(text)))


# ---------------------------------------------------------------------------
# Tests — init
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_onnx_init_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    from oneiric.core.lifecycle import LifecycleError

    monkeypatch.setattr("oneiric.adapters.embedding.onnx._onnx_available", False)
    adapter = _make_adapter()
    with pytest.raises(LifecycleError, match="onnx-runtime-import-failed"):
        await adapter.init()


@pytest.mark.asyncio
async def test_onnx_init_load_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from oneiric.core.lifecycle import LifecycleError

    adapter = _make_adapter()

    async def bad_load() -> None:
        raise RuntimeError("model not found")

    monkeypatch.setattr(adapter, "_load_model", bad_load)
    with pytest.raises(LifecycleError, match="onnx-init-failed"):
        await adapter.init()


@pytest.mark.asyncio
async def test_onnx_init_success(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _make_adapter()

    async def fake_load() -> None:
        adapter._session = MockSession()
        adapter._tokenizer = MockTokenizer()

    async def fake_embed_text(text: str, **kwargs) -> list[float]:
        return [0.1, 0.2]

    monkeypatch.setattr(adapter, "_load_model", fake_load)
    monkeypatch.setattr(adapter, "embed_text", fake_embed_text)
    await adapter.init()


# ---------------------------------------------------------------------------
# Tests — _ensure_client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_onnx_ensure_client_calls_load_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _make_adapter()
    loaded: list[bool] = []

    async def fake_load() -> None:
        adapter._session = MockSession()
        adapter._tokenizer = MockTokenizer()
        loaded.append(True)

    monkeypatch.setattr(adapter, "_load_model", fake_load)
    session, tokenizer = await adapter._ensure_client()
    assert loaded == [True]
    assert session is adapter._session


# ---------------------------------------------------------------------------
# Tests — health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_onnx_health_false_no_session() -> None:
    adapter = _make_adapter()
    assert await adapter.health() is False


@pytest.mark.asyncio
async def test_onnx_health_true(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _make_adapter()
    adapter._session = MockSession()
    adapter._tokenizer = MockTokenizer()

    async def fake_embed_text(text: str, **kwargs) -> list[float]:
        return [0.5]

    monkeypatch.setattr(adapter, "embed_text", fake_embed_text)
    assert await adapter.health() is True


@pytest.mark.asyncio
async def test_onnx_health_false_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _make_adapter()
    adapter._session = MockSession()
    adapter._tokenizer = MockTokenizer()

    async def bad_embed_text(text: str, **kwargs) -> list[float]:
        raise RuntimeError("inference error")

    monkeypatch.setattr(adapter, "embed_text", bad_embed_text)
    assert await adapter.health() is False


# ---------------------------------------------------------------------------
# Tests — cleanup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_onnx_cleanup_session_del_raises() -> None:
    """cleanup() catches exception when del self._session raises (lines 253-254)."""
    from oneiric.adapters.embedding.onnx import ONNXEmbeddingAdapter, ONNXEmbeddingSettings

    class FailDelSessionAdapter(ONNXEmbeddingAdapter):
        def __delattr__(self, name: str) -> None:
            if name == "_session":
                raise RuntimeError("cannot delete session")
            super().__delattr__(name)

    adapter = FailDelSessionAdapter(ONNXEmbeddingSettings(model_path="m.onnx"))
    adapter._session = MockSession()
    adapter._tokenizer = MockTokenizer()
    await adapter.cleanup()  # must not propagate
    assert adapter._model_cache == {}


@pytest.mark.asyncio
async def test_onnx_cleanup_tokenizer_del_raises() -> None:
    """cleanup() catches exception when del self._tokenizer raises (lines 260-261)."""
    from oneiric.adapters.embedding.onnx import ONNXEmbeddingAdapter, ONNXEmbeddingSettings

    class FailDelTokenizerAdapter(ONNXEmbeddingAdapter):
        def __delattr__(self, name: str) -> None:
            if name == "_tokenizer":
                raise RuntimeError("cannot delete tokenizer")
            super().__delattr__(name)

    adapter = FailDelTokenizerAdapter(ONNXEmbeddingSettings(model_path="m.onnx"))
    adapter._session = None  # session already cleared
    adapter._tokenizer = MockTokenizer()
    await adapter.cleanup()  # must not propagate
    assert adapter._model_cache == {}


@pytest.mark.asyncio
async def test_onnx_cleanup() -> None:
    adapter = _make_adapter()
    adapter._session = MockSession()
    adapter._tokenizer = MockTokenizer()
    adapter._input_names = ["input_ids"]
    adapter._output_names = ["output"]

    await adapter.cleanup()

    assert adapter._session is None
    assert adapter._tokenizer is None
    assert adapter._input_names == []
    assert adapter._output_names == []


# ---------------------------------------------------------------------------
# Tests — _embed_texts / _embed_documents
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_onnx_embed_texts_with_mocks(monkeypatch: pytest.MonkeyPatch) -> None:
    from oneiric.adapters.embedding.embedding_interface import EmbeddingBatch, EmbeddingResult

    adapter = _make_adapter()
    session = MockSession()
    tokenizer = MockTokenizer()

    async def fake_ensure_client():
        return session, tokenizer

    results_fixture = [
        EmbeddingResult(text="a", embedding=[0.1, 0.2], model="m", dimensions=2),
        EmbeddingResult(text="b", embedding=[0.3, 0.4], model="m", dimensions=2),
    ]

    async def fake_process_all(texts, batch_size, sess, tok, model, normalize):
        return results_fixture

    monkeypatch.setattr(adapter, "_ensure_client", fake_ensure_client)
    monkeypatch.setattr(adapter, "_process_all_batches", fake_process_all)

    batch = await adapter._embed_texts(
        ["a", "b"], model="m", normalize=True, batch_size=32
    )
    assert len(batch.results) == 2


@pytest.mark.asyncio
async def test_onnx_embed_documents(monkeypatch: pytest.MonkeyPatch) -> None:
    from oneiric.adapters.embedding.embedding_interface import EmbeddingBatch, EmbeddingResult

    adapter = _make_adapter()

    async def fake_embed_texts(texts, model, normalize, batch_size, **kwargs):
        results = [
            EmbeddingResult(text=t, embedding=[0.1], model=model, dimensions=1)
            for t in texts
        ]
        return EmbeddingBatch(results=results, model=model, batch_size=len(results))

    monkeypatch.setattr(adapter, "_embed_texts", fake_embed_texts)

    batches = await adapter._embed_documents(
        ["hello world"], chunk_size=5, chunk_overlap=0, model="m"
    )
    assert len(batches) == 1
    for result in batches[0].results:
        assert result.metadata.get("is_chunk") is True


# ---------------------------------------------------------------------------
# Tests — _process_all_batches error path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_onnx_process_all_batches_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from oneiric.core.lifecycle import LifecycleError

    adapter = _make_adapter()
    session = MockSession()
    tokenizer = MockTokenizer()

    async def bad_single_batch(batch_texts, sess, tok, model, normalize):
        raise RuntimeError("inference crash")

    monkeypatch.setattr(adapter, "_process_single_batch", bad_single_batch)

    with pytest.raises(LifecycleError, match="onnx-batch-failed"):
        await adapter._process_all_batches(
            ["text"], batch_size=1, session=session, tokenizer=tokenizer,
            model="m", normalize=False
        )


# ---------------------------------------------------------------------------
# Tests — _apply_pooling unsupported strategy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_onnx_apply_pooling_unsupported() -> None:
    from oneiric.adapters.embedding.embedding_interface import PoolingStrategy

    adapter = _make_adapter()
    token_embeddings = np.array([[[1.0, 2.0]]])
    attention_mask = np.array([[1]])

    class FakeStrategy:
        value = "unsupported"

    with pytest.raises(ValueError, match="Unsupported pooling strategy"):
        await adapter._apply_pooling(token_embeddings, attention_mask, FakeStrategy())


# ---------------------------------------------------------------------------
# Tests — _compute_similarity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_onnx_compute_similarity_all_methods() -> None:
    adapter = _make_adapter()
    v1, v2 = [1.0, 0.0], [0.0, 1.0]

    cosine = await adapter._compute_similarity(v1, v2, "cosine")
    assert abs(cosine) < 0.01

    euclidean = await adapter._compute_similarity(v1, v2, "euclidean")
    assert abs(euclidean - 1.4142) < 0.01

    dot = await adapter._compute_similarity(v1, v2, "dot")
    assert dot == 0.0

    manhattan = await adapter._compute_similarity(v1, v2, "manhattan")
    assert manhattan == 2.0

    with pytest.raises(ValueError, match="Unsupported similarity method"):
        await adapter._compute_similarity(v1, v2, "unknown")


# ---------------------------------------------------------------------------
# Tests — _get_model_info / _list_models / get_performance_metrics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_onnx_get_model_info_no_session() -> None:
    adapter = _make_adapter()
    info = await adapter._get_model_info("onnx-all-MiniLM-L6-v2")
    assert info["provider"] == "onnx"
    assert "providers" not in info


@pytest.mark.asyncio
async def test_onnx_get_model_info_with_session() -> None:
    adapter = _make_adapter()
    adapter._session = MockSession()
    info = await adapter._get_model_info("onnx-all-MiniLM-L6-v2")
    assert "providers" in info


@pytest.mark.asyncio
async def test_onnx_list_models() -> None:
    adapter = _make_adapter()
    models = await adapter._list_models()
    assert len(models) == 2
    assert all(m["provider"] == "onnx" for m in models)


@pytest.mark.asyncio
async def test_onnx_get_performance_metrics_no_session() -> None:
    adapter = _make_adapter()
    metrics = await adapter.get_performance_metrics()
    assert metrics == {}


@pytest.mark.asyncio
async def test_onnx_get_performance_metrics_with_session() -> None:
    adapter = _make_adapter()
    adapter._session = MockSession()
    metrics = await adapter.get_performance_metrics()
    assert "providers" in metrics
    assert metrics["profiling_enabled"] is False


@pytest.mark.asyncio
async def test_onnx_get_performance_metrics_session_raises() -> None:
    """get_performance_metrics() returns error dict when session call raises (lines 622-624)."""

    class BadSession:
        def get_providers(self) -> list[str]:
            raise RuntimeError("providers unavailable")

    adapter = _make_adapter()
    adapter._session = BadSession()  # type: ignore[assignment]
    metrics = await adapter.get_performance_metrics()
    assert "error" in metrics
    assert "providers unavailable" in metrics["error"]


@pytest.mark.asyncio
async def test_onnx_get_performance_metrics_with_profiling() -> None:
    settings = ONNXEmbeddingSettings(model_path="model.onnx", enable_profiling=True)
    adapter = ONNXEmbeddingAdapter(settings)
    adapter._session = MockSession()
    metrics = await adapter.get_performance_metrics()
    assert metrics["profiling_data"] == "profile.json"


# ---------------------------------------------------------------------------
# Tests — _create_embedding_result / _prepare_onnx_inputs with token_type_ids
# ---------------------------------------------------------------------------


def test_onnx_create_embedding_result() -> None:
    adapter = _make_adapter()
    embedding = np.array([0.1, 0.2, 0.3])
    result = adapter._create_embedding_result("hello", embedding, "model", token_count=5)
    assert result.text == "hello"
    assert result.tokens == 5
    assert "pooling_strategy" in result.metadata


def test_onnx_prepare_inputs_with_token_type_ids() -> None:
    adapter = _make_adapter()
    adapter._input_names = ["input_ids", "attention_mask", "token_type_ids"]
    tokenized = {
        "input_ids": np.array([[1, 2]]),
        "attention_mask": np.array([[1, 1]]),
        "token_type_ids": np.array([[0, 0]]),
    }
    result = adapter._prepare_onnx_inputs(tokenized)
    assert "token_type_ids" in result


# ---------------------------------------------------------------------------
# Tests — _process_single_batch (full path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_onnx_process_single_batch() -> None:
    adapter = _make_adapter()
    adapter._input_names = ["input_ids", "attention_mask"]
    adapter._output_names = ["last_hidden_state"]

    session = MockSession()
    tokenizer = MockTokenizer()

    results = await adapter._process_single_batch(
        ["hello", "world"],
        session,
        tokenizer,
        model="onnx-model",
        normalize=True,
    )
    assert len(results) == 2
    assert results[0].text == "hello"
    assert len(results[0].embedding) > 0
    assert results[0].metadata["pooling_strategy"] is not None


# ---------------------------------------------------------------------------
# Tests — _process_all_batches success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_onnx_process_all_batches_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from oneiric.adapters.embedding.embedding_interface import EmbeddingResult

    adapter = _make_adapter()

    async def fake_single_batch(batch_texts, session, tokenizer, model, normalize):
        return [
            EmbeddingResult(text=t, embedding=[0.1, 0.2], model=model, dimensions=2)
            for t in batch_texts
        ]

    monkeypatch.setattr(adapter, "_process_single_batch", fake_single_batch)

    results = await adapter._process_all_batches(
        ["a", "b", "c"],
        batch_size=2,
        session=None,
        tokenizer=None,
        model="m",
        normalize=False,
    )
    assert len(results) == 3


# ---------------------------------------------------------------------------
# Tests — _load_model with mocked onnxruntime + transformers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_onnx_load_model_success(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import types

    fake_session_opts = types.SimpleNamespace(
        enable_cpu_mem_arena=True,
        enable_mem_pattern=True,
        enable_profiling=False,
        inter_op_num_threads=0,
        intra_op_num_threads=0,
        graph_optimization_level=None,
    )
    fake_graph_opt = types.SimpleNamespace(
        ORT_ENABLE_ALL="ORT_ENABLE_ALL",
        ORT_DISABLE_ALL="ORT_DISABLE_ALL",
        ORT_ENABLE_BASIC="ORT_ENABLE_BASIC",
        ORT_ENABLE_EXTENDED="ORT_ENABLE_EXTENDED",
    )
    fake_ort = types.SimpleNamespace(
        SessionOptions=lambda: fake_session_opts,
        GraphOptimizationLevel=fake_graph_opt,
        InferenceSession=lambda *a, **kw: MockSession(),
    )
    fake_transformers = types.SimpleNamespace(
        AutoTokenizer=types.SimpleNamespace(
            from_pretrained=lambda *a, **kw: MockTokenizer()
        )
    )
    monkeypatch.setitem(sys.modules, "onnxruntime", fake_ort)
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)

    adapter = ONNXEmbeddingAdapter(ONNXEmbeddingSettings(model_path="fake.onnx"))
    await adapter._load_model()

    assert adapter._tokenizer is not None
    assert adapter._session is not None


@pytest.mark.asyncio
async def test_onnx_load_model_with_thread_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    import types

    fake_session_opts = types.SimpleNamespace(
        enable_cpu_mem_arena=True,
        enable_mem_pattern=True,
        enable_profiling=False,
        inter_op_num_threads=0,
        intra_op_num_threads=0,
        graph_optimization_level=None,
    )
    fake_graph_opt = types.SimpleNamespace(
        ORT_ENABLE_ALL="ORT_ENABLE_ALL",
        ORT_DISABLE_ALL="ORT_DISABLE_ALL",
        ORT_ENABLE_BASIC="ORT_ENABLE_BASIC",
        ORT_ENABLE_EXTENDED="ORT_ENABLE_EXTENDED",
    )
    fake_ort = types.SimpleNamespace(
        SessionOptions=lambda: fake_session_opts,
        GraphOptimizationLevel=fake_graph_opt,
        InferenceSession=lambda *a, **kw: MockSession(),
    )
    fake_transformers = types.SimpleNamespace(
        AutoTokenizer=types.SimpleNamespace(
            from_pretrained=lambda *a, **kw: MockTokenizer()
        )
    )
    monkeypatch.setitem(sys.modules, "onnxruntime", fake_ort)
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)

    settings = ONNXEmbeddingSettings(
        model_path="fake.onnx",
        inter_op_num_threads=4,
        intra_op_num_threads=2,
    )
    adapter = ONNXEmbeddingAdapter(settings)
    await adapter._load_model()

    assert fake_session_opts.inter_op_num_threads == 4
    assert fake_session_opts.intra_op_num_threads == 2


@pytest.mark.asyncio
async def test_onnx_load_model_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import types
    from oneiric.core.lifecycle import LifecycleError

    fake_ort = types.SimpleNamespace(
        SessionOptions=lambda: types.SimpleNamespace(
            enable_cpu_mem_arena=True,
            enable_mem_pattern=True,
            enable_profiling=False,
            inter_op_num_threads=0,
            intra_op_num_threads=0,
            graph_optimization_level=None,
        ),
        GraphOptimizationLevel=types.SimpleNamespace(ORT_ENABLE_ALL="all"),
        InferenceSession=lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("bad model")),
    )
    fake_transformers = types.SimpleNamespace(
        AutoTokenizer=types.SimpleNamespace(
            from_pretrained=lambda *a, **kw: MockTokenizer()
        )
    )
    monkeypatch.setitem(sys.modules, "onnxruntime", fake_ort)
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)

    adapter = ONNXEmbeddingAdapter(ONNXEmbeddingSettings(model_path="fake.onnx"))
    with pytest.raises(LifecycleError, match="onnx-model-load-failed"):
        await adapter._load_model()
