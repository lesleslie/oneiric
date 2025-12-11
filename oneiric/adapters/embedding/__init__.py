"""Embedding adapters for Oneiric."""

from oneiric.adapters.embedding.common import (
    EmbeddingBase,
    EmbeddingBaseSettings,
    EmbeddingBatch,
    EmbeddingMatrix,
    EmbeddingModel,
    EmbeddingResult,
    EmbeddingUtils,
    EmbeddingVector,
    PoolingStrategy,
    VectorNormalization,
)
from oneiric.adapters.embedding.onnx import (
    ONNXEmbeddingAdapter,
    ONNXEmbeddingSettings,
)
from oneiric.adapters.embedding.openai import (
    OpenAIEmbeddingAdapter,
    OpenAIEmbeddingSettings,
)
from oneiric.adapters.embedding.sentence_transformers import (
    SentenceTransformersAdapter,
    SentenceTransformersSettings,
)

__all__ = [
    # Base classes
    "EmbeddingBase",
    "EmbeddingBaseSettings",
    # Models
    "EmbeddingModel",
    "EmbeddingResult",
    "EmbeddingBatch",
    # Utilities
    "EmbeddingUtils",
    "EmbeddingVector",
    "EmbeddingMatrix",
    # Enums
    "PoolingStrategy",
    "VectorNormalization",
    # OpenAI
    "OpenAIEmbeddingAdapter",
    "OpenAIEmbeddingSettings",
    # Sentence Transformers
    "SentenceTransformersAdapter",
    "SentenceTransformersSettings",
    # ONNX
    "ONNXEmbeddingAdapter",
    "ONNXEmbeddingSettings",
]
