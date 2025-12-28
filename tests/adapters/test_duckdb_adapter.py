from __future__ import annotations

from types import SimpleNamespace

import pytest

from oneiric.adapters.database.duckdb import (
    DuckDBDatabaseAdapter,
    DuckDBDatabaseSettings,
)
from oneiric.core.lifecycle import LifecycleError


class FakeResult:
    def __init__(
        self, rows: list[tuple[object, ...]], has_description: bool = True
    ) -> None:
        self._rows = rows
        self.description = ["col"] if has_description else None

    def fetchall(self) -> list[tuple[object, ...]]:
        return list(self._rows)

    def fetchone(self) -> tuple[object, ...] | None:
        return self._rows[0] if self._rows else None

    def df(self) -> object:
        raise ImportError("pandas missing")

    def arrow(self) -> object:
        raise ImportError("pyarrow missing")


class FakeConn:
    def __init__(self) -> None:
        self.executed: list[str] = []

    def execute(self, sql: str, *_args: object) -> FakeResult:
        self.executed.append(sql)
        if sql.startswith("SELECT 1"):
            return FakeResult([(1,)], has_description=True)
        return FakeResult([], has_description=True)

    def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_duckdb_settings_validation_and_init(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ValueError, match="duckdb://"):
        DuckDBDatabaseSettings(database_url="sqlite:///bad.db")

    settings = DuckDBDatabaseSettings(
        database_url=f"duckdb:///{tmp_path}/app.duckdb",
        threads=4,
        pragmas={"memory_limit": "4GB", "max_memory": 1024},
        extensions=["httpfs"],
        temp_directory=str(tmp_path / "tmp"),
    )
    assert settings.database_path == tmp_path / "app.duckdb"
    adapter = DuckDBDatabaseAdapter(settings)
    conn = FakeConn()

    fake_duckdb = SimpleNamespace(connect=lambda **_: conn)
    monkeypatch.setitem(__import__("sys").modules, "duckdb", fake_duckdb)

    await adapter.init()

    assert any("PRAGMA threads=4" in sql for sql in conn.executed)
    assert any("PRAGMA memory_limit='4GB'" in sql for sql in conn.executed)
    assert any("PRAGMA max_memory=1024" in sql for sql in conn.executed)
    assert any("INSTALL httpfs" in sql for sql in conn.executed)
    assert any("LOAD httpfs" in sql for sql in conn.executed)
    assert any("SET temp_directory" in sql for sql in conn.executed)


@pytest.mark.asyncio
async def test_duckdb_execute_and_fetch_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = DuckDBDatabaseSettings(database_url="duckdb:///:memory:")
    adapter = DuckDBDatabaseAdapter(settings)

    with pytest.raises(LifecycleError, match="duckdb-connection-not-initialized"):
        await adapter.execute("SELECT 1")

    conn = FakeConn()
    adapter._conn = conn

    rowcount = await adapter.execute("SELECT 1")
    assert rowcount == 1

    with pytest.raises(LifecycleError, match="duckdb-pandas-missing"):
        await adapter.fetch_df("SELECT 1")

    with pytest.raises(LifecycleError, match="duckdb-arrow-missing"):
        await adapter.fetch_arrow("SELECT 1")
