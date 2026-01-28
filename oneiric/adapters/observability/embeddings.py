"""Embedding service for trace similarity search."""

from __future__ import annotations

import hashlib
from typing import Any

import numpy as np


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

        return f"{service} {operation} {status} in {duration_ms}ms attributes: {attr_str}"

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
        return np.array([
            (hash_int >> i) & 0xFF
            for i in range(384)
        ]) / 255.0
