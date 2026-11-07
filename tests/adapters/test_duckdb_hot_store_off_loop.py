"""``DuckdbHotStore`` must not block the event loop, and must not let two
threads into DuckDB at once.

``duckdb.DuckDBPyConnection.execute`` is a blocking call. When it is called
from an ``async def`` — as every method of this class was — the event loop
is pinned for the whole query, and the coroutine looks async without being
async. On the OTLP ingest path that is half a second to a second per batch,
which is long enough to starve every other coroutine: akosha's Redis client
(``socket_timeout=5``) began failing with ``TimeoutError`` and the HTTP and
gRPC surfaces stopped answering while TCP still connected — the kernel's
accept backlog hides a stalled loop.

Moving the work to a worker thread fixes that and introduces a second
problem: DuckDB refuses concurrent use of one connection rather than
queueing, so a caller that reaches for ``conn`` directly — akosha's
retention sweep and its aging service both do — would collide with an
in-flight write. The connection therefore serializes every call itself.

These tests pin both halves.
"""

from __future__ import annotations

import asyncio
import itertools
import threading
import time
from pathlib import Path
from typing import Any

import duckdb
import pytest

from oneiric.adapters.vector.duckdb_hot_store import (
    METRICS_SUBSTRATE_COLUMNS,
    DuckdbHotStore,
)

pytestmark = pytest.mark.asyncio


class _SlowConnection:
    """A DuckDB connection whose queries take a measurable amount of time.

    The sleep stands in for a real query: what is under test is not how slow
    DuckDB is but whether the event loop keeps running while it is busy, and
    whether two callers can be inside DuckDB at the same moment. The sleep
    happens off the event loop, which is the whole point — ``time.sleep``
    releases the GIL, so the loop can make progress while the thread waits.
    """

    def __init__(self, conn: duckdb.DuckDBPyConnection, delay: float) -> None:
        self._conn = conn
        self._delay = delay
        self.calls: list[tuple[float, float]] = []

    def _record(self) -> None:
        started = time.monotonic()
        time.sleep(self._delay)
        self.calls.append((started, time.monotonic()))

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        self._record()
        return self._conn.execute(*args, **kwargs)

    def executemany(self, *args: Any, **kwargs: Any) -> Any:
        self._record()
        return self._conn.executemany(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


async def _ticker(stop: asyncio.Event, ticks: list[int]) -> None:
    """Count loop iterations until told to stop."""
    while not stop.is_set():
        ticks.append(1)
        await asyncio.sleep(0.005)


@pytest.fixture
async def store(tmp_path: Path) -> DuckdbHotStore:
    hs = DuckdbHotStore(database_path=tmp_path / "off.duckdb", embedding_dim=384)
    await hs.initialize()
    return hs


def _span(span_id: str, trace_id: str = "t1") -> dict[str, Any]:
    """A minimal row satisfying every NOT NULL column of the substrate."""
    return {
        "span_id": span_id,
        "trace_id": trace_id,
        "service_name": "mahavishnu",
        "service_namespace": "bodai",
        "span_name": "unit-test-span",
        "start_time_unix_nano": 1,
        "received_at_unix_nano": 2,
        "attributes": "{}",
        "resource": "{}",
    }


def _metric(ts: int) -> dict[str, Any]:
    """A minimal metric point covering every NOT NULL column."""
    return {
        "ts": ts,
        "service_name": "mahavishnu",
        "service_namespace": "bodai",
        "scope_name": "scope",
        "metric_name": "requests",
        "data_type": "gauge",
        "value_sum": 1.0,
        "value_count": 1,
        "value_min": 1.0,
        "value_max": 1.0,
        "value_sum_of_squares": 1.0,
        "buckets_json": "{}",
        "attributes": "{}",
        "resource": "{}",
    }


def _conn(store: DuckdbHotStore) -> Any:
    """The live connection.

    ``store.conn`` is Optional until ``initialize()`` has run; the fixture
    always initializes, so the assertion is a narrowing, not a runtime check.
    """
    conn = store.conn
    assert conn is not None
    return conn


def _slow_connect(monkeypatch: pytest.MonkeyPatch, delay: float) -> None:
    """Make every connection this store opens take ``delay`` seconds.

    The delay is installed on the RAW connection, underneath the store's
    serializing wrapper, so the wrapper's locking stays in play — which is
    the thing under test.
    """
    real_connect = duckdb.connect

    def slow_connect(*args: Any, **kwargs: Any) -> Any:
        return _SlowConnection(real_connect(*args, **kwargs), delay)

    monkeypatch.setattr(duckdb, "connect", slow_connect)


def _calls(conn: Any) -> list[tuple[float, float]]:
    """The recorded query windows on the slow connection.

    The store wraps the raw connection in a serializing proxy, so the
    recorder lives one level down. Asserting on the shape here keeps a
    missing wrapper from surfacing as an ``AttributeError`` deep in a test.
    """
    raw = getattr(conn, "_conn", None)
    assert isinstance(raw, _SlowConnection), (
        "the store is not wrapping the raw connection — the serializing "
        "wrapper is what keeps concurrent callers out of DuckDB"
    )
    return raw.calls


async def test_a_span_write_does_not_block_the_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The regression test.

    Three spans means four blocking calls — one existence probe per row plus
    the INSERT — so the write occupies roughly 200 ms of DuckDB time. If that
    time is spent on the event loop, the ticker cannot run at all and the
    count does not move.
    """
    _slow_connect(monkeypatch, delay=0.05)
    slow = DuckdbHotStore(database_path=tmp_path / "s.duckdb", embedding_dim=384)
    await slow.initialize()
    rows = [_span("a"), _span("b"), _span("c")]

    ticks: list[int] = []
    stop = asyncio.Event()
    ticker = asyncio.create_task(_ticker(stop, ticks))
    await asyncio.sleep(0.02)
    before = len(ticks)

    inserted, deduped = await slow.insert_spans_substrate(rows)

    after = len(ticks)
    stop.set()
    await ticker

    assert (inserted, deduped) == (3, 0)
    assert after - before >= 5, (
        f"the event loop advanced only {after - before} times during a "
        f"blocking write — the store is still running DuckDB on the loop"
    )


async def test_a_metrics_write_does_not_block_the_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The metrics path had the same shape as the span path."""
    _slow_connect(monkeypatch, delay=0.05)
    slow = DuckdbHotStore(database_path=tmp_path / "m.duckdb", embedding_dim=384)
    await slow.initialize()
    rows = [_metric(1_700_000_000_000 + i) for i in range(3)]

    ticks: list[int] = []
    stop = asyncio.Event()
    ticker = asyncio.create_task(_ticker(stop, ticks))
    await asyncio.sleep(0.02)
    before = len(ticks)

    inserted, deduped = await slow.insert_metrics_substrate(rows)

    after = len(ticks)
    stop.set()
    await ticker

    assert (inserted, deduped) == (3, 0)
    assert after - before >= 5, (
        f"the event loop advanced only {after - before} times during a "
        f"blocking write — the store is still running DuckDB on the loop"
    )


async def test_a_direct_connection_call_takes_the_connection_lock(
    tmp_path: Path,
) -> None:
    """A caller that reaches for ``conn`` directly must go through the lock.

    akosha's retention sweep and its aging service call
    ``hot_store.conn.execute(...)`` without going through the store's API.
    DuckDB refuses concurrent use of one connection rather than queueing —
    the second caller gets ``Resource In Use Error: connection is busy with
    another call`` — so the connection has to serialize its own calls.

    Rather than race two callers and hope they overlap, this holds the
    connection lock and checks that the direct call waits for it. That is
    the invariant the collision depends on, and it is deterministic.
    """
    store = DuckdbHotStore(database_path=tmp_path / "d.duckdb", embedding_dim=384)
    await store.initialize()

    lock = store._conn_lock
    lock.acquire()
    finished = threading.Event()

    def direct_call() -> None:
        _conn(store).execute("SELECT count(*) FROM spans_substrate").fetchone()
        finished.set()

    worker = threading.Thread(target=direct_call, daemon=True)
    worker.start()
    try:
        await asyncio.sleep(0.2)
        assert not finished.is_set(), (
            "a direct connection call did not take the connection lock — it "
            "can collide with an in-flight write"
        )
    finally:
        lock.release()

    worker.join(timeout=5)
    assert finished.is_set(), "the direct call never completed"


async def test_a_result_read_takes_the_connection_lock(
    tmp_path: Path,
) -> None:
    """The result read is a second DuckDB call, and it must be locked too.

    ``DuckDBPyConnection.execute`` returns the connection itself with the
    result attached — ``conn.execute(sql)`` *is* ``conn`` — so reading that
    result (``fetchone``, ``fetchall``, ``rowcount``) is another call into
    DuckDB. A wrapper that locked only ``execute`` would let the read slip
    into the gap between the two, where it collides with an in-flight write
    exactly like an unlocked query would.

    This is the failure the first version of the offload shipped with: the
    write raised ``Resource In Use Error`` while a direct caller's
    ``fetchone`` was in flight.
    """
    store = DuckdbHotStore(database_path=tmp_path / "r.duckdb", embedding_dim=384)
    await store.initialize()

    # Take the query first, while the lock is free, so only the READ is
    # left to be checked.
    result = _conn(store).execute("SELECT count(*) FROM spans_substrate")

    lock = store._conn_lock
    lock.acquire()
    finished = threading.Event()

    def read_result() -> None:
        result.fetchone()
        finished.set()

    worker = threading.Thread(target=read_result, daemon=True)
    worker.start()
    try:
        await asyncio.sleep(0.2)
        assert not finished.is_set(), (
            "the result read did not take the connection lock — it can "
            "collide with an in-flight write"
        )
    finally:
        lock.release()

    worker.join(timeout=5)
    assert finished.is_set(), "the result read never completed"


async def test_the_lock_is_held_for_the_whole_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The lock has to cover the offloaded work, not just the hand-off.

    DuckDB serializes statements internally, but not sequences of them: two
    probes racing on one connection returned inconsistent intermediate counts.
    The ``asyncio.Lock`` is what gives a multi-statement write a consistent
    view, so it must still be held while the thread is working — otherwise
    two writers interleave their statements on one connection.
    """
    _slow_connect(monkeypatch, delay=0.05)
    store = DuckdbHotStore(database_path=tmp_path / "l.duckdb", embedding_dim=384)
    await store.initialize()

    await asyncio.gather(
        store.insert_spans_substrate([_span("a")]),
        store.insert_spans_substrate([_span("b")]),
    )

    windows = sorted(_calls(_conn(store)))
    assert windows, "the store never called the connection"
    for (_, first_end), (second_start, _) in itertools.pairwise(windows):
        assert first_end <= second_start, (
            "two DuckDB calls overlapped — the lock did not cover the offloaded work"
        )


async def test_concurrent_writes_do_not_corrupt_the_batch(
    store: DuckdbHotStore,
) -> None:
    """Two writers at once must land every row exactly once."""
    first = [_span(f"a{i}") for i in range(5)]
    second = [_span(f"b{i}") for i in range(5)]

    results = await asyncio.gather(
        store.insert_spans_substrate(first),
        store.insert_spans_substrate(second),
    )

    assert results == [(5, 0), (5, 0)]
    row = _conn(store).execute("SELECT count(*) FROM spans_substrate").fetchone()
    assert row is not None
    assert int(row[0]) == 10


async def test_the_substrate_tables_are_still_written(
    store: DuckdbHotStore,
) -> None:
    """The offload must not change what lands in the table."""
    await store.insert_spans_substrate([_span("a")])
    await store.insert_metrics_substrate([_metric(1_700_000_000_000)])

    spans = _conn(store).execute("SELECT count(*) FROM spans_substrate").fetchone()
    metrics = _conn(store).execute("SELECT count(*) FROM metrics_substrate").fetchone()
    assert spans is not None
    assert metrics is not None
    assert int(spans[0]) == 1
    assert int(metrics[0]) == 1


async def test_the_metric_columns_are_still_the_documented_set() -> None:
    """Guards against a column-set drift sneaking in with the refactor."""
    assert METRICS_SUBSTRATE_COLUMNS[0] == "ts"
    assert "metric_name" in METRICS_SUBSTRATE_COLUMNS
