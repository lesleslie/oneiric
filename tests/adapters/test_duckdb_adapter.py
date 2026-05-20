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


# ---------------------------------------------------------------------------
# Tests — DuckDBDatabaseSettings.database_path edge cases
# ---------------------------------------------------------------------------


def test_settings_database_path_none_memory() -> None:
    s = DuckDBDatabaseSettings(database_url="duckdb:///:memory:")
    assert s.database_path is None


def test_settings_database_path_with_query_string(tmp_path) -> None:
    url = f"duckdb:///{tmp_path}/app.duckdb?timeout=30"
    s = DuckDBDatabaseSettings(database_url=url)
    assert s.database_path == tmp_path / "app.duckdb"


def test_settings_database_path_no_triple_slash() -> None:
    # duckdb:// without /// → database_path returns None
    # This URL is technically invalid per validator but let's test the property
    # directly using a manually constructed object
    s = DuckDBDatabaseSettings.__new__(DuckDBDatabaseSettings)
    object.__setattr__(s, "database_url", "duckdb://host/path")
    assert s.database_path is None


# ---------------------------------------------------------------------------
# Tests — init: in-memory database (no db_path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duckdb_init_memory_database(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = DuckDBDatabaseSettings(database_url="duckdb:///:memory:")
    assert settings.database_path is None

    adapter = DuckDBDatabaseAdapter(settings)
    conn = FakeConn()
    fake_duckdb = SimpleNamespace(connect=lambda **_: conn)
    monkeypatch.setitem(__import__("sys").modules, "duckdb", fake_duckdb)

    await adapter.init()
    assert adapter._conn is conn


@pytest.mark.asyncio
async def test_duckdb_init_with_url_query_param(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = f"duckdb:///{tmp_path}/app.duckdb?access_mode=read_only"
    settings = DuckDBDatabaseSettings(database_url=url)
    adapter = DuckDBDatabaseAdapter(settings)
    conn = FakeConn()
    fake_duckdb = SimpleNamespace(connect=lambda **_: conn)
    monkeypatch.setitem(__import__("sys").modules, "duckdb", fake_duckdb)

    await adapter.init()
    assert adapter._conn is conn


@pytest.mark.asyncio
async def test_duckdb_init_connection_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = DuckDBDatabaseSettings(database_url="duckdb:///:memory:")
    adapter = DuckDBDatabaseAdapter(settings)

    def bad_connect(**_):
        raise RuntimeError("locked")

    fake_duckdb = SimpleNamespace(connect=bad_connect)
    monkeypatch.setitem(__import__("sys").modules, "duckdb", fake_duckdb)

    with pytest.raises(LifecycleError, match="duckdb-connection-failed"):
        await adapter.init()


@pytest.mark.asyncio
async def test_duckdb_init_read_only_skips_extensions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = DuckDBDatabaseSettings(
        database_url="duckdb:///:memory:",
        read_only=True,
        extensions=["httpfs"],
    )
    adapter = DuckDBDatabaseAdapter(settings)
    conn = FakeConn()
    fake_duckdb = SimpleNamespace(connect=lambda **_: conn)
    monkeypatch.setitem(__import__("sys").modules, "duckdb", fake_duckdb)

    await adapter.init()
    assert not any("INSTALL" in sql for sql in conn.executed)


@pytest.mark.asyncio
async def test_duckdb_init_extension_failure_is_logged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailOnInstall:
        executed: list[str] = []

        def execute(self, sql: str, *_args: object) -> "FakeResult":
            self.executed.append(sql)
            if "INSTALL" in sql:
                raise RuntimeError("network unavailable")
            return FakeResult([], has_description=True)

        def close(self) -> None:
            pass

    settings = DuckDBDatabaseSettings(
        database_url="duckdb:///:memory:",
        extensions=["httpfs"],
    )
    adapter = DuckDBDatabaseAdapter(settings)
    conn = FailOnInstall()
    fake_duckdb = SimpleNamespace(connect=lambda **_: conn)
    monkeypatch.setitem(__import__("sys").modules, "duckdb", fake_duckdb)

    # Extension failure should be logged, not raised
    await adapter.init()


# ---------------------------------------------------------------------------
# Tests — health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duckdb_health_true() -> None:
    settings = DuckDBDatabaseSettings(database_url="duckdb:///:memory:")
    adapter = DuckDBDatabaseAdapter(settings)
    adapter._conn = FakeConn()
    assert await adapter.health() is True


@pytest.mark.asyncio
async def test_duckdb_health_false_no_conn() -> None:
    adapter = DuckDBDatabaseAdapter(DuckDBDatabaseSettings(database_url="duckdb:///:memory:"))
    assert await adapter.health() is False


@pytest.mark.asyncio
async def test_duckdb_health_false_on_error() -> None:
    class ErrorConn:
        def execute(self, sql: str, *_args: object) -> None:
            raise RuntimeError("connection lost")

        def close(self) -> None:
            pass

    adapter = DuckDBDatabaseAdapter(DuckDBDatabaseSettings(database_url="duckdb:///:memory:"))
    adapter._conn = ErrorConn()  # type: ignore[assignment]
    assert await adapter.health() is False


# ---------------------------------------------------------------------------
# Tests — cleanup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duckdb_cleanup_with_conn() -> None:
    adapter = DuckDBDatabaseAdapter(DuckDBDatabaseSettings(database_url="duckdb:///:memory:"))
    adapter._conn = FakeConn()
    await adapter.cleanup()
    assert adapter._conn is None


@pytest.mark.asyncio
async def test_duckdb_cleanup_close_exception() -> None:
    class BrokenClose:
        def close(self) -> None:
            raise RuntimeError("already closed")

    adapter = DuckDBDatabaseAdapter(DuckDBDatabaseSettings(database_url="duckdb:///:memory:"))
    adapter._conn = BrokenClose()  # type: ignore[assignment]
    await adapter.cleanup()  # should not raise
    assert adapter._conn is None


# ---------------------------------------------------------------------------
# Tests — execute / fetch_all / fetch_one variants
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duckdb_execute_with_args() -> None:
    adapter = DuckDBDatabaseAdapter(DuckDBDatabaseSettings(database_url="duckdb:///:memory:"))
    adapter._conn = FakeConn()
    rowcount = await adapter.execute("SELECT ?", 42)
    assert rowcount == 0  # FakeResult with no rows


@pytest.mark.asyncio
async def test_duckdb_execute_no_description() -> None:
    class NoDescConn:
        def execute(self, sql: str, *_args: object) -> FakeResult:
            return FakeResult([], has_description=False)

        def close(self) -> None:
            pass

    adapter = DuckDBDatabaseAdapter(DuckDBDatabaseSettings(database_url="duckdb:///:memory:"))
    adapter._conn = NoDescConn()  # type: ignore[assignment]
    rowcount = await adapter.execute("INSERT INTO t VALUES (1)")
    assert rowcount == 0


@pytest.mark.asyncio
async def test_duckdb_execute_exception() -> None:
    class ExplodingConn:
        def execute(self, sql: str, *_args: object) -> None:
            raise RuntimeError("syntax error")

        def close(self) -> None:
            pass

    adapter = DuckDBDatabaseAdapter(DuckDBDatabaseSettings(database_url="duckdb:///:memory:"))
    adapter._conn = ExplodingConn()  # type: ignore[assignment]
    with pytest.raises(LifecycleError, match="duckdb-execute-failed"):
        await adapter.execute("BAAD SQL")


@pytest.mark.asyncio
async def test_duckdb_fetch_all_with_args() -> None:
    class RowConn:
        def execute(self, sql: str, *_args: object) -> FakeResult:
            return FakeResult([(1,), (2,)])

        def close(self) -> None:
            pass

    adapter = DuckDBDatabaseAdapter(DuckDBDatabaseSettings(database_url="duckdb:///:memory:"))
    adapter._conn = RowConn()  # type: ignore[assignment]
    rows = await adapter.fetch_all("SELECT ?", 1)
    assert rows == [(1,), (2,)]


@pytest.mark.asyncio
async def test_duckdb_fetch_all_exception() -> None:
    class BoomConn:
        def execute(self, sql: str, *_args: object) -> None:
            raise RuntimeError("table not found")

        def close(self) -> None:
            pass

    adapter = DuckDBDatabaseAdapter(DuckDBDatabaseSettings(database_url="duckdb:///:memory:"))
    adapter._conn = BoomConn()  # type: ignore[assignment]
    with pytest.raises(LifecycleError, match="duckdb-fetch-all-failed"):
        await adapter.fetch_all("SELECT * FROM missing")


@pytest.mark.asyncio
async def test_duckdb_fetch_one_with_args() -> None:
    class OneRowConn:
        def execute(self, sql: str, *_args: object) -> FakeResult:
            return FakeResult([(42,)])

        def close(self) -> None:
            pass

    adapter = DuckDBDatabaseAdapter(DuckDBDatabaseSettings(database_url="duckdb:///:memory:"))
    adapter._conn = OneRowConn()  # type: ignore[assignment]
    row = await adapter.fetch_one("SELECT ? AS val", 42)
    assert row == (42,)


@pytest.mark.asyncio
async def test_duckdb_fetch_one_without_args() -> None:
    adapter = DuckDBDatabaseAdapter(DuckDBDatabaseSettings(database_url="duckdb:///:memory:"))
    adapter._conn = FakeConn()
    row = await adapter.fetch_one("SELECT 1")
    assert row == (1,)


@pytest.mark.asyncio
async def test_duckdb_fetch_one_exception() -> None:
    class BoomConn:
        def execute(self, sql: str, *_args: object) -> None:
            raise RuntimeError("gone")

        def close(self) -> None:
            pass

    adapter = DuckDBDatabaseAdapter(DuckDBDatabaseSettings(database_url="duckdb:///:memory:"))
    adapter._conn = BoomConn()  # type: ignore[assignment]
    with pytest.raises(LifecycleError, match="duckdb-fetch-one-failed"):
        await adapter.fetch_one("SELECT 1")


# ---------------------------------------------------------------------------
# Tests — fetch_df / fetch_arrow success paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duckdb_fetch_df_success() -> None:
    class DFResult:
        description = ["col"]

        def df(self) -> dict:
            return {"col": [1, 2, 3]}

        def fetchall(self):
            return [(1,), (2,), (3,)]

    class DFConn:
        def execute(self, sql: str, *_args: object) -> DFResult:
            return DFResult()

        def close(self) -> None:
            pass

    adapter = DuckDBDatabaseAdapter(DuckDBDatabaseSettings(database_url="duckdb:///:memory:"))
    adapter._conn = DFConn()  # type: ignore[assignment]
    result = await adapter.fetch_df("SELECT 1")
    assert result is not None


@pytest.mark.asyncio
async def test_duckdb_fetch_df_generic_exception() -> None:
    class ErrorResult:
        description = ["col"]

        def df(self) -> None:
            raise RuntimeError("df failed")

    class ErrorConn:
        def execute(self, sql: str, *_args: object) -> ErrorResult:
            return ErrorResult()

        def close(self) -> None:
            pass

    adapter = DuckDBDatabaseAdapter(DuckDBDatabaseSettings(database_url="duckdb:///:memory:"))
    adapter._conn = ErrorConn()  # type: ignore[assignment]
    with pytest.raises(LifecycleError, match="duckdb-fetch-df-failed"):
        await adapter.fetch_df("SELECT 1")


@pytest.mark.asyncio
async def test_duckdb_fetch_arrow_success() -> None:
    class ArrowResult:
        description = ["col"]

        def arrow(self) -> dict:
            return {"col": [1]}

        def fetchall(self):
            return [(1,)]

    class ArrowConn:
        def execute(self, sql: str, *_args: object) -> ArrowResult:
            return ArrowResult()

        def close(self) -> None:
            pass

    adapter = DuckDBDatabaseAdapter(DuckDBDatabaseSettings(database_url="duckdb:///:memory:"))
    adapter._conn = ArrowConn()  # type: ignore[assignment]
    result = await adapter.fetch_arrow("SELECT 1")
    assert result is not None


@pytest.mark.asyncio
async def test_duckdb_fetch_arrow_generic_exception() -> None:
    class ErrorResult:
        description = ["col"]

        def arrow(self) -> None:
            raise RuntimeError("arrow failed")

    class ErrorConn:
        def execute(self, sql: str, *_args: object) -> ErrorResult:
            return ErrorResult()

        def close(self) -> None:
            pass

    adapter = DuckDBDatabaseAdapter(DuckDBDatabaseSettings(database_url="duckdb:///:memory:"))
    adapter._conn = ErrorConn()  # type: ignore[assignment]
    with pytest.raises(LifecycleError, match="duckdb-fetch-arrow-failed"):
        await adapter.fetch_arrow("SELECT 1")


# ---------------------------------------------------------------------------
# Tests — connection property / _ensure_conn
# ---------------------------------------------------------------------------


def test_duckdb_connection_property() -> None:
    adapter = DuckDBDatabaseAdapter(DuckDBDatabaseSettings(database_url="duckdb:///:memory:"))
    conn = FakeConn()
    adapter._conn = conn
    assert adapter.connection is conn


def test_duckdb_ensure_conn_raises_when_none() -> None:
    adapter = DuckDBDatabaseAdapter(DuckDBDatabaseSettings(database_url="duckdb:///:memory:"))
    with pytest.raises(LifecycleError, match="duckdb-connection-not-initialized"):
        adapter._ensure_conn()


# ---------------------------------------------------------------------------
# Tests — coverage gaps: fetchall exception, fetch_df/arrow with args
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duckdb_execute_fetchall_raises_uses_fallback() -> None:
    """Inner except in execute() sets rowcount=0 when fetchall() raises."""

    class BoomFetchall:
        description = ["col"]

        def fetchall(self) -> None:
            raise RuntimeError("cursor closed")

    class BoomFetchallConn:
        def execute(self, sql: str, *_args: object) -> "BoomFetchall":
            return BoomFetchall()

        def close(self) -> None:
            pass

    adapter = DuckDBDatabaseAdapter(DuckDBDatabaseSettings(database_url="duckdb:///:memory:"))
    adapter._conn = BoomFetchallConn()  # type: ignore[assignment]
    rowcount = await adapter.execute("SELECT 1")
    assert rowcount == 0


@pytest.mark.asyncio
async def test_duckdb_fetch_df_with_args() -> None:
    """fetch_df with positional args takes the if-args branch."""

    class DFResult:
        description = ["col"]

        def df(self) -> list[int]:
            return [1, 2]

        def fetchall(self) -> list[tuple[int]]:
            return [(1,), (2,)]

    class DFConn:
        def execute(self, sql: str, *_args: object) -> DFResult:
            return DFResult()

        def close(self) -> None:
            pass

    adapter = DuckDBDatabaseAdapter(DuckDBDatabaseSettings(database_url="duckdb:///:memory:"))
    adapter._conn = DFConn()  # type: ignore[assignment]
    result = await adapter.fetch_df("SELECT ?", 1)
    assert result == [1, 2]


@pytest.mark.asyncio
async def test_duckdb_fetch_arrow_with_args() -> None:
    """fetch_arrow with positional args takes the if-args branch."""

    class ArrowResult:
        description = ["col"]

        def arrow(self) -> list[int]:
            return [42]

        def fetchall(self) -> list[tuple[int]]:
            return [(42,)]

    class ArrowConn:
        def execute(self, sql: str, *_args: object) -> ArrowResult:
            return ArrowResult()

        def close(self) -> None:
            pass

    adapter = DuckDBDatabaseAdapter(DuckDBDatabaseSettings(database_url="duckdb:///:memory:"))
    adapter._conn = ArrowConn()  # type: ignore[assignment]
    result = await adapter.fetch_arrow("SELECT ?", 42)
    assert result == [42]
