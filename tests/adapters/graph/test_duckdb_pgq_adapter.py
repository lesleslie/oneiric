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
