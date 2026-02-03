import json
from uuid import UUID

import pytest

from oneiric.adapters.vector.vector_types import VectorDocument
from oneiric.adapters.vector.pgvector import PgvectorAdapter, PgvectorSettings
from oneiric.core.lifecycle import LifecycleError


class FakeConnection:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[object, ...]]] = []
        self.fetch_calls: list[tuple[str, tuple[object, ...]]] = []
        self.fetchrow_calls: list[tuple[str, tuple[object, ...]]] = []
        self.fetchval_calls: list[tuple[str, tuple[object, ...]]] = []

    async def execute(self, sql: str, *params: object) -> None:
        self.executed.append((sql, params))

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        self.fetch_calls.append((sql, params))
        return [
            {
                "id": "doc-1",
                "metadata": {"k": "v"},
                "embedding": [0.1, 0.2],
                "distance": 0.25,
            },
        ]

    async def fetchrow(self, sql: str, *params: object) -> dict[str, object] | None:
        self.fetchrow_calls.append((sql, params))
        return {"id": params[0]}

    async def fetchval(self, sql: str, *params: object) -> object:
        self.fetchval_calls.append((sql, params))
        return 12


class FakePool:
    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn

    async def acquire(self) -> FakeConnection:
        return self._conn

    async def release(self, conn: FakeConnection) -> None:
        assert conn is self._conn

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_pgvector_helpers_and_connection_kwargs() -> None:
    settings = PgvectorSettings(
        host="db",
        port=5432,
        user="user",
        password="secret",
        database="app",
        db_schema="data",
        ssl=True,
        statement_timeout_ms=2500,
        collection_prefix="vec_",
    )
    adapter = PgvectorAdapter(settings)

    assert adapter._distance_operator() == "<=>"
    assert adapter._index_operator("euclidean") == "vector_l2_ops"
    assert adapter._index_operator("dot_product") == "vector_ip_ops"
    assert adapter._index_operator("cosine") == "vector_cosine_ops"

    assert adapter._normalize_collection_name("items") == "vec_items"
    assert adapter._normalize_collection_name("9items") == "vec_9items"

    empty_settings = settings.model_copy(update={"collection_prefix": ""})
    empty_adapter = PgvectorAdapter(empty_settings)
    with pytest.raises(LifecycleError, match="pgvector-invalid-collection-name"):
        empty_adapter._normalize_collection_name("")

    assert adapter._sanitize_identifier("data") == "data"
    assert adapter._sanitize_identifier("9data").startswith("v_")
    with pytest.raises(LifecycleError, match="pgvector-invalid-identifier"):
        adapter._sanitize_identifier("")

    kwargs = adapter._connection_kwargs()
    assert kwargs["host"] == "db"
    assert kwargs["ssl"] is True
    assert kwargs["command_timeout"] == 2.5


@pytest.mark.asyncio
async def test_pgvector_search_and_write_documents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FakeConnection()
    pool = FakePool(conn)
    settings = PgvectorSettings(
        database="app",
        db_schema="public",
        collection_prefix="vec_",
        ensure_extension=False,
    )

    async def _pool_factory(**_kwargs: object) -> FakePool:
        return pool

    adapter = PgvectorAdapter(settings, pool_factory=_pool_factory)

    results = await adapter.search(
        "items",
        [0.1, 0.2],
        limit=3,
        filter_expr={"kind": "demo"},
        include_vectors=True,
    )
    assert results[0].id == "doc-1"
    assert results[0].vector == [0.1, 0.2]
    assert "metadata @> $2::jsonb" in conn.fetch_calls[0][0]
    assert json.loads(conn.fetch_calls[0][1][1]) == {"kind": "demo"}

    monkeypatch.setattr(
        "oneiric.adapters.vector.pgvector.uuid4",
        lambda: UUID("00000000-0000-0000-0000-000000000123"),
    )
    inserted = await adapter.insert(
        "items",
        [VectorDocument(id=None, vector=[0.2], metadata={"a": 1})],
    )
    assert inserted == ["00000000-0000-0000-0000-000000000123"]

    count = await adapter.count("items", filter_expr={"kind": "demo"})
    assert count == 12
