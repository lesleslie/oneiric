from __future__ import annotations

from typing import Any

import pytest

from oneiric.adapters.vector.pgvector import PgvectorAdapter, PgvectorSettings
from oneiric.adapters.vector.vector_types import VectorDocument


class _FakePgConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.search_results = [
            {
                "id": "doc1",
                "metadata": {"topic": "demo"},
                "embedding": [0.01, 0.02],
                "distance": 0.1,
            },
        ]
        self.get_results = [
            {"id": "doc1", "metadata": {"topic": "demo"}, "embedding": [0.01, 0.02]},
        ]
        self.count_value = 4
        self.collection_names = ["vectors_demo"]

    async def execute(self, query: str, *args: Any) -> str:
        self.calls.append(("execute", query.strip()))
        return "OK"

    async def fetch(self, query: str, *args: Any):
        self.calls.append(("fetch", query.strip()))
        if "information_schema.tables" in query:
            return [{"table_name": name} for name in self.collection_names]
        if "ORDER BY distance" in query:
            return self.search_results
        if "WHERE id = ANY" in query:
            return self.get_results
        return []

    async def fetchrow(self, query: str, *args: Any):
        self.calls.append(("fetchrow", query.strip()))
        return {"id": args[0]}

    async def fetchval(self, query: str, *args: Any):
        self.calls.append(("fetchval", query.strip()))
        return self.count_value


class _FakePgPool:
    def __init__(self) -> None:
        self.connection = _FakePgConnection()
        self.closed = False
        self.acquires = 0
        self.releases = 0

    async def acquire(self) -> _FakePgConnection:
        self.acquires += 1
        return self.connection

    async def release(self, _conn: _FakePgConnection) -> None:
        self.releases += 1

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_pgvector_adapter_roundtrip() -> None:
    pool = _FakePgPool()

    init_kwargs: dict[str, Any] = {}

    async def pool_factory(**kwargs: Any) -> _FakePgPool:
        init_kwargs.update(kwargs)
        return pool

    registered: list[Any] = []

    async def register_vector(conn: Any) -> None:
        registered.append(conn)

    adapter = PgvectorAdapter(
        PgvectorSettings(collection_prefix="vectors_"),
        pool_factory=pool_factory,
        register_vector=register_vector,
    )

    await adapter.init()
    init_fn = init_kwargs.get("init")
    assert callable(init_fn)
    await init_fn("fake-conn")
    assert registered == ["fake-conn"]
    await adapter.create_collection("demo", dimension=2)
    inserted = await adapter.insert(
        "demo",
        [VectorDocument(id="doc1", vector=[0.1, 0.2], metadata={"topic": "demo"})],
    )
    assert inserted == ["doc1"]
    upserted = await adapter.upsert(
        "demo",
        [VectorDocument(id="doc1", vector=[0.3, 0.4], metadata={"topic": "demo"})],
    )
    assert upserted == ["doc1"]
    results = await adapter.search(
        "demo",
        query_vector=[0.1, 0.2],
        limit=5,
        filter_expr={"topic": "demo"},
        include_vectors=True,
    )
    assert results[0].id == "doc1"
    assert results[0].vector == [0.01, 0.02]

    docs = await adapter.get("demo", ["doc1"], include_vectors=False)
    assert docs[0].id == "doc1"
    assert docs[0].metadata == {"topic": "demo"}

    assert await adapter.count("demo") == 4
    assert await adapter.list_collections() == ["vectors_demo"]
    assert await adapter.delete("demo", ["doc1"])
    assert await adapter.delete_collection("demo")
    await adapter.cleanup()
    assert pool.closed


@pytest.mark.asyncio
async def test_pgvector_namespace_acl_default_deny() -> None:
    """REGRESSION: caller_namespace != target_namespace without grant raises PermissionError."""
    adapter = PgvectorAdapter(
        PgvectorSettings(caller_namespace="akosha", cross_namespace_grant=False)
    )
    with pytest.raises(PermissionError, match="cannot read target_namespace='sb'"):
        adapter.assert_caller_namespace_allowed("sb")


@pytest.mark.asyncio
async def test_pgvector_namespace_acl_same_namespace_allowed() -> None:
    """Same-namespace access is always allowed (no grant required)."""
    adapter = PgvectorAdapter(PgvectorSettings(caller_namespace="akosha"))
    assert adapter.assert_caller_namespace_allowed("akosha") == "akosha"
    # None defaults to caller's own namespace.
    assert adapter.assert_caller_namespace_allowed(None) == "akosha"


@pytest.mark.asyncio
async def test_pgvector_namespace_acl_admin_grant_allows_cross_namespace() -> None:
    """With cross_namespace_grant=True, the admin can read other namespaces."""
    adapter = PgvectorAdapter(
        PgvectorSettings(caller_namespace="akosha", cross_namespace_grant=True)
    )
    assert adapter.assert_caller_namespace_allowed("sb") == "sb"
