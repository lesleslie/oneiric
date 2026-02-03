from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, SecretStr

from oneiric.core.logging import get_logger

_NP_MODULE: Any | None = None


def _require_numpy() -> Any:
    global _NP_MODULE
    if _NP_MODULE is None:
        try:
            import numpy as np  # type: ignore
        except ImportError as exc:  # pragma: no cover - import guard
            msg = (
                "numpy is required for embedding helpers. "
                "Install the optional AI extras or add numpy to your environment."
            )
            raise ImportError(msg) from exc
        _NP_MODULE = np
    return _NP_MODULE


class EmbeddingModel(str, Enum):
    TEXT_EMBEDDING_3_SMALL = "text-embedding-3-small"
    TEXT_EMBEDDING_3_LARGE = "text-embedding-3-large"
    TEXT_EMBEDDING_ADA_002 = "text-embedding-ada-002"

    ALL_MINILM_L6_V2 = "all-MiniLM-L6-v2"
    ALL_MPNET_BASE_V2 = "all-mpnet-base-v2"
    MULTI_QA_MPNET_BASE_DOT_V1 = "multi-qa-mpnet-base-dot-v1"
    ALL_DISTILROBERTA_V1 = "all-distilroberta-v1"
    PARAPHRASE_MULTILINGUAL_MPNET_BASE_V2 = "paraphrase-multilingual-mpnet-base-v2"

    ONNX_ALL_MINILM_L6_V2 = "onnx-all-MiniLM-L6-v2"
    ONNX_ALL_MPNET_BASE_V2 = "onnx-all-mpnet-base-v2"


class PoolingStrategy(str, Enum):
    MEAN = "mean"
    MAX = "max"
    CLS = "cls"
    WEIGHTED_MEAN = "weighted_mean"


class VectorNormalization(str, Enum):
    L2 = "l2"
    L1 = "l1"
    NONE = "none"


class EmbeddingResult(BaseModel):
    text: str
    embedding: list[float]
    model: str
    dimensions: int
    tokens: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EmbeddingBatch(BaseModel):
    results: list[EmbeddingResult]
    total_tokens: int | None = None
    processing_time: float | None = None
    model: str
    batch_size: int


class EmbeddingBaseSettings(BaseModel):
    model: str = Field(default="text-embedding-3-small")
    api_key: SecretStr | None = Field(default=None)
    base_url: str | None = Field(default=None)
    max_retries: int = Field(default=3)
    timeout: float = Field(default=30.0)
    batch_size: int = Field(default=32)
    max_tokens_per_batch: int = Field(default=8192)
    normalize_embeddings: bool = Field(default=True)

    chunk_size: int = Field(default=512)
    chunk_overlap: int = Field(default=50)
    pooling_strategy: PoolingStrategy = Field(default=PoolingStrategy.MEAN)
    normalization: VectorNormalization = Field(default=VectorNormalization.L2)


class EmbeddingBase(ABC):
    def __init__(self, settings: EmbeddingBaseSettings) -> None:
        self._settings = settings
        self._client: Any | None = None
        self._model_cache: dict[str, Any] = {}
        self._logger = get_logger("adapter.embedding.base")

    @property
    def settings(self) -> EmbeddingBaseSettings:
        return self._settings

    @property
    def client(self) -> Any:
        return self._client

    @abstractmethod
    async def init(self) -> None: ...

    @abstractmethod
    async def health(self) -> bool: ...

    @abstractmethod
    async def cleanup(self) -> None: ...

    async def embed_text(
        self,
        text: str,
        model: str | EmbeddingModel | None = None,
        normalize: bool | None = None,
        **kwargs: Any,
    ) -> list[float]:
        result = await self.embed_texts(
            [text],
            model=model,
            normalize=normalize,
            **kwargs,
        )
        return result.results[0].embedding

    async def embed_texts(
        self,
        texts: list[str],
        model: str | EmbeddingModel | None = None,
        normalize: bool | None = None,
        batch_size: int | None = None,
        **kwargs: Any,
    ) -> EmbeddingBatch:
        return await self._embed_texts(
            texts,
            model=model or self._settings.model,
            normalize=normalize
            if normalize is not None
            else self._settings.normalize_embeddings,
            batch_size=batch_size or self._settings.batch_size,
            **kwargs,
        )

    async def embed_documents(
        self,
        documents: list[str],
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
        model: str | EmbeddingModel | None = None,
        **kwargs: Any,
    ) -> list[EmbeddingBatch]:
        return await self._embed_documents(
            documents,
            chunk_size=chunk_size or self._settings.chunk_size,
            chunk_overlap=chunk_overlap or self._settings.chunk_overlap,
            model=model or self._settings.model,
            **kwargs,
        )

    async def compute_similarity(
        self,
        embedding1: list[float],
        embedding2: list[float],
        method: str = "cosine",
    ) -> float:
        return await self._compute_similarity(embedding1, embedding2, method)

    async def get_model_info(
        self,
        model: str | EmbeddingModel | None = None,
    ) -> dict[str, Any]:
        return await self._get_model_info(model or self._settings.model)

    async def list_models(self) -> list[dict[str, Any]]:
        return await self._list_models()

    @abstractmethod
    async def _ensure_client(self) -> Any: ...

    @abstractmethod
    async def _embed_texts(
        self,
        texts: list[str],
        model: str,
        normalize: bool,
        batch_size: int,
        **kwargs: Any,
    ) -> EmbeddingBatch: ...

    @abstractmethod
    async def _embed_documents(
        self,
        documents: list[str],
        chunk_size: int,
        chunk_overlap: int,
        model: str,
        **kwargs: Any,
    ) -> list[EmbeddingBatch]: ...

    @abstractmethod
    async def _compute_similarity(
        self,
        embedding1: list[float],
        embedding2: list[float],
        method: str,
    ) -> float: ...

    @abstractmethod
    async def _get_model_info(self, model: str) -> dict[str, Any]: ...

    @abstractmethod
    async def _list_models(self) -> list[dict[str, Any]]: ...

    def _normalize_vector(
        self,
        vector: list[float],
        method: VectorNormalization = VectorNormalization.L2,
    ) -> list[float]:
        if method == VectorNormalization.NONE:
            return vector

        np_module = _require_numpy()
        np_vector = np_module.array(vector, dtype=float)

        if method == VectorNormalization.L2:
            norm = np_module.linalg.norm(np_vector)
            if norm == 0:
                return vector
            normalized: list[float] = (np_vector / norm).tolist()
            return normalized
        if method == VectorNormalization.L1:
            norm = np_module.sum(np_module.abs(np_vector))
            if norm == 0:
                return vector
            normalized_l1: list[float] = (np_vector / norm).tolist()
            return normalized_l1

        return vector

    def _chunk_text(self, text: str, chunk_size: int, overlap: int = 0) -> list[str]:
        if len(text) <= chunk_size:
            return [text]

        chunks = []
        start = 0

        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end]
            chunks.append(chunk)

            if end >= len(text):
                break

            start = end - overlap

        return chunks

    def _batch_texts(self, texts: list[str], batch_size: int) -> list[list[str]]:
        return [texts[i : i + batch_size] for i in range(0, len(texts), batch_size)]


class EmbeddingUtils:
    @staticmethod
    def cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
        np_module = _require_numpy()
        np_vec1 = np_module.array(vec1, dtype=float)
        np_vec2 = np_module.array(vec2, dtype=float)

        dot_product = np_module.dot(np_vec1, np_vec2)
        norm1 = np_module.linalg.norm(np_vec1)
        norm2 = np_module.linalg.norm(np_vec2)

        if 0 in (norm1, norm2):
            return 0.0

        return float(dot_product / (norm1 * norm2))

    @staticmethod
    def euclidean_distance(vec1: list[float], vec2: list[float]) -> float:
        np_module = _require_numpy()
        np_vec1 = np_module.array(vec1, dtype=float)
        np_vec2 = np_module.array(vec2, dtype=float)
        return float(np_module.linalg.norm(np_vec1 - np_vec2))

    @staticmethod
    def dot_product(vec1: list[float], vec2: list[float]) -> float:
        np_module = _require_numpy()
        np_vec1 = np_module.array(vec1, dtype=float)
        np_vec2 = np_module.array(vec2, dtype=float)
        return float(np_module.dot(np_vec1, np_vec2))

    @staticmethod
    def manhattan_distance(vec1: list[float], vec2: list[float]) -> float:
        np_module = _require_numpy()
        np_vec1 = np_module.array(vec1, dtype=float)
        np_vec2 = np_module.array(vec2, dtype=float)
        return float(np_module.sum(np_module.abs(np_vec1 - np_vec2)))


EmbeddingVector = list[float]
EmbeddingMatrix = list[list[float]]
