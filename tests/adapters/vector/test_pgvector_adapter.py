import json
from uuid import UUID

import pytest

from oneiric.adapters.vector.pgvector import PgvectorAdapter, PgvectorSettings
from oneiric.adapters.vector.vector_types import VectorDocument
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


# ---------------------------------------------------------------------------
# Tests — coverage gaps
# ---------------------------------------------------------------------------


@pytest.fixture()
def pool_adapter() -> tuple[PgvectorAdapter, FakeConnection]:
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
    return adapter, conn


@pytest.mark.asyncio
async def test_init_with_ensure_extension() -> None:
    """init() calls _ensure_extension when ensure_extension=True (lines 88-91)."""
    conn = FakeConnection()
    pool = FakePool(conn)
    settings = PgvectorSettings(
        database="app",
        db_schema="public",
        collection_prefix="vec_",
        ensure_extension=True,
    )

    async def _pool_factory(**_kwargs: object) -> FakePool:
        return pool

    adapter = PgvectorAdapter(settings, pool_factory=_pool_factory)
    await adapter.init()
    executed_sql = [sql for sql, _ in conn.executed]
    assert any("CREATE EXTENSION" in sql for sql in executed_sql)


@pytest.mark.asyncio
async def test_health_returns_true(pool_adapter: tuple[PgvectorAdapter, FakeConnection]) -> None:
    """health() executes SELECT 1 and returns True (lines 94-97)."""
    adapter, conn = pool_adapter
    result = await adapter.health()
    assert result is True
    assert any("SELECT 1" in sql for sql, _ in conn.executed)


@pytest.mark.asyncio
async def test_cleanup_closes_pool(pool_adapter: tuple[PgvectorAdapter, FakeConnection]) -> None:
    """cleanup() closes the pool and nils _pool (lines 103-107)."""
    adapter, _conn = pool_adapter
    await adapter.init()
    await adapter.cleanup()
    assert adapter._pool is None


@pytest.mark.asyncio
async def test_search_no_filter(pool_adapter: tuple[PgvectorAdapter, FakeConnection]) -> None:
    """search() uses $2 as limit param when no filter_expr (line 132)."""
    adapter, conn = pool_adapter
    await adapter.search("items", [0.1, 0.2], limit=5)
    sql, params = conn.fetch_calls[-1]
    assert "$2" in sql
    assert "metadata @> $2::jsonb" not in sql


@pytest.mark.asyncio
async def test_upsert_uses_on_conflict_update(pool_adapter: tuple[PgvectorAdapter, FakeConnection]) -> None:
    """upsert() calls _write_documents with upsert=True (line 162, 406)."""
    adapter, conn = pool_adapter
    inserted = await adapter.upsert(
        "items",
        [VectorDocument(id="u1", vector=[0.5], metadata={})],
    )
    assert "u1" in inserted
    sql = conn.fetchrow_calls[-1][0]
    assert "ON CONFLICT (id) DO UPDATE SET" in sql


@pytest.mark.asyncio
async def test_delete_with_ids(pool_adapter: tuple[PgvectorAdapter, FakeConnection]) -> None:
    """delete() executes DELETE WHERE id = ANY (lines 170-178)."""
    adapter, conn = pool_adapter
    result = await adapter.delete("items", ["id1", "id2"])
    assert result is True
    assert any("DELETE FROM" in sql for sql, _ in conn.executed)


@pytest.mark.asyncio
async def test_get_with_ids(pool_adapter: tuple[PgvectorAdapter, FakeConnection]) -> None:
    """get() fetches rows by id list (lines 187-196)."""
    adapter, conn = pool_adapter
    docs = await adapter.get("items", ["doc-1"])
    assert len(docs) == 1
    assert docs[0].id == "doc-1"
    assert any("WHERE id = ANY" in sql for sql, _ in conn.fetch_calls)


@pytest.mark.asyncio
async def test_count_no_filter(pool_adapter: tuple[PgvectorAdapter, FakeConnection]) -> None:
    """count() uses COUNT(*) without WHERE when filter_expr is None (lines 216-217)."""
    adapter, conn = pool_adapter
    result = await adapter.count("items")
    assert result == 12
    sql, _ = conn.fetchval_calls[-1]
    assert "WHERE" not in sql


@pytest.mark.asyncio
async def test_create_collection(pool_adapter: tuple[PgvectorAdapter, FakeConnection]) -> None:
    """create_collection() issues CREATE TABLE and CREATE INDEX (lines 229-258)."""
    adapter, conn = pool_adapter
    ok = await adapter.create_collection("things", dimension=128, distance_metric="cosine")
    assert ok is True
    all_sql = [sql for sql, _ in conn.executed]
    assert any("CREATE TABLE" in sql for sql in all_sql)
    assert any("CREATE INDEX" in sql for sql in all_sql)


@pytest.mark.asyncio
async def test_delete_collection(pool_adapter: tuple[PgvectorAdapter, FakeConnection]) -> None:
    """delete_collection() issues DROP TABLE (lines 261-269)."""
    adapter, conn = pool_adapter
    ok = await adapter.delete_collection("things")
    assert ok is True
    assert any("DROP TABLE" in sql for sql, _ in conn.executed)


@pytest.mark.asyncio
async def test_list_collections() -> None:
    """list_collections() queries information_schema.tables (lines 272-282)."""

    class TableNameConnection(FakeConnection):
        async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
            self.fetch_calls.append((sql, params))
            return [{"table_name": "vec_items"}]

    conn = TableNameConnection()
    pool = FakePool(conn)
    settings = PgvectorSettings(
        database="app", db_schema="public", collection_prefix="vec_", ensure_extension=False
    )

    async def _pool_factory(**_kwargs: object) -> FakePool:
        return pool

    adapter = PgvectorAdapter(settings, pool_factory=_pool_factory)
    result = await adapter.list_collections()
    assert result == ["vec_items"]
    sql, _ = conn.fetch_calls[-1]
    assert "information_schema.tables" in sql


@pytest.mark.asyncio
async def test_create_client_default_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    """_create_client uses asyncpg.create_pool and pgvector.asyncpg.register_vector when no factory (lines 293-315)."""
    import sys
    import types

    created_pools: list[dict] = []

    async def fake_create_pool(*, init, **kwargs: object) -> FakePool:
        conn = FakeConnection()
        pool = FakePool(conn)
        await init(conn)
        created_pools.append(kwargs)
        return pool

    fake_asyncpg = types.ModuleType("asyncpg")
    fake_asyncpg.create_pool = fake_create_pool  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "asyncpg", fake_asyncpg)

    register_calls: list[object] = []

    async def fake_register_vector(conn: object) -> None:
        register_calls.append(conn)

    fake_pgvector_asyncpg = types.ModuleType("pgvector.asyncpg")
    fake_pgvector_asyncpg.register_vector = fake_register_vector  # type: ignore[attr-defined]
    fake_pgvector = types.ModuleType("pgvector")
    monkeypatch.setitem(sys.modules, "pgvector", fake_pgvector)
    monkeypatch.setitem(sys.modules, "pgvector.asyncpg", fake_pgvector_asyncpg)

    settings = PgvectorSettings(database="testdb", ensure_extension=False)
    adapter = PgvectorAdapter(settings)
    await adapter.init()
    assert len(created_pools) == 1
    assert len(register_calls) == 1


def test_connection_kwargs_dsn() -> None:
    """_connection_kwargs returns {dsn: ...} when dsn is set (line 332)."""
    settings = PgvectorSettings(dsn="postgresql://user:pass@host/db")
    adapter = PgvectorAdapter(settings)
    kwargs = adapter._connection_kwargs()
    assert kwargs == {"dsn": "postgresql://user:pass@host/db"}


def test_distance_operator_euclidean() -> None:
    """_distance_operator returns '<->' for euclidean (line 352)."""
    settings = PgvectorSettings(default_distance_metric="euclidean")
    adapter = PgvectorAdapter(settings)
    assert adapter._distance_operator() == "<->"


def test_distance_operator_dot_product() -> None:
    """_distance_operator returns '<#>' for dot_product (line 354)."""
    settings = PgvectorSettings(default_distance_metric="dot_product")
    adapter = PgvectorAdapter(settings)
    assert adapter._distance_operator() == "<#>"


@pytest.mark.asyncio
async def test_cleanup_no_pool_is_noop(pool_adapter: tuple[PgvectorAdapter, FakeConnection]) -> None:
    """cleanup() returns early when _pool is None (line 104)."""
    adapter, _conn = pool_adapter
    assert adapter._pool is None
    await adapter.cleanup()  # must not raise
    assert adapter._pool is None


@pytest.mark.asyncio
async def test_delete_empty_ids_returns_true(pool_adapter: tuple[PgvectorAdapter, FakeConnection]) -> None:
    """delete() returns True immediately when ids is empty (line 172)."""
    adapter, conn = pool_adapter
    result = await adapter.delete("items", [])
    assert result is True
    assert not any("DELETE" in sql for sql, _ in conn.executed)


@pytest.mark.asyncio
async def test_get_empty_ids_returns_empty(pool_adapter: tuple[PgvectorAdapter, FakeConnection]) -> None:
    """get() returns [] immediately when ids is empty (line 189)."""
    adapter, _conn = pool_adapter
    result = await adapter.get("items", [])
    assert result == []


@pytest.mark.asyncio
async def test_create_collection_with_ensure_extension() -> None:
    """create_collection creates extension when ensure_extension=True (line 236)."""
    conn = FakeConnection()
    pool = FakePool(conn)
    settings = PgvectorSettings(
        database="app",
        db_schema="public",
        collection_prefix="vec_",
        ensure_extension=True,
    )

    async def _pool_factory(**_kwargs: object) -> FakePool:
        return pool

    adapter = PgvectorAdapter(settings, pool_factory=_pool_factory)
    await adapter.create_collection("things", dimension=64)
    all_sql = [sql for sql, _ in conn.executed]
    # Both the _ensure_extension call (init isn't used here) and the
    # create_collection internal extension check should emit CREATE EXTENSION
    extension_calls = [s for s in all_sql if "CREATE EXTENSION" in s]
    assert len(extension_calls) >= 1


def test_normalize_collection_digit_prefix() -> None:
    """_normalize_collection_name prepends v_ when name starts with digit after strip (line 376)."""
    settings = PgvectorSettings(collection_prefix="")
    adapter = PgvectorAdapter(settings)
    result = adapter._normalize_collection_name("9things")
    assert result.startswith("v_")
    assert "9things" in result
