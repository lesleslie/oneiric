"""Vector storage adapters for Oneiric.

Defines the contract for vector-backed hot-tier storage (HotStore Protocol)
and ships concrete implementations (DuckDB-backed for development/test,
pgvector-backed for production).
"""

from .agentdb import AgentDBAdapter
from .pinecone import PineconeAdapter
from .qdrant import QdrantAdapter

__all__ = [
    "AgentDBAdapter",
    "PineconeAdapter",
    "QdrantAdapter",
]
