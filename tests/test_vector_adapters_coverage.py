"""Coverage-focused tests for Qdrant, AgentDB, and Pinecone vector adapters.

Targets uncovered lines in:
  - oneiric/adapters/vector/qdrant.py   (133 miss, 42.9%)
  - oneiric/adapters/vector/agentdb.py  (118 miss, 24.8%)
  - oneiric/adapters/vector/pinecone.py (102 miss, 50.7%)
"""

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr

from oneiric.adapters.vector.agentdb import AgentDBAdapter, AgentDBSettings
from oneiric.adapters.vector.pinecone import PineconeAdapter, PineconeSettings
from oneiric.adapters.vector.qdrant import QdrantAdapter, QdrantSettings
from oneiric.adapters.vector.vector_types import VectorDocument, VectorSearchResult
from oneiric.core.lifecycle import LifecycleError


# ---------------------------------------------------------------------------
# Shared fakes / helpers
# ---------------------------------------------------------------------------


def _inject_qdrant_models(monkeypatch: pytest.MonkeyPatch) -> None:
    """Register lightweight stubs for qdrant_client and qdrant_client.models."""

    @dataclass
    class MatchValue:
        value: Any

    @dataclass
    class MatchAny:
        any: list[Any]

    @dataclass
    class FieldCondition:
        key: str
        match: Any

    @dataclass
    class Filter:
        must: list[FieldCondition]

    @dataclass
    class VectorParams:
        size: int
        distance: str
        on_disk: bool

    @dataclass
    class HnswConfigDiff:
        m: int
        ef_construct: int
        full_scan_threshold: int
        max_indexing_threads: int

    @dataclass
    class ScalarQuantizationConfig:
        type: str
        quantile: float
        always_ram: bool

    @dataclass
    class ScalarQuantization:
        scalar: ScalarQuantizationConfig

    class ScalarType:
        INT8 = "int8"

    class Distance:
        COSINE = "cosine"
        EUCLID = "euclid"
        DOT = "dot"
        MANHATTAN = "manhattan"

    @dataclass
    class PointStruct:
        id: str
        vector: list[float]
        payload: dict[str, Any]

    @dataclass
    class PointIdsList:
        points: list[str]

    @dataclass
    class FakeCollectionInfo:
        name: str

    @dataclass
    class FakeCollectionsResponse:
        collections: list[FakeCollectionInfo] = field(default_factory=list)

    models = SimpleNamespace(
        FieldCondition=FieldCondition,
        Filter=Filter,
        MatchAny=MatchAny,
        MatchValue=MatchValue,
        Distance=Distance,
        VectorParams=VectorParams,
        HnswConfigDiff=HnswConfigDiff,
        ScalarQuantization=ScalarQuantization,
        ScalarQuantizationConfig=ScalarQuantizationConfig,
        ScalarType=ScalarType,
        PointStruct=PointStruct,
        PointIdsList=PointIdsList,
    )
    monkeypatch.setitem(sys.modules, "qdrant_client.models", models)
    monkeypatch.setitem(
        sys.modules, "qdrant_client", SimpleNamespace(AsyncQdrantClient=object, models=models)
    )


class FakeQdrantClient:
    """Callable stand-in for AsyncQdrantClient."""

    def __init__(
        self,
        *,
        existing_collections: list[str] | None = None,
        search_results: list | None = None,
        scroll_results: tuple[list, str | None] | None = None,
        fail_on: str | None = None,
    ) -> None:
        self._existing = existing_collections or []
        self._search_results = search_results
        self._scroll_results = scroll_results
        self._fail_on = fail_on
        self.created: list[dict[str, Any]] = []
        self.deleted_collections: list[str] = []
        self.closed = False

    async def get_cluster_info(self) -> dict[str, Any]:
        if self._fail_on == "cluster_info":
            raise RuntimeError("cluster unavailable")
        return {"status": "ok"}

    async def get_collections(self) -> Any:
        return SimpleNamespace(
            collections=[SimpleNamespace(name=n) for n in self._existing]
        )

    async def create_collection(self, **kwargs: Any) -> None:
        self.created.append(kwargs)

    async def delete_collection(self, collection_name: str) -> None:
        self.deleted_collections.append(collection_name)

    async def search(self, **kwargs: Any) -> list:
        return self._search_results or []

    async def upsert(self, **kwargs: Any) -> Any:
        return SimpleNamespace(status=SimpleNamespace(name="COMPLETED"))

    async def delete(self, **kwargs: Any) -> Any:
        return SimpleNamespace(status=SimpleNamespace(name="COMPLETED"))

    async def retrieve(self, **kwargs: Any) -> list:
        return []

    async def count(self, **kwargs: Any) -> Any:
        return SimpleNamespace(count=0)

    async def scroll(self, **kwargs: Any) -> tuple[list, str | None]:
        return self._scroll_results or ([], None)

    async def close(self) -> None:
        self.closed = True


class FakeAgentDBMCPClient:
    """Stand-in for MCPClient used by AgentDBAdapter."""

    def __init__(self, *, healthy: bool = True) -> None:
        self._healthy = healthy
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._closed = False

    async def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, args))
        if name == "agentdb_health":
            return {"status": "healthy" if self._healthy else "unhealthy"}
        if name == "agentdb_search":
            return {"results": [{"id": "h1", "score": 0.9, "metadata": {}}]}
        if name == "agentdb_insert":
            return {"ids": ["id-1"]}
        if name == "agentdb_upsert":
            return {"ids": ["id-1"]}
        if name == "agentdb_delete":
            return {"success": True}
        if name == "agentdb_get":
            return {"documents": [{"id": "g1", "metadata": {}}]}
        if name == "agentdb_count":
            return {"count": 5}
        if name == "agentdb_create_collection":
            return {"success": True}
        if name == "agentdb_delete_collection":
            return {"success": True}
        if name == "agentdb_list_collections":
            return {"collections": ["agent_docs", "other"]}
        if name == "agentdb_init":
            return {}
        return {}

    async def close(self) -> None:
        self._closed = True


class FakePineconeIndex:
    """Stand-in for a Pinecone index object."""

    def __init__(self) -> None:
        self.queries: list[dict] = []
        self.upserts: list[dict] = []
        self.deletes: list[dict] = []
        self.fetches: list[dict] = []

    def query(self, **kwargs: Any) -> dict[str, Any]:
        self.queries.append(kwargs)
        return {"matches": []}

    def upsert(self, **kwargs: Any) -> dict[str, Any]:
        self.upserts.append(kwargs)
        return {"upserted_count": len(kwargs.get("vectors", []))}

    def delete(self, **kwargs: Any) -> None:
        self.deletes.append(kwargs)

    def fetch(self, **kwargs: Any) -> dict[str, Any]:
        self.fetches.append(kwargs)
        return {"vectors": {}}

    def describe_index_stats(self, **kwargs: Any) -> dict[str, Any]:
        return {"total_vector_count": 0, "namespaces": {}}


# ===========================================================================
# QDRANT ADAPTER TESTS
# ===========================================================================


class TestQdrantAdapterInit:
    """Cover initialization, settings defaults, and client creation paths."""

    def test_settings_defaults(self) -> None:
        s = QdrantSettings()
        # Note: source has a space in the URL default
        assert "localhost" in s.url
        assert s.api_key is None
        assert s.prefer_grpc is True
        assert s.timeout == 30.0
        assert s.default_collection == "documents"
        assert s.on_disk_vectors is False
        assert s.enable_quantization is False
        assert "m" in s.hnsw_config

    def test_settings_with_api_key(self) -> None:
        s = QdrantSettings(url="http://other:6333", api_key=SecretStr("secret"))
        assert s.api_key.get_secret_value() == "secret"

    def test_adapter_metadata(self) -> None:
        assert QdrantAdapter.metadata.provider == "qdrant"
        assert "vector_search" in QdrantAdapter.metadata.capabilities
        assert QdrantAdapter.metadata.requires_secrets is False

    def test_has_capability(self) -> None:
        adapter = QdrantAdapter(QdrantSettings())
        assert adapter.has_capability("vector_search") is True
        assert adapter.has_capability("scroll") is True
        assert adapter.has_capability("quantization") is True
        assert adapter.has_capability("streaming") is True
        assert adapter.has_capability("batch_operations") is True
        assert adapter.has_capability("metadata_filtering") is True
        assert adapter.has_capability("unknown") is False


class TestQdrantCreateClient:
    """Cover _create_client with and without credentials."""

    @pytest.mark.asyncio
    async def test_create_client_basic(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)

        fake_client = FakeQdrantClient()
        init_calls: list[dict] = []

        def fake_init(**kwargs: Any) -> FakeQdrantClient:
            init_calls.append(kwargs)
            return fake_client

        monkeypatch.setitem(
            sys.modules,
            "qdrant_client",
            SimpleNamespace(AsyncQdrantClient=fake_init, models=SimpleNamespace()),
        )

        adapter = QdrantAdapter(QdrantSettings())
        client = await adapter._create_client()

        assert client is fake_client
        assert len(init_calls) == 1
        assert "localhost" in init_calls[0]["url"]
        assert init_calls[0]["prefer_grpc"] is True
        assert init_calls[0]["timeout"] == 30.0
        assert "api_key" not in init_calls[0]

    @pytest.mark.asyncio
    async def test_create_client_with_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)

        fake_client = FakeQdrantClient()
        init_calls: list[dict] = []

        def fake_init(**kwargs: Any) -> FakeQdrantClient:
            init_calls.append(kwargs)
            return fake_client

        monkeypatch.setitem(
            sys.modules,
            "qdrant_client",
            SimpleNamespace(AsyncQdrantClient=fake_init, models=SimpleNamespace()),
        )

        adapter = QdrantAdapter(
            QdrantSettings(api_key=SecretStr("my-key"), grpc_port=6334, https=True)
        )
        await adapter._create_client()

        assert init_calls[0]["api_key"] == "my-key"
        assert init_calls[0]["grpc_port"] == 6334
        assert init_calls[0]["https"] is True

    @pytest.mark.asyncio
    async def test_create_client_import_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ImportError from missing qdrant_client should raise LifecycleError."""

        def _raise_import(*args: Any, **kwargs: Any) -> Any:
            raise ImportError("no module")

        monkeypatch.setitem(
            sys.modules,
            "qdrant_client",
            SimpleNamespace(AsyncQdrantClient=_raise_import, models=SimpleNamespace()),
        )

        adapter = QdrantAdapter(QdrantSettings())
        with pytest.raises(LifecycleError, match="qdrant-client-import-failed"):
            await adapter._create_client()

    @pytest.mark.asyncio
    async def test_create_client_runtime_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Generic exception during client creation should raise LifecycleError."""

        def _raise_runtime(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("connection refused")

        monkeypatch.setitem(
            sys.modules,
            "qdrant_client",
            SimpleNamespace(AsyncQdrantClient=_raise_runtime, models=SimpleNamespace()),
        )

        adapter = QdrantAdapter(QdrantSettings())
        with pytest.raises(LifecycleError, match="qdrant-client-creation-failed"):
            await adapter._create_client()


class TestQdrantEnsureClient:
    """Cover _ensure_client caching behaviour."""

    @pytest.mark.asyncio
    async def test_ensure_client_creates_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)

        fake_client = FakeQdrantClient()
        call_count = 0

        def fake_init(**kwargs: Any) -> FakeQdrantClient:
            nonlocal call_count
            call_count += 1
            return fake_client

        monkeypatch.setitem(
            sys.modules,
            "qdrant_client",
            SimpleNamespace(AsyncQdrantClient=fake_init, models=SimpleNamespace()),
        )

        adapter = QdrantAdapter(QdrantSettings())
        c1 = await adapter._ensure_client()
        c2 = await adapter._ensure_client()
        assert c1 is c2
        assert call_count == 1


class TestQdrantInit:
    """Cover init success and failure paths."""

    @pytest.mark.asyncio
    async def test_init_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)

        fake_client = FakeQdrantClient()

        def fake_init(**kwargs: Any) -> FakeQdrantClient:
            return fake_client

        monkeypatch.setitem(
            sys.modules,
            "qdrant_client",
            SimpleNamespace(AsyncQdrantClient=fake_init, models=SimpleNamespace()),
        )

        adapter = QdrantAdapter(QdrantSettings())
        await adapter.init()
        assert adapter._client is fake_client

    @pytest.mark.asyncio
    async def test_init_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)

        fake_client = FakeQdrantClient(fail_on="cluster_info")

        def fake_init(**kwargs: Any) -> FakeQdrantClient:
            return fake_client

        monkeypatch.setitem(
            sys.modules,
            "qdrant_client",
            SimpleNamespace(AsyncQdrantClient=fake_init, models=SimpleNamespace()),
        )

        adapter = QdrantAdapter(QdrantSettings())
        with pytest.raises(LifecycleError, match="qdrant-init-failed"):
            await adapter.init()


class TestQdrantHealth:
    """Cover health check with/without client."""

    @pytest.mark.asyncio
    async def test_health_no_client(self) -> None:
        adapter = QdrantAdapter(QdrantSettings())
        assert await adapter.health() is False

    @pytest.mark.asyncio
    async def test_health_success(self) -> None:
        adapter = QdrantAdapter(QdrantSettings())
        adapter._client = FakeQdrantClient()
        assert await adapter.health() is True

    @pytest.mark.asyncio
    async def test_health_failure(self) -> None:
        adapter = QdrantAdapter(QdrantSettings())
        adapter._client = FakeQdrantClient(fail_on="cluster_info")
        assert await adapter.health() is False


class TestQdrantCleanup:
    """Cover cleanup with and without errors."""

    @pytest.mark.asyncio
    async def test_cleanup_no_client(self) -> None:
        adapter = QdrantAdapter(QdrantSettings())
        adapter._client = None
        await adapter.cleanup()  # should not raise

    @pytest.mark.asyncio
    async def test_cleanup_success(self) -> None:
        adapter = QdrantAdapter(QdrantSettings())
        adapter._client = FakeQdrantClient()
        await adapter.cleanup()
        assert adapter._client is None

    @pytest.mark.asyncio
    async def test_cleanup_close_error(self) -> None:
        class BrokenClient:
            async def close(self) -> None:
                raise RuntimeError("close failed")

        adapter = QdrantAdapter(QdrantSettings())
        adapter._client = BrokenClient()
        await adapter.cleanup()  # should not raise, logs warning
        assert adapter._client is None


class TestQdrantSearch:
    """Cover search with filters, score_threshold, and error handling."""

    @pytest.mark.asyncio
    async def test_search_empty_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)
        adapter = QdrantAdapter(QdrantSettings())
        adapter._client = FakeQdrantClient(search_results=[])
        results = await adapter.search("col", [0.1, 0.2])
        assert results == []

    @pytest.mark.asyncio
    async def test_search_with_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)

        point = SimpleNamespace(
            id="p1", score=0.85, payload={"k": "v"}, vector=[1.0, 2.0]
        )
        adapter = QdrantAdapter(QdrantSettings())
        adapter._client = FakeQdrantClient(search_results=[point])

        results = await adapter.search("col", [0.1], include_vectors=True)
        assert len(results) == 1
        assert results[0].id == "p1"
        assert results[0].score == 0.85
        assert results[0].metadata == {"k": "v"}
        assert results[0].vector == [1.0, 2.0]

    @pytest.mark.asyncio
    async def test_search_without_vectors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)

        point = SimpleNamespace(
            id="p1", score=0.85, payload={}, vector=[1.0]
        )
        adapter = QdrantAdapter(QdrantSettings())
        adapter._client = FakeQdrantClient(search_results=[point])

        results = await adapter.search("col", [0.1], include_vectors=False)
        assert results[0].vector is None

    @pytest.mark.asyncio
    async def test_search_uses_default_collection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)
        adapter = QdrantAdapter(QdrantSettings(default_collection="my_default"))
        adapter._client = FakeQdrantClient(search_results=[])
        # Passing empty string should fall back to default_collection
        results = await adapter.search("", [0.1])
        assert results == []

    @pytest.mark.asyncio
    async def test_search_error_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)

        class FailingClient:
            async def search(self, **kwargs: Any) -> Any:
                raise RuntimeError("search exploded")

        adapter = QdrantAdapter(QdrantSettings())
        adapter._client = FailingClient()
        results = await adapter.search("col", [0.1])
        assert results == []


class TestQdrantBuildFilter:
    """Cover _build_qdrant_filter for various value types."""

    def test_filter_string_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)
        adapter = QdrantAdapter(QdrantSettings())
        f = adapter._build_qdrant_filter({"status": "active"})
        assert f is not None
        assert len(f.must) == 1

    def test_filter_numeric_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)
        adapter = QdrantAdapter(QdrantSettings())
        f = adapter._build_qdrant_filter({"age": 25})
        assert f is not None

    def test_filter_bool_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)
        adapter = QdrantAdapter(QdrantSettings())
        f = adapter._build_qdrant_filter({"active": True})
        assert f is not None

    def test_filter_list_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)
        adapter = QdrantAdapter(QdrantSettings())
        f = adapter._build_qdrant_filter({"tags": ["a", "b"]})
        assert f is not None

    def test_filter_empty_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)
        adapter = QdrantAdapter(QdrantSettings())
        assert adapter._build_qdrant_filter({}) is None

    def test_filter_exception_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Don't inject models -- the import inside _build_qdrant_filter will fail
        adapter = QdrantAdapter(QdrantSettings())
        result = adapter._build_qdrant_filter({"key": "val"})
        assert result is None


class TestQdrantUpsert:
    """Cover upsert, including batch splitting and error handling."""

    @pytest.mark.asyncio
    async def test_upsert_with_ids(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)
        adapter = QdrantAdapter(QdrantSettings())
        adapter._client = FakeQdrantClient(existing_collections=["col"])

        docs = [VectorDocument(id="d1", vector=[0.1]), VectorDocument(id="d2", vector=[0.2])]
        ids = await adapter.upsert("col", docs)
        assert ids == ["d1", "d2"]

    @pytest.mark.asyncio
    async def test_upsert_generates_uuid_when_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _inject_qdrant_models(monkeypatch)
        adapter = QdrantAdapter(QdrantSettings())
        adapter._client = FakeQdrantClient(existing_collections=["col"])

        docs = [VectorDocument(id=None, vector=[0.1])]
        ids = await adapter.upsert("col", docs)
        assert len(ids) == 1
        # Verify it's a valid UUID string
        uuid.UUID(ids[0])  # raises if invalid

    @pytest.mark.asyncio
    async def test_upsert_empty_docs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)
        adapter = QdrantAdapter(QdrantSettings())
        adapter._client = FakeQdrantClient(existing_collections=["col"])
        ids = await adapter.upsert("col", [])
        assert ids == []

    @pytest.mark.asyncio
    async def test_upsert_batch_splitting(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)
        adapter = QdrantAdapter(QdrantSettings(batch_size=2))
        adapter._client = FakeQdrantClient(existing_collections=["col"])

        docs = [
            VectorDocument(id=f"d{i}", vector=[0.1])
            for i in range(5)
        ]
        ids = await adapter.upsert("col", docs)
        assert len(ids) == 5

    @pytest.mark.asyncio
    async def test_upsert_error_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)

        class FailClient:
            async def get_collections(self) -> Any:
                raise RuntimeError("fail")

        adapter = QdrantAdapter(QdrantSettings())
        adapter._client = FailClient()
        ids = await adapter.upsert("col", [VectorDocument(id="d1", vector=[0.1])])
        assert ids == []

    @pytest.mark.asyncio
    async def test_insert_delegates_to_upsert(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)
        adapter = QdrantAdapter(QdrantSettings())
        adapter._client = FakeQdrantClient(existing_collections=["col"])

        docs = [VectorDocument(id="d1", vector=[0.1])]
        ids = await adapter.insert("col", docs)
        assert ids == ["d1"]


class TestQdrantDelete:
    """Cover delete success and failure."""

    @pytest.mark.asyncio
    async def test_delete_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)
        adapter = QdrantAdapter(QdrantSettings())
        adapter._client = FakeQdrantClient()
        assert await adapter.delete("col", ["id1", "id2"]) is True

    @pytest.mark.asyncio
    async def test_delete_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)

        class FailClient:
            async def delete(self, **kwargs: Any) -> Any:
                raise RuntimeError("delete failed")

        adapter = QdrantAdapter(QdrantSettings())
        adapter._client = FailClient()
        assert await adapter.delete("col", ["id1"]) is False


class TestQdrantGet:
    """Cover retrieve / get."""

    @pytest.mark.asyncio
    async def test_get_with_vectors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)

        point = SimpleNamespace(id="g1", vector=[0.5], payload={"k": "v"})
        client = FakeQdrantClient()

        async def fake_retrieve(**kwargs: Any) -> list:
            return [point]

        client.retrieve = fake_retrieve
        adapter = QdrantAdapter(QdrantSettings())
        adapter._client = client

        docs = await adapter.get("col", ["g1"], include_vectors=True)
        assert len(docs) == 1
        assert docs[0].vector == [0.5]

    @pytest.mark.asyncio
    async def test_get_without_vectors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)

        point = SimpleNamespace(id="g1", vector=[0.5], payload={})
        client = FakeQdrantClient()

        async def fake_retrieve(**kwargs: Any) -> list:
            return [point]

        client.retrieve = fake_retrieve
        adapter = QdrantAdapter(QdrantSettings())
        adapter._client = client

        docs = await adapter.get("col", ["g1"], include_vectors=False)
        assert docs[0].vector == []

    @pytest.mark.asyncio
    async def test_get_error_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)

        class FailClient:
            async def retrieve(self, **kwargs: Any) -> Any:
                raise RuntimeError("retrieve failed")

        adapter = QdrantAdapter(QdrantSettings())
        adapter._client = FailClient()
        assert await adapter.get("col", ["id1"]) == []


class TestQdrantCount:
    """Cover count with and without filters."""

    @pytest.mark.asyncio
    async def test_count_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)
        adapter = QdrantAdapter(QdrantSettings())
        adapter._client = FakeQdrantClient()
        assert await adapter.count("col") == 0

    @pytest.mark.asyncio
    async def test_count_with_filter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)
        adapter = QdrantAdapter(QdrantSettings())
        adapter._client = FakeQdrantClient()
        assert await adapter.count("col", {"status": "active"}) == 0

    @pytest.mark.asyncio
    async def test_count_error_returns_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)

        class FailClient:
            async def count(self, **kwargs: Any) -> Any:
                raise RuntimeError("count failed")

        adapter = QdrantAdapter(QdrantSettings())
        adapter._client = FailClient()
        assert await adapter.count("col") == 0


class TestQdrantEnsureCollectionExists:
    """Cover _ensure_collection_exists including creation and quantization."""

    @pytest.mark.asyncio
    async def test_collection_already_exists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)
        adapter = QdrantAdapter(QdrantSettings())
        adapter._client = FakeQdrantClient(existing_collections=["mycol"])
        assert await adapter._ensure_collection_exists("mycol") is True
        assert len(adapter._client.created) == 0

    @pytest.mark.asyncio
    async def test_collection_created_without_quantization(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _inject_qdrant_models(monkeypatch)
        adapter = QdrantAdapter(QdrantSettings(enable_quantization=False))
        adapter._client = FakeQdrantClient(existing_collections=[])

        result = await adapter._ensure_collection_exists("newcol", dimension=128)
        assert result is True
        assert len(adapter._client.created) == 1
        call = adapter._client.created[0]
        assert call["collection_name"] == "newcol"
        assert call["quantization_config"] is None

    @pytest.mark.asyncio
    async def test_collection_created_with_quantization(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _inject_qdrant_models(monkeypatch)
        adapter = QdrantAdapter(QdrantSettings(enable_quantization=True))
        adapter._client = FakeQdrantClient(existing_collections=[])

        result = await adapter._ensure_collection_exists("newcol", dimension=256)
        assert result is True
        call = adapter._client.created[0]
        assert call["quantization_config"] is not None

    @pytest.mark.asyncio
    async def test_collection_creation_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _inject_qdrant_models(monkeypatch)

        class FailClient:
            async def get_collections(self) -> Any:
                return SimpleNamespace(collections=[])

            async def create_collection(self, **kwargs: Any) -> None:
                raise RuntimeError("creation failed")

        adapter = QdrantAdapter(QdrantSettings())
        adapter._client = FailClient()
        assert await adapter._ensure_collection_exists("failcol") is False

    @pytest.mark.asyncio
    async def test_collection_uses_default_dimension(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _inject_qdrant_models(monkeypatch)
        adapter = QdrantAdapter(QdrantSettings(default_dimension=512))
        adapter._client = FakeQdrantClient(existing_collections=[])

        await adapter._ensure_collection_exists("newcol", dimension=None)
        call = adapter._client.created[0]
        # default_dimension should be used since dimension=None
        assert call["vectors_config"].size == 512


class TestQdrantDistanceMetrics:
    """Cover distance metric mapping."""

    @pytest.mark.asyncio
    async def test_cosine_metric(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)
        adapter = QdrantAdapter(QdrantSettings())
        adapter._client = FakeQdrantClient(existing_collections=[])

        await adapter._ensure_collection_exists("col", dimension=64, distance_metric="cosine")
        call = adapter._client.created[0]
        assert call["vectors_config"].distance == "cosine"

    @pytest.mark.asyncio
    async def test_euclidean_metric(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)
        adapter = QdrantAdapter(QdrantSettings())
        adapter._client = FakeQdrantClient(existing_collections=[])

        await adapter._ensure_collection_exists(
            "col", dimension=64, distance_metric="euclidean"
        )
        call = adapter._client.created[0]
        assert call["vectors_config"].distance == "euclid"

    @pytest.mark.asyncio
    async def test_dot_product_metric(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)
        adapter = QdrantAdapter(QdrantSettings())
        adapter._client = FakeQdrantClient(existing_collections=[])

        await adapter._ensure_collection_exists(
            "col", dimension=64, distance_metric="dot_product"
        )
        call = adapter._client.created[0]
        assert call["vectors_config"].distance == "dot"

    @pytest.mark.asyncio
    async def test_manhattan_metric(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)
        adapter = QdrantAdapter(QdrantSettings())
        adapter._client = FakeQdrantClient(existing_collections=[])

        await adapter._ensure_collection_exists(
            "col", dimension=64, distance_metric="manhattan"
        )
        call = adapter._client.created[0]
        assert call["vectors_config"].distance == "manhattan"

    @pytest.mark.asyncio
    async def test_unknown_metric_defaults_to_cosine(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _inject_qdrant_models(monkeypatch)
        adapter = QdrantAdapter(QdrantSettings())
        adapter._client = FakeQdrantClient(existing_collections=[])

        await adapter._ensure_collection_exists(
            "col", dimension=64, distance_metric="unknown_metric"
        )
        call = adapter._client.created[0]
        assert call["vectors_config"].distance == "cosine"


class TestQdrantCreateDeleteListCollections:
    """Cover create_collection, delete_collection, list_collections."""

    @pytest.mark.asyncio
    async def test_create_collection_delegates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)
        adapter = QdrantAdapter(QdrantSettings())
        adapter._client = FakeQdrantClient(existing_collections=[])

        result = await adapter.create_collection("newcol", 128)
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_collection_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)
        adapter = QdrantAdapter(QdrantSettings())
        adapter._client = FakeQdrantClient()
        assert await adapter.delete_collection("col") is True
        assert "col" in adapter._client.deleted_collections

    @pytest.mark.asyncio
    async def test_delete_collection_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)

        class FailClient:
            async def delete_collection(self, **kwargs: Any) -> None:
                raise RuntimeError("delete failed")

        adapter = QdrantAdapter(QdrantSettings())
        adapter._client = FailClient()
        assert await adapter.delete_collection("col") is False

    @pytest.mark.asyncio
    async def test_list_collections_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)
        adapter = QdrantAdapter(QdrantSettings())
        adapter._client = FakeQdrantClient(existing_collections=["c1", "c2"])
        assert await adapter.list_collections() == ["c1", "c2"]

    @pytest.mark.asyncio
    async def test_list_collections_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)

        class FailClient:
            async def get_collections(self) -> Any:
                raise RuntimeError("list failed")

        adapter = QdrantAdapter(QdrantSettings())
        adapter._client = FailClient()
        assert await adapter.list_collections() == []


class TestQdrantScroll:
    """Cover scroll pagination."""

    @pytest.mark.asyncio
    async def test_scroll_with_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)

        point = SimpleNamespace(id="s1", vector=[0.3], payload={})
        adapter = QdrantAdapter(QdrantSettings())
        adapter._client = FakeQdrantClient(
            scroll_results=([point], "next_offset")
        )

        docs, offset = await adapter.scroll("col", include_vectors=True)
        assert len(docs) == 1
        assert docs[0].id == "s1"
        assert docs[0].vector == [0.3]
        assert offset == "next_offset"

    @pytest.mark.asyncio
    async def test_scroll_no_more_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)
        adapter = QdrantAdapter(QdrantSettings())
        adapter._client = FakeQdrantClient(scroll_results=([], None))

        docs, offset = await adapter.scroll("col")
        assert docs == []
        assert offset is None

    @pytest.mark.asyncio
    async def test_scroll_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)

        class FailClient:
            async def scroll(self, **kwargs: Any) -> Any:
                raise RuntimeError("scroll failed")

        adapter = QdrantAdapter(QdrantSettings())
        adapter._client = FailClient()
        docs, offset = await adapter.scroll("col")
        assert docs == []
        assert offset is None


class TestQdrantOnDiskVectors:
    """Cover on_disk_vectors setting in collection creation."""

    @pytest.mark.asyncio
    async def test_on_disk_vectors_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _inject_qdrant_models(monkeypatch)
        adapter = QdrantAdapter(QdrantSettings(on_disk_vectors=True))
        adapter._client = FakeQdrantClient(existing_collections=[])

        await adapter._ensure_collection_exists("col", dimension=64)
        call = adapter._client.created[0]
        assert call["vectors_config"].on_disk is True


# ===========================================================================
# AGENTDB ADAPTER TESTS
# ===========================================================================


class TestAgentDBSettingsDefaults:
    """Cover AgentDBSettings defaults and metadata."""

    def test_settings_defaults(self) -> None:
        s = AgentDBSettings()
        assert s.mcp_server_url == "stdio://agentdb"
        assert s.mcp_timeout == 30.0
        assert s.storage_path is None
        assert s.in_memory is True
        assert s.sync_enabled is False
        assert s.default_collection == "agent_memory"
        assert s.collection_prefix == "agent_"
        assert s.default_dimension == 1536
        assert s.default_distance_metric == "cosine"
        assert s.cache_size_mb == 256
        assert s.max_connections == 10

    def test_adapter_metadata(self) -> None:
        assert AgentDBAdapter.metadata.provider == "agentdb"
        assert "vector_search" in AgentDBAdapter.metadata.capabilities
        assert "quic_sync" in AgentDBAdapter.metadata.capabilities
        assert AgentDBAdapter.metadata.requires_secrets is False

    def test_has_capability(self) -> None:
        adapter = AgentDBAdapter(AgentDBSettings())
        assert adapter.has_capability("vector_search") is True
        assert adapter.has_capability("batch_operations") is True
        assert adapter.has_capability("metadata_filtering") is True
        assert adapter.has_capability("real_time") is True
        assert adapter.has_capability("quic_sync") is True
        assert adapter.has_capability("agent_optimized") is True
        assert adapter.has_capability("unknown") is False


class TestAgentDBCreateClient:
    """Cover _create_client success and failure."""

    @pytest.mark.asyncio
    async def test_create_client_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_mcp = FakeAgentDBMCPClient()

        class FakeMCPClient:
            def __init__(self, **kwargs: Any) -> None:
                pass

            async def call_tool(self, name: str, args: dict) -> dict:
                return await fake_mcp.call_tool(name, args)

        monkeypatch.setitem(
            sys.modules, "mcp_common.client", SimpleNamespace(MCPClient=FakeMCPClient)
        )

        adapter = AgentDBAdapter(AgentDBSettings())
        client = await adapter._create_client()
        assert client is not None

    @pytest.mark.asyncio
    async def test_create_client_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class FailMCPClient:
            def __init__(self, **kwargs: Any) -> None:
                raise RuntimeError("connection refused")

        monkeypatch.setitem(
            sys.modules, "mcp_common.client", SimpleNamespace(MCPClient=FailMCPClient)
        )

        adapter = AgentDBAdapter(AgentDBSettings())
        with pytest.raises(LifecycleError, match="Failed to initialize AgentDB adapter"):
            await adapter._create_client()

    @pytest.mark.asyncio
    async def test_ensure_client_caches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        call_count = 0

        class CountingMCPClient:
            def __init__(self, **kwargs: Any) -> None:
                nonlocal call_count
                call_count += 1

            async def call_tool(self, name: str, args: dict) -> dict:
                return {}

        monkeypatch.setitem(
            sys.modules,
            "mcp_common.client",
            SimpleNamespace(MCPClient=CountingMCPClient),
        )

        adapter = AgentDBAdapter(AgentDBSettings())
        c1 = await adapter._ensure_client()
        c2 = await adapter._ensure_client()
        assert c1 is c2
        assert call_count == 1


class TestAgentDBInit:
    """Cover init success, health failure, and exception propagation."""

    @pytest.mark.asyncio
    async def test_init_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_mcp = FakeAgentDBMCPClient(healthy=True)

        class FakeMCPClient:
            def __init__(self, **kwargs: Any) -> None:
                pass

            async def call_tool(self, name: str, args: dict) -> dict:
                return await fake_mcp.call_tool(name, args)

        monkeypatch.setitem(
            sys.modules, "mcp_common.client", SimpleNamespace(MCPClient=FakeMCPClient)
        )

        adapter = AgentDBAdapter(AgentDBSettings())
        await adapter.init()  # should not raise

    @pytest.mark.asyncio
    async def test_init_health_check_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_mcp = FakeAgentDBMCPClient(healthy=False)

        class FakeMCPClient:
            def __init__(self, **kwargs: Any) -> None:
                pass

            async def call_tool(self, name: str, args: dict) -> dict:
                return await fake_mcp.call_tool(name, args)

        monkeypatch.setitem(
            sys.modules, "mcp_common.client", SimpleNamespace(MCPClient=FakeMCPClient)
        )

        adapter = AgentDBAdapter(AgentDBSettings())
        with pytest.raises(LifecycleError, match="health check failed"):
            await adapter.init()


class TestAgentDBHealth:
    """Cover health with and without client."""

    @pytest.mark.asyncio
    async def test_health_no_client(self) -> None:
        adapter = AgentDBAdapter(AgentDBSettings())
        # _ensure_client will fail since no MCPClient is injected
        result = await adapter.health()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_healthy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_mcp = FakeAgentDBMCPClient(healthy=True)

        class FakeMCPClient:
            def __init__(self, **kwargs: Any) -> None:
                pass

            async def call_tool(self, name: str, args: dict) -> dict:
                return await fake_mcp.call_tool(name, args)

        monkeypatch.setitem(
            sys.modules, "mcp_common.client", SimpleNamespace(MCPClient=FakeMCPClient)
        )

        adapter = AgentDBAdapter(AgentDBSettings())
        adapter._client = await adapter._create_client()
        assert await adapter.health() is True

    @pytest.mark.asyncio
    async def test_health_unhealthy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_mcp = FakeAgentDBMCPClient(healthy=False)

        class FakeMCPClient:
            def __init__(self, **kwargs: Any) -> None:
                pass

            async def call_tool(self, name: str, args: dict) -> dict:
                return await fake_mcp.call_tool(name, args)

        monkeypatch.setitem(
            sys.modules, "mcp_common.client", SimpleNamespace(MCPClient=FakeMCPClient)
        )

        adapter = AgentDBAdapter(AgentDBSettings())
        adapter._client = await adapter._create_client()
        assert await adapter.health() is False


class TestAgentDBCleanup:
    """Cover cleanup with and without MCP client."""

    @pytest.mark.asyncio
    async def test_cleanup_with_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_mcp = FakeAgentDBMCPClient()

        class FakeMCPClient:
            def __init__(self, **kwargs: Any) -> None:
                pass

            async def call_tool(self, name: str, args: dict) -> dict:
                return await fake_mcp.call_tool(name, args)

            async def close(self) -> None:
                fake_mcp._closed = True

        monkeypatch.setitem(
            sys.modules, "mcp_common.client", SimpleNamespace(MCPClient=FakeMCPClient)
        )

        adapter = AgentDBAdapter(AgentDBSettings())
        adapter._mcp_client = FakeMCPClient()
        adapter._client = adapter._mcp_client
        await adapter.cleanup()
        assert adapter._mcp_client is None
        assert adapter._client is None

    @pytest.mark.asyncio
    async def test_cleanup_no_client(self) -> None:
        adapter = AgentDBAdapter(AgentDBSettings())
        adapter._mcp_client = None
        adapter._client = None
        await adapter.cleanup()  # should not raise

    @pytest.mark.asyncio
    async def test_cleanup_close_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class BrokenMCPClient:
            async def close(self) -> None:
                raise RuntimeError("close failed")

        adapter = AgentDBAdapter(AgentDBSettings())
        adapter._mcp_client = BrokenMCPClient()
        await adapter.cleanup()  # should not raise, logs warning


class TestAgentDBSearch:
    """Cover search with collection prefix, filters, and error handling."""

    @pytest.mark.asyncio
    async def test_search_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_mcp = FakeAgentDBMCPClient()

        class FakeMCPClient:
            def __init__(self, **kwargs: Any) -> None:
                pass

            async def call_tool(self, name: str, args: dict) -> dict:
                return await fake_mcp.call_tool(name, args)

        monkeypatch.setitem(
            sys.modules, "mcp_common.client", SimpleNamespace(MCPClient=FakeMCPClient)
        )

        adapter = AgentDBAdapter(AgentDBSettings())
        adapter._client = FakeMCPClient()

        results = await adapter.search("docs", [0.1, 0.2], limit=5)
        assert len(results) == 1
        assert results[0].id == "h1"
        assert results[0].score == 0.9

        # Verify collection prefix was applied
        call = fake_mcp.calls[-1]
        assert call[1]["collection"] == "agent_docs"

    @pytest.mark.asyncio
    async def test_search_with_include_vectors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_mcp = FakeAgentDBMCPClient()

        class FakeMCPClient:
            def __init__(self, **kwargs: Any) -> None:
                pass

            async def call_tool(self, name: str, args: dict) -> dict:
                args_copy = dict(args)
                if name == "agentdb_search":
                    return {
                        "results": [
                            {
                                "id": "v1",
                                "score": 0.8,
                                "metadata": {},
                                "vector": [1.0, 2.0],
                            }
                        ]
                    }
                return {}

        monkeypatch.setitem(
            sys.modules, "mcp_common.client", SimpleNamespace(MCPClient=FakeMCPClient)
        )

        adapter = AgentDBAdapter(AgentDBSettings())
        adapter._client = FakeMCPClient()

        results = await adapter.search("docs", [0.1], include_vectors=True)
        assert results[0].vector == [1.0, 2.0]

    @pytest.mark.asyncio
    async def test_search_error_reraises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class FailMCPClient:
            async def call_tool(self, name: str, args: dict) -> dict:
                raise RuntimeError("search failed")

        adapter = AgentDBAdapter(AgentDBSettings())
        adapter._client = FailMCPClient()

        with pytest.raises(RuntimeError, match="search failed"):
            await adapter.search("docs", [0.1])


class TestAgentDBInsert:
    """Cover insert with collection prefix."""

    @pytest.mark.asyncio
    async def test_insert_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_mcp = FakeAgentDBMCPClient()

        class FakeMCPClient:
            def __init__(self, **kwargs: Any) -> None:
                pass

            async def call_tool(self, name: str, args: dict) -> dict:
                return await fake_mcp.call_tool(name, args)

        monkeypatch.setitem(
            sys.modules, "mcp_common.client", SimpleNamespace(MCPClient=FakeMCPClient)
        )

        adapter = AgentDBAdapter(AgentDBSettings())
        adapter._client = FakeMCPClient()

        docs = [VectorDocument(id="d1", vector=[0.1, 0.2], metadata={"k": "v"})]
        ids = await adapter.insert("docs", docs)
        assert ids == ["id-1"]

        call = fake_mcp.calls[-1]
        assert call[0] == "agentdb_insert"
        assert call[1]["collection"] == "agent_docs"

    @pytest.mark.asyncio
    async def test_insert_doc_without_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_mcp = FakeAgentDBMCPClient()

        class FakeMCPClient:
            def __init__(self, **kwargs: Any) -> None:
                pass

            async def call_tool(self, name: str, args: dict) -> dict:
                return await fake_mcp.call_tool(name, args)

        monkeypatch.setitem(
            sys.modules, "mcp_common.client", SimpleNamespace(MCPClient=FakeMCPClient)
        )

        adapter = AgentDBAdapter(AgentDBSettings())
        adapter._client = FakeMCPClient()

        docs = [VectorDocument(id=None, vector=[0.1])]
        ids = await adapter.insert("docs", docs)
        assert len(ids) == 1

        # Check that the generated id contains the collection prefix
        inserted_doc = fake_mcp.calls[-1][1]["documents"][0]
        assert "docs_" in inserted_doc["id"]


class TestAgentDBUpsert:
    """Cover upsert."""

    @pytest.mark.asyncio
    async def test_upsert_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_mcp = FakeAgentDBMCPClient()

        class FakeMCPClient:
            def __init__(self, **kwargs: Any) -> None:
                pass

            async def call_tool(self, name: str, args: dict) -> dict:
                return await fake_mcp.call_tool(name, args)

        monkeypatch.setitem(
            sys.modules, "mcp_common.client", SimpleNamespace(MCPClient=FakeMCPClient)
        )

        adapter = AgentDBAdapter(AgentDBSettings())
        adapter._client = FakeMCPClient()

        docs = [VectorDocument(id="u1", vector=[0.1])]
        ids = await adapter.upsert("docs", docs)
        assert ids == ["id-1"]

        call = fake_mcp.calls[-1]
        assert call[0] == "agentdb_upsert"


class TestAgentDBDelete:
    """Cover delete."""

    @pytest.mark.asyncio
    async def test_delete_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_mcp = FakeAgentDBMCPClient()

        class FakeMCPClient:
            def __init__(self, **kwargs: Any) -> None:
                pass

            async def call_tool(self, name: str, args: dict) -> dict:
                return await fake_mcp.call_tool(name, args)

        monkeypatch.setitem(
            sys.modules, "mcp_common.client", SimpleNamespace(MCPClient=FakeMCPClient)
        )

        adapter = AgentDBAdapter(AgentDBSettings())
        adapter._client = FakeMCPClient()

        assert await adapter.delete("docs", ["id1"]) is True
        call = fake_mcp.calls[-1]
        assert call[0] == "agentdb_delete"
        assert call[1]["ids"] == ["id1"]


class TestAgentDBGet:
    """Cover get with and without vectors."""

    @pytest.mark.asyncio
    async def test_get_with_vectors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_mcp = FakeAgentDBMCPClient()

        class FakeMCPClient:
            def __init__(self, **kwargs: Any) -> None:
                pass

            async def call_tool(self, name: str, args: dict) -> dict:
                if name == "agentdb_get":
                    return {
                        "documents": [
                            {"id": "g1", "vector": [1.0], "metadata": {"k": "v"}}
                        ]
                    }
                return {}

        monkeypatch.setitem(
            sys.modules, "mcp_common.client", SimpleNamespace(MCPClient=FakeMCPClient)
        )

        adapter = AgentDBAdapter(AgentDBSettings())
        adapter._client = FakeMCPClient()

        docs = await adapter.get("docs", ["g1"], include_vectors=True)
        assert len(docs) == 1
        assert docs[0].id == "g1"
        assert docs[0].vector == [1.0]
        assert docs[0].metadata == {"k": "v"}

    @pytest.mark.asyncio
    async def test_get_without_vectors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_mcp = FakeAgentDBMCPClient()

        class FakeMCPClient:
            def __init__(self, **kwargs: Any) -> None:
                pass

            async def call_tool(self, name: str, args: dict) -> dict:
                if name == "agentdb_get":
                    return {
                        "documents": [
                            {"id": "g1", "vector": [1.0], "metadata": {}}
                        ]
                    }
                return {}

        monkeypatch.setitem(
            sys.modules, "mcp_common.client", SimpleNamespace(MCPClient=FakeMCPClient)
        )

        adapter = AgentDBAdapter(AgentDBSettings())
        adapter._client = FakeMCPClient()

        docs = await adapter.get("docs", ["g1"], include_vectors=False)
        assert docs[0].vector == []


class TestAgentDBCount:
    """Cover count."""

    @pytest.mark.asyncio
    async def test_count_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_mcp = FakeAgentDBMCPClient()

        class FakeMCPClient:
            def __init__(self, **kwargs: Any) -> None:
                pass

            async def call_tool(self, name: str, args: dict) -> dict:
                return await fake_mcp.call_tool(name, args)

        monkeypatch.setitem(
            sys.modules, "mcp_common.client", SimpleNamespace(MCPClient=FakeMCPClient)
        )

        adapter = AgentDBAdapter(AgentDBSettings())
        adapter._client = FakeMCPClient()

        assert await adapter.count("docs") == 5

    @pytest.mark.asyncio
    async def test_count_with_filter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_mcp = FakeAgentDBMCPClient()

        class FakeMCPClient:
            def __init__(self, **kwargs: Any) -> None:
                pass

            async def call_tool(self, name: str, args: dict) -> dict:
                return await fake_mcp.call_tool(name, args)

        monkeypatch.setitem(
            sys.modules, "mcp_common.client", SimpleNamespace(MCPClient=FakeMCPClient)
        )

        adapter = AgentDBAdapter(AgentDBSettings())
        adapter._client = FakeMCPClient()

        assert await adapter.count("docs", {"status": "active"}) == 5
        call = fake_mcp.calls[-1]
        assert call[1]["filter"] == {"status": "active"}


class TestAgentDBCreateDeleteListCollections:
    """Cover collection management operations."""

    @pytest.mark.asyncio
    async def test_create_collection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_mcp = FakeAgentDBMCPClient()

        class FakeMCPClient:
            def __init__(self, **kwargs: Any) -> None:
                pass

            async def call_tool(self, name: str, args: dict) -> dict:
                return await fake_mcp.call_tool(name, args)

        monkeypatch.setitem(
            sys.modules, "mcp_common.client", SimpleNamespace(MCPClient=FakeMCPClient)
        )

        adapter = AgentDBAdapter(AgentDBSettings())
        adapter._client = FakeMCPClient()

        result = await adapter.create_collection("mycol", 128, "euclidean")
        assert result is True
        call = fake_mcp.calls[-1]
        assert call[0] == "agentdb_create_collection"
        assert call[1]["collection"] == "agent_mycol"
        assert call[1]["dimension"] == 128
        assert call[1]["distance_metric"] == "euclidean"

    @pytest.mark.asyncio
    async def test_delete_collection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_mcp = FakeAgentDBMCPClient()

        class FakeMCPClient:
            def __init__(self, **kwargs: Any) -> None:
                pass

            async def call_tool(self, name: str, args: dict) -> dict:
                return await fake_mcp.call_tool(name, args)

        monkeypatch.setitem(
            sys.modules, "mcp_common.client", SimpleNamespace(MCPClient=FakeMCPClient)
        )

        adapter = AgentDBAdapter(AgentDBSettings())
        adapter._client = FakeMCPClient()

        result = await adapter.delete_collection("mycol")
        assert result is True
        call = fake_mcp.calls[-1]
        assert call[0] == "agentdb_delete_collection"
        assert call[1]["collection"] == "agent_mycol"

    @pytest.mark.asyncio
    async def test_list_collections_strips_prefix(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_mcp = FakeAgentDBMCPClient()

        class FakeMCPClient:
            def __init__(self, **kwargs: Any) -> None:
                pass

            async def call_tool(self, name: str, args: dict) -> dict:
                return await fake_mcp.call_tool(name, args)

        monkeypatch.setitem(
            sys.modules, "mcp_common.client", SimpleNamespace(MCPClient=FakeMCPClient)
        )

        adapter = AgentDBAdapter(AgentDBSettings())
        adapter._client = FakeMCPClient()

        collections = await adapter.list_collections()
        assert "docs" in collections  # "agent_docs" stripped to "docs"
        assert "other" in collections  # "other" has no prefix, kept as-is

    @pytest.mark.asyncio
    async def test_list_collections_error_reraises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class FailMCPClient:
            async def call_tool(self, name: str, args: dict) -> dict:
                raise RuntimeError("list failed")

        adapter = AgentDBAdapter(AgentDBSettings())
        adapter._client = FailMCPClient()

        with pytest.raises(RuntimeError, match="list failed"):
            await adapter.list_collections()


# ===========================================================================
# PINECONE ADAPTER TESTS
# ===========================================================================


class TestPineconeSettingsDefaults:
    """Cover PineconeSettings defaults and metadata."""

    def test_settings_defaults(self) -> None:
        s = PineconeSettings(api_key=SecretStr("key"))
        assert s.environment == "us-west1-gcp-free"
        assert s.index_name == "default"
        assert s.serverless is True
        assert s.cloud == "aws"
        assert s.region == "us-east-1"
        assert s.metric == "cosine"
        assert s.pod_type == "p1.x1"
        assert s.replicas == 1
        assert s.shards == 1
        assert s.upsert_batch_size == 100
        assert s.upsert_max_retries == 3
        assert s.upsert_timeout == 30.0

    def test_adapter_metadata(self) -> None:
        assert PineconeAdapter.metadata.provider == "pinecone"
        assert "vector_search" in PineconeAdapter.metadata.capabilities
        assert "namespaces" in PineconeAdapter.metadata.capabilities
        assert "serverless" in PineconeAdapter.metadata.capabilities
        assert PineconeAdapter.metadata.requires_secrets is True

    def test_has_capability(self) -> None:
        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        assert adapter.has_capability("vector_search") is True
        assert adapter.has_capability("batch_operations") is True
        assert adapter.has_capability("metadata_filtering") is True
        assert adapter.has_capability("namespaces") is True
        assert adapter.has_capability("serverless") is True
        assert adapter.has_capability("unknown") is False


class TestPineconeCreateClient:
    """Cover _create_client with import error and generic error."""

    @pytest.mark.asyncio
    async def test_create_client_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_pc = SimpleNamespace()

        def fake_pinecone_init(*args: Any, **kwargs: Any) -> SimpleNamespace:
            return fake_pc

        monkeypatch.setitem(
            sys.modules,
            "pinecone",
            SimpleNamespace(Pinecone=fake_pinecone_init),
        )

        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        client = await adapter._create_client()
        assert client is fake_pc

    @pytest.mark.asyncio
    async def test_create_client_import_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "pinecone", None)

        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        with pytest.raises(LifecycleError, match="pinecone-client-import-failed"):
            await adapter._create_client()

    @pytest.mark.asyncio
    async def test_create_client_runtime_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_pinecone_init(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("bad api key")

        monkeypatch.setitem(
            sys.modules,
            "pinecone",
            SimpleNamespace(Pinecone=fake_pinecone_init),
        )

        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        with pytest.raises(LifecycleError, match="pinecone-client-creation-failed"):
            await adapter._create_client()


class TestPineconeEnsureClient:
    """Cover _ensure_client caching."""

    @pytest.mark.asyncio
    async def test_ensure_client_caches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_pc = SimpleNamespace()
        call_count = 0

        def fake_pinecone_init(*args: Any, **kwargs: Any) -> SimpleNamespace:
            nonlocal call_count
            call_count += 1
            return fake_pc

        monkeypatch.setitem(
            sys.modules,
            "pinecone",
            SimpleNamespace(Pinecone=fake_pinecone_init),
        )

        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        c1 = await adapter._ensure_client()
        c2 = await adapter._ensure_client()
        assert c1 is c2
        assert call_count == 1


class TestPineconeGetIndex:
    """Cover _get_index caching."""

    @pytest.mark.asyncio
    async def test_get_index_caches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_pc = SimpleNamespace(Index=lambda name: SimpleNamespace())
        monkeypatch.setitem(
            sys.modules,
            "pinecone",
            SimpleNamespace(Pinecone=lambda **kw: fake_pc),
        )

        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        idx1 = await adapter._get_index()
        idx2 = await adapter._get_index()
        assert idx1 is idx2


class TestPineconeInit:
    """Cover init with existing index, missing index, and failure."""

    @pytest.mark.asyncio
    async def test_init_existing_index(self, monkeypatch: pytest.MonkeyPatch) -> None:
        index = FakePineconeIndex()
        fake_pc = SimpleNamespace(
            describe_index=lambda name: {"name": name},
            Index=lambda name: index,
        )
        monkeypatch.setitem(
            sys.modules,
            "pinecone",
            SimpleNamespace(Pinecone=lambda **kw: fake_pc),
        )

        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        await adapter.init()
        assert adapter._index is index

    @pytest.mark.asyncio
    async def test_init_creates_index_when_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        index = FakePineconeIndex()
        created: list[dict] = []

        def fake_describe(name: str) -> Any:
            raise Exception("not found")

        fake_pc = SimpleNamespace(
            describe_index=fake_describe,
            Index=lambda name: index,
            create_index=lambda **kw: created.append(kw),
        )
        monkeypatch.setitem(
            sys.modules,
            "pinecone",
            SimpleNamespace(Pinecone=lambda **kw: fake_pc),
        )

        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        await adapter.init()
        assert len(created) == 1
        assert created[0]["name"] == "default"

    @pytest.mark.asyncio
    async def test_init_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_describe(name: str) -> Any:
            raise Exception("not found")

        def fake_create(**kw: Any) -> Any:
            raise Exception("creation failed")

        fake_pc = SimpleNamespace(
            describe_index=fake_describe,
            create_index=fake_create,
        )
        monkeypatch.setitem(
            sys.modules,
            "pinecone",
            SimpleNamespace(Pinecone=lambda **kw: fake_pc),
        )

        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        with pytest.raises(LifecycleError, match="pinecone-init-failed"):
            await adapter.init()


class TestPineconeCreateDefaultIndex:
    """Cover serverless and pod-based index creation."""

    @pytest.mark.asyncio
    async def test_create_serverless_index(self, monkeypatch: pytest.MonkeyPatch) -> None:
        created: list[dict] = []

        fake_pc = SimpleNamespace(create_index=lambda **kw: created.append(kw))
        monkeypatch.setitem(
            sys.modules,
            "pinecone",
            SimpleNamespace(Pinecone=lambda **kw: fake_pc),
        )

        adapter = PineconeAdapter(
            PineconeSettings(
                api_key=SecretStr("key"),
                serverless=True,
                cloud="gcp",
                region="us-west1",
            )
        )
        adapter._client = fake_pc
        await adapter._create_default_index()

        assert len(created) == 1
        assert "serverless" in created[0]["spec"]
        assert created[0]["spec"]["serverless"]["cloud"] == "gcp"
        assert created[0]["spec"]["serverless"]["region"] == "us-west1"

    @pytest.mark.asyncio
    async def test_create_pod_index(self, monkeypatch: pytest.MonkeyPatch) -> None:
        created: list[dict] = []

        fake_pc = SimpleNamespace(create_index=lambda **kw: created.append(kw))
        monkeypatch.setitem(
            sys.modules,
            "pinecone",
            SimpleNamespace(Pinecone=lambda **kw: fake_pc),
        )

        adapter = PineconeAdapter(
            PineconeSettings(
                api_key=SecretStr("key"),
                serverless=False,
                environment="prod",
                pod_type="p2.x1",
                replicas=2,
                shards=2,
            )
        )
        adapter._client = fake_pc
        await adapter._create_default_index()

        assert len(created) == 1
        assert "pod" in created[0]["spec"]
        assert created[0]["spec"]["pod"]["environment"] == "prod"
        assert created[0]["spec"]["pod"]["pod_type"] == "p2.x1"
        assert created[0]["spec"]["pod"]["replicas"] == 2
        assert created[0]["spec"]["pod"]["shards"] == 2

    @pytest.mark.asyncio
    async def test_create_index_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_pc = SimpleNamespace(
            create_index=lambda **kw: (_ for _ in ()).throw(
                Exception("creation error")
            ),
        )
        monkeypatch.setitem(
            sys.modules,
            "pinecone",
            SimpleNamespace(Pinecone=lambda **kw: fake_pc),
        )

        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        adapter._client = fake_pc

        with pytest.raises(LifecycleError, match="pinecone-index-creation-failed"):
            await adapter._create_default_index()


class TestPineconeHealth:
    """Cover health with and without client/index."""

    @pytest.mark.asyncio
    async def test_health_no_client(self) -> None:
        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        assert await adapter.health() is False

    @pytest.mark.asyncio
    async def test_health_no_index(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_pc = SimpleNamespace()
        monkeypatch.setitem(
            sys.modules,
            "pinecone",
            SimpleNamespace(Pinecone=lambda **kw: fake_pc),
        )

        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        adapter._client = fake_pc
        adapter._index = None
        assert await adapter.health() is False

    @pytest.mark.asyncio
    async def test_health_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        index = FakePineconeIndex()
        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        adapter._client = SimpleNamespace()
        adapter._index = index
        assert await adapter.health() is True

    @pytest.mark.asyncio
    async def test_health_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class BrokenIndex:
            def describe_index_stats(self) -> Any:
                raise RuntimeError("stats failed")

        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        adapter._client = SimpleNamespace()
        adapter._index = BrokenIndex()
        assert await adapter.health() is False


class TestPineconeCleanup:
    """Cover cleanup."""

    @pytest.mark.asyncio
    async def test_cleanup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_pc = SimpleNamespace()
        monkeypatch.setitem(
            sys.modules,
            "pinecone",
            SimpleNamespace(Pinecone=lambda **kw: fake_pc),
        )

        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        adapter._client = fake_pc
        adapter._index = SimpleNamespace()
        await adapter.cleanup()
        assert adapter._client is None
        assert adapter._index is None


class TestPineconeSearch:
    """Cover search with namespaces, filters, and error handling."""

    @pytest.mark.asyncio
    async def test_search_default_no_namespace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that 'default' collection does not add namespace to query."""
        index = FakePineconeIndex()
        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))

        async def _fake_get_index() -> FakePineconeIndex:
            return index

        monkeypatch.setattr(adapter, "_get_index", _fake_get_index)

        await adapter.search("default", [0.1])
        assert "namespace" not in index.queries[0]

    @pytest.mark.asyncio
    async def test_search_empty_string_no_namespace(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that empty string collection does not add namespace."""
        index = FakePineconeIndex()
        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))

        async def _fake_get_index() -> FakePineconeIndex:
            return index

        monkeypatch.setattr(adapter, "_get_index", _fake_get_index)

        await adapter.search("", [0.1])
        assert "namespace" not in index.queries[0]

    @pytest.mark.asyncio
    async def test_search_with_filter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that filter expression is passed to the Pinecone query."""
        index = FakePineconeIndex()
        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))

        async def _fake_get_index() -> FakePineconeIndex:
            return index

        monkeypatch.setattr(adapter, "_get_index", _fake_get_index)

        await adapter.search("ns", [0.1], filter_expr={"type": "doc"})
        assert index.queries[0]["filter"] == {"type": "doc"}

    @pytest.mark.asyncio
    async def test_search_error_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that search exceptions return empty list."""
        class BrokenIndex:
            def query(self, **kw: Any) -> Any:
                raise RuntimeError("query failed")

        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))

        async def _fake_get_index() -> BrokenIndex:
            return BrokenIndex()

        monkeypatch.setattr(adapter, "_get_index", _fake_get_index)

        results = await adapter.search("ns", [0.1])
        assert results == []


class TestPineconePrepareVectors:
    """Cover _prepare_pinecone_vector and _prepare_all_vectors."""

    def test_prepare_vector_with_id(self) -> None:
        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        doc_id, data = adapter._prepare_pinecone_vector(
            VectorDocument(id="myid", vector=[0.1], metadata={"k": "v"}), 0
        )
        assert doc_id == "myid"
        assert data["values"] == [0.1]
        assert data["metadata"] == {"k": "v"}

    def test_prepare_vector_without_id(self) -> None:
        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        doc_id, data = adapter._prepare_pinecone_vector(
            VectorDocument(id=None, vector=[0.1]), 3
        )
        assert doc_id == "vec_3"

    def test_prepare_vector_no_metadata(self) -> None:
        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        doc_id, data = adapter._prepare_pinecone_vector(
            VectorDocument(id="myid", vector=[0.1], metadata={}), 0
        )
        assert "metadata" not in data

    def test_prepare_all_vectors(self) -> None:
        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        docs = [
            VectorDocument(id="a", vector=[0.1]),
            VectorDocument(id="b", vector=[0.2], metadata={"k": "v"}),
        ]
        ids, vectors = adapter._prepare_all_vectors(docs)
        assert ids == ["a", "b"]
        assert len(vectors) == 2


class TestPineconeUpsertBatch:
    """Cover _upsert_batch including the no-upsert warning path."""

    @pytest.mark.asyncio
    async def test_upsert_batch_success(self) -> None:
        index = FakePineconeIndex()
        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))

        await adapter._upsert_batch(index, [{"id": "a", "values": [0.1]}], "ns", 1)
        assert len(index.upserts) == 1
        assert index.upserts[0]["namespace"] == "ns"

    @pytest.mark.asyncio
    async def test_upsert_batch_no_namespace(self) -> None:
        index = FakePineconeIndex()
        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))

        await adapter._upsert_batch(index, [{"id": "a", "values": [0.1]}], None, 1)
        assert "namespace" not in index.upserts[0]

    @pytest.mark.asyncio
    async def test_upsert_batch_zero_count(self) -> None:
        """When upserted_count is 0, a warning should be logged."""

        class ZeroIndex:
            def upsert(self, **kw: Any) -> dict[str, Any]:
                return {"upserted_count": 0}

        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        # Should not raise, just log a warning
        await adapter._upsert_batch(ZeroIndex(), [{"id": "a", "values": [0.1]}], "ns", 1)


class TestPineconeUpsert:
    """Cover full upsert flow with batching."""

    @pytest.mark.asyncio
    async def test_upsert_with_namespace(self) -> None:
        index = FakePineconeIndex()
        adapter = PineconeAdapter(
            PineconeSettings(api_key=SecretStr("key"), upsert_batch_size=1)
        )
        adapter._index = index

        docs = [
            VectorDocument(id="a", vector=[0.1]),
            VectorDocument(id="b", vector=[0.2]),
        ]
        ids = await adapter.upsert("ns", docs)
        assert ids == ["a", "b"]
        assert len(index.upserts) == 2
        assert index.upserts[0]["namespace"] == "ns"

    @pytest.mark.asyncio
    async def test_upsert_default_no_namespace(self) -> None:
        index = FakePineconeIndex()
        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        adapter._index = index

        docs = [VectorDocument(id="a", vector=[0.1])]
        ids = await adapter.upsert("default", docs)
        assert ids == ["a"]
        assert "namespace" not in index.upserts[0]

    @pytest.mark.asyncio
    async def test_upsert_error_returns_empty(self) -> None:
        class BrokenIndex:
            def upsert(self, **kw: Any) -> Any:
                raise RuntimeError("upsert failed")

        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        adapter._index = BrokenIndex()

        ids = await adapter.upsert(
            "ns", [VectorDocument(id="a", vector=[0.1])]
        )
        assert ids == []

    @pytest.mark.asyncio
    async def test_insert_delegates_to_upsert(self) -> None:
        index = FakePineconeIndex()
        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        adapter._index = index

        docs = [VectorDocument(id="a", vector=[0.1])]
        ids = await adapter.insert("ns", docs)
        assert ids == ["a"]


class TestPineconeDelete:
    """Cover delete with and without namespace."""

    @pytest.mark.asyncio
    async def test_delete_with_namespace(self) -> None:
        index = FakePineconeIndex()
        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        adapter._index = index

        assert await adapter.delete("ns", ["id1"]) is True
        assert index.deletes[0]["namespace"] == "ns"
        assert index.deletes[0]["ids"] == ["id1"]

    @pytest.mark.asyncio
    async def test_delete_default_no_namespace(self) -> None:
        index = FakePineconeIndex()
        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        adapter._index = index

        assert await adapter.delete("default", ["id1"]) is True
        assert "namespace" not in index.deletes[0]

    @pytest.mark.asyncio
    async def test_delete_error_returns_false(self) -> None:
        class BrokenIndex:
            def delete(self, **kw: Any) -> Any:
                raise RuntimeError("delete failed")

        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        adapter._index = BrokenIndex()
        assert await adapter.delete("ns", ["id1"]) is False


class TestPineconeGet:
    """Cover fetch / get."""

    @pytest.mark.asyncio
    async def test_get_with_vectors(self) -> None:
        index = FakePineconeIndex()
        index.fetch = lambda **kw: {
            "vectors": {
                "g1": {"values": [1.0, 2.0], "metadata": {"k": "v"}}
            }
        }

        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        adapter._index = index

        docs = await adapter.get("ns", ["g1"], include_vectors=True)
        assert len(docs) == 1
        assert docs[0].id == "g1"
        assert docs[0].vector == [1.0, 2.0]
        assert docs[0].metadata == {"k": "v"}

    @pytest.mark.asyncio
    async def test_get_without_vectors(self) -> None:
        index = FakePineconeIndex()
        index.fetch = lambda **kw: {
            "vectors": {
                "g1": {"values": [1.0], "metadata": {}}
            }
        }

        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        adapter._index = index

        docs = await adapter.get("ns", ["g1"], include_vectors=False)
        assert docs[0].vector == []

    @pytest.mark.asyncio
    async def test_get_with_namespace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        index = FakePineconeIndex()
        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))

        async def _fake_get_index() -> FakePineconeIndex:
            return index

        monkeypatch.setattr(adapter, "_get_index", _fake_get_index)

        await adapter.get("ns", ["g1"])
        assert index.fetches[0]["namespace"] == "ns"

    @pytest.mark.asyncio
    async def test_get_error_returns_empty(self) -> None:
        class BrokenIndex:
            def fetch(self, **kw: Any) -> Any:
                raise RuntimeError("fetch failed")

        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        adapter._index = BrokenIndex()
        assert await adapter.get("ns", ["g1"]) == []


class TestPineconeCount:
    """Cover count with and without namespace filtering."""

    @pytest.mark.asyncio
    async def test_count_namespace(self) -> None:
        index = FakePineconeIndex()
        index.describe_index_stats = lambda **kw: {
            "total_vector_count": 10,
            "namespaces": {"ns": {"vector_count": 3}},
        }

        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        adapter._index = index

        assert await adapter.count("ns") == 3

    @pytest.mark.asyncio
    async def test_count_default(self) -> None:
        index = FakePineconeIndex()
        index.describe_index_stats = lambda **kw: {
            "total_vector_count": 10,
            "namespaces": {"ns": {"vector_count": 3}},
        }

        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        adapter._index = index

        assert await adapter.count("default") == 10

    @pytest.mark.asyncio
    async def test_count_with_filter(self) -> None:
        index = FakePineconeIndex()
        filter_received: dict = {}

        def describe(**kw: Any) -> dict:
            filter_received.update(kw)
            return {"total_vector_count": 5, "namespaces": {}}

        index.describe_index_stats = describe

        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        adapter._index = index

        assert await adapter.count("default", {"type": "doc"}) == 5
        assert filter_received["filter"] == {"type": "doc"}

    @pytest.mark.asyncio
    async def test_count_error_returns_zero(self) -> None:
        class BrokenIndex:
            def describe_index_stats(self, **kw: Any) -> Any:
                raise RuntimeError("stats failed")

        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        adapter._index = BrokenIndex()
        assert await adapter.count("ns") == 0


class TestPineconeCreateDeleteListCollections:
    """Cover collection (namespace) management."""

    @pytest.mark.asyncio
    async def test_create_collection_is_implicit(self) -> None:
        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        assert await adapter.create_collection("mycol", 128) is True

    @pytest.mark.asyncio
    async def test_delete_collection_with_namespace(self) -> None:
        index = FakePineconeIndex()
        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        adapter._index = index

        assert await adapter.delete_collection("ns") is True
        assert index.deletes[0]["namespace"] == "ns"
        assert index.deletes[0]["delete_all"] is True

    @pytest.mark.asyncio
    async def test_delete_collection_default(self) -> None:
        index = FakePineconeIndex()
        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        adapter._index = index

        assert await adapter.delete_collection("default") is True
        assert "namespace" not in index.deletes[0]
        assert index.deletes[0]["delete_all"] is True

    @pytest.mark.asyncio
    async def test_delete_collection_error(self) -> None:
        class BrokenIndex:
            def delete(self, **kw: Any) -> Any:
                raise RuntimeError("delete all failed")

        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        adapter._index = BrokenIndex()
        assert await adapter.delete_collection("ns") is False

    @pytest.mark.asyncio
    async def test_list_collections_with_default(self) -> None:
        index = FakePineconeIndex()
        index.describe_index_stats = lambda **kw: {
            "total_vector_count": 10,
            "namespaces": {"ns1": {"vector_count": 3}},
        }

        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        adapter._index = index

        collections = await adapter.list_collections()
        assert "ns1" in collections
        assert "default" in collections  # because 10 > 3

    @pytest.mark.asyncio
    async def test_list_collections_no_default(self) -> None:
        index = FakePineconeIndex()
        index.describe_index_stats = lambda **kw: {
            "total_vector_count": 3,
            "namespaces": {"ns1": {"vector_count": 3}},
        }

        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        adapter._index = index

        collections = await adapter.list_collections()
        assert "ns1" in collections
        assert "default" not in collections  # because 3 == 3

    @pytest.mark.asyncio
    async def test_list_collections_empty(self) -> None:
        index = FakePineconeIndex()
        index.describe_index_stats = lambda **kw: {
            "total_vector_count": 0,
            "namespaces": {},
        }

        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        adapter._index = index

        collections = await adapter.list_collections()
        assert collections == []

    @pytest.mark.asyncio
    async def test_list_collections_error(self) -> None:
        class BrokenIndex:
            def describe_index_stats(self, **kw: Any) -> Any:
                raise RuntimeError("stats failed")

        adapter = PineconeAdapter(PineconeSettings(api_key=SecretStr("key")))
        adapter._index = BrokenIndex()
        assert await adapter.list_collections() == []
