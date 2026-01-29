"""Embedding service for trace similarity search."""

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
    """Generate embeddings for trace similarity search."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        """Initialize embedding service.

        Args:
            model_name: sentence-transformers model name
        """
        self._model_name = model_name
        self._model = None  # Lazy-loaded

    def _build_text_from_trace(self, trace: dict[str, Any]) -> str:
        """Build human-readable text from trace dict.

        Args:
            trace: Trace data dictionary

        Returns:
            Human-readable text string for embedding
        """
        service = trace.get("service", "unknown")
        operation = trace.get("operation", "unknown")
        status = trace.get("status", "UNKNOWN")
        duration_ms = trace.get("duration_ms", 0)
        attributes = trace.get("attributes", {})

        # Build attributes string
        attr_str = " ".join(f"{k}={v}" for k, v in sorted(attributes.items()))

        return (
            f"{service} {operation} {status} in {duration_ms}ms attributes: {attr_str}"
        )

    def _generate_cache_key(self, trace: dict[str, Any]) -> int:
        """Generate cache key from trace dict.

        Uses hash of sorted items for determinism.

        Args:
            trace: Trace data dictionary

        Returns:
            Cache key (hash integer)
        """
        return hash(frozenset(sorted(trace.items())))

    def _generate_fallback_embedding(self, trace_id: str) -> np.ndarray:
        """Generate fallback embedding from trace_id hash.

        Creates deterministic 384-dim vector using SHA-256 hash.
        Used when sentence-transformers model fails.

        Args:
            trace_id: Trace identifier

        Returns:
            384-dim vector with values in [0, 1]
        """
        # Hash trace_id to get deterministic bytes
        hash_int = int(hashlib.sha256(trace_id.encode()).hexdigest(), 16)

        # Convert to 384-dim vector
        # Each byte (0-255) becomes a value in [0, 1]
        return np.array([(hash_int >> i) & 0xFF for i in range(384)]) / 255.0

    def _load_model(self) -> Any:
        """Lazy-load sentence-transformers model.

        Returns:
            Loaded SentenceTransformer model
        """
        if not SENTENCE_TRANSFORMERS_AVAILABLE:
            raise ImportError(
                "sentence-transformers is not installed. Install it with: pip install sentence-transformers"
            )

        if self._model is None:
            self._model = SentenceTransformer(self._model_name)
        return self._model

    async def _generate_embedding(self, text: str) -> np.ndarray:
        """Generate embedding from text.

        Args:
            text: Text string to embed

        Returns:
            384-dim vector
        """
        model = self._load_model()
        return model.encode(text)

    @lru_cache(maxsize=1000)
    def _embed_cached(self, cache_key: int, text: str) -> np.ndarray:
        """Generate embedding with LRU caching.

        Args:
            cache_key: Cache key (hash of trace)
            text: Text to embed

        Returns:
            384-dim vector
        """
        # Note: This is sync, but fast because model is cached
        model = self._load_model()
        return model.encode(text)

    async def embed_trace(self, trace: dict[str, Any]) -> np.ndarray:
        """Generate embedding from trace dict.

        Args:
            trace: Trace data dictionary

        Returns:
            384-dim vector embedding
        """
        from oneiric.core.logging import get_logger

        logger = get_logger("otel.embedding")

        try:
            # Build text
            text = self._build_text_from_trace(trace)

            # Generate cache key
            cache_key = self._generate_cache_key(trace)

            # Generate embedding (cached)
            embedding = self._embed_cached(cache_key, text)

            logger.debug("embedding-generated", trace_id=trace.get("trace_id"))
            return embedding

        except Exception as exc:
            # Fallback on any error
            logger.warning(
                "embedding-generation-failed",
                error=str(exc),
                trace_id=trace.get("trace_id"),
                fallback=True,
            )
            return self._generate_fallback_embedding(trace.get("trace_id", "unknown"))
