"""Lazy-loaded observability adapters.

Submodules here have heavy optional dependencies (pgvector for
``otel``, httpx-only for ``embeddings``). Importing this package must
NOT trigger those imports so consumers like akosha can pull in only
the embedding service without paying for pgvector.

Use module-level access:

    from oneiric.adapters.observability.embeddings import EmbeddingService
    from oneiric.adapters.observability.otel import OTelStorageAdapter

Or use the names exported below via lazy attribute access:

    from oneiric.adapters.observability import EmbeddingService  # works
    from oneiric.adapters.observability import OTelStorageAdapter  # works
"""

from __future__ import annotations

from typing import TYPE_CHECKING

__all__ = [
    "OTelStorageAdapter",
    "OTelStorageSettings",
    "EmbeddingService",
    "EmbeddingSettings",
]


if TYPE_CHECKING:
    from oneiric.adapters.observability.embeddings import EmbeddingService
    from oneiric.adapters.observability.embedding_settings import EmbeddingSettings
    from oneiric.adapters.observability.otel import OTelStorageAdapter
    from oneiric.adapters.observability.settings import OTelStorageSettings


_LAZY_EXPORTS = {
    "OTelStorageAdapter": ("oneiric.adapters.observability.otel", "OTelStorageAdapter"),
    "OTelStorageSettings": (
        "oneiric.adapters.observability.settings",
        "OTelStorageSettings",
    ),
    "EmbeddingService": (
        "oneiric.adapters.observability.embeddings",
        "EmbeddingService",
    ),
    "EmbeddingSettings": (
        "oneiric.adapters.observability.embedding_settings",
        "EmbeddingSettings",
    ),
}


def __getattr__(name: str):  # noqa: D401 — module-level __getattr__
    """Lazily resolve submodule exports on first attribute access.

    This keeps ``from oneiric.adapters.observability.embeddings import
    EmbeddingService`` working as expected, AND also enables
    ``from oneiric.adapters.observability import EmbeddingService``
    without forcing pgvector to load at package import time.
    """
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_path, attr_name = target
    import importlib

    module = importlib.import_module(module_path)
    value = getattr(module, attr_name)
    globals()[name] = value  # cache for subsequent access
    return value
