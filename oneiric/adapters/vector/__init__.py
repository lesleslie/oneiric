"""Lazy-loaded vector adapters.

The concrete adapters below are re-exported lazily (PEP 562). Importing
this package eagerly pulled in every sibling adapter in the family and
every client library they need, which cost seconds of import time -- and a consumer
importing a single concrete adapter paid that tax too, because Python
executes every parent package's ``__init__`` on the way down.

Resolution is now deferred to first attribute access, so
``from oneiric.adapters.vector import SomeAdapter`` still works and
``import oneiric.adapters.vector`` stays cheap.

See ``oneiric/adapters/_lazy.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = [
    "AgentDBAdapter",
    "PgvectorAdapter",
    "PineconeAdapter",
    "QdrantAdapter",
]


if TYPE_CHECKING:
    from oneiric.adapters.vector.agentdb import AgentDBAdapter
    from oneiric.adapters.vector.pgvector import PgvectorAdapter
    from oneiric.adapters.vector.pinecone import PineconeAdapter
    from oneiric.adapters.vector.qdrant import QdrantAdapter


_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "AgentDBAdapter": ("oneiric.adapters.vector.agentdb", "AgentDBAdapter"),
    "PgvectorAdapter": ("oneiric.adapters.vector.pgvector", "PgvectorAdapter"),
    "PineconeAdapter": ("oneiric.adapters.vector.pinecone", "PineconeAdapter"),
    "QdrantAdapter": ("oneiric.adapters.vector.qdrant", "QdrantAdapter"),
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
