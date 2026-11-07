# DuckdbHotStore: get synchronous DuckDB work off the event loop

**Date:** 2026-11-07
**Status:** in progress
**Affects:** `oneiric/adapters/vector/duckdb_hot_store.py`
**Consumers:** akosha (OTLP receiver), mahavishnu (`mahavishnu/ingesters/otel_ingester.py:609`)

## Problem

`DuckdbHotStore` exposes an `async` surface, but every method body performs
**synchronous** DuckDB work on the calling thread — the event loop.
`duckdb.DuckDBPyConnection.execute` is a blocking call: it runs the query and
returns the materialized result. Nothing in the class ever awaits I/O except
the `asyncio.Lock` acquire, so `async def` here buys nothing and costs
everything: the loop is pinned for the whole duration of the query.

### Observed symptom (akosha)

The akosha MCP server wedges roughly four minutes after boot. TCP connects
succeed (the kernel backlog accepts them) but HTTP and gRPC never answer, and
Redis calls fail with `redis.exceptions.TimeoutError` against a
`socket_timeout=5` client (`akosha/modes/standard.py:139`). Redis itself is
healthy — `PING` returns in 0.2-0.3 ms — so the timeouts are a symptom of the
event loop not being serviced, not a Redis fault. `akosha.err` carries 1,449
such timeouts.

### Root cause

Each incoming OTLP batch blocks the event loop for roughly half a second to a
second, and back-to-back batches leave the loop no idle window in which to
service other I/O. Measured against a copy of the live database
(18,157 spans / 4,046 metrics):

| Operation | Blocking time |
|---|---|
| `insert_spans_substrate` — 512-row existence probe | 455 ms (0.89 ms/row) |
| `insert_metrics_substrate` — 500-row `INSERT ... RETURNING` | 117 ms |
| WAL replay on open (14.7 MB WAL) | 6.82 s |

akosha's `MAX_BATCH_SIZE` is 512, so one span batch is the worst case.

### Amplifier: WAL checkpointing

The live database is 5.2 MB with a 14.7 MB WAL. DuckDB's
`checkpoint_threshold` is 16 MiB, so the next write burst triggers a
checkpoint — a large blocking operation — inside the write path, and every
reopen replays 14.7 MB of WAL (6.82 s).

### Why this belongs in oneiric, not akosha

The blocking call lives in `DuckdbHotStore`. mahavishnu constructs the same
class directly (`mahavishnu/ingesters/otel_inger.py:609` — the ingester), so
an akosha-side override would duplicate the logic and leave mahavishnu
carrying the same defect. The class owns the shared connection and the lock;
the fix belongs with them.

## Scope

Every DuckDB touchpoint in `DuckdbHotStore` is a synchronous call on the
event loop. Fixing only the write path would leave the same landmine in the
read path for the next reader, so the whole class is converted:

| Method | Notes |
|---|---|
| `initialize` | DDL; the 6.82 s WAL replay lands here |
| `insert_spans_substrate` | hot write path |
| `insert_metrics_substrate` | hot write path |
| `insert_dlq_rows` | error path |
| `table_exists` | catalog query |
| `insert` | conversation ingest |
| `search_similar` | read path |
| `close` | shutdown |

## Approach

Each public `async def` keeps its signature and its semantics, and becomes a
thin wrapper: take the lock, hand the work to a worker thread, return the
result. The query bodies move into plain `def` helpers, because a helper with
no `await` in it is exactly what a thread can run.

**`asyncio.to_thread`, with the existing `asyncio.Lock` still held.**

DuckDB's Python connection was verified safe for this use:

- A connection created on the main thread, then used from worker threads via
  `asyncio.to_thread`, returned correct results (row counts 1, 2, 3, 4, 5).
- Three concurrent `to_thread` calls against one connection produced no
  corruption and no duplication (final count 8, 8 distinct ids).

The lock is still load-bearing for a different reason: concurrent probes
against one connection returned *non-deterministic intermediate counts*
(`[8, 6, 8]`), because DuckDB serializes at the statement level but does not
give the caller a consistent view across statements. The `asyncio.Lock` is
what provides logical isolation, so it stays.

### The second defect: the connection was never really thread-safe

The first version of this fix moved the queries to a worker thread and left
the connection alone. That was wrong, and it showed up in production.

DuckDB's Python binding **refuses** concurrent use of one connection: the
second caller gets `Resource In Use Error: connection is busy with another
call` rather than waiting for the first to finish. It does not queue.

Before the change this never happened, because the event loop was the only
thread that ever touched the connection — every query ran synchronously
inside an `async def`, so the loop serialized them for free. Moving the
substrate's work to a thread removed that free serialization, and callers
that reach for `conn` directly collided with an in-flight write. akosha does
exactly that in five places: its retention sweep (`otlp_receiver.py:1181`)
and its aging service (`storage/aging.py:321, 423, 441, 458`) all call
`hot_store.conn.execute(...)` without going through the store's API.

The live symptom was `akosha.canary.substrate_write_failed detail=spans
substrate write failed: Resource In Use Error: connection is busy with
another call`.

So the guarantee has to be explicit. `self.conn` becomes a
`_SerializedConnection` proxy that takes a re-entrant `threading.RLock`
around every call. Re-entrancy is load-bearing: the store holds the lock
for a whole operation and the queries inside it re-take the lock on the same
thread.

**Locking `execute` is not enough on its own.** DuckDB's `execute` returns
the connection itself with the result attached — `conn.execute(sql)` *is*
`conn` — so reading that result (`fetchone`, `fetchall`, `rowcount`) is
another call into DuckDB. An unlocked read slips into the gap between the
two and collides with an in-flight write exactly like an unlocked query
would. This was the second version of the bug: the proxy locked `execute`,
the write still raised `Resource In Use Error`, and the read that escaped
the lock was the colliding call. The proxy therefore returns a
`_SerializedResult` that takes the same lock for the reads.

Two locks, guarding different things:

| Lock | Guards |
|---|---|
| `self._lock` (asyncio) | this store's operations against each other — a consistent view across a multi-statement write |
| `self._conn_lock` (threading) | the connection against callers that reach for `conn` directly |

`table_exists` did not take `self._lock` originally, and was safe only by
accident; it takes it now, like every other method.

## Rollback

Revert the commit. The public API is unchanged; no schema, DDL, or
configuration changes.

## Verification

- A regression test that fails on the old code: a ticker task on the event
  loop must keep advancing while a substrate write is in flight.
- A regression test for the connection: a direct `conn.execute` must take the
  connection lock, and so must the result read that follows it.
- A test that the lock covers the whole offloaded operation: no two DuckDB
  calls may overlap.
- Existing substrate tests must pass unchanged — counts, dedup semantics,
  constraint enforcement, idempotency.
- `crackerjack run -v -f` must be clean.

Each was checked by mutating the implementation and confirming the matching
test fails: putting the query back on the loop, moving the offload outside
the lock, dropping the serializing wrapper, and leaving the result read
unlocked each produce exactly the failures they are meant to catch.

The connection tests hold the connection lock and assert the call waits for
it, rather than racing two callers and hoping they overlap. The collision
is timing-dependent, and a flaky test for it would be worse than none — an
earlier version of these tests passed against a broken implementation when
the machine was busy enough to change the interleaving.

End-to-end verification against akosha's own `HotStore` on a copy of the
live database: a 512-row write and a direct-connection read run
concurrently with no exception, and the event loop keeps ticking
throughout — 1,291 ticks during the write, 0.2 ms max poll latency.

## Deployment

oneiric is installed editable in the akosha venv
(`_editable_impl_oneiric.pth` → `/Users/les/Projects/oneiric`), and the
running service imports `/Users/les/Projects/oneiric/oneiric/__init__.py`.
The fix is live in the running akosha on restart, with no publish.

The publish is still required for delivery: `akosha/uv.lock` pins oneiric
0.34.0, so a fresh `uv sync` anywhere would pull a build without the fix.
It ships as **0.35.0** — not 0.34.1 — because that release also has to carry
the unpublished `metrics_substrate` feature (`f869951`) that akosha 0.27.0
depends on. Publish order: oneiric 0.35.0, then akosha 0.27.0 with its pin
raised to `oneiric>=0.35`.

## Follow-up (not in this change)

`insert_spans_substrate` probes existence once per row before its
`executemany`, because DuckDB's `executemany` reports no per-row outcome.
The metrics path already avoids this with a single `INSERT ... RETURNING ts`
and counts the returned rows. The span path could use the same shape
(`INSERT ... RETURNING span_id`), turning 455 ms into a single statement —
but that changes the dedup accounting, so it is a separate change.
