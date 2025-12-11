"""Base classes for vector database adapters."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from pydantic import BaseModel, Field

from oneiric.core.logging import get_logger


class VectorSearchResult(BaseModel):
    """Standard vector search result."""

    id: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)
    vector: list[float] | None = None


class VectorDocument(BaseModel):
    """Standard vector document for insertion."""

    id: str | None = None
    vector: list[float]
    metadata: dict[str, Any] = Field(default_factory=dict)


class VectorBaseSettings(BaseModel):
    """Base settings for vector adapters."""

    collection_prefix: str = ""
    default_dimension: int = 1536  # OpenAI ada-002 default
    default_distance_metric: str = "cosine"  # cosine, euclidean, dot_product

    # Connection settings
    connect_timeout: float = 30.0
    request_timeout: float = 30.0
    max_retries: int = 3

    # Performance settings
    batch_size: int = 100
    max_connections: int = 10


class VectorCollection:
    """Wrapper for vector collection operations."""

    def __init__(self, adapter: Any, name: str) -> None:
        self.adapter = adapter
        self.name = name

    async def search(
        self,
        query_vector: list[float],
        limit: int = 10,
        filter_expr: dict[str, Any] | None = None,
        include_vectors: bool = False,
        **kwargs: Any,
    ) -> list[VectorSearchResult]:
        """Perform vector similarity search."""
        return await self.adapter.search(
            self.name,
            query_vector,
            limit,
            filter_expr,
            include_vectors,
            **kwargs,
        )

    async def insert(
        self,
        documents: list[VectorDocument],
        **kwargs: Any,
    ) -> list[str]:
        """Insert documents with vectors."""
        return await self.adapter.insert(
            self.name,
            documents,
            **kwargs,
        )

    async def upsert(
        self,
        documents: list[VectorDocument],
        **kwargs: Any,
    ) -> list[str]:
        """Upsert documents with vectors."""
        return await self.adapter.upsert(
            self.name,
            documents,
            **kwargs,
        )

    async def delete(self, ids: list[str], **kwargs: Any) -> bool:
        """Delete documents by IDs."""
        return await self.adapter.delete(
            self.name,
            ids,
            **kwargs,
        )

    async def get(
        self,
        ids: list[str],
        include_vectors: bool = False,
        **kwargs: Any,
    ) -> list[VectorDocument]:
        """Retrieve documents by IDs."""
        return await self.adapter.get(
            self.name,
            ids,
            include_vectors,
            **kwargs,
        )

    async def count(
        self,
        filter_expr: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> int:
        """Count documents in collection."""
        return await self.adapter.count(
            self.name,
            filter_expr,
            **kwargs,
        )


class VectorBase:
    """Base class for vector database adapters with lifecycle integration."""

    def __init__(self, settings: VectorBaseSettings) -> None:
        self._settings = settings
        self._collections: dict[str, VectorCollection] = {}
        self._client: Any | None = None
        self._logger = get_logger("adapter.vector.base")

    def __getattr__(self, name: str) -> Any:
        """Dynamic collection access."""
        if name not in self._collections:
            self._collections[name] = VectorCollection(self, name)
        return self._collections[name]

    async def get_client(self) -> Any:
        """Get the underlying vector database client."""
        return await self._ensure_client()

    # Lifecycle hooks (to be implemented by Oneiric lifecycle manager)
    @abstractmethod
    async def init(self) -> None:
        """Initialize the vector adapter."""
        ...

    @abstractmethod
    async def health(self) -> bool:
        """Check if the vector database is healthy."""
        ...

    @abstractmethod
    async def cleanup(self) -> None:
        """Cleanup vector database resources."""
        ...

    # Core vector operations (to be implemented by concrete adapters)
    @abstractmethod
    async def search(
        self,
        collection: str,
        query_vector: list[float],
        limit: int = 10,
        filter_expr: dict[str, Any] | None = None,
        include_vectors: bool = False,
        **kwargs: Any,
    ) -> list[VectorSearchResult]:
        """Perform vector similarity search."""
        ...

    @abstractmethod
    async def insert(
        self,
        collection: str,
        documents: list[VectorDocument],
        **kwargs: Any,
    ) -> list[str]:
        """Insert documents with vectors."""
        ...

    @abstractmethod
    async def upsert(
        self,
        collection: str,
        documents: list[VectorDocument],
        **kwargs: Any,
    ) -> list[str]:
        """Upsert documents with vectors."""
        ...

    @abstractmethod
    async def delete(
        self,
        collection: str,
        ids: list[str],
        **kwargs: Any,
    ) -> bool:
        """Delete documents by IDs."""
        ...

    @abstractmethod
    async def get(
        self,
        collection: str,
        ids: list[str],
        include_vectors: bool = False,
        **kwargs: Any,
    ) -> list[VectorDocument]:
        """Retrieve documents by IDs."""
        ...

    @abstractmethod
    async def count(
        self,
        collection: str,
        filter_expr: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> int:
        """Count documents in collection."""
        ...

    @abstractmethod
    async def create_collection(
        self,
        name: str,
        dimension: int,
        distance_metric: str = "cosine",
        **kwargs: Any,
    ) -> bool:
        """Create a new collection."""
        ...

    @abstractmethod
    async def delete_collection(
        self,
        name: str,
        **kwargs: Any,
    ) -> bool:
        """Delete a collection."""
        ...

    @abstractmethod
    async def list_collections(self, **kwargs: Any) -> list[str]:
        """List all collections."""
        ...

    @abstractmethod
    async def _ensure_client(self) -> Any:
        """Ensure client is initialized."""
        ...

    @abstractmethod
    async def _create_client(self) -> Any:
        """Create the underlying client."""
        ...

    def has_capability(self, capability: str) -> bool:
        """Check if adapter supports a specific capability."""
        return False  # Base implementation - override in adapters

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[Any]:
        """Transaction context manager (if supported)."""
        client = await self.get_client()
        yield client
