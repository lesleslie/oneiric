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
