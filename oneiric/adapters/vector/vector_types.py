from __future__ import annotations

from abc import abstractmethod
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from pydantic import BaseModel, Field

from oneiric.core.logging import get_logger


class VectorSearchResult(BaseModel):
    id: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)
    vector: list[float] | None = None


class VectorDocument(BaseModel):
    id: str | None = None
    vector: list[float]
    metadata: dict[str, Any] = Field(default_factory=dict)


class VectorBaseSettings(BaseModel):
    collection_prefix: str = ""
    default_dimension: int = 1536
    default_distance_metric: str = "cosine"

    connect_timeout: float = 30.0
    request_timeout: float = 30.0
    max_retries: int = 3

    batch_size: int = 100
    max_connections: int = 10


class VectorCollection:
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
        return await self.adapter.upsert(
            self.name,
            documents,
            **kwargs,
        )

    async def delete(self, ids: list[str], **kwargs: Any) -> bool:
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
        return await self.adapter.count(
            self.name,
            filter_expr,
            **kwargs,
        )


class VectorBase:
    def __init__(self, settings: VectorBaseSettings) -> None:
        self._settings = settings
        self._collections: dict[str, VectorCollection] = {}
        self._client: Any | None = None
        self._logger = get_logger("adapter.vector.base")

    def __getattr__(self, name: str) -> Any:
        if name not in self._collections:
            self._collections[name] = VectorCollection(self, name)
        return self._collections[name]

    async def get_client(self) -> Any:
        return await self._ensure_client()

    @abstractmethod
    async def init(self) -> None: ...

    @abstractmethod
    async def health(self) -> bool: ...

    @abstractmethod
    async def cleanup(self) -> None: ...

    @abstractmethod
    async def search(
        self,
        collection: str,
        query_vector: list[float],
        limit: int = 10,
        filter_expr: dict[str, Any] | None = None,
        include_vectors: bool = False,
        **kwargs: Any,
    ) -> list[VectorSearchResult]: ...

    @abstractmethod
    async def insert(
        self,
        collection: str,
        documents: list[VectorDocument],
        **kwargs: Any,
    ) -> list[str]: ...

    @abstractmethod
    async def upsert(
        self,
        collection: str,
        documents: list[VectorDocument],
        **kwargs: Any,
    ) -> list[str]: ...

    @abstractmethod
    async def delete(
        self,
        collection: str,
        ids: list[str],
        **kwargs: Any,
    ) -> bool: ...

    @abstractmethod
    async def get(
        self,
        collection: str,
        ids: list[str],
        include_vectors: bool = False,
        **kwargs: Any,
    ) -> list[VectorDocument]: ...

    @abstractmethod
    async def count(
        self,
        collection: str,
        filter_expr: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> int: ...

    @abstractmethod
    async def create_collection(
        self,
        name: str,
        dimension: int,
        distance_metric: str = "cosine",
        **kwargs: Any,
    ) -> bool: ...

    @abstractmethod
    async def delete_collection(
        self,
        name: str,
        **kwargs: Any,
    ) -> bool: ...

    @abstractmethod
    async def list_collections(self, **kwargs: Any) -> list[str]: ...

    @abstractmethod
    async def _ensure_client(self) -> Any: ...

    @abstractmethod
    async def _create_client(self) -> Any: ...

    def has_capability(self, capability: str) -> bool:
        return False

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[Any]:
        client = await self.get_client()
        yield client
