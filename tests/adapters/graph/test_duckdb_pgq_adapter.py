"""Tests for the DuckDB PGQ adapter."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from oneiric.adapters.graph.duckdb_pgq import DuckDBPGQAdapter, DuckDBPGQSettings


class FakeConnection:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.executed_many: list[tuple[str, Sequence[tuple[Any, ...]]]] = []
        self.closed = False
        self._result_queue: list[
            tuple[list[tuple[Any, ...]], list[tuple[str, Any]]]
        ] = []
        self.description: list[tuple[str, Any]] | None = None
        self._last_result: list[tuple[Any, ...]] = []

    def queue_result(
        self, rows: list[tuple[Any, ...]], columns: list[str] | None = None
    ) -> None:
        description = [(col, None) for col in (columns or [])]
        self._result_queue.append((rows, description))

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> FakeConnection:
        self.executed.append((sql, params))
        if self._result_queue:
            rows, description = self._result_queue.pop(0)
        else:
            rows, description = ([], [])
        self._last_result = rows
        self.description = description
        return self

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._last_result)

    def executemany(self, sql: str, sequences: Sequence[tuple[Any, ...]]) -> None:
        self.executed_many.append((sql, sequences))

    def close(self) -> None:
        self.closed = True


async def immediate_executor(func, args, kwargs):
    return func(*args, **kwargs)


@pytest.fixture()
def fake_connection() -> FakeConnection:
    return FakeConnection()


@pytest.fixture()
def adapter(fake_connection: FakeConnection) -> DuckDBPGQAdapter:
    settings = DuckDBPGQSettings(database=":memory:", install_pgq=True)

    return DuckDBPGQAdapter(
        settings,
        connection_factory=lambda: fake_connection,
        sync_executor=immediate_executor,
    )


@pytest.mark.asyncio()
async def test_init_and_health(
    adapter: DuckDBPGQAdapter, fake_connection: FakeConnection
) -> None:
    fake_connection.queue_result([], [])
    fake_connection.queue_result([], [])
    fake_connection.queue_result([], [])
    await adapter.init()
    fake_connection.queue_result([(1,)], ["ok"])
    assert await adapter.health() is True


@pytest.mark.asyncio()
async def test_ingest_and_neighbors(
    adapter: DuckDBPGQAdapter, fake_connection: FakeConnection
) -> None:
    fake_connection.queue_result([], [])
    fake_connection.queue_result([], [])
    fake_connection.queue_result([], [])
    await adapter.init()
    await adapter.ingest_edges([("a", "b"), ("a", "c")])
    fake_connection.queue_result([("b",), ("c",)], [adapter._settings.target_column])  # type: ignore[attr-defined]
    neighbors = await adapter.neighbors("a")
    assert neighbors == ["b", "c"]


@pytest.mark.asyncio()
async def test_query_returns_dicts(
    adapter: DuckDBPGQAdapter, fake_connection: FakeConnection
) -> None:
    fake_connection.queue_result([], [])
    fake_connection.queue_result([], [])
    fake_connection.queue_result([], [])
    await adapter.init()
    fake_connection.queue_result([(1, "two")], ["col1", "col2"])
    rows = await adapter.query("SELECT 1 AS col1, 'two' AS col2")
    assert rows == [{"col1": 1, "col2": "two"}]


@pytest.mark.asyncio()
async def test_cleanup(
    adapter: DuckDBPGQAdapter, fake_connection: FakeConnection
) -> None:
    fake_connection.queue_result([], [])
    fake_connection.queue_result([], [])
    fake_connection.queue_result([], [])
    await adapter.init()
    await adapter.cleanup()
    assert fake_connection.closed is True


# ---------------------------------------------------------------------------
# Tests — coverage gaps
# ---------------------------------------------------------------------------


def test_ensure_database_dir_real_path(tmp_path) -> None:
    """ensure_database_dir() creates parent dirs for non-memory databases (lines 42-44)."""
    from oneiric.adapters.graph.duckdb_pgq import DuckDBPGQSettings

    db_path = tmp_path / "sub" / "graph.db"
    settings = DuckDBPGQSettings(database=str(db_path))
    settings.ensure_database_dir()
    assert db_path.parent.exists()


@pytest.mark.asyncio()
async def test_cleanup_awaitable_close() -> None:
    """cleanup() awaits close() when it returns a coroutine (line 101)."""
    closed: list[bool] = []

    class AsyncCloseConn(FakeConnection):
        async def close(self) -> None:
            closed.append(True)

    conn = AsyncCloseConn()
    conn.queue_result([], [])
    conn.queue_result([], [])
    conn.queue_result([], [])
    adapter = DuckDBPGQAdapter(
        DuckDBPGQSettings(database=":memory:"),
        connection_factory=lambda: conn,
        sync_executor=immediate_executor,
    )
    await adapter.init()
    await adapter.cleanup()
    assert closed == [True]


@pytest.mark.asyncio()
async def test_ingest_edges_empty(adapter: DuckDBPGQAdapter, fake_connection: FakeConnection) -> None:
    """ingest_edges() returns early when edges is empty (line 106)."""
    fake_connection.queue_result([], [])
    fake_connection.queue_result([], [])
    fake_connection.queue_result([], [])
    await adapter.init()
    before = len(fake_connection.executed_many)
    await adapter.ingest_edges([])
    assert len(fake_connection.executed_many) == before  # no executemany call


@pytest.mark.asyncio()
async def test_query_no_columns_returns_enumerated_dict(
    adapter: DuckDBPGQAdapter, fake_connection: FakeConnection
) -> None:
    """query() returns dict(enumerate(row)) when no column names (line 136)."""
    fake_connection.queue_result([], [])
    fake_connection.queue_result([], [])
    fake_connection.queue_result([], [])
    await adapter.init()
    # Queue result with no columns (empty description)
    fake_connection.queue_result([(42, "hello")], columns=None)
    # Force description to None so columns list will be empty
    fake_connection.description = None
    rows = await adapter.query("PRAGMA database_list")
    assert rows == [{0: 42, 1: "hello"}]


@pytest.mark.asyncio()
async def test_ensure_connection_awaitable_factory() -> None:
    """_ensure_connection awaits factory result when it returns a coroutine (line 146)."""
    conn = FakeConnection()
    conn.queue_result([], [])
    conn.queue_result([], [])
    conn.queue_result([], [])

    async def async_factory() -> FakeConnection:
        return conn

    adapter = DuckDBPGQAdapter(
        DuckDBPGQSettings(),
        connection_factory=async_factory,
        sync_executor=immediate_executor,
    )
    await adapter.init()
    assert adapter._conn is conn


@pytest.mark.asyncio()
async def test_bootstrap_early_return_when_no_conn() -> None:
    """_bootstrap() returns immediately when _conn is None (line 155)."""
    adapter = DuckDBPGQAdapter(DuckDBPGQSettings(), sync_executor=immediate_executor)
    # _conn is None — should return without error
    await adapter._bootstrap()


@pytest.mark.asyncio()
async def test_run_sync_uses_asyncio_to_thread(
    fake_connection: FakeConnection,
) -> None:
    """_run_sync uses asyncio.to_thread when no sync_executor provided (line 194)."""
    fake_connection.queue_result([], [])
    fake_connection.queue_result([], [])
    fake_connection.queue_result([], [])
    adapter = DuckDBPGQAdapter(
        DuckDBPGQSettings(database=":memory:"),
        connection_factory=lambda: fake_connection,
        # no sync_executor → falls through to asyncio.to_thread
    )
    await adapter.init()
    fake_connection.queue_result([(1,)], ["v"])
    rows = await adapter.query("SELECT 1")
    assert rows == [{"v": 1}]


def test_default_connection_factory(monkeypatch) -> None:
    """_default_connection_factory creates duckdb.connect() when duckdb is importable (lines 197-204)."""
    import sys
    import types

    created: list[dict] = []

    def fake_connect(database: str, read_only: bool = False) -> FakeConnection:
        created.append({"database": database, "read_only": read_only})
        return FakeConnection()

    fake_duckdb = types.ModuleType("duckdb")
    fake_duckdb.connect = fake_connect  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "duckdb", fake_duckdb)

    adapter = DuckDBPGQAdapter(DuckDBPGQSettings(database=":memory:"))
    conn = adapter._default_connection_factory()
    assert isinstance(conn, FakeConnection)
    assert created[0]["database"] == ":memory:"
