"""Pinecone vector database adapter with lifecycle integration."""

from __future__ import annotations

from typing import Any

from pydantic import SecretStr

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource

from .common import VectorBase, VectorBaseSettings, VectorDocument, VectorSearchResult


class PineconeSettings(VectorBaseSettings):
    """Pinecone vector adapter settings."""

    api_key: SecretStr
    environment: str = "us-west1-gcp-free"
    index_name: str = "default"
    serverless: bool = True
    cloud: str = "aws"
    region: str = "us-east-1"

    # Index configuration
    metric: str = "cosine"  # cosine, euclidean, dotproduct
    pod_type: str = "p1.x1"  # For non-serverless indexes
    replicas: int = 1
    shards: int = 1

    # Upsert configuration
    upsert_batch_size: int = 100
    upsert_max_retries: int = 3
    upsert_timeout: float = 30.0


class PineconeAdapter(VectorBase):
    """Pinecone vector database adapter implementing the lifecycle contract."""

    metadata = AdapterMetadata(
        category="vector",
        provider="pinecone",
        factory="oneiric.adapters.vector.pinecone:PineconeAdapter",
        capabilities=[
            "vector_search",
            "batch_operations",
            "metadata_filtering",
            "namespaces",
            "serverless",
        ],
        stack_level=30,
        priority=500,
        source=CandidateSource.LOCAL_PKG,
        owner="Data Platform",
        requires_secrets=True,
        settings_model=PineconeSettings,
    )

    def __init__(self, settings: PineconeSettings) -> None:
        super().__init__(settings)
        self._settings: PineconeSettings = settings
        self._client: Any | None = None
        self._index: Any | None = None
        self._logger = get_logger("adapter.vector.pinecone").bind(
            domain="adapter",
            key="vector",
            provider="pinecone",
        )

    async def _create_client(self) -> Any:
        """Create Pinecone client."""
        try:
            import pinecone

            # Initialize Pinecone client
            pc = pinecone.Pinecone(
                api_key=self._settings.api_key.get_secret_value(),
            )

            self._logger.debug("pinecone-client-initialized")
            return pc
        except ImportError as exc:
            raise LifecycleError(
                "pinecone-client-import-failed: pip install pinecone-client"
            ) from exc
        except Exception as exc:
            raise LifecycleError(f"pinecone-client-creation-failed: {exc}") from exc

    async def _ensure_client(self) -> Any:
        """Ensure Pinecone client is available."""
        if self._client is None:
            self._client = await self._create_client()
        return self._client

    async def _get_index(self) -> Any:
        """Get Pinecone index instance."""
        if self._index is None:
            client = await self._ensure_client()
            self._index = client.Index(self._settings.index_name)
        return self._index

    async def init(self) -> None:
        """Initialize Pinecone vector adapter."""
        self._logger.info(
            "pinecone-adapter-init-start", index=self._settings.index_name
        )

        try:
            client = await self._ensure_client()

            # Check if index exists, create if needed
            try:
                client.describe_index(self._settings.index_name)
                self._logger.debug(
                    "pinecone-index-exists", index=self._settings.index_name
                )
            except Exception:
                self._logger.info(
                    "pinecone-index-not-found-creating", index=self._settings.index_name
                )
                await self._create_default_index()

            # Initialize index reference
            await self._get_index()

            self._logger.info("pinecone-adapter-init-success")
        except Exception as exc:
            self._logger.error("pinecone-adapter-init-failed", error=str(exc))
            raise LifecycleError(f"pinecone-init-failed: {exc}") from exc

    async def _create_default_index(self) -> None:
        """Create default index if it doesn't exist."""
        client = await self._ensure_client()

        try:
            if self._settings.serverless:
                spec = {
                    "serverless": {
                        "cloud": self._settings.cloud,
                        "region": self._settings.region,
                    },
                }
            else:
                spec = {
                    "pod": {
                        "environment": self._settings.environment,
                        "pod_type": self._settings.pod_type,
                        "pods": 1,
                        "replicas": self._settings.replicas,
                        "shards": self._settings.shards,
                    },
                }

            client.create_index(
                name=self._settings.index_name,
                dimension=self._settings.default_dimension,
                metric=self._settings.metric,
                spec=spec,
            )

            self._logger.info("pinecone-index-created", index=self._settings.index_name)
        except Exception as exc:
            raise LifecycleError(f"pinecone-index-creation-failed: {exc}") from exc

    async def health(self) -> bool:
        """Check if Pinecone is healthy."""
        if not self._client or not self._index:
            return False

        try:
            # Pinecone has no health endpoint, check if we can describe index
            stats = self._index.describe_index_stats()
            return stats is not None
        except Exception as exc:
            self._logger.warning("pinecone-health-check-failed", error=str(exc))
            return False

    async def cleanup(self) -> None:
        """Cleanup Pinecone resources."""
        self._client = None
        self._index = None
        self._logger.info("pinecone-cleanup-complete")

    async def search(
        self,
        collection: str,  # In Pinecone, this is namespace
        query_vector: list[float],
        limit: int = 10,
        filter_expr: dict[str, Any] | None = None,
        include_vectors: bool = False,
        **kwargs: Any,
    ) -> list[VectorSearchResult]:
        """Perform vector similarity search in Pinecone."""
        index = await self._get_index()

        try:
            # Build query parameters
            query_params: dict[str, Any] = {
                "vector": query_vector,
                "top_k": limit,
                "include_metadata": True,
                "include_values": include_vectors,
            }

            # Add namespace if collection is specified
            if collection and collection != "default":
                query_params["namespace"] = collection

            # Add filter if provided
            if filter_expr:
                query_params["filter"] = filter_expr

            # Perform query
            response = index.query(**query_params)

            # Convert to VectorSearchResult
            results = []
            for match in response.get("matches", []):
                result = VectorSearchResult(
                    id=match["id"],
                    score=float(match["score"]),
                    metadata=match.get("metadata", {}),
                    vector=match.get("values") if include_vectors else None,
                )
                results.append(result)

            return results

        except Exception as exc:
            self._logger.exception("pinecone-search-failed", error=str(exc))
            return []

    async def insert(
        self,
        collection: str,
        documents: list[VectorDocument],
        **kwargs: Any,
    ) -> list[str]:
        """Insert documents with vectors into Pinecone."""
        return await self.upsert(collection, documents, **kwargs)

    def _prepare_pinecone_vector(
        self, doc: VectorDocument, index: int
    ) -> tuple[str, dict[str, Any]]:
        """Prepare a single document as Pinecone vector. Returns (doc_id, vector_data)."""
        doc_id = doc.id or f"vec_{index}"

        vector_data: dict[str, Any] = {
            "id": doc_id,
            "values": doc.vector,
        }

        if doc.metadata:
            vector_data["metadata"] = doc.metadata

        return doc_id, vector_data

    def _prepare_all_vectors(
        self, documents: list[VectorDocument]
    ) -> tuple[list[str], list[dict[str, Any]]]:
        """Prepare all documents as Pinecone vectors. Returns (doc_ids, vectors)."""
        document_ids: list[str] = []
        vectors: list[dict[str, Any]] = []

        for idx, doc in enumerate(documents):
            doc_id, vector_data = self._prepare_pinecone_vector(doc, idx)
            document_ids.append(doc_id)
            vectors.append(vector_data)

        return document_ids, vectors

    async def _upsert_batch(
        self,
        index: Any,
        batch: list[dict[str, Any]],
        namespace: str | None,
        batch_num: int,
    ) -> None:
        """Upsert a single batch to Pinecone."""
        upsert_params: dict[str, Any] = {"vectors": batch}
        if namespace:
            upsert_params["namespace"] = namespace

        response = index.upsert(**upsert_params)

        if not response.get("upserted_count"):
            self._logger.warning("pinecone-upsert-batch-failed", batch_num=batch_num)

    async def upsert(
        self,
        collection: str,
        documents: list[VectorDocument],
        **kwargs: Any,
    ) -> list[str]:
        """Upsert documents with vectors into Pinecone."""
        index = await self._get_index()

        try:
            # Prepare vectors for upsert
            document_ids, vectors = self._prepare_all_vectors(documents)

            # Batch upsert
            batch_size = self._settings.upsert_batch_size
            namespace = collection if collection != "default" else None

            for i in range(0, len(vectors), batch_size):
                batch = vectors[i : i + batch_size]
                await self._upsert_batch(index, batch, namespace, i // batch_size + 1)

            return document_ids

        except Exception as exc:
            self._logger.exception("pinecone-upsert-failed", error=str(exc))
            return []

    async def delete(
        self,
        collection: str,
        ids: list[str],
        **kwargs: Any,
    ) -> bool:
        """Delete documents by IDs from Pinecone."""
        index = await self._get_index()

        try:
            delete_params: dict[str, Any] = {"ids": ids}
            if collection and collection != "default":
                delete_params["namespace"] = collection

            index.delete(**delete_params)
            return True  # Pinecone delete doesn't return detailed status

        except Exception as exc:
            self._logger.exception("pinecone-delete-failed", error=str(exc))
            return False

    async def get(
        self,
        collection: str,
        ids: list[str],
        include_vectors: bool = False,
        **kwargs: Any,
    ) -> list[VectorDocument]:
        """Retrieve documents by IDs from Pinecone."""
        index = await self._get_index()

        try:
            fetch_params: dict[str, Any] = {
                "ids": ids,
                "include_metadata": True,
                "include_values": include_vectors,
            }

            if collection and collection != "default":
                fetch_params["namespace"] = collection

            response = index.fetch(**fetch_params)

            documents = []
            for doc_id, vector_data in response.get("vectors", {}).items():
                doc = VectorDocument(
                    id=doc_id,
                    vector=vector_data.get("values", []) if include_vectors else [],
                    metadata=vector_data.get("metadata", {}),
                )
                documents.append(doc)

            return documents

        except Exception as exc:
            self._logger.exception("pinecone-fetch-failed", error=str(exc))
            return []

    async def count(
        self,
        collection: str,
        filter_expr: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> int:
        """Count documents in Pinecone namespace."""
        index = await self._get_index()

        try:
            # Pinecone doesn't have a direct count method
            # We need to use describe_index_stats
            describe_params: dict[str, Any] = {}
            if filter_expr:
                describe_params["filter"] = filter_expr

            stats = index.describe_index_stats(**describe_params)

            if collection and collection != "default":
                namespace_stats = stats.get("namespaces", {}).get(collection, {})
                return namespace_stats.get("vector_count", 0)
            return stats.get("total_vector_count", 0)

        except Exception as exc:
            self._logger.exception("pinecone-count-failed", error=str(exc))
            return 0

    async def create_collection(
        self,
        name: str,
        dimension: int,
        distance_metric: str = "cosine",
        **kwargs: Any,
    ) -> bool:
        """Create a new collection (namespace) in Pinecone."""
        # In Pinecone, namespaces are created implicitly when inserting vectors
        # The index itself needs to be created at the account level
        # This method is mainly for compatibility with the base interface
        self._logger.info(
            "pinecone-namespace-implicit",
            message=f"Namespace '{name}' will be created implicitly on first insert",
        )
        return True

    async def delete_collection(
        self,
        name: str,
        **kwargs: Any,
    ) -> bool:
        """Delete a collection (namespace) in Pinecone."""
        index = await self._get_index()

        try:
            # Delete all vectors in the namespace
            if name and name != "default":
                index.delete(delete_all=True, namespace=name)
            else:
                index.delete(delete_all=True)

            return True

        except Exception as exc:
            self._logger.exception("pinecone-namespace-delete-failed", error=str(exc))
            return False

    async def list_collections(self, **kwargs: Any) -> list[str]:
        """List all collections (namespaces) in Pinecone."""
        index = await self._get_index()

        try:
            stats = index.describe_index_stats()
            namespaces = list(stats.get("namespaces", {}).keys())

            # Include default namespace if it has vectors
            if stats.get("total_vector_count", 0) > sum(
                ns.get("vector_count", 0) for ns in stats.get("namespaces", {}).values()
            ):
                namespaces.append("default")

            return namespaces

        except Exception as exc:
            self._logger.exception("pinecone-list-namespaces-failed", error=str(exc))
            return []

    def has_capability(self, capability: str) -> bool:
        """Check if Pinecone adapter supports a specific capability."""
        supported_capabilities = {
            "vector_search",
            "batch_operations",
            "metadata_filtering",
            "namespaces",
            "serverless",
        }
        return capability in supported_capabilities
