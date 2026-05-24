from __future__ import annotations

import pytest

from oneiric.adapters.observability.migrations import (
    create_ivfflat_index_if_ready,
    create_otel_schema,
    create_query_optimization_indexes,
    create_vector_index,
    drop_otel_schema,
)


class _Result:
    def __init__(self, *, scalar=None, fetchone=None) -> None:
        self._scalar = scalar
        self._fetchone = fetchone

    def scalar(self):
        return self._scalar

    def fetchone(self):
        return self._fetchone


class _Session:
    def __init__(
        self, results: list[_Result] | None = None, fail_on: int | None = None
    ):
        self.results = list(results or [])
        self.fail_on = fail_on
        self.statements: list[str] = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, stmt):
        if self.fail_on is not None and len(self.statements) == self.fail_on:
            raise RuntimeError("boom")
        self.statements.append(str(stmt))
        if self.results:
            return self.results.pop(0)
        return _Result()

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


@pytest.mark.asyncio
async def test_create_and_drop_schema_and_vector_index() -> None:
    session = _Session()

    await create_otel_schema(session)
    assert len(session.statements) == 15
    assert "CREATE TABLE IF NOT EXISTS otel_traces" in session.statements[0]
    assert "ix_traces_attributes_gin" in "".join(session.statements)
    assert session.commits == 1

    await create_vector_index(session, num_lists=128)
    assert "lists = 128" in session.statements[-1]
    assert session.commits == 2

    await drop_otel_schema(session)
    assert session.statements[-4:] == [
        "DROP TABLE IF EXISTS otel_telemetry_dlq CASCADE",
        "DROP TABLE IF EXISTS otel_logs CASCADE",
        "DROP TABLE IF EXISTS otel_metrics CASCADE",
        "DROP TABLE IF EXISTS otel_traces CASCADE",
    ]
    assert session.commits == 3


@pytest.mark.asyncio
async def test_ivfflat_index_branch_paths() -> None:
    session = _Session(results=[_Result(scalar=10)])
    created = await create_ivfflat_index_if_ready(session)
    assert created is False
    assert session.commits == 0

    session = _Session(results=[_Result(scalar=1000), _Result(fetchone=("ix",))])
    created = await create_ivfflat_index_if_ready(session)
    assert created is False
    assert session.commits == 0

    session = _Session(results=[_Result(scalar=1000), _Result(fetchone=None)])
    created = await create_ivfflat_index_if_ready(session)
    assert created is True
    assert session.commits == 1
    assert (
        "CREATE INDEX CONCURRENTLY ix_traces_embedding_ivfflat"
        in session.statements[-1]
    )

    session = _Session(fail_on=0)
    with pytest.raises(RuntimeError):
        await create_ivfflat_index_if_ready(session)
    assert session.rollbacks == 1


@pytest.mark.asyncio
async def test_query_index_creation_and_failure_paths() -> None:
    session = _Session()
    await create_query_optimization_indexes(session)
    assert session.commits == 1
    assert "ix_traces_start_time_status" in session.statements[0]

    session = _Session(fail_on=0)
    with pytest.raises(RuntimeError):
        await create_query_optimization_indexes(session)
    assert session.rollbacks == 1
