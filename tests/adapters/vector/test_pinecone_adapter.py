from __future__ import annotations

import pytest
from pydantic import SecretStr

from oneiric.adapters.vector.pinecone import PineconeAdapter, PineconeSettings
from oneiric.adapters.vector.vector_types import VectorDocument


class FakeIndex:
    def __init__(self) -> None:
        self.queries: list[dict[str, object]] = []
        self.upserts: list[dict[str, object]] = []
        self.deletes: list[dict[str, object]] = []
        self.fetches: list[dict[str, object]] = []

    def query(self, **kwargs: object) -> dict[str, object]:
        self.queries.append(kwargs)
        return {
            "matches": [
                {"id": "doc-1", "score": 0.42, "metadata": {"k": "v"}, "values": [1.0]}
            ]
        }

    def upsert(self, **kwargs: object) -> dict[str, object]:
        self.upserts.append(kwargs)
        return {"upserted_count": len(kwargs.get("vectors", []))}

    def delete(self, **kwargs: object) -> None:
        self.deletes.append(kwargs)

    def fetch(self, **kwargs: object) -> dict[str, object]:
        self.fetches.append(kwargs)
        return {"vectors": {"doc-1": {"values": [1.0], "metadata": {"k": "v"}}}}

    def describe_index_stats(self, **kwargs: object) -> dict[str, object]:
        return {
            "total_vector_count": 5,
            "namespaces": {"ns": {"vector_count": 2}},
        }


@pytest.mark.asyncio
async def test_pinecone_prepare_and_search(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = PineconeSettings(api_key=SecretStr("key"))
    adapter = PineconeAdapter(settings)
    index = FakeIndex()

    async def _get_index() -> FakeIndex:
        return index

    monkeypatch.setattr(adapter, "_get_index", _get_index)

    doc_ids, vectors = adapter._prepare_all_vectors(
        [VectorDocument(id=None, vector=[0.1], metadata={"a": 1})]
    )
    assert doc_ids == ["vec_0"]
    assert vectors[0]["metadata"] == {"a": 1}

    results = await adapter.search(
        "ns",
        [0.1],
        limit=1,
        filter_expr={"kind": "demo"},
        include_vectors=True,
    )
    assert results[0].id == "doc-1"
    assert index.queries[0]["namespace"] == "ns"
    assert index.queries[0]["filter"] == {"kind": "demo"}


@pytest.mark.asyncio
async def test_pinecone_upsert_count_and_list(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = PineconeSettings(api_key=SecretStr("key"), upsert_batch_size=1)
    adapter = PineconeAdapter(settings)
    index = FakeIndex()

    async def _get_index() -> FakeIndex:
        return index

    monkeypatch.setattr(adapter, "_get_index", _get_index)

    inserted = await adapter.upsert(
        "ns",
        [
            VectorDocument(id="a", vector=[0.1], metadata={}),
            VectorDocument(id="b", vector=[0.2], metadata={}),
        ],
    )
    assert inserted == ["a", "b"]
    assert len(index.upserts) == 2
    assert index.upserts[0]["namespace"] == "ns"

    count_ns = await adapter.count("ns")
    assert count_ns == 2
    count_all = await adapter.count("default")
    assert count_all == 5

    collections = await adapter.list_collections()
    assert "ns" in collections
    assert "default" in collections


# ---------------------------------------------------------------------------
# Infrastructure & coverage-gap tests
# ---------------------------------------------------------------------------

import sys
import types
from typing import Any


def _make_fake_pinecone_module(index: FakeIndex | None = None) -> types.ModuleType:
    _index = index or FakeIndex()

    class FakePc:
        def __init__(self, api_key: str) -> None:
            self._key = api_key

        def describe_index(self, name: str) -> dict[str, Any]:
            return {"name": name}

        def create_index(self, **kwargs: Any) -> None:
            pass

        def Index(self, name: str) -> FakeIndex:
            return _index

    fake_mod = types.ModuleType("pinecone")
    fake_mod.Pinecone = FakePc  # type: ignore[attr-defined]
    return fake_mod


@pytest.mark.asyncio
async def test_pinecone_create_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """_create_client() imports pinecone and returns a Pinecone instance (lines 70-78)."""
    monkeypatch.setitem(sys.modules, "pinecone", _make_fake_pinecone_module())
    settings = PineconeSettings(api_key=SecretStr("key"))
    adapter = PineconeAdapter(settings)
    client = await adapter._create_client()
    assert client is not None


@pytest.mark.asyncio
async def test_pinecone_create_client_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """_create_client() raises LifecycleError when pinecone is missing (lines 79-82)."""
    from oneiric.core.lifecycle import LifecycleError

    monkeypatch.setitem(sys.modules, "pinecone", None)
    settings = PineconeSettings(api_key=SecretStr("key"))
    adapter = PineconeAdapter(settings)
    with pytest.raises(LifecycleError, match="pinecone-client-import-failed"):
        await adapter._create_client()


@pytest.mark.asyncio
async def test_pinecone_create_client_construction_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """_create_client() raises LifecycleError when Pinecone() raises non-ImportError (lines 83-84)."""
    from oneiric.core.lifecycle import LifecycleError

    class ExplodingPc:
        def __init__(self, api_key: str) -> None:
            raise ValueError("bad key")

    bad_mod = types.ModuleType("pinecone")
    bad_mod.Pinecone = ExplodingPc  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pinecone", bad_mod)
    settings = PineconeSettings(api_key=SecretStr("key"))
    adapter = PineconeAdapter(settings)
    with pytest.raises(LifecycleError, match="pinecone-client-creation-failed"):
        await adapter._create_client()


@pytest.mark.asyncio
async def test_pinecone_ensure_client_when_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """_ensure_client() calls _create_client when _client is None (lines 87-89)."""
    monkeypatch.setitem(sys.modules, "pinecone", _make_fake_pinecone_module())
    settings = PineconeSettings(api_key=SecretStr("key"))
    adapter = PineconeAdapter(settings)
    assert adapter._client is None
    client = await adapter._ensure_client()
    assert client is not None
    assert adapter._client is client


@pytest.mark.asyncio
async def test_pinecone_get_index_when_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """_get_index() calls client.Index when _index is None (lines 92-95)."""
    index = FakeIndex()
    monkeypatch.setitem(sys.modules, "pinecone", _make_fake_pinecone_module(index))
    settings = PineconeSettings(api_key=SecretStr("key"))
    adapter = PineconeAdapter(settings)
    result = await adapter._get_index()
    assert result is index
    assert adapter._index is index


@pytest.mark.asyncio
async def test_pinecone_init_index_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    """init() succeeds when describe_index doesn't raise (lines 98-118)."""
    monkeypatch.setitem(sys.modules, "pinecone", _make_fake_pinecone_module())
    settings = PineconeSettings(api_key=SecretStr("key"))
    adapter = PineconeAdapter(settings)
    await adapter.init()  # must not raise
    assert adapter._index is not None


@pytest.mark.asyncio
async def test_pinecone_init_creates_index_when_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """init() calls _create_default_index when describe_index raises (lines 110-114)."""
    index = FakeIndex()

    class PcNoIndex:
        def __init__(self, api_key: str) -> None:
            pass

        def describe_index(self, name: str) -> None:
            raise Exception("not found")

        def create_index(self, **kwargs: Any) -> None:
            pass

        def Index(self, name: str) -> FakeIndex:
            return index

    bad_mod = types.ModuleType("pinecone")
    bad_mod.Pinecone = PcNoIndex  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pinecone", bad_mod)
    settings = PineconeSettings(api_key=SecretStr("key"))
    adapter = PineconeAdapter(settings)
    await adapter.init()
    assert adapter._index is index


@pytest.mark.asyncio
async def test_pinecone_init_raises_on_client_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """init() wraps unexpected errors in LifecycleError (lines 119-121)."""
    from oneiric.core.lifecycle import LifecycleError

    monkeypatch.setitem(sys.modules, "pinecone", None)
    settings = PineconeSettings(api_key=SecretStr("key"))
    adapter = PineconeAdapter(settings)
    with pytest.raises(LifecycleError, match="pinecone-init-failed"):
        await adapter.init()


@pytest.mark.asyncio
async def test_pinecone_create_default_index_pod_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    """_create_default_index() uses pod spec when serverless=False (lines 134-143)."""
    created: list[dict[str, Any]] = []

    class PcPod:
        def __init__(self, api_key: str) -> None:
            pass

        def create_index(self, **kwargs: Any) -> None:
            created.append(kwargs)

        def Index(self, name: str) -> FakeIndex:
            return FakeIndex()

    pod_mod = types.ModuleType("pinecone")
    pod_mod.Pinecone = PcPod  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pinecone", pod_mod)
    settings = PineconeSettings(api_key=SecretStr("key"), serverless=False)
    adapter = PineconeAdapter(settings)
    await adapter._ensure_client()
    await adapter._create_default_index()
    assert created[0]["spec"]["pod"]["pod_type"] == "p1.x1"


@pytest.mark.asyncio
async def test_pinecone_create_default_index_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """_create_default_index() wraps errors in LifecycleError (lines 153-154)."""
    from oneiric.core.lifecycle import LifecycleError

    class PcBadCreate:
        def __init__(self, api_key: str) -> None:
            pass

        def create_index(self, **kwargs: Any) -> None:
            raise RuntimeError("quota exceeded")

        def Index(self, name: str) -> FakeIndex:
            return FakeIndex()

    bad_mod = types.ModuleType("pinecone")
    bad_mod.Pinecone = PcBadCreate  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pinecone", bad_mod)
    settings = PineconeSettings(api_key=SecretStr("key"))
    adapter = PineconeAdapter(settings)
    await adapter._ensure_client()
    with pytest.raises(LifecycleError, match="pinecone-index-creation-failed"):
        await adapter._create_default_index()


@pytest.mark.asyncio
async def test_pinecone_health_no_client_or_index(monkeypatch: pytest.MonkeyPatch) -> None:
    """health() returns False when _client or _index is None (line 157-158)."""
    settings = PineconeSettings(api_key=SecretStr("key"))
    adapter = PineconeAdapter(settings)
    assert await adapter.health() is False


@pytest.mark.asyncio
async def test_pinecone_health_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """health() returns True when describe_index_stats succeeds (lines 160-162)."""
    settings = PineconeSettings(api_key=SecretStr("key"))
    adapter = PineconeAdapter(settings)
    adapter._client = object()
    adapter._index = FakeIndex()
    assert await adapter.health() is True


@pytest.mark.asyncio
async def test_pinecone_health_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """health() returns False when describe_index_stats raises (lines 163-165)."""
    class BrokenIndex(FakeIndex):
        def describe_index_stats(self, **kwargs: Any) -> None:  # type: ignore[override]
            raise RuntimeError("timeout")

    settings = PineconeSettings(api_key=SecretStr("key"))
    adapter = PineconeAdapter(settings)
    adapter._client = object()
    adapter._index = BrokenIndex()
    assert await adapter.health() is False


@pytest.mark.asyncio
async def test_pinecone_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    """cleanup() sets client and index to None (lines 168-170)."""
    settings = PineconeSettings(api_key=SecretStr("key"))
    adapter = PineconeAdapter(settings)
    adapter._client = object()
    adapter._index = FakeIndex()
    await adapter.cleanup()
    assert adapter._client is None
    assert adapter._index is None


@pytest.mark.asyncio
async def test_pinecone_search_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """search() returns [] when query raises (lines 211-213)."""
    class BrokenIndex(FakeIndex):
        def query(self, **kwargs: Any) -> None:  # type: ignore[override]
            raise RuntimeError("query failed")

    settings = PineconeSettings(api_key=SecretStr("key"))
    adapter = PineconeAdapter(settings)

    async def _get_index() -> BrokenIndex:
        return BrokenIndex()

    monkeypatch.setattr(adapter, "_get_index", _get_index)
    result = await adapter.search("ns", [0.1])
    assert result == []


@pytest.mark.asyncio
async def test_pinecone_insert_delegates_to_upsert(monkeypatch: pytest.MonkeyPatch) -> None:
    """insert() delegates to upsert() (line 221)."""
    settings = PineconeSettings(api_key=SecretStr("key"))
    adapter = PineconeAdapter(settings)

    async def _get_index() -> FakeIndex:
        return FakeIndex()

    monkeypatch.setattr(adapter, "_get_index", _get_index)
    ids = await adapter.insert("ns", [VectorDocument(id="d1", vector=[0.1])])
    assert ids == ["d1"]


@pytest.mark.asyncio
async def test_pinecone_upsert_batch_zero_count_logs_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    """_upsert_batch() logs warning when upserted_count is 0 (line 265)."""
    class ZeroCountIndex(FakeIndex):
        def upsert(self, **kwargs: Any) -> dict[str, Any]:  # type: ignore[override]
            return {"upserted_count": 0}

    settings = PineconeSettings(api_key=SecretStr("key"))
    adapter = PineconeAdapter(settings)

    async def _get_index() -> ZeroCountIndex:
        return ZeroCountIndex()

    monkeypatch.setattr(adapter, "_get_index", _get_index)
    # must not raise even though upserted_count is 0
    ids = await adapter.upsert("ns", [VectorDocument(id="d1", vector=[0.1])])
    assert ids == ["d1"]


@pytest.mark.asyncio
async def test_pinecone_upsert_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """upsert() returns [] when an error occurs (lines 287-289)."""
    class BrokenUpsert(FakeIndex):
        def upsert(self, **kwargs: Any) -> None:  # type: ignore[override]
            raise RuntimeError("upsert failed")

    settings = PineconeSettings(api_key=SecretStr("key"))
    adapter = PineconeAdapter(settings)

    async def _get_index() -> BrokenUpsert:
        return BrokenUpsert()

    monkeypatch.setattr(adapter, "_get_index", _get_index)
    result = await adapter.upsert("ns", [VectorDocument(id="d1", vector=[0.1])])
    assert result == []


@pytest.mark.asyncio
async def test_pinecone_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    """delete() calls index.delete and returns True (lines 297-305)."""
    index = FakeIndex()
    settings = PineconeSettings(api_key=SecretStr("key"))
    adapter = PineconeAdapter(settings)

    async def _get_index() -> FakeIndex:
        return index

    monkeypatch.setattr(adapter, "_get_index", _get_index)
    result = await adapter.delete("ns", ["id1", "id2"])
    assert result is True
    assert index.deletes[0]["namespace"] == "ns"


@pytest.mark.asyncio
async def test_pinecone_delete_default_namespace(monkeypatch: pytest.MonkeyPatch) -> None:
    """delete() omits namespace when collection is 'default' (line 301)."""
    index = FakeIndex()
    settings = PineconeSettings(api_key=SecretStr("key"))
    adapter = PineconeAdapter(settings)

    async def _get_index() -> FakeIndex:
        return index

    monkeypatch.setattr(adapter, "_get_index", _get_index)
    result = await adapter.delete("default", ["id1"])
    assert result is True
    assert "namespace" not in index.deletes[0]


@pytest.mark.asyncio
async def test_pinecone_delete_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """delete() returns False when index.delete raises (lines 307-309)."""
    class BrokenDelete(FakeIndex):
        def delete(self, **kwargs: Any) -> None:  # type: ignore[override]
            raise RuntimeError("delete failed")

    settings = PineconeSettings(api_key=SecretStr("key"))
    adapter = PineconeAdapter(settings)

    async def _get_index() -> BrokenDelete:
        return BrokenDelete()

    monkeypatch.setattr(adapter, "_get_index", _get_index)
    result = await adapter.delete("ns", ["id1"])
    assert result is False


@pytest.mark.asyncio
async def test_pinecone_get(monkeypatch: pytest.MonkeyPatch) -> None:
    """get() fetches documents and maps vectors (lines 318-341)."""
    settings = PineconeSettings(api_key=SecretStr("key"))
    adapter = PineconeAdapter(settings)

    async def _get_index() -> FakeIndex:
        return FakeIndex()

    monkeypatch.setattr(adapter, "_get_index", _get_index)
    docs = await adapter.get("ns", ["doc-1"], include_vectors=True)
    assert len(docs) == 1
    assert docs[0].id == "doc-1"
    assert docs[0].vector == [1.0]


@pytest.mark.asyncio
async def test_pinecone_get_default_namespace(monkeypatch: pytest.MonkeyPatch) -> None:
    """get() omits namespace when collection is 'default' (line 327)."""
    index = FakeIndex()
    settings = PineconeSettings(api_key=SecretStr("key"))
    adapter = PineconeAdapter(settings)

    async def _get_index() -> FakeIndex:
        return index

    monkeypatch.setattr(adapter, "_get_index", _get_index)
    docs = await adapter.get("default", ["doc-1"])
    assert "namespace" not in index.fetches[0]


@pytest.mark.asyncio
async def test_pinecone_get_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """get() returns [] when index.fetch raises (lines 343-345)."""
    class BrokenFetch(FakeIndex):
        def fetch(self, **kwargs: Any) -> None:  # type: ignore[override]
            raise RuntimeError("fetch failed")

    settings = PineconeSettings(api_key=SecretStr("key"))
    adapter = PineconeAdapter(settings)

    async def _get_index() -> BrokenFetch:
        return BrokenFetch()

    monkeypatch.setattr(adapter, "_get_index", _get_index)
    result = await adapter.get("ns", ["id1"])
    assert result == []


@pytest.mark.asyncio
async def test_pinecone_count_with_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    """count() passes filter to describe_index_stats (line 358)."""
    index = FakeIndex()
    settings = PineconeSettings(api_key=SecretStr("key"))
    adapter = PineconeAdapter(settings)

    async def _get_index() -> FakeIndex:
        return index

    monkeypatch.setattr(adapter, "_get_index", _get_index)
    result = await adapter.count("default", filter_expr={"kind": "article"})
    assert result == 5


@pytest.mark.asyncio
async def test_pinecone_count_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """count() returns 0 when describe_index_stats raises (lines 367-369)."""
    class BrokenStats(FakeIndex):
        def describe_index_stats(self, **kwargs: Any) -> None:  # type: ignore[override]
            raise RuntimeError("stats failed")

    settings = PineconeSettings(api_key=SecretStr("key"))
    adapter = PineconeAdapter(settings)

    async def _get_index() -> BrokenStats:
        return BrokenStats()

    monkeypatch.setattr(adapter, "_get_index", _get_index)
    result = await adapter.count("ns")
    assert result == 0


@pytest.mark.asyncio
async def test_pinecone_create_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    """create_collection() logs and returns True (lines 378-382)."""
    settings = PineconeSettings(api_key=SecretStr("key"))
    adapter = PineconeAdapter(settings)
    result = await adapter.create_collection("ns", dimension=128)
    assert result is True


@pytest.mark.asyncio
async def test_pinecone_delete_collection_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """delete_collection() deletes all when collection is 'default' (line 394-395)."""
    index = FakeIndex()
    settings = PineconeSettings(api_key=SecretStr("key"))
    adapter = PineconeAdapter(settings)

    async def _get_index() -> FakeIndex:
        return index

    monkeypatch.setattr(adapter, "_get_index", _get_index)
    result = await adapter.delete_collection("default")
    assert result is True
    assert index.deletes[0].get("delete_all") is True
    assert "namespace" not in index.deletes[0]


@pytest.mark.asyncio
async def test_pinecone_delete_collection_namespace(monkeypatch: pytest.MonkeyPatch) -> None:
    """delete_collection() deletes namespace when name is not 'default' (lines 392-393)."""
    index = FakeIndex()
    settings = PineconeSettings(api_key=SecretStr("key"))
    adapter = PineconeAdapter(settings)

    async def _get_index() -> FakeIndex:
        return index

    monkeypatch.setattr(adapter, "_get_index", _get_index)
    result = await adapter.delete_collection("my-ns")
    assert result is True
    assert index.deletes[0]["namespace"] == "my-ns"


@pytest.mark.asyncio
async def test_pinecone_delete_collection_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """delete_collection() returns False when index.delete raises (lines 399-401)."""
    class BrokenDelete(FakeIndex):
        def delete(self, **kwargs: Any) -> None:  # type: ignore[override]
            raise RuntimeError("delete failed")

    settings = PineconeSettings(api_key=SecretStr("key"))
    adapter = PineconeAdapter(settings)

    async def _get_index() -> BrokenDelete:
        return BrokenDelete()

    monkeypatch.setattr(adapter, "_get_index", _get_index)
    result = await adapter.delete_collection("ns")
    assert result is False


@pytest.mark.asyncio
async def test_pinecone_list_collections_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """list_collections() returns [] when describe_index_stats raises (lines 417-419)."""
    class BrokenStats(FakeIndex):
        def describe_index_stats(self, **kwargs: Any) -> None:  # type: ignore[override]
            raise RuntimeError("stats failed")

    settings = PineconeSettings(api_key=SecretStr("key"))
    adapter = PineconeAdapter(settings)

    async def _get_index() -> BrokenStats:
        return BrokenStats()

    monkeypatch.setattr(adapter, "_get_index", _get_index)
    result = await adapter.list_collections()
    assert result == []


def test_pinecone_has_capability() -> None:
    """has_capability() returns True for known capabilities (lines 422-429)."""
    settings = PineconeSettings(api_key=SecretStr("key"))
    adapter = PineconeAdapter(settings)
    assert adapter.has_capability("vector_search") is True
    assert adapter.has_capability("serverless") is True
    assert adapter.has_capability("nonexistent") is False
