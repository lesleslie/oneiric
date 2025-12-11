"""Qdrant vector database adapter with lifecycle integration."""

from __future__ import annotations

import uuid as uuid_module
from typing import Any

from pydantic import Field, SecretStr

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource

from .common import VectorBase, VectorBaseSettings, VectorDocument, VectorSearchResult


class QdrantSettings(VectorBaseSettings):
    """Qdrant vector adapter settings."""

    url: str = "http://localhost:6333"
    api_key: SecretStr | None = None

    # Connection settings
    grpc_port: int | None = None
    prefer_grpc: bool = True
    https: bool | None = None

    # Performance settings
    timeout: float = 30.0

    # Collection settings
    default_collection: str = "documents"

    # Vector configuration
    on_disk_vectors: bool = False
    hnsw_config: dict[str, Any] = Field(
        default_factory=lambda: {
            "m": 16,
            "ef_construct": 100,
            "full_scan_threshold": 10000,
            "max_indexing_threads": 0,  # 0 = auto
        }
    )

    # Quantization settings
    enable_quantization: bool = False
    quantization_config: dict[str, Any] = Field(
        default_factory=lambda: {
            "scalar": {
                "type": "int8",
                "quantile": 0.99,
                "always_ram": True,
            },
        }
    )


class QdrantAdapter(VectorBase):
    """Qdrant vector database adapter implementing the lifecycle contract."""

    metadata = AdapterMetadata(
        category="vector",
        provider="qdrant",
        factory="oneiric.adapters.vector.qdrant:QdrantAdapter",
        capabilities=[
            "vector_search",
            "batch_operations",
            "metadata_filtering",
            "quantization",
            "scroll",
            "streaming",
        ],
        stack_level=30,
        priority=500,
        source=CandidateSource.LOCAL_PKG,
        owner="Data Platform",
        requires_secrets=False,
        settings_model=QdrantSettings,
    )

    def __init__(self, settings: QdrantSettings) -> None:
        super().__init__(settings)
        self._settings: QdrantSettings = settings
        self._client: Any | None = None
        self._logger = get_logger("adapter.vector.qdrant").bind(
            domain="adapter",
            key="vector",
            provider="qdrant",
        )

    async def _create_client(self) -> Any:
        """Create Qdrant client."""
        try:
            from qdrant_client import AsyncQdrantClient

            # Build connection parameters
            connection_params: dict[str, Any] = {
                "url": self._settings.url,
                "timeout": self._settings.timeout,
                "prefer_grpc": self._settings.prefer_grpc,
            }

            # Add API key if provided
            if self._settings.api_key:
                connection_params["api_key"] = self._settings.api_key.get_secret_value()

            # Add gRPC port if specified
            if self._settings.grpc_port:
                connection_params["grpc_port"] = self._settings.grpc_port

            # Add HTTPS setting if specified
            if self._settings.https is not None:
                connection_params["https"] = self._settings.https

            # Create async client
            client = AsyncQdrantClient(**connection_params)

            self._logger.debug("qdrant-client-initialized")
            return client
        except ImportError as exc:
            raise LifecycleError(
                "qdrant-client-import-failed: pip install qdrant-client"
            ) from exc
        except Exception as exc:
            raise LifecycleError(f"qdrant-client-creation-failed: {exc}") from exc

    async def _ensure_client(self) -> Any:
        """Ensure Qdrant client is available."""
        if self._client is None:
            self._client = await self._create_client()
        return self._client

    async def init(self) -> None:
        """Initialize Qdrant vector adapter."""
        self._logger.info("qdrant-adapter-init-start")

        try:
            client = await self._ensure_client()

            # Check connection
            health_info = await client.get_cluster_info()
            self._logger.debug("qdrant-cluster-status", status=str(health_info))

            self._logger.info("qdrant-adapter-init-success")
        except Exception as exc:
            self._logger.error("qdrant-adapter-init-failed", error=str(exc))
            raise LifecycleError(f"qdrant-init-failed: {exc}") from exc

    async def _ensure_collection_exists(
        self,
        collection_name: str,
        dimension: int | None = None,
        distance_metric: str = "cosine",
    ) -> bool:
        """Ensure Qdrant collection exists, create if needed."""
        client = await self._ensure_client()

        try:
            # Check if collection exists
            collections = await client.get_collections()
            existing_collections = [col.name for col in collections.collections]

            if collection_name in existing_collections:
                return True

            if dimension is None:
                dimension = self._settings.default_dimension

            # Import required types
            from qdrant_client.models import Distance, VectorParams

            # Map distance metric
            distance_map = {
                "cosine": Distance.COSINE,
                "euclidean": Distance.EUCLID,
                "dot_product": Distance.DOT,
                "manhattan": Distance.MANHATTAN,
            }

            distance = distance_map.get(distance_metric.lower(), Distance.COSINE)

            # Create vector configuration
            vectors_config = VectorParams(
                size=dimension,
                distance=distance,
                on_disk=self._settings.on_disk_vectors,
            )

            # Create HNSW configuration
            from qdrant_client.models import HnswConfigDiff

            hnsw_config = HnswConfigDiff(
                m=self._settings.hnsw_config.get("m", 16),
                ef_construct=self._settings.hnsw_config.get("ef_construct", 100),
                full_scan_threshold=self._settings.hnsw_config.get(
                    "full_scan_threshold",
                    10000,
                ),
                max_indexing_threads=self._settings.hnsw_config.get(
                    "max_indexing_threads",
                    0,
                ),
            )

            # Create quantization config if enabled
            quantization_config = None
            if self._settings.enable_quantization:
                from qdrant_client.models import (
                    ScalarQuantization,
                    ScalarQuantizationConfig,
                    ScalarType,
                )

                quantization_config = ScalarQuantization(
                    scalar=ScalarQuantizationConfig(
                        type=ScalarType.INT8,
                        quantile=self._settings.quantization_config["scalar"].get(
                            "quantile",
                            0.99,
                        ),
                        always_ram=self._settings.quantization_config["scalar"].get(
                            "always_ram",
                            True,
                        ),
                    ),
                )

            # Create collection
            await client.create_collection(
                collection_name=collection_name,
                vectors_config=vectors_config,
                hnsw_config=hnsw_config,
                quantization_config=quantization_config,
            )

            self._logger.info("qdrant-collection-created", collection=collection_name)
            return True

        except Exception as exc:
            self._logger.exception(
                "qdrant-collection-creation-failed",
                collection=collection_name,
                error=str(exc),
            )
            return False

    async def health(self) -> bool:
        """Check if Qdrant is healthy."""
        if not self._client:
            return False

        try:
            # Check if we can get cluster info
            await self._client.get_cluster_info()
            return True
        except Exception as exc:
            self._logger.warning("qdrant-health-check-failed", error=str(exc))
            return False

    async def cleanup(self) -> None:
        """Cleanup Qdrant resources."""
        if self._client:
            try:
                await self._client.close()
            except Exception as exc:
                self._logger.warning("qdrant-cleanup-warning", error=str(exc))
            finally:
                self._client = None

        self._logger.info("qdrant-cleanup-complete")

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        limit: int = 10,
        filter_expr: dict[str, Any] | None = None,
        include_vectors: bool = False,
        **kwargs: Any,
    ) -> list[VectorSearchResult]:
        """Perform vector similarity search in Qdrant."""
        client = await self._ensure_client()
        collection_name = collection or self._settings.default_collection

        try:
            # Build filter
            qdrant_filter = None
            if filter_expr:
                qdrant_filter = self._build_qdrant_filter(filter_expr)

            # Perform search
            search_result = await client.search(
                collection_name=collection_name,
                query_vector=query_vector,
                limit=limit,
                query_filter=qdrant_filter,
                with_payload=True,
                with_vectors=include_vectors,
                score_threshold=kwargs.get("score_threshold"),
            )

            # Convert to VectorSearchResult
            results = []
            for point in search_result:
                result = VectorSearchResult(
                    id=str(point.id),
                    score=float(point.score),
                    metadata=point.payload,
                    vector=point.vector if include_vectors else None,
                )
                results.append(result)

            return results

        except Exception as exc:
            self._logger.exception("qdrant-search-failed", error=str(exc))
            return []

    def _build_qdrant_filter(self, filter_expr: dict[str, Any]) -> Any | None:
        """Build Qdrant filter from filter expression."""
        try:
            from qdrant_client.models import (
                FieldCondition,
                Filter,
                MatchAny,
                MatchValue,
            )

            conditions = []
            for key, value in filter_expr.items():
                if isinstance(value, (str, int, float, bool)):
                    conditions.append(
                        FieldCondition(key=key, match=MatchValue(value=value)),
                    )
                elif isinstance(value, list):
                    conditions.append(
                        FieldCondition(key=key, match=MatchAny(any=value)),
                    )

            if conditions:
                return Filter(must=conditions)

            return None

        except Exception as exc:
            self._logger.warning("qdrant-filter-build-failed", error=str(exc))
            return None

    async def insert(
        self,
        collection: str,
        documents: list[VectorDocument],
        **kwargs: Any,
    ) -> list[str]:
        """Insert documents with vectors into Qdrant."""
        return await self.upsert(collection, documents, **kwargs)

    async def upsert(
        self,
        collection: str,
        documents: list[VectorDocument],
        **kwargs: Any,
    ) -> list[str]:
        """Upsert documents with vectors into Qdrant."""
        client = await self._ensure_client()
        collection_name = collection or self._settings.default_collection

        # Ensure collection exists
        dimension = len(documents[0].vector) if documents else None
        await self._ensure_collection_exists(collection_name, dimension)

        try:
            from qdrant_client.models import PointStruct

            # Prepare points for upsert
            points = []
            document_ids = []

            for doc in documents:
                doc_id = doc.id
                if not doc_id:
                    doc_id = str(uuid_module.uuid4())

                document_ids.append(doc_id)

                point = PointStruct(
                    id=doc_id,
                    vector=doc.vector,
                    payload=doc.metadata,
                )
                points.append(point)

            # Batch upsert
            batch_size = self._settings.batch_size
            for i in range(0, len(points), batch_size):
                batch = points[i : i + batch_size]

                operation_info = await client.upsert(
                    collection_name=collection_name,
                    points=batch,
                    wait=True,  # Wait for operation to complete
                )

                if operation_info.status.name != "COMPLETED":
                    self._logger.warning(
                        "qdrant-upsert-batch-failed",
                        batch_num=i // batch_size + 1,
                        status=operation_info.status.name,
                    )

            return document_ids

        except Exception as exc:
            self._logger.exception("qdrant-upsert-failed", error=str(exc))
            return []

    async def delete(
        self,
        collection: str,
        ids: list[str],
        **kwargs: Any,
    ) -> bool:
        """Delete documents by IDs from Qdrant."""
        client = await self._ensure_client()
        collection_name = collection or self._settings.default_collection

        try:
            from qdrant_client.models import PointIdsList

            # Delete points
            operation_info = await client.delete(
                collection_name=collection_name,
                points_selector=PointIdsList(points=ids),
                wait=True,
            )

            return operation_info.status.name == "COMPLETED"

        except Exception as exc:
            self._logger.exception("qdrant-delete-failed", error=str(exc))
            return False

    async def get(
        self,
        collection: str,
        ids: list[str],
        include_vectors: bool = False,
        **kwargs: Any,
    ) -> list[VectorDocument]:
        """Retrieve documents by IDs from Qdrant."""
        client = await self._ensure_client()
        collection_name = collection or self._settings.default_collection

        try:
            # Retrieve points
            points = await client.retrieve(
                collection_name=collection_name,
                ids=ids,
                with_payload=True,
                with_vectors=include_vectors,
            )

            documents = []
            for point in points:
                doc = VectorDocument(
                    id=str(point.id),
                    vector=point.vector if include_vectors else [],
                    metadata=point.payload,
                )
                documents.append(doc)

            return documents

        except Exception as exc:
            self._logger.exception("qdrant-retrieve-failed", error=str(exc))
            return []

    async def count(
        self,
        collection: str,
        filter_expr: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> int:
        """Count documents in Qdrant collection."""
        client = await self._ensure_client()
        collection_name = collection or self._settings.default_collection

        try:
            # Build filter
            qdrant_filter = None
            if filter_expr:
                qdrant_filter = self._build_qdrant_filter(filter_expr)

            # Count points
            count_result = await client.count(
                collection_name=collection_name,
                count_filter=qdrant_filter,
            )

            return count_result.count

        except Exception as exc:
            self._logger.exception("qdrant-count-failed", error=str(exc))
            return 0

    async def create_collection(
        self,
        name: str,
        dimension: int,
        distance_metric: str = "cosine",
        **kwargs: Any,
    ) -> bool:
        """Create a new collection in Qdrant."""
        return await self._ensure_collection_exists(name, dimension, distance_metric)

    async def delete_collection(
        self,
        name: str,
        **kwargs: Any,
    ) -> bool:
        """Delete a collection in Qdrant."""
        client = await self._ensure_client()

        try:
            await client.delete_collection(collection_name=name)
            return True

        except Exception as exc:
            self._logger.exception("qdrant-collection-delete-failed", error=str(exc))
            return False

    async def list_collections(self, **kwargs: Any) -> list[str]:
        """List all collections in Qdrant."""
        client = await self._ensure_client()

        try:
            collections = await client.get_collections()
            return [col.name for col in collections.collections]

        except Exception as exc:
            self._logger.exception("qdrant-list-collections-failed", error=str(exc))
            return []

    async def scroll(
        self,
        collection: str,
        limit: int = 100,
        offset: str | None = None,
        filter_expr: dict[str, Any] | None = None,
        include_vectors: bool = False,
        **kwargs: Any,
    ) -> tuple[list[VectorDocument], str | None]:
        """Scroll through documents in Qdrant collection."""
        client = await self._ensure_client()
        collection_name = collection or self._settings.default_collection

        try:
            # Build filter
            qdrant_filter = None
            if filter_expr:
                qdrant_filter = self._build_qdrant_filter(filter_expr)

            # Scroll through points
            scroll_result = await client.scroll(
                collection_name=collection_name,
                limit=limit,
                offset=offset,
                scroll_filter=qdrant_filter,
                with_payload=True,
                with_vectors=include_vectors,
            )

            # Convert to VectorDocument
            documents = []
            for point in scroll_result[0]:  # First element is the list of points
                doc = VectorDocument(
                    id=str(point.id),
                    vector=point.vector if include_vectors else [],
                    metadata=point.payload,
                )
                documents.append(doc)

            next_offset = scroll_result[1]  # Second element is the next offset
            return documents, next_offset

        except Exception as exc:
            self._logger.exception("qdrant-scroll-failed", error=str(exc))
            return [], None

    def has_capability(self, capability: str) -> bool:
        """Check if Qdrant adapter supports a specific capability."""
        supported_capabilities = {
            "vector_search",
            "batch_operations",
            "metadata_filtering",
            "scroll",
            "quantization",
            "streaming",
        }
        return capability in supported_capabilities
