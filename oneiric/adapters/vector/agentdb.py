"""AgentDB vector database adapter with lifecycle integration.

AgentDB provides agents with a real cognitive layer optimized for:
- In-memory vector search (sub-1ms latency)
- Multi-node QUIC synchronization
- Agent-specific memory patterns
- Distributed AI systems

This adapter bridges AgentDB's Node.js architecture with Python via MCP.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource

from .common import VectorBase, VectorBaseSettings, VectorDocument, VectorSearchResult


class AgentDBSettings(VectorBaseSettings):
    """AgentDB vector adapter settings."""

    # MCP server connection (AgentDB runs as MCP server)
    mcp_server_url: str = "stdio://agentdb"  # stdio or http
    mcp_timeout: float = 30.0

    # AgentDB-specific settings
    storage_path: str | None = None  # Local file path for on-disk storage
    in_memory: bool = True  # Use in-memory vs disk storage
    sync_enabled: bool = False  # QUIC sync across nodes
    sync_nodes: list[str] = Field(default_factory=list)  # Node URLs for QUIC sync

    # Collection settings
    default_collection: str = "agent_memory"
    collection_prefix: str = "agent_"

    # Vector configuration
    default_dimension: int = 1536
    default_distance_metric: str = "cosine"  # cosine, euclidean, dot_product

    # Performance tuning
    cache_size_mb: int = 256  # In-memory cache size
    max_connections: int = 10


class AgentDBAdapter(VectorBase):
    """AgentDB vector database adapter implementing the lifecycle contract.

    AgentDB excels at:
    - Real-time agent memory (sub-1ms access)
    - Multi-node synchronization via QUIC
    - Agent-specific cognitive patterns
    - Hybrid vector search with HNSW

    This adapter uses AgentDB's MCP server interface for Python integration.
    """

    metadata = AdapterMetadata(
        category="vector",
        provider="agentdb",
        factory="oneiric.adapters.vector.agentdb:AgentDBAdapter",
        capabilities=[
            "vector_search",
            "batch_operations",
            "metadata_filtering",
            "real_time",
            "quic_sync",
            "agent_optimized",
        ],
        stack_level=30,
        priority=600,  # Higher priority for agent workloads
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
        """Create AgentDB MCP client."""
        try:
            # Import MCP client
            from mcp_common.client import MCPClient

            # Create MCP connection to AgentDB
            self._logger.info(
                "Creating AgentDB MCP client",
                server_url=self._settings.mcp_server_url,
                in_memory=self._settings.in_memory,
            )

            self._mcp_client = MCPClient(
                server_url=self._settings.mcp_server_url,
                timeout=self._settings.mcp_timeout,
            )

            # Initialize AgentDB via MCP
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
        """Ensure AgentDB client is initialized."""
        if self._client is None:
            self._client = await self._create_client()
        return self._client

    # Lifecycle hooks
    async def init(self) -> None:
        """Initialize AgentDB adapter."""
        try:
            self._logger.info("Initializing AgentDB adapter")
            await self._ensure_client()

            # Health check
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
        """Check if AgentDB is healthy."""
        try:
            client = await self._ensure_client()
            result = await client.call_tool("agentdb_health", {})
            return result.get("status") == "healthy"
        except Exception as e:
            self._logger.warning("AgentDB health check failed", error=str(e))
            return False

    async def cleanup(self) -> None:
        """Cleanup AgentDB resources."""
        try:
            if self._mcp_client:
                await self._mcp_client.close()
                self._mcp_client = None
            self._client = None
            self._logger.info("AgentDB adapter cleaned up")
        except Exception as e:
            self._logger.warning("Error during AgentDB cleanup", error=str(e))

    # Core vector operations
    async def search(
        self,
        collection: str,
        query_vector: list[float],
        limit: int = 10,
        filter_expr: dict[str, Any] | None = None,
        include_vectors: bool = False,
        **kwargs: Any,
    ) -> list[VectorSearchResult]:
        """Perform vector similarity search in AgentDB."""
        try:
            client = await self._ensure_client()

            collection_name = f"{self._settings.collection_prefix}{collection}"

            # Call AgentDB search via MCP
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

            # Transform to VectorSearchResult
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
        """Insert documents into AgentDB."""
        try:
            client = await self._ensure_client()
            collection_name = f"{self._settings.collection_prefix}{collection}"

            # Prepare documents for AgentDB
            docs_data = [
                {
                    "id": doc.id or f"{collection}_{hash(str(doc.vector))}",
                    "vector": doc.vector,
                    "metadata": doc.metadata,
                }
                for doc in documents
            ]

            # Call AgentDB insert via MCP
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
        """Upsert documents into AgentDB."""
        try:
            client = await self._ensure_client()
            collection_name = f"{self._settings.collection_prefix}{collection}"

            # Prepare documents for AgentDB
            docs_data = [
                {
                    "id": doc.id or f"{collection}_{hash(str(doc.vector))}",
                    "vector": doc.vector,
                    "metadata": doc.metadata,
                }
                for doc in documents
            ]

            # Call AgentDB upsert via MCP
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
        """Delete documents from AgentDB."""
        try:
            client = await self._ensure_client()
            collection_name = f"{self._settings.collection_prefix}{collection}"

            # Call AgentDB delete via MCP
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
        """Retrieve documents from AgentDB."""
        try:
            client = await self._ensure_client()
            collection_name = f"{self._settings.collection_prefix}{collection}"

            # Call AgentDB get via MCP
            result = await client.call_tool(
                "agentdb_get",
                {
                    "collection": collection_name,
                    "ids": ids,
                    "include_vectors": include_vectors,
                },
            )

            # Transform to VectorDocument
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
        """Count documents in AgentDB collection."""
        try:
            client = await self._ensure_client()
            collection_name = f"{self._settings.collection_prefix}{collection}"

            # Call AgentDB count via MCP
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

    # Collection management
    async def create_collection(
        self,
        name: str,
        dimension: int,
        distance_metric: str = "cosine",
        **kwargs: Any,
    ) -> bool:
        """Create a new AgentDB collection."""
        try:
            client = await self._ensure_client()
            collection_name = f"{self._settings.collection_prefix}{name}"

            # Call AgentDB create_collection via MCP
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
        """Delete an AgentDB collection."""
        try:
            client = await self._ensure_client()
            collection_name = f"{self._settings.collection_prefix}{name}"

            # Call AgentDB delete_collection via MCP
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
        """List all AgentDB collections."""
        try:
            client = await self._ensure_client()

            # Call AgentDB list_collections via MCP
            result = await client.call_tool("agentdb_list_collections", {})

            collections = result.get("collections", [])
            # Strip prefix if present
            prefix = self._settings.collection_prefix
            return [
                col[len(prefix) :] if col.startswith(prefix) else col
                for col in collections
            ]

        except Exception as e:
            self._logger.error("AgentDB list_collections failed", error=str(e))
            raise

    def has_capability(self, capability: str) -> bool:
        """Check if AgentDB adapter supports a specific capability."""
        return capability in self.metadata.capabilities
