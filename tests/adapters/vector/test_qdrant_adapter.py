from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from oneiric.adapters.vector.qdrant import QdrantAdapter, QdrantSettings


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


class FakeCollections:
    def __init__(self, names: list[str]) -> None:
        self.collections = [SimpleNamespace(name=name) for name in names]


class FakeClient:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.deleted: list[str] = []

    async def get_collections(self) -> FakeCollections:
        return FakeCollections(["existing"])

    async def create_collection(self, **kwargs: Any) -> None:
        self.created.append(kwargs)

    async def get_cluster_info(self) -> dict[str, Any]:
        return {"status": "ok"}

    async def search(self, **kwargs: Any) -> list[Any]:
        return [
            SimpleNamespace(
                id="doc-1",
                score=0.4,
                payload={"k": "v"},
                vector=[0.1],
            )
        ]

    async def upsert(self, **kwargs: Any) -> Any:
        return SimpleNamespace(status=SimpleNamespace(name="COMPLETED"))

    async def delete(self, **kwargs: Any) -> Any:
        return SimpleNamespace(status=SimpleNamespace(name="COMPLETED"))

    async def retrieve(self, **kwargs: Any) -> list[Any]:
        return [
            SimpleNamespace(id="doc-1", vector=[0.2], payload={"k": "v"}),
        ]

    async def count(self, **kwargs: Any) -> Any:
        return SimpleNamespace(count=7)

    async def scroll(self, **kwargs: Any) -> tuple[list[Any], str | None]:
        return (
            [
                SimpleNamespace(id="doc-2", vector=[0.3], payload={"k": "v"}),
            ],
            "next",
        )

    async def delete_collection(self, collection_name: str) -> None:
        self.deleted.append(collection_name)

    async def close(self) -> None:
        return None


def _inject_qdrant_models(monkeypatch: pytest.MonkeyPatch) -> None:
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
    sys_modules = __import__("sys").modules
    monkeypatch.setitem(sys_modules, "qdrant_client.models", models)
    monkeypatch.setitem(sys_modules, "qdrant_client", SimpleNamespace(models=models))


@pytest.mark.asyncio
async def test_qdrant_filter_and_collection_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _inject_qdrant_models(monkeypatch)
    settings = QdrantSettings(enable_quantization=True)
    adapter = QdrantAdapter(settings)
    adapter._client = FakeClient()

    q_filter = adapter._build_qdrant_filter({"kind": "demo", "tags": ["a", "b"]})
    assert isinstance(q_filter, Filter)
    assert len(q_filter.must) == 2

    created = await adapter._ensure_collection_exists("new", dimension=3)
    assert created is True
    created_call = adapter._client.created[0]
    assert created_call["collection_name"] == "new"
    assert created_call["quantization_config"] is not None


@pytest.mark.asyncio
async def test_qdrant_search_and_scroll(monkeypatch: pytest.MonkeyPatch) -> None:
    _inject_qdrant_models(monkeypatch)
    adapter = QdrantAdapter(QdrantSettings())
    adapter._client = FakeClient()

    results = await adapter.search("docs", [0.1], include_vectors=True)
    assert results[0].vector == [0.1]

    documents, offset = await adapter.scroll("docs", include_vectors=True)
    assert documents[0].id == "doc-2"
    assert offset == "next"


@pytest.mark.asyncio
async def test_qdrant_search_with_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    """search() with filter_expr builds a Qdrant filter (line 262)."""
    _inject_qdrant_models(monkeypatch)
    adapter = QdrantAdapter(QdrantSettings())
    adapter._client = FakeClient()
    results = await adapter.search("docs", [0.1], filter_expr={"kind": "article"})
    assert len(results) == 1


@pytest.mark.asyncio
async def test_qdrant_scroll_with_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    """scroll() with filter_expr builds a Qdrant filter (line 514)."""
    _inject_qdrant_models(monkeypatch)
    adapter = QdrantAdapter(QdrantSettings())
    adapter._client = FakeClient()
    documents, _ = await adapter.scroll("docs", filter_expr={"kind": "article"})
    assert len(documents) == 1


@pytest.mark.asyncio
async def test_qdrant_upsert_non_completed_status_logs_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """upsert() logs a warning when a batch status is not COMPLETED (line 370)."""
    _inject_qdrant_models(monkeypatch)

    class FailUpsertClient(FakeClient):
        async def upsert(self, **kwargs: Any) -> Any:
            return SimpleNamespace(status=SimpleNamespace(name="FAILED"))

    from oneiric.adapters.vector.vector_types import VectorDocument

    adapter = QdrantAdapter(QdrantSettings())
    adapter._client = FailUpsertClient()
    docs = [VectorDocument(id="d1", vector=[0.1, 0.2])]
    ids = await adapter.upsert("col", docs)
    assert ids == ["d1"]


# ---------------------------------------------------------------------------
# Tests — coverage gaps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_qdrant_init_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """init() calls _ensure_client and get_cluster_info (lines 122-133)."""
    _inject_qdrant_models(monkeypatch)
    adapter = QdrantAdapter(QdrantSettings())
    adapter._client = FakeClient()
    await adapter.init()  # must not raise


@pytest.mark.asyncio
async def test_qdrant_ensure_client_when_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """_ensure_client() calls _create_client when _client is None (line 118)."""
    _inject_qdrant_models(monkeypatch)
    fake = FakeClient()

    async def _fake_create(_self: Any) -> FakeClient:
        return fake

    monkeypatch.setattr(QdrantAdapter, "_create_client", _fake_create)
    adapter = QdrantAdapter(QdrantSettings())
    client = await adapter._ensure_client()
    assert client is fake
    assert adapter._client is fake


@pytest.mark.asyncio
async def test_qdrant_health_returns_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """health() returns True when get_cluster_info succeeds (lines 229-231)."""
    _inject_qdrant_models(monkeypatch)
    adapter = QdrantAdapter(QdrantSettings())
    adapter._client = FakeClient()
    assert await adapter.health() is True


@pytest.mark.asyncio
async def test_qdrant_health_returns_false_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """health() returns False when get_cluster_info raises (lines 232-234)."""
    _inject_qdrant_models(monkeypatch)

    class BrokenClient(FakeClient):
        async def get_cluster_info(self) -> dict:
            raise RuntimeError("timeout")

    adapter = QdrantAdapter(QdrantSettings())
    adapter._client = BrokenClient()
    assert await adapter.health() is False


@pytest.mark.asyncio
async def test_qdrant_cleanup_with_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """cleanup() closes client and sets _client to None (lines 237-244)."""
    _inject_qdrant_models(monkeypatch)
    adapter = QdrantAdapter(QdrantSettings())
    adapter._client = FakeClient()
    await adapter.cleanup()
    assert adapter._client is None


@pytest.mark.asyncio
async def test_qdrant_cleanup_without_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """cleanup() is a no-op when _client is None (line 237 branch)."""
    _inject_qdrant_models(monkeypatch)
    adapter = QdrantAdapter(QdrantSettings())
    await adapter.cleanup()  # must not raise
    assert adapter._client is None


@pytest.mark.asyncio
async def test_qdrant_ensure_collection_already_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    """_ensure_collection_exists returns True when collection already present (line 148)."""
    _inject_qdrant_models(monkeypatch)
    adapter = QdrantAdapter(QdrantSettings())
    adapter._client = FakeClient()  # FakeClient returns ["existing"]
    result = await adapter._ensure_collection_exists("existing")
    assert result is True
    assert adapter._client.created == []


@pytest.mark.asyncio
async def test_qdrant_ensure_collection_dimension_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """_ensure_collection_exists uses default_dimension when dimension is None (line 151)."""
    _inject_qdrant_models(monkeypatch)
    settings = QdrantSettings(default_dimension=64)
    adapter = QdrantAdapter(settings)
    adapter._client = FakeClient()
    result = await adapter._ensure_collection_exists("new_col", dimension=None)
    assert result is True
    assert adapter._client.created[0]["collection_name"] == "new_col"


@pytest.mark.asyncio
async def test_qdrant_ensure_collection_creation_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """_ensure_collection_exists returns False when creation raises (lines 217-223)."""
    _inject_qdrant_models(monkeypatch)

    class ErrorCollections:
        async def get_collections(self) -> Any:
            raise RuntimeError("network error")

    class BrokenCreateClient(FakeClient):
        async def get_collections(self) -> Any:
            raise RuntimeError("collection listing failed")

    adapter = QdrantAdapter(QdrantSettings())
    adapter._client = BrokenCreateClient()
    result = await adapter._ensure_collection_exists("new", dimension=3)
    assert result is False


@pytest.mark.asyncio
async def test_qdrant_build_filter_returns_none_for_empty_expr(monkeypatch: pytest.MonkeyPatch) -> None:
    """_build_qdrant_filter returns None when filter_expr is empty dict (line 325)."""
    _inject_qdrant_models(monkeypatch)
    adapter = QdrantAdapter(QdrantSettings())
    result = adapter._build_qdrant_filter({})
    assert result is None


@pytest.mark.asyncio
async def test_qdrant_build_filter_exception_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """_build_qdrant_filter returns None when qdrant_client import fails (lines 313-317)."""
    import sys
    import types

    bad_models = types.ModuleType("qdrant_client.models")
    # Make it raise when accessed
    monkeypatch.setitem(sys.modules, "qdrant_client.models", None)  # type: ignore[arg-type]

    adapter = QdrantAdapter(QdrantSettings())
    result = adapter._build_qdrant_filter({"key": "val"})
    assert result is None


@pytest.mark.asyncio
async def test_qdrant_search_returns_empty_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """search() returns [] when client.search raises (lines 286-288)."""
    _inject_qdrant_models(monkeypatch)

    class ErrorSearchClient(FakeClient):
        async def search(self, **_: Any) -> Any:
            raise RuntimeError("search failed")

    adapter = QdrantAdapter(QdrantSettings())
    adapter._client = ErrorSearchClient()
    results = await adapter.search("col", [0.1])
    assert results == []


@pytest.mark.asyncio
async def test_qdrant_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    """delete() calls client.delete and returns True on COMPLETED (lines 388-404)."""
    _inject_qdrant_models(monkeypatch)
    adapter = QdrantAdapter(QdrantSettings())
    adapter._client = FakeClient()
    result = await adapter.delete("col", ["id1", "id2"])
    assert result is True


@pytest.mark.asyncio
async def test_qdrant_delete_returns_false_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """delete() returns False when client.delete raises (lines 402-404)."""
    _inject_qdrant_models(monkeypatch)

    class ErrorDeleteClient(FakeClient):
        async def delete(self, **_: Any) -> Any:
            raise RuntimeError("delete failed")

    adapter = QdrantAdapter(QdrantSettings())
    adapter._client = ErrorDeleteClient()
    result = await adapter.delete("col", ["id1"])
    assert result is False


@pytest.mark.asyncio
async def test_qdrant_get(monkeypatch: pytest.MonkeyPatch) -> None:
    """get() retrieves documents by id (lines 413-437)."""
    _inject_qdrant_models(monkeypatch)
    adapter = QdrantAdapter(QdrantSettings())
    adapter._client = FakeClient()
    docs = await adapter.get("col", ["doc-1"], include_vectors=True)
    assert len(docs) == 1
    assert docs[0].id == "doc-1"
    assert docs[0].vector == [0.2]


@pytest.mark.asyncio
async def test_qdrant_get_returns_empty_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """get() returns [] when client.retrieve raises (lines 435-437)."""
    _inject_qdrant_models(monkeypatch)

    class ErrorRetrieveClient(FakeClient):
        async def retrieve(self, **_: Any) -> Any:
            raise RuntimeError("retrieve failed")

    adapter = QdrantAdapter(QdrantSettings())
    adapter._client = ErrorRetrieveClient()
    result = await adapter.get("col", ["id1"])
    assert result == []


@pytest.mark.asyncio
async def test_qdrant_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """count() returns result.count (lines 445-462)."""
    _inject_qdrant_models(monkeypatch)
    adapter = QdrantAdapter(QdrantSettings())
    adapter._client = FakeClient()
    total = await adapter.count("col")
    assert total == 7


@pytest.mark.asyncio
async def test_qdrant_count_with_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    """count() builds filter when filter_expr provided (line 451)."""
    _inject_qdrant_models(monkeypatch)
    adapter = QdrantAdapter(QdrantSettings())
    adapter._client = FakeClient()
    total = await adapter.count("col", filter_expr={"kind": "article"})
    assert total == 7


@pytest.mark.asyncio
async def test_qdrant_count_returns_zero_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """count() returns 0 when client.count raises (lines 460-462)."""
    _inject_qdrant_models(monkeypatch)

    class ErrorCountClient(FakeClient):
        async def count(self, **_: Any) -> Any:
            raise RuntimeError("count failed")

    adapter = QdrantAdapter(QdrantSettings())
    adapter._client = ErrorCountClient()
    result = await adapter.count("col")
    assert result == 0


@pytest.mark.asyncio
async def test_qdrant_create_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    """create_collection() delegates to _ensure_collection_exists (line 471)."""
    _inject_qdrant_models(monkeypatch)
    adapter = QdrantAdapter(QdrantSettings())
    adapter._client = FakeClient()
    ok = await adapter.create_collection("new_col", dimension=128)
    assert ok is True


@pytest.mark.asyncio
async def test_qdrant_delete_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    """delete_collection() calls client.delete_collection (lines 478-486)."""
    _inject_qdrant_models(monkeypatch)
    adapter = QdrantAdapter(QdrantSettings())
    adapter._client = FakeClient()
    ok = await adapter.delete_collection("old_col")
    assert ok is True
    assert "old_col" in adapter._client.deleted


@pytest.mark.asyncio
async def test_qdrant_delete_collection_returns_false_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """delete_collection() returns False when client raises (lines 484-486)."""
    _inject_qdrant_models(monkeypatch)

    class ErrorDelColClient(FakeClient):
        async def delete_collection(self, **_: Any) -> None:
            raise RuntimeError("delete collection failed")

    adapter = QdrantAdapter(QdrantSettings())
    adapter._client = ErrorDelColClient()
    result = await adapter.delete_collection("col")
    assert result is False


@pytest.mark.asyncio
async def test_qdrant_list_collections(monkeypatch: pytest.MonkeyPatch) -> None:
    """list_collections() returns collection names (lines 489-497)."""
    _inject_qdrant_models(monkeypatch)
    adapter = QdrantAdapter(QdrantSettings())
    adapter._client = FakeClient()
    names = await adapter.list_collections()
    assert "existing" in names


@pytest.mark.asyncio
async def test_qdrant_list_collections_returns_empty_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """list_collections() returns [] when client raises (lines 495-497)."""
    _inject_qdrant_models(monkeypatch)

    class ErrorListClient(FakeClient):
        async def get_collections(self) -> Any:
            raise RuntimeError("list failed")

    adapter = QdrantAdapter(QdrantSettings())
    adapter._client = ErrorListClient()
    result = await adapter.list_collections()
    assert result == []


@pytest.mark.asyncio
async def test_qdrant_scroll_returns_empty_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """scroll() returns ([], None) when client.scroll raises (lines 537-539)."""
    _inject_qdrant_models(monkeypatch)

    class ErrorScrollClient(FakeClient):
        async def scroll(self, **_: Any) -> Any:
            raise RuntimeError("scroll failed")

    adapter = QdrantAdapter(QdrantSettings())
    adapter._client = ErrorScrollClient()
    docs, offset = await adapter.scroll("col")
    assert docs == []
    assert offset is None


def test_qdrant_has_capability(monkeypatch: pytest.MonkeyPatch) -> None:
    """has_capability() returns True for known capabilities, False otherwise (lines 542-550)."""
    _inject_qdrant_models(monkeypatch)
    adapter = QdrantAdapter(QdrantSettings())
    assert adapter.has_capability("vector_search") is True
    assert adapter.has_capability("scroll") is True
    assert adapter.has_capability("nonexistent") is False


@pytest.mark.asyncio
async def test_qdrant_upsert_generates_id_for_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """upsert() generates uuid when doc.id is None (line 348)."""
    from oneiric.adapters.vector.vector_types import VectorDocument

    _inject_qdrant_models(monkeypatch)
    adapter = QdrantAdapter(QdrantSettings())
    adapter._client = FakeClient()
    docs = [VectorDocument(id=None, vector=[0.1, 0.2])]
    ids = await adapter.upsert("col", docs)
    assert len(ids) == 1
    assert ids[0]  # non-empty uuid string


@pytest.mark.asyncio
async def test_qdrant_upsert_returns_empty_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """upsert() returns [] when client.upsert raises (lines 378-380)."""
    _inject_qdrant_models(monkeypatch)

    class ErrorUpsertClient(FakeClient):
        async def upsert(self, **_: Any) -> Any:
            raise RuntimeError("upsert failed")

    from oneiric.adapters.vector.vector_types import VectorDocument

    adapter = QdrantAdapter(QdrantSettings())
    adapter._client = ErrorUpsertClient()
    docs = [VectorDocument(id="d1", vector=[0.1])]
    result = await adapter.upsert("col", docs)
    assert result == []


# ---------------------------------------------------------------------------
# Additional coverage: _create_client, init exception, health/cleanup branches
# ---------------------------------------------------------------------------


def _inject_qdrant_full(monkeypatch: pytest.MonkeyPatch) -> type:
    """Inject full fake qdrant_client module including AsyncQdrantClient."""
    import sys

    models = __import__("sys").modules.get("qdrant_client.models")
    if models is None:
        _inject_qdrant_models(monkeypatch)
        models = sys.modules["qdrant_client.models"]

    class FakeAsyncQdrantClient:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        async def get_cluster_info(self) -> dict[str, Any]:
            return {"status": "ok"}

        async def close(self) -> None:
            return None

    fake_qdrant_module = SimpleNamespace(
        AsyncQdrantClient=FakeAsyncQdrantClient,
        models=models,
    )
    monkeypatch.setitem(sys.modules, "qdrant_client", fake_qdrant_module)
    monkeypatch.setitem(sys.modules, "qdrant_client.models", models)
    return FakeAsyncQdrantClient


@pytest.mark.asyncio
async def test_qdrant_create_client_basic(monkeypatch: pytest.MonkeyPatch) -> None:
    """_create_client() instantiates AsyncQdrantClient with url/timeout/prefer_grpc (lines 87-108)."""
    FakeAsyncQdrantClient = _inject_qdrant_full(monkeypatch)
    adapter = QdrantAdapter(QdrantSettings(url="http://localhost:6333"))
    client = await adapter._create_client()
    assert isinstance(client, FakeAsyncQdrantClient)
    assert client.kwargs["url"] == "http://localhost:6333"


@pytest.mark.asyncio
async def test_qdrant_create_client_with_optional_params(monkeypatch: pytest.MonkeyPatch) -> None:
    """_create_client() includes api_key, grpc_port, https when set (lines 96-103)."""
    from pydantic import SecretStr

    FakeAsyncQdrantClient = _inject_qdrant_full(monkeypatch)
    settings = QdrantSettings(
        url="http://localhost:6333",
        api_key=SecretStr("secret-key"),
        grpc_port=6334,
        https=True,
    )
    adapter = QdrantAdapter(settings)
    client = await adapter._create_client()
    assert isinstance(client, FakeAsyncQdrantClient)
    assert client.kwargs["api_key"] == "secret-key"
    assert client.kwargs["grpc_port"] == 6334
    assert client.kwargs["https"] is True


@pytest.mark.asyncio
async def test_qdrant_create_client_construction_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """_create_client() raises LifecycleError when AsyncQdrantClient() raises non-ImportError (lines 113-114)."""
    import sys

    from oneiric.core.lifecycle import LifecycleError

    models = __import__("sys").modules.get("qdrant_client.models")
    if models is None:
        _inject_qdrant_models(monkeypatch)
        models = sys.modules["qdrant_client.models"]

    class ExplodingClient:
        def __init__(self, **kwargs: Any) -> None:
            raise ValueError("bad connection params")

    fake_qdrant_module = SimpleNamespace(AsyncQdrantClient=ExplodingClient, models=models)
    monkeypatch.setitem(sys.modules, "qdrant_client", fake_qdrant_module)
    adapter = QdrantAdapter(QdrantSettings())
    with pytest.raises(LifecycleError, match="qdrant-client-creation-failed"):
        await adapter._create_client()


@pytest.mark.asyncio
async def test_qdrant_create_client_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """_create_client() raises LifecycleError when qdrant_client is missing (lines 109-112)."""
    import sys

    from oneiric.core.lifecycle import LifecycleError

    monkeypatch.setitem(sys.modules, "qdrant_client", None)
    monkeypatch.setitem(sys.modules, "qdrant_client.models", None)
    adapter = QdrantAdapter(QdrantSettings())
    with pytest.raises(LifecycleError, match="qdrant-client-import-failed"):
        await adapter._create_client()


@pytest.mark.asyncio
async def test_qdrant_init_raises_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """init() re-raises as LifecycleError when _ensure_client/get_cluster_info fails (lines 131-133)."""
    from oneiric.core.lifecycle import LifecycleError

    _inject_qdrant_models(monkeypatch)

    class BrokenInitClient(FakeClient):
        async def get_cluster_info(self) -> dict[str, Any]:
            raise RuntimeError("cluster unreachable")

    adapter = QdrantAdapter(QdrantSettings())
    adapter._client = BrokenInitClient()
    with pytest.raises(LifecycleError, match="qdrant-init-failed"):
        await adapter.init()


@pytest.mark.asyncio
async def test_qdrant_health_returns_false_when_no_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """health() returns False immediately when _client is None (line 227)."""
    _inject_qdrant_models(monkeypatch)
    adapter = QdrantAdapter(QdrantSettings())
    assert adapter._client is None
    assert await adapter.health() is False


@pytest.mark.asyncio
async def test_qdrant_cleanup_logs_warning_on_close_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """cleanup() logs a warning when client.close() raises (lines 240-241)."""
    _inject_qdrant_models(monkeypatch)

    class BrokenCloseClient(FakeClient):
        async def close(self) -> None:
            raise RuntimeError("close failed")

    adapter = QdrantAdapter(QdrantSettings())
    adapter._client = BrokenCloseClient()
    await adapter.cleanup()  # must not raise
    assert adapter._client is None


@pytest.mark.asyncio
async def test_qdrant_insert_delegates_to_upsert(monkeypatch: pytest.MonkeyPatch) -> None:
    """insert() delegates to upsert() (line 325)."""
    from oneiric.adapters.vector.vector_types import VectorDocument

    _inject_qdrant_models(monkeypatch)
    adapter = QdrantAdapter(QdrantSettings())
    adapter._client = FakeClient()
    docs = [VectorDocument(id="d1", vector=[0.1, 0.2])]
    ids = await adapter.insert("col", docs)
    assert ids == ["d1"]
