from __future__ import annotations

from typing import Any

import pytest

from oneiric.adapters.vector.common import VectorDocument
from oneiric.adapters.vector.pgvector import PgvectorAdapter, PgvectorSettings


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
