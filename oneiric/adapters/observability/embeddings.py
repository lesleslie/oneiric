"""Embedding service for trace similarity search."""

from __future__ import annotations

from typing import Any


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
