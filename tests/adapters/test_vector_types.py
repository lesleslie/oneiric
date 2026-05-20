from __future__ import annotations

from typing import Any

import pytest

from oneiric.adapters.vector.vector_types import (
    VectorBase,
    VectorBaseSettings,
    VectorCollection,
    VectorDocument,
    VectorSearchResult,
)


# ---------------------------------------------------------------------------
# Minimal concrete VectorBase implementation
# ---------------------------------------------------------------------------


class _Adapter(VectorBase):
    async def init(self) -> None: ...
    async def health(self) -> bool: return True
    async def cleanup(self) -> None: ...

    async def search(self, collection, query_vector, limit=10, filter_expr=None,
                     include_vectors=False, **kwargs) -> list[VectorSearchResult]:
        return [VectorSearchResult(id="r1", score=0.9)]

    async def insert(self, collection, documents, **kwargs) -> list[str]:
        return [d.id or "new" for d in documents]

    async def upsert(self, collection, documents, **kwargs) -> list[str]:
        return [d.id or "upserted" for d in documents]

    async def delete(self, collection, ids, **kwargs) -> bool:
        return True

    async def get(self, collection, ids, include_vectors=False, **kwargs) -> list[VectorDocument]:
        return [VectorDocument(id=i, vector=[0.1]) for i in ids]

    async def count(self, collection, filter_expr=None, **kwargs) -> int:
        return 42

    async def create_collection(self, name, dimension, distance_metric="cosine",
                                **kwargs) -> bool:
        return True

    async def delete_collection(self, name, **kwargs) -> bool:
        return True

    async def list_collections(self, **kwargs) -> list[str]:
        return ["col1"]

    async def _ensure_client(self) -> Any:
        return self._client

    async def _create_client(self) -> Any:
        return object()


def _make() -> _Adapter:
    return _Adapter(VectorBaseSettings())


# ---------------------------------------------------------------------------
# Tests — models
# ---------------------------------------------------------------------------


def test_vector_search_result() -> None:
    r = VectorSearchResult(id="x", score=0.8, metadata={"k": "v"}, vector=[1.0])
    assert r.id == "x"
    assert r.score == 0.8


def test_vector_document_defaults() -> None:
    doc = VectorDocument(vector=[0.1, 0.2])
    assert doc.id is None
    assert doc.metadata == {}


def test_vector_base_settings_defaults() -> None:
    s = VectorBaseSettings()
    assert s.default_dimension == 1536
    assert s.batch_size == 100


# ---------------------------------------------------------------------------
# Tests — VectorCollection delegation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vector_collection_search() -> None:
    adapter = _make()
    col = VectorCollection(adapter, "my-col")
    results = await col.search([0.1, 0.2], limit=5)
    assert len(results) == 1
    assert results[0].id == "r1"


@pytest.mark.asyncio
async def test_vector_collection_insert() -> None:
    adapter = _make()
    col = VectorCollection(adapter, "items")
    docs = [VectorDocument(id="d1", vector=[0.5])]
    ids = await col.insert(docs)
    assert "d1" in ids


@pytest.mark.asyncio
async def test_vector_collection_upsert() -> None:
    adapter = _make()
    col = VectorCollection(adapter, "items")
    docs = [VectorDocument(id="d2", vector=[0.5])]
    ids = await col.upsert(docs)
    assert "d2" in ids


@pytest.mark.asyncio
async def test_vector_collection_delete() -> None:
    adapter = _make()
    col = VectorCollection(adapter, "items")
    assert await col.delete(["d1", "d2"]) is True


@pytest.mark.asyncio
async def test_vector_collection_get() -> None:
    adapter = _make()
    col = VectorCollection(adapter, "items")
    docs = await col.get(["id1", "id2"])
    assert len(docs) == 2
    assert docs[0].id == "id1"


@pytest.mark.asyncio
async def test_vector_collection_count() -> None:
    adapter = _make()
    col = VectorCollection(adapter, "items")
    assert await col.count() == 42


@pytest.mark.asyncio
async def test_vector_collection_count_with_filter() -> None:
    adapter = _make()
    col = VectorCollection(adapter, "items")
    assert await col.count(filter_expr={"status": "active"}) == 42


# ---------------------------------------------------------------------------
# Tests — VectorBase.__getattr__ lazy collection creation
# ---------------------------------------------------------------------------


def test_getattr_creates_collection() -> None:
    adapter = _make()
    col = adapter.my_collection  # type: ignore[attr-defined]
    assert isinstance(col, VectorCollection)
    assert col.name == "my_collection"


def test_getattr_returns_cached_collection() -> None:
    adapter = _make()
    col1 = adapter.items  # type: ignore[attr-defined]
    col2 = adapter.items  # type: ignore[attr-defined]
    assert col1 is col2


# ---------------------------------------------------------------------------
# Tests — get_client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_client_delegates() -> None:
    adapter = _make()
    adapter._client = object()
    result = await adapter.get_client()
    assert result is adapter._client


# ---------------------------------------------------------------------------
# Tests — has_capability
# ---------------------------------------------------------------------------


def test_has_capability_default_false() -> None:
    adapter = _make()
    assert adapter.has_capability("some-cap") is False


# ---------------------------------------------------------------------------
# Tests — transaction context manager
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transaction_yields_client() -> None:
    adapter = _make()
    sentinel = object()
    adapter._client = sentinel

    async with adapter.transaction() as client:
        assert client is sentinel
