"""Unit tests for OTelStorageAdapter without requiring PostgreSQL."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from oneiric.adapters.observability.otel import OTelStorageAdapter
from oneiric.adapters.observability.settings import OTelStorageSettings


class _ConcreteAdapter(OTelStorageAdapter):
    """Minimal concrete subclass — does NOT override base class concrete methods."""


def _make_adapter() -> _ConcreteAdapter:
    settings = OTelStorageSettings(
        connection_string="postgresql://postgres:postgres@localhost:5432/otel_test"
    )
    return _ConcreteAdapter(settings=settings)


def _fake_session_factory(
    execute_return: Any = None, raise_on_execute: Exception | None = None
):
    """Return a callable that yields a mock session as an async context manager."""

    @asynccontextmanager
    async def _factory():
        session = AsyncMock()
        if raise_on_execute:
            session.execute.side_effect = raise_on_execute
        else:
            mock_result = MagicMock()
            mock_result.fetchone.return_value = ("vector",)
            mock_result.scalars.return_value.all.return_value = []
            session.execute.return_value = mock_result
        session.commit = AsyncMock()
        session.add = MagicMock()
        session.add_all = MagicMock()
        yield session

    return _factory


# ---------------------------------------------------------------------------
# init() tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_init_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """init() creates engine, session factory, flush task, and query service (lines 35-76)."""
    import sqlalchemy.ext.asyncio as sa_async

    fake_engine = MagicMock()
    monkeypatch.setattr(sa_async, "create_async_engine", lambda *a, **kw: fake_engine)

    adapter = _make_adapter()
    monkeypatch.setattr(
        sa_async, "async_sessionmaker", lambda **kw: adapter._session_factory
    )
    adapter._session_factory = _fake_session_factory(
        execute_return=MagicMock(fetchone=MagicMock(return_value=("vector",)))
    )

    import sqlalchemy

    monkeypatch.setattr(sqlalchemy, "text", lambda s: s)

    from oneiric.adapters.observability import migrations

    monkeypatch.setattr(migrations, "create_ivfflat_index_if_ready", AsyncMock())

    import oneiric.adapters.observability.otel as otel_mod

    fake_qs = MagicMock()
    monkeypatch.setattr(otel_mod, "QueryService", lambda **kw: fake_qs)

    await adapter.init()
    assert adapter._engine is fake_engine
    assert adapter._query_service is fake_qs
    assert adapter._flush_task is not None
    adapter._flush_task.cancel()
    try:
        await adapter._flush_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_init_raises_when_vector_extension_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """init() raises RuntimeError when vector extension is not installed (lines 64-67)."""
    import sqlalchemy.ext.asyncio as sa_async

    fake_engine = MagicMock()
    monkeypatch.setattr(sa_async, "create_async_engine", lambda *a, **kw: fake_engine)

    adapter = _make_adapter()

    @asynccontextmanager
    async def no_vector_factory():
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None  # extension not found
        session.execute.return_value = mock_result
        yield session

    monkeypatch.setattr(sa_async, "async_sessionmaker", lambda **kw: no_vector_factory)
    adapter._session_factory = no_vector_factory

    import sqlalchemy

    monkeypatch.setattr(sqlalchemy, "text", lambda s: s)

    with pytest.raises(RuntimeError, match="Pgvector extension not installed"):
        await adapter.init()


@pytest.mark.asyncio
async def test_init_re_raises_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """init() logs error and re-raises on unexpected failure (lines 78-80)."""
    import sqlalchemy.ext.asyncio as sa_async

    def bad_engine(*a: Any, **kw: Any) -> None:
        raise RuntimeError("engine creation failed")

    monkeypatch.setattr(sa_async, "create_async_engine", bad_engine)

    adapter = _make_adapter()
    with pytest.raises(RuntimeError, match="engine creation failed"):
        await adapter.init()


# ---------------------------------------------------------------------------
# health() tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_returns_false_when_no_engine() -> None:
    """health() returns False when _engine is None (lines 83-84)."""
    adapter = _make_adapter()
    assert adapter._engine is None
    assert await adapter.health() is False


@pytest.mark.asyncio
async def test_health_returns_true_when_session_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """health() returns True when SELECT 1 executes (lines 86-91)."""
    adapter = _make_adapter()
    adapter._engine = MagicMock()  # truthy
    adapter._session_factory = _fake_session_factory()

    # patch sqlalchemy.text to return a dummy
    monkeypatch.setattr(
        "oneiric.adapters.observability.otel.OTelStorageAdapter.health",
        _ConcreteAdapter.health,
        raising=False,
    )

    import sqlalchemy

    monkeypatch.setattr(sqlalchemy, "text", lambda s: s)
    assert await adapter.health() is True


@pytest.mark.asyncio
async def test_health_returns_false_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """health() returns False when session.execute raises (lines 92-94)."""
    import sqlalchemy

    monkeypatch.setattr(sqlalchemy, "text", lambda s: s)
    adapter = _make_adapter()
    adapter._engine = MagicMock()
    adapter._session_factory = _fake_session_factory(
        raise_on_execute=RuntimeError("db down")
    )
    assert await adapter.health() is False


# ---------------------------------------------------------------------------
# cleanup() tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_returns_early_when_no_engine() -> None:
    """cleanup() does nothing when _engine is None (lines 97-98)."""
    adapter = _make_adapter()
    await adapter.cleanup()  # must not raise
    assert adapter._engine is None


@pytest.mark.asyncio
async def test_cleanup_cancels_flush_task() -> None:
    """cleanup() cancels the flush task and disposes the engine (lines 100-113)."""
    adapter = _make_adapter()
    engine = AsyncMock()
    adapter._engine = engine

    # Create a real long-running task to cancel
    async def _long_task() -> None:
        await asyncio.sleep(100)

    flush_task = asyncio.create_task(_long_task())
    adapter._flush_task = flush_task

    # Provide empty buffer so _flush_buffer() is a no-op
    adapter._session_factory = _fake_session_factory()

    await adapter.cleanup()
    assert flush_task.cancelled()
    engine.dispose.assert_awaited()
    assert adapter._engine is None


@pytest.mark.asyncio
async def test_cleanup_without_flush_task() -> None:
    """cleanup() works when _flush_task is None (line 100 branch)."""
    adapter = _make_adapter()
    engine = AsyncMock()
    adapter._engine = engine
    adapter._flush_task = None
    adapter._session_factory = _fake_session_factory()

    await adapter.cleanup()
    engine.dispose.assert_awaited()


# ---------------------------------------------------------------------------
# store_trace() tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_trace_appends_to_buffer() -> None:
    """store_trace() appends trace to write buffer (lines 115-116)."""
    adapter = _make_adapter()
    trace = {
        "trace_id": "t1",
        "name": "span",
        "status": "OK",
        "start_time": "2026-01-01T00:00:00",
    }
    await adapter.store_trace(trace)
    assert len(adapter._write_buffer) == 1


@pytest.mark.asyncio
async def test_store_trace_flushes_on_batch_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """store_trace() calls _flush_buffer when buffer reaches batch_size (lines 117-118)."""
    flushed: list[int] = []

    adapter = _make_adapter()
    object.__setattr__(adapter._settings, "batch_size", 2)

    async def fake_flush(self: Any) -> None:
        flushed.append(1)
        adapter._write_buffer.clear()

    monkeypatch.setattr(_ConcreteAdapter, "_flush_buffer", fake_flush)
    trace = {
        "trace_id": "t1",
        "name": "span",
        "status": "OK",
        "start_time": "2026-01-01T00:00:00",
    }
    await adapter.store_trace(trace)
    await adapter.store_trace(trace)
    assert len(flushed) == 1


# ---------------------------------------------------------------------------
# _flush_buffer_periodically() tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flush_buffer_periodically_cancels() -> None:
    """_flush_buffer_periodically() breaks on CancelledError (lines 121-126)."""
    adapter = _make_adapter()
    adapter._session_factory = _fake_session_factory()

    task = asyncio.create_task(adapter._flush_buffer_periodically())
    await asyncio.sleep(0.01)
    task.cancel()
    await task  # CancelledError is caught internally — loop just breaks


@pytest.mark.asyncio
async def test_flush_buffer_periodically_logs_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_flush_buffer_periodically() logs and continues on non-cancel exceptions (lines 127-128)."""
    call_count = 0
    adapter = _make_adapter()
    object.__setattr__(adapter._settings, "batch_interval_seconds", 0.001)

    async def fake_flush(self: Any) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("transient error")

    monkeypatch.setattr(_ConcreteAdapter, "_flush_buffer", fake_flush)

    task = asyncio.create_task(adapter._flush_buffer_periodically())
    await asyncio.sleep(0.05)
    task.cancel()
    await task
    assert call_count >= 1


# ---------------------------------------------------------------------------
# _flush_buffer() tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flush_buffer_empty_is_noop() -> None:
    """_flush_buffer() returns early when buffer is empty (lines 131-133)."""
    adapter = _make_adapter()
    assert not adapter._write_buffer
    await adapter._flush_buffer()  # must not raise


@pytest.mark.asyncio
async def test_flush_buffer_stores_traces(monkeypatch: pytest.MonkeyPatch) -> None:
    """_flush_buffer() builds TraceModel instances and commits (lines 135-170)."""
    adapter = _make_adapter()
    adapter._session_factory = _fake_session_factory()

    # Return a fixed embedding so TraceModel gets embedding.tolist()
    fake_embedding = np.zeros(384)
    adapter._embedding_service.embed_trace = AsyncMock(return_value=fake_embedding)

    trace = {
        "trace_id": "t1",
        "name": "span",
        "status": "OK",
        "start_time": "2026-01-01T00:00:00",
        "end_time": "2026-01-01T00:00:01",
    }
    adapter._write_buffer.append(trace)
    await adapter._flush_buffer()
    assert len(adapter._write_buffer) == 0


@pytest.mark.asyncio
async def test_flush_buffer_sends_to_dlq_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_flush_buffer() sends to DLQ when commit raises (lines 172-178)."""
    dlq_calls: list[str] = []

    adapter = _make_adapter()

    @asynccontextmanager
    async def bad_session():
        session = AsyncMock()
        session.execute = AsyncMock()
        session.commit.side_effect = RuntimeError("commit failed")
        session.add_all = MagicMock()
        yield session

    adapter._session_factory = bad_session

    fake_embedding = np.zeros(384)
    adapter._embedding_service.embed_trace = AsyncMock(return_value=fake_embedding)

    async def fake_dlq(self: Any, trace: dict, error: str) -> None:
        dlq_calls.append(error)

    monkeypatch.setattr(_ConcreteAdapter, "_send_to_dlq", fake_dlq)

    trace = {
        "trace_id": "t1",
        "name": "span",
        "status": "OK",
        "start_time": "2026-01-01T00:00:00",
    }
    adapter._write_buffer.append(trace)
    await adapter._flush_buffer()
    assert len(dlq_calls) == 1


# ---------------------------------------------------------------------------
# _send_to_dlq() tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_to_dlq_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """_send_to_dlq() inserts into DLQ table (lines 180-194)."""
    import sqlalchemy

    monkeypatch.setattr(sqlalchemy, "text", lambda s: s)
    adapter = _make_adapter()
    adapter._session_factory = _fake_session_factory()
    await adapter._send_to_dlq({"trace_id": "t1"}, "some error")  # must not raise


@pytest.mark.asyncio
async def test_send_to_dlq_logs_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """_send_to_dlq() logs and swallows exceptions (lines 195-196)."""
    import sqlalchemy

    monkeypatch.setattr(sqlalchemy, "text", lambda s: s)
    adapter = _make_adapter()
    adapter._session_factory = _fake_session_factory(
        raise_on_execute=RuntimeError("dlq down")
    )
    await adapter._send_to_dlq({"trace_id": "t1"}, "err")  # must not raise


# ---------------------------------------------------------------------------
# store_log() tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_log_success() -> None:
    """store_log() builds LogModel and commits (lines 199-225)."""
    adapter = _make_adapter()
    adapter._session_factory = _fake_session_factory()
    log = {
        "trace_id": "t1",
        "start_time": datetime.now(UTC),
        "attributes": {"log.level": "INFO", "log.message": "hello"},
    }
    await adapter.store_log(log)  # must not raise


@pytest.mark.asyncio
async def test_store_log_raises_on_error() -> None:
    """store_log() re-raises when commit fails (lines 227-229)."""

    @asynccontextmanager
    async def bad_session():
        session = AsyncMock()
        session.add = MagicMock()
        session.commit.side_effect = RuntimeError("commit failed")
        yield session

    adapter = _make_adapter()
    adapter._session_factory = bad_session
    log = {
        "trace_id": "t1",
        "start_time": datetime.now(UTC),
        "attributes": {"log.level": "ERROR", "log.message": "oops"},
    }
    with pytest.raises(RuntimeError, match="commit failed"):
        await adapter.store_log(log)


# ---------------------------------------------------------------------------
# store_metrics() tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_metrics_success() -> None:
    """store_metrics() builds MetricModel list and commits (lines 232-254)."""
    adapter = _make_adapter()
    adapter._session_factory = _fake_session_factory()
    metrics = [
        {
            "name": "req_count",
            "type": "counter",
            "value": 10.0,
            "unit": "count",
            "labels": {},
            "timestamp": datetime.now(UTC),
        }
    ]
    await adapter.store_metrics(metrics)  # must not raise


@pytest.mark.asyncio
async def test_store_metrics_raises_on_error() -> None:
    """store_metrics() re-raises on commit failure (lines 256-258)."""

    @asynccontextmanager
    async def bad_session():
        session = AsyncMock()
        session.add_all = MagicMock()
        session.commit.side_effect = RuntimeError("commit failed")
        yield session

    adapter = _make_adapter()
    adapter._session_factory = bad_session
    with pytest.raises(RuntimeError, match="commit failed"):
        await adapter.store_metrics(
            [
                {
                    "name": "m",
                    "value": 1.0,
                    "timestamp": datetime.now(UTC),
                    "type": "gauge",
                }
            ]
        )


# ---------------------------------------------------------------------------
# find_similar_traces() tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_similar_traces_no_query_service() -> None:
    """find_similar_traces() returns [] when _query_service is None (lines 277-279)."""
    adapter = _make_adapter()
    assert adapter._query_service is None
    result = await adapter.find_similar_traces([0.1] * 384)
    assert result == []


@pytest.mark.asyncio
async def test_find_similar_traces_success() -> None:
    """find_similar_traces() calls query_service and returns model_dump results (lines 281-298)."""
    adapter = _make_adapter()

    mock_result = MagicMock()
    mock_result.model_dump.return_value = {"trace_id": "t1"}
    qs = AsyncMock()
    qs.find_similar_traces = AsyncMock(return_value=[mock_result])
    adapter._query_service = qs

    results = await adapter.find_similar_traces([0.1] * 384)
    assert results == [{"trace_id": "t1"}]


@pytest.mark.asyncio
async def test_find_similar_traces_raises_on_error() -> None:
    """find_similar_traces() re-raises when query_service raises (lines 300-306)."""
    adapter = _make_adapter()
    qs = AsyncMock()
    qs.find_similar_traces.side_effect = RuntimeError("query failed")
    adapter._query_service = qs
    with pytest.raises(RuntimeError, match="query failed"):
        await adapter.find_similar_traces([0.1] * 384)


# ---------------------------------------------------------------------------
# get_traces_by_error() tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_traces_by_error_no_query_service() -> None:
    """get_traces_by_error() returns [] when _query_service is None (lines 324-326)."""
    adapter = _make_adapter()
    result = await adapter.get_traces_by_error("NullPointerException")
    assert result == []


@pytest.mark.asyncio
async def test_get_traces_by_error_success() -> None:
    """get_traces_by_error() calls query_service and returns model_dump results (lines 328-342)."""
    adapter = _make_adapter()

    mock_result = MagicMock()
    mock_result.model_dump.return_value = {"trace_id": "t2"}
    qs = AsyncMock()
    qs.get_traces_by_error = AsyncMock(return_value=[mock_result])
    adapter._query_service = qs

    results = await adapter.get_traces_by_error("NullPointerException", service="svc")
    assert results == [{"trace_id": "t2"}]


@pytest.mark.asyncio
async def test_get_traces_by_error_raises_on_error() -> None:
    """get_traces_by_error() re-raises when query_service raises (lines 344-351)."""
    adapter = _make_adapter()
    qs = AsyncMock()
    qs.get_traces_by_error.side_effect = RuntimeError("query failed")
    adapter._query_service = qs
    with pytest.raises(RuntimeError, match="query failed"):
        await adapter.get_traces_by_error("err")


# ---------------------------------------------------------------------------
# search_logs() tests (base class implementation)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_logs_no_session_factory() -> None:
    """search_logs() returns [] when _session_factory is None (lines 367-369)."""
    adapter = _make_adapter()
    assert adapter._session_factory is None
    result = await adapter.search_logs("trace-001")
    assert result == []


@pytest.mark.asyncio
async def test_search_logs_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """search_logs() queries logs and returns dicts (lines 371-409)."""
    import sqlalchemy

    from oneiric.adapters.observability.models import LogModel

    monkeypatch.setattr(sqlalchemy, "select", lambda *_: MagicMock())

    now = datetime.now(UTC)
    fake_log = MagicMock(spec=LogModel)
    fake_log.id = "log-1"
    fake_log.timestamp = now
    fake_log.level = "INFO"
    fake_log.message = "test"
    fake_log.trace_id = "trace-001"
    fake_log.resource_attributes = {}
    fake_log.span_attributes = {}

    @asynccontextmanager
    async def session_factory():
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [fake_log]
        session.execute.return_value = mock_result
        yield session

    adapter = _make_adapter()
    adapter._session_factory = session_factory

    results = await adapter.search_logs("trace-001", level="INFO")
    assert len(results) == 1
    assert results[0]["trace_id"] == "trace-001"
    assert results[0]["level"] == "INFO"


@pytest.mark.asyncio
async def test_search_logs_raises_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """search_logs() re-raises when session.execute raises (lines 411-418)."""
    import sqlalchemy

    monkeypatch.setattr(sqlalchemy, "select", lambda *_: MagicMock())
    adapter = _make_adapter()
    adapter._session_factory = _fake_session_factory(
        raise_on_execute=RuntimeError("db error")
    )
    with pytest.raises(RuntimeError, match="db error"):
        await adapter.search_logs("trace-001")
