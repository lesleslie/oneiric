"""Lazy-loaded embedding adapters.

The concrete adapters below are re-exported lazily (PEP 562). Importing
this package eagerly pulled in every sibling adapter in the family and
every client library they need, which cost seconds of import time -- and a consumer
importing a single concrete adapter paid that tax too, because Python
executes every parent package's ``__init__`` on the way down.

Resolution is now deferred to first attribute access, so
``from oneiric.adapters.embedding import SomeAdapter`` still works and
``import oneiric.adapters.embedding`` stays cheap.

See ``oneiric/adapters/_lazy.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = [
    "EmbeddingBase",
    "EmbeddingBaseSettings",
    "EmbeddingBatch",
    "EmbeddingMatrix",
    "EmbeddingModel",
    "EmbeddingResult",
    "EmbeddingUtils",
    "EmbeddingVector",
    "OpenAIEmbeddingAdapter",
    "OpenAIEmbeddingSettings",
    "PoolingStrategy",
    "VectorNormalization",
]


if TYPE_CHECKING:
    from oneiric.adapters.embedding.embedding_interface import (
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
    from oneiric.adapters.embedding.openai import (
        OpenAIEmbeddingAdapter,
        OpenAIEmbeddingSettings,
    )


_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "EmbeddingBase": (
        "oneiric.adapters.embedding.embedding_interface",
        "EmbeddingBase",
    ),
    "EmbeddingBaseSettings": (
        "oneiric.adapters.embedding.embedding_interface",
        "EmbeddingBaseSettings",
    ),
    "EmbeddingBatch": (
        "oneiric.adapters.embedding.embedding_interface",
        "EmbeddingBatch",
    ),
    "EmbeddingMatrix": (
        "oneiric.adapters.embedding.embedding_interface",
        "EmbeddingMatrix",
    ),
    "EmbeddingModel": (
        "oneiric.adapters.embedding.embedding_interface",
        "EmbeddingModel",
    ),
    "EmbeddingResult": (
        "oneiric.adapters.embedding.embedding_interface",
        "EmbeddingResult",
    ),
    "EmbeddingUtils": (
        "oneiric.adapters.embedding.embedding_interface",
        "EmbeddingUtils",
    ),
    "EmbeddingVector": (
        "oneiric.adapters.embedding.embedding_interface",
        "EmbeddingVector",
    ),
    "OpenAIEmbeddingAdapter": (
        "oneiric.adapters.embedding.openai",
        "OpenAIEmbeddingAdapter",
    ),
    "OpenAIEmbeddingSettings": (
        "oneiric.adapters.embedding.openai",
        "OpenAIEmbeddingSettings",
    ),
    "PoolingStrategy": (
        "oneiric.adapters.embedding.embedding_interface",
        "PoolingStrategy",
    ),
    "VectorNormalization": (
        "oneiric.adapters.embedding.embedding_interface",
        "VectorNormalization",
    ),
}


def __getattr__(name: str) -> Any:
    """Resolve a re-exported adapter on first attribute access (PEP 562)."""
    from oneiric.adapters._lazy import resolve_lazy_export

    value = resolve_lazy_export(__name__, name, _LAZY_EXPORTS)
    globals()[name] = value  # cache for subsequent access
    return value


def __dir__() -> list[str]:
    """Advertise the lazy exports to ``dir()`` and tab-completion."""
    return sorted(__all__)
