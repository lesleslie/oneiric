from __future__ import annotations

from typing import Any

from pydantic import Field

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource

from .vector_types import (
    VectorBase,
    VectorBaseSettings,
    VectorDocument,
    VectorSearchResult,
)


class AgentDBSettings(VectorBaseSettings):
    mcp_server_url: str = "stdio://agentdb"
    mcp_timeout: float = 30.0

    storage_path: str | None = None
    in_memory: bool = True
    sync_enabled: bool = False
    sync_nodes: list[str] = Field(default_factory=list)

    default_collection: str = "agent_memory"
    collection_prefix: str = "agent_"

    default_dimension: int = 1536
    default_distance_metric: str = "cosine"

    cache_size_mb: int = 256
    max_connections: int = 10


class AgentDBAdapter(VectorBase):
    metadata = AdapterMetadata(
        category="vector",
        provider="agentdb",
        factory="oneiric.adapters.vector.agentdb: AgentDBAdapter",
        capabilities=[
            "vector_search",
            "batch_operations",
            "metadata_filtering",
            "real_time",
            "quic_sync",
            "agent_optimized",
        ],
        stack_level=30,
        priority=600,
        source=CandidateSource.LOCAL_PKG,
        owner="AI Platform",
        requires_secrets=False,
        settings_model=AgentDBSettings,
    )

    def __init__(self, settings: AgentDBSettings) -> None:
        super().__init__(settings)
        self._settings: AgentDBSettings = settings
        self._client: Any | None = None
        self._mcp_client: Any | None = None
        self._logger = get_logger("adapter.vector.agentdb").bind(
            domain="adapter",
            key="vector",
            provider="agentdb",
        )

    async def _create_client(self) -> Any:
        try:
            from mcp_common.client import MCPClient

            self._logger.info(
                "Creating AgentDB MCP client",
                server_url=self._settings.mcp_server_url,
                in_memory=self._settings.in_memory,
            )

            self._mcp_client = MCPClient(
                server_url=self._settings.mcp_server_url,
                timeout=self._settings.mcp_timeout,
            )

            await self._mcp_client.call_tool(
                "agentdb_init",
                {
                    "storage_path": self._settings.storage_path,
                    "in_memory": self._settings.in_memory,
                    "cache_size_mb": self._settings.cache_size_mb,
                },
            )

            return self._mcp_client

        except Exception as e:
            self._logger.error(
                "Failed to create AgentDB client",
                error=str(e),
                error_type=type(e).__name__,
            )
            raise LifecycleError(f"Failed to initialize AgentDB adapter: {e}") from e

    async def _ensure_client(self) -> Any:
        if self._client is None:
            self._client = await self._create_client()
        return self._client

    async def init(self) -> None:
        try:
            self._logger.info("Initializing AgentDB adapter")
            await self._ensure_client()

            is_healthy = await self.health()
            if not is_healthy:
                raise LifecycleError("AgentDB health check failed")

            self._logger.info(
                "AgentDB adapter initialized successfully",
                in_memory=self._settings.in_memory,
                sync_enabled=self._settings.sync_enabled,
            )

        except Exception as e:
            self._logger.error("Failed to initialize AgentDB adapter", error=str(e))
            raise

    async def health(self) -> bool:
        try:
            client = await self._ensure_client()
            result = await client.call_tool("agentdb_health", {})
            return result.get("status") == "healthy"
        except Exception as e:
            self._logger.warning("AgentDB health check failed", error=str(e))
            return False

    async def cleanup(self) -> None:
        try:
            if self._mcp_client:
                await self._mcp_client.close()
                self._mcp_client = None
            self._client = None
            self._logger.info("AgentDB adapter cleaned up")
        except Exception as e:
            self._logger.warning("Error during AgentDB cleanup", error=str(e))

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        limit: int = 10,
        filter_expr: dict[str, Any] | None = None,
        include_vectors: bool = False,
        **kwargs: Any,
    ) -> list[VectorSearchResult]:
        try:
            client = await self._ensure_client()

            collection_name = f"{self._settings.collection_prefix}{collection}"

            result = await client.call_tool(
                "agentdb_search",
                {
                    "collection": collection_name,
                    "query_vector": query_vector,
                    "limit": limit,
                    "filter": filter_expr,
                    "include_vectors": include_vectors,
                    "distance_metric": kwargs.get(
                        "distance_metric", self._settings.default_distance_metric
                    ),
                },
            )

            return [
                VectorSearchResult(
                    id=hit["id"],
                    score=hit["score"],
                    metadata=hit.get("metadata", {}),
                    vector=hit.get("vector") if include_vectors else None,
                )
                for hit in result.get("results", [])
            ]

        except Exception as e:
            self._logger.error("AgentDB search failed", error=str(e))
            raise

    async def insert(
        self,
        collection: str,
        documents: list[VectorDocument],
        **kwargs: Any,
    ) -> list[str]:
        try:
            client = await self._ensure_client()
            collection_name = f"{self._settings.collection_prefix}{collection}"

            docs_data = [
                {
                    "id": doc.id or f"{collection}_{hash(str(doc.vector))}",
                    "vector": doc.vector,
                    "metadata": doc.metadata,
                }
                for doc in documents
            ]

            result = await client.call_tool(
                "agentdb_insert",
                {
                    "collection": collection_name,
                    "documents": docs_data,
                },
            )

            return result.get("ids", [])

        except Exception as e:
            self._logger.error("AgentDB insert failed", error=str(e))
            raise

    async def upsert(
        self,
        collection: str,
        documents: list[VectorDocument],
        **kwargs: Any,
    ) -> list[str]:
        try:
            client = await self._ensure_client()
            collection_name = f"{self._settings.collection_prefix}{collection}"

            docs_data = [
                {
                    "id": doc.id or f"{collection}_{hash(str(doc.vector))}",
                    "vector": doc.vector,
                    "metadata": doc.metadata,
                }
                for doc in documents
            ]

            result = await client.call_tool(
                "agentdb_upsert",
                {
                    "collection": collection_name,
                    "documents": docs_data,
                },
            )

            return result.get("ids", [])

        except Exception as e:
            self._logger.error("AgentDB upsert failed", error=str(e))
            raise

    async def delete(
        self,
        collection: str,
        ids: list[str],
        **kwargs: Any,
    ) -> bool:
        try:
            client = await self._ensure_client()
            collection_name = f"{self._settings.collection_prefix}{collection}"

            result = await client.call_tool(
                "agentdb_delete",
                {
                    "collection": collection_name,
                    "ids": ids,
                },
            )

            return result.get("success", False)

        except Exception as e:
            self._logger.error("AgentDB delete failed", error=str(e))
            raise

    async def get(
        self,
        collection: str,
        ids: list[str],
        include_vectors: bool = False,
        **kwargs: Any,
    ) -> list[VectorDocument]:
        try:
            client = await self._ensure_client()
            collection_name = f"{self._settings.collection_prefix}{collection}"

            result = await client.call_tool(
                "agentdb_get",
                {
                    "collection": collection_name,
                    "ids": ids,
                    "include_vectors": include_vectors,
                },
            )

            return [
                VectorDocument(
                    id=doc["id"],
                    vector=doc.get("vector") if include_vectors else [],
                    metadata=doc.get("metadata", {}),
                )
                for doc in result.get("documents", [])
            ]

        except Exception as e:
            self._logger.error("AgentDB get failed", error=str(e))
            raise

    async def count(
        self,
        collection: str,
        filter_expr: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> int:
        try:
            client = await self._ensure_client()
            collection_name = f"{self._settings.collection_prefix}{collection}"

            result = await client.call_tool(
                "agentdb_count",
                {
                    "collection": collection_name,
                    "filter": filter_expr,
                },
            )

            return result.get("count", 0)

        except Exception as e:
            self._logger.error("AgentDB count failed", error=str(e))
            raise

    async def create_collection(
        self,
        name: str,
        dimension: int,
        distance_metric: str = "cosine",
        **kwargs: Any,
    ) -> bool:
        try:
            client = await self._ensure_client()
            collection_name = f"{self._settings.collection_prefix}{name}"

            result = await client.call_tool(
                "agentdb_create_collection",
                {
                    "collection": collection_name,
                    "dimension": dimension,
                    "distance_metric": distance_metric,
                },
            )

            return result.get("success", False)

        except Exception as e:
            self._logger.error("AgentDB create_collection failed", error=str(e))
            raise

    async def delete_collection(
        self,
        name: str,
        **kwargs: Any,
    ) -> bool:
        try:
            client = await self._ensure_client()
            collection_name = f"{self._settings.collection_prefix}{name}"

            result = await client.call_tool(
                "agentdb_delete_collection",
                {
                    "collection": collection_name,
                },
            )

            return result.get("success", False)

        except Exception as e:
            self._logger.error("AgentDB delete_collection failed", error=str(e))
            raise

    async def list_collections(self, **kwargs: Any) -> list[str]:
        try:
            client = await self._ensure_client()

            result = await client.call_tool("agentdb_list_collections", {})

            collections = result.get("collections", [])

            prefix = self._settings.collection_prefix
            return [
                col[len(prefix) :] if col.startswith(prefix) else col
                for col in collections
            ]

        except Exception as e:
            self._logger.error("AgentDB list_collections failed", error=str(e))
            raise

    def has_capability(self, capability: str) -> bool:
        return capability in self.metadata.capabilities
