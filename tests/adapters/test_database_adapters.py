from __future__ import annotations

from typing import Any

import pytest

from oneiric.adapters.database.mysql import MySQLDatabaseAdapter, MySQLDatabaseSettings
from oneiric.adapters.database.postgres import (
    PostgresDatabaseAdapter,
    PostgresDatabaseSettings,
)
from oneiric.adapters.database.sqlite import (
    SQLiteDatabaseAdapter,
    SQLiteDatabaseSettings,
)


class _DummyPgConnection:
    def __init__(self, history: list[tuple[str, str]]) -> None:
        self.history = history

    async def execute(self, query: str) -> str:
        self.history.append(("health", query))
        return "OK"


class _DummyPgPool:
    def __init__(self) -> None:
        self.history: list[tuple[str, str]] = []
        self.closed = False

    async def execute(self, query: str, *args: Any) -> str:
        self.history.append(("execute", query))
        return "EXECUTED"

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.history.append(("fetch", query))
        return [{"value": 1}]

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any]:
        self.history.append(("fetchrow", query))
        return {"value": 1}

    async def acquire(self) -> _DummyPgConnection:
        return _DummyPgConnection(self.history)

    async def release(self, _: _DummyPgConnection) -> None:
        self.history.append(("release", ""))

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_postgres_adapter_executes_and_fetches() -> None:
    pool = _DummyPgPool()

    async def pool_factory(**_: Any) -> _DummyPgPool:
        return pool

    adapter = PostgresDatabaseAdapter(
        PostgresDatabaseSettings(), pool_factory=pool_factory
    )
    await adapter.init()
    assert await adapter.health()
    await adapter.execute("UPDATE foo SET bar=1")
    rows = await adapter.fetch_all("SELECT * FROM foo")
    assert rows == [{"value": 1}]
    row = await adapter.fetch_one("SELECT * FROM foo LIMIT 1")
    assert row == {"value": 1}
    await adapter.cleanup()
    assert pool.closed


class _DummyMySQLCursor:
    def __init__(self, store: dict[str, Any]) -> None:
        self.store = store
        self.rowcount = 1

    async def execute(self, query: str, args: tuple[Any, ...] = ()) -> None:
        self.store["last_query"] = query
        self.store["last_args"] = args

    async def fetchall(self) -> list[tuple[int]]:
        return [(1,)]

    async def fetchone(self) -> tuple[int] | None:
        return (1,)

    async def close(self) -> None:  # pragma: no cover - trivial
        return None


class _DummyMySQLConnection:
    def __init__(self, store: dict[str, Any]) -> None:
        self.store = store

    async def cursor(self) -> _DummyMySQLCursor:
        return _DummyMySQLCursor(self.store)

    async def commit(self) -> None:
        self.store["committed"] = True


class _DummyMySQLPool:
    def __init__(self) -> None:
        self.store: dict[str, Any] = {}
        self.closed = False

    async def acquire(self) -> _DummyMySQLConnection:
        return _DummyMySQLConnection(self.store)

    def release(self, _conn: _DummyMySQLConnection) -> None:
        self.store["released"] = True

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


@pytest.mark.asyncio
async def test_mysql_adapter_executes_queries() -> None:
    pool = _DummyMySQLPool()

    async def pool_factory(**_: Any) -> _DummyMySQLPool:
        return pool

    adapter = MySQLDatabaseAdapter(MySQLDatabaseSettings(), pool_factory=pool_factory)
    await adapter.init()
    await adapter.execute("INSERT INTO foo VALUES (%s)", 1)
    rows = await adapter.fetch_all("SELECT * FROM foo")
    assert rows == [(1,)]
    row = await adapter.fetch_one("SELECT * FROM foo LIMIT 1")
    assert row == (1,)
    await adapter.cleanup()
    assert pool.closed


@pytest.mark.asyncio
async def test_sqlite_adapter_roundtrip(tmp_path) -> None:
    pytest.importorskip("aiosqlite")
    settings = SQLiteDatabaseSettings(path=str(tmp_path / "db.sqlite3"))
    adapter = SQLiteDatabaseAdapter(settings)
    await adapter.init()
    await adapter.execute(
        "CREATE TABLE IF NOT EXISTS foo (id INTEGER PRIMARY KEY, value TEXT)"
    )
    await adapter.execute("INSERT INTO foo(value) VALUES (?)", "hello")
    rows = await adapter.fetch_all("SELECT value FROM foo")
    assert rows[0][0] == "hello"
    row = await adapter.fetch_one("SELECT value FROM foo WHERE value = ?", "hello")
    assert row[0] == "hello"
    await adapter.cleanup()


# ---------------------------------------------------------------------------
# SQLite — coverage gap tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sqlite_init_idempotent() -> None:
    """Second init() returns early when connection already exists."""
    pytest.importorskip("aiosqlite")
    adapter = SQLiteDatabaseAdapter()
    await adapter.init()
    conn_before = adapter._conn
    await adapter.init()
    assert adapter._conn is conn_before
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_sqlite_init_with_pragmas(tmp_path: Any) -> None:
    """PRAGMAs supplied in settings are applied during init."""
    pytest.importorskip("aiosqlite")
    settings = SQLiteDatabaseSettings(
        path=str(tmp_path / "pragma.sqlite3"),
        pragmas={"journal_mode": "WAL"},
    )
    adapter = SQLiteDatabaseAdapter(settings)
    await adapter.init()
    rows = await adapter.fetch_all("PRAGMA journal_mode")
    assert rows[0][0] == "wal"
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_sqlite_health_returns_true() -> None:
    """health() runs SELECT 1 and returns True."""
    pytest.importorskip("aiosqlite")
    adapter = SQLiteDatabaseAdapter()
    await adapter.init()
    assert await adapter.health() is True
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_sqlite_cleanup_no_conn_is_noop() -> None:
    """cleanup() returns early when connection has never been opened."""
    adapter = SQLiteDatabaseAdapter()
    assert adapter._conn is None
    await adapter.cleanup()  # must not raise


def test_sqlite_ensure_conn_raises() -> None:
    """_ensure_conn raises LifecycleError when adapter is not initialised."""
    from oneiric.core.lifecycle import LifecycleError

    adapter = SQLiteDatabaseAdapter()
    with pytest.raises(LifecycleError, match="sqlite-connection-not-initialized"):
        adapter._ensure_conn()


# ---------------------------------------------------------------------------
# PostgreSQL — coverage gap tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_postgres_init_idempotent() -> None:
    """Second call to init() returns early when pool already exists."""
    pool = _DummyPgPool()

    async def pool_factory(**_: Any) -> _DummyPgPool:
        return pool

    adapter = PostgresDatabaseAdapter(
        PostgresDatabaseSettings(), pool_factory=pool_factory
    )
    await adapter.init()
    pool_before = adapter._pool
    await adapter.init()
    assert adapter._pool is pool_before
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_postgres_init_with_dsn() -> None:
    """DSN setting is forwarded to pool factory conn_kwargs."""
    received: list[dict[str, Any]] = []
    pool = _DummyPgPool()

    async def pool_factory(**kw: Any) -> _DummyPgPool:
        received.append(kw)
        return pool

    adapter = PostgresDatabaseAdapter(
        PostgresDatabaseSettings(dsn="postgresql://user:pw@host/db"),
        pool_factory=pool_factory,
    )
    await adapter.init()
    assert received[0]["dsn"] == "postgresql://user:pw@host/db"
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_postgres_cleanup_no_pool_is_noop() -> None:
    """cleanup() returns early when pool is None."""
    adapter = PostgresDatabaseAdapter(PostgresDatabaseSettings())
    assert adapter._pool is None
    await adapter.cleanup()  # must not raise


def test_postgres_ensure_pool_raises() -> None:
    """_ensure_pool raises LifecycleError when not initialised."""
    from oneiric.core.lifecycle import LifecycleError

    adapter = PostgresDatabaseAdapter(PostgresDatabaseSettings())
    with pytest.raises(LifecycleError, match="postgres-pool-not-initialized"):
        adapter._ensure_pool()


def test_postgres_connection_kwargs_with_timeout() -> None:
    """statement_timeout_ms is translated into statement_cache_size and command_timeout."""
    settings = PostgresDatabaseSettings(statement_timeout_ms=5000)
    adapter = PostgresDatabaseAdapter(settings)
    kwargs = adapter._connection_kwargs()
    assert kwargs["statement_cache_size"] == 0
    assert kwargs["command_timeout"] == 5.0


def test_postgres_connection_kwargs_with_ssl() -> None:
    """ssl=True is forwarded to conn kwargs."""
    settings = PostgresDatabaseSettings(ssl=True)
    adapter = PostgresDatabaseAdapter(settings)
    kwargs = adapter._connection_kwargs()
    assert kwargs["ssl"] is True


@pytest.mark.asyncio
async def test_postgres_init_via_asyncpg(monkeypatch: pytest.MonkeyPatch) -> None:
    """When pool_factory is None, asyncpg.create_pool is used."""
    import asyncpg

    pool = _DummyPgPool()

    async def fake_create_pool(**_: Any) -> _DummyPgPool:
        return pool

    monkeypatch.setattr(asyncpg, "create_pool", fake_create_pool)
    adapter = PostgresDatabaseAdapter(PostgresDatabaseSettings())
    await adapter.init()
    assert adapter._pool is pool
    await adapter.cleanup()


# ---------------------------------------------------------------------------
# MySQL — coverage gap tests (pool_factory injected throughout)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mysql_init_idempotent() -> None:
    """Second call to init() returns early when pool already exists."""
    pool = _DummyMySQLPool()

    async def pool_factory(**_: Any) -> _DummyMySQLPool:
        return pool

    adapter = MySQLDatabaseAdapter(MySQLDatabaseSettings(), pool_factory=pool_factory)
    await adapter.init()
    pool_before = adapter._pool
    await adapter.init()
    assert adapter._pool is pool_before
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_mysql_health() -> None:
    """health() acquires a connection, executes SELECT 1, and returns True."""
    pool = _DummyMySQLPool()

    async def pool_factory(**_: Any) -> _DummyMySQLPool:
        return pool

    adapter = MySQLDatabaseAdapter(MySQLDatabaseSettings(), pool_factory=pool_factory)
    await adapter.init()
    assert await adapter.health() is True
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_mysql_cleanup_no_pool_is_noop() -> None:
    """cleanup() returns early when pool is None."""
    adapter = MySQLDatabaseAdapter(MySQLDatabaseSettings())
    assert adapter._pool is None
    await adapter.cleanup()  # must not raise


@pytest.mark.asyncio
async def test_mysql_execute_with_autocommit_false() -> None:
    """execute() calls conn.commit() when autocommit=False."""
    pool = _DummyMySQLPool()

    async def pool_factory(**_: Any) -> _DummyMySQLPool:
        return pool

    settings = MySQLDatabaseSettings(autocommit=False)
    adapter = MySQLDatabaseAdapter(settings, pool_factory=pool_factory)
    await adapter.init()
    await adapter.execute("UPDATE foo SET bar=1")
    assert pool.store.get("committed") is True
    await adapter.cleanup()


def test_mysql_ensure_pool_raises() -> None:
    """_ensure_pool raises LifecycleError when not initialised."""
    from oneiric.core.lifecycle import LifecycleError

    adapter = MySQLDatabaseAdapter(MySQLDatabaseSettings())
    with pytest.raises(LifecycleError, match="mysql-pool-not-initialized"):
        adapter._ensure_pool()


@pytest.mark.asyncio
async def test_mysql_init_uses_aiomysql_when_no_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    """init() falls through to aiomysql.create_pool when no pool_factory provided (lines 61-65)."""
    import sys
    import types

    created: list[dict] = []

    class _FakePool:
        async def acquire(self):
            return None

        def release(self, _conn):
            pass

        def close(self):
            pass

        async def wait_closed(self):
            pass

    async def fake_create_pool(**kwargs):
        created.append(kwargs)
        return _FakePool()

    fake_aiomysql = types.ModuleType("aiomysql")
    fake_aiomysql.create_pool = fake_create_pool  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "aiomysql", fake_aiomysql)

    adapter = MySQLDatabaseAdapter(MySQLDatabaseSettings(database="testdb"))
    await adapter.init()
    assert len(created) == 1
    await adapter.cleanup()
