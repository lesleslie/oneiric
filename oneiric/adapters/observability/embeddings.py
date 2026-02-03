from __future__ import annotations

import hashlib
from functools import lru_cache
from typing import Any

import numpy as np

try:
    from sentence_transformers import SentenceTransformer

    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    SentenceTransformer = None  # type: ignore


class EmbeddingService:
    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self._model_name = model_name
        self._model = None

    def _build_text_from_trace(self, trace: dict[str, Any]) -> str:
        service = trace.get("service", "unknown")
        operation = trace.get("operation", "unknown")
        status = trace.get("status", "UNKNOWN")
        duration_ms = trace.get("duration_ms", 0)
        attributes = trace.get("attributes", {})

        attr_str = " ".join(f"{k}={v}" for k, v in sorted(attributes.items()))

        return (
            f"{service} {operation} {status} in {duration_ms}ms attributes: {attr_str}"
        )

    def _generate_cache_key(self, trace: dict[str, Any]) -> int:
        return hash(frozenset(sorted(trace.items())))

    def _generate_fallback_embedding(self, trace_id: str) -> np.ndarray:
        hash_int = int(hashlib.sha256(trace_id.encode()).hexdigest(), 16)

        return np.array([(hash_int >> i) & 0xFF for i in range(384)]) / 255.0

    def _load_model(self) -> Any:
        if not SENTENCE_TRANSFORMERS_AVAILABLE:
            raise ImportError(
                "sentence-transformers is not installed. Install it with: pip install sentence-transformers"
            )

        if self._model is None:
            self._model = SentenceTransformer(self._model_name)
        return self._model

    async def _generate_embedding(self, text: str) -> np.ndarray:
        model = self._load_model()
        return model.encode(text)

    @lru_cache(maxsize=1000)
    def _embed_cached(self, cache_key: int, text: str) -> np.ndarray:
        model = self._load_model()
        return model.encode(text)

    async def embed_trace(self, trace: dict[str, Any]) -> np.ndarray:
        from oneiric.core.logging import get_logger

        logger = get_logger("otel.embedding")

        try:
            text = self._build_text_from_trace(trace)

            cache_key = self._generate_cache_key(trace)

            embedding = self._embed_cached(cache_key, text)

            logger.debug("embedding-generated", trace_id=trace.get("trace_id"))
            return embedding

        except Exception as exc:
            logger.warning(
                "embedding-generation-failed",
                error=str(exc),
                trace_id=trace.get("trace_id"),
                fallback=True,
            )
            return self._generate_fallback_embedding(trace.get("trace_id", "unknown"))
