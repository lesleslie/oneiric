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

    async def execute(self, query: str, args: tuple[Any, ...]) -> None:
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
