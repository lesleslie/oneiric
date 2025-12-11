"""Vector database adapters for Oneiric."""

from oneiric.adapters.vector.common import (
    VectorBase,
    VectorBaseSettings,
    VectorCollection,
    VectorDocument,
    VectorSearchResult,
)
from oneiric.adapters.vector.pgvector import PgvectorAdapter, PgvectorSettings
from oneiric.adapters.vector.pinecone import PineconeAdapter, PineconeSettings
from oneiric.adapters.vector.qdrant import QdrantAdapter, QdrantSettings

__all__ = [
    "VectorBase",
    "VectorBaseSettings",
    "VectorCollection",
    "VectorDocument",
    "VectorSearchResult",
    "PgvectorAdapter",
    "PgvectorSettings",
    "PineconeAdapter",
    "PineconeSettings",
    "QdrantAdapter",
    "QdrantSettings",
]
