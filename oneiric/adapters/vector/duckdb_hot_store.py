"""DuckDB-backed HotStore concrete — Oneiric substrate implementation.

Per ADR 017, the canonical HotStore implementation lives with the
substrate library (Oneiric), not with the application-layer component
(AkoSHA). This module ports the conversations-table surface from
``akosha/storage/hot_store.py`` to Oneiric; AkoSHA's ``HotStore`` class
extends this with code-graph sub-features (per akosha-specific
domain).

Substrate level (this file):
  - ``__init__``, ``initialize``, ``insert``, ``search_similar``, ``close``,
    ``conn`` attribute — the surface ``otel_ingester.py`` calls.
  - DuckDB-backed; HNSW index; metadata filter helpers.
  - Stateless helpers: ``_to_naive_utc``, ``_strip_tz_suffix``.

NOT in scope (stay in AkoSHA):
  - Code-graph sub-features: ``initialize_code_graphs_table``,
    ``store_code_graph``, ``get_code_graph``, ``list_code_graphs``
    — these are AkoSHA's domain (cross-repo pattern ingestion).
    AkoSHA's ``HotStore`` extends ``DuckdbHotStore`` and adds these.

Refs:
- docs/adr/017-oneiric-shared-persistence-substrate.md
- oneiric commit 93f60cd (Protocol sibling)

Dependencies:
- duckdb (third-party). The class is importable only when ``duckdb`` is
  installed; Oneiric's substrate ships duckdb as an optional dep so the
  pgvector-backed production path stays the default.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import logging
import threading
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from itertools import batched
from pathlib import Path
from typing import Any, TypeVar

import duckdb  # third-party; substrate ships it as an optional extra for development

from oneiric.adapters.vector.metrics import (
    record_metrics_substrate_insert,
    record_metrics_substrate_insert_failure,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

# ── `spans_substrate` DDL ──────────────────────────────────────────────────
# Verbatim from spec §5.1 of
# `docs/specs/2026-10-19-bodai-substrate-otel-v7.md`. Verified against the
# DuckDB build `uv.lock` pins; the audit trail is §5.1a.
#
# Two DuckDB constraints shaped this and neither is obvious:
#
# - `uq_span_identity` is INLINE in CREATE TABLE, not a separate ALTER. v5
#   tried `ALTER TABLE ... ADD COLUMN received_at_unix_nano BIGINT NOT NULL
#   DEFAULT (...)` and DuckDB rejects adding a constrained column
#   (1.5.6: "Adding columns with constraints not yet supported";
#   2.0.0-dev: DependencyException). Same conclusion, different diagnostic.
#   Columns therefore ship in the initial schema.
# - The indexes carry NO `WHERE` clause. DuckDB raises NotImplementedException
#   for partial indexes on both builds, so the outcome predicate lives in the
#   read-side SELECT instead.
#
# One writer exists: the akosha OTLP receiver, via `HotStore.insert_spans_substrate`.
# akosha's read-path tests carry their own copy in
# `akosha/tests/_support/spans_ddl.py`; the two must be updated together.
SPANS_SUBSTRATE_DDL = """
CREATE TABLE IF NOT EXISTS spans_substrate (
    span_id                   TEXT PRIMARY KEY,
    trace_id                  TEXT,
    parent_span_id            TEXT,
    service_name              TEXT         NOT NULL,
    service_namespace         TEXT         NOT NULL,
    deployment_environment    TEXT,
    telemetry_source          TEXT,
    telemetry_source_type     TEXT,
    span_name                 TEXT         NOT NULL,
    start_time_unix_nano      BIGINT       NOT NULL,
    end_time_unix_nano        BIGINT,
    received_at_unix_nano     BIGINT       NOT NULL,
    duration_ms               REAL,
    outcome                   TEXT,
    selector                  TEXT,
    task_class                TEXT,
    latency_ms                REAL,
    gen_ai_provider_name      TEXT,
    gen_ai_request_model      TEXT,
    gen_ai_response_model     TEXT,
    gen_ai_usage_input_tokens INTEGER,
    gen_ai_usage_output_tokens INTEGER,
    gen_ai_usage_cost         NUMERIC(10, 6),
    status_code               TEXT,
    status_message            TEXT,
    attributes                JSON         NOT NULL,
    events                    JSON,
    resource                  JSON         NOT NULL,
    has_gen_ai_attrs          BOOLEAN      NOT NULL DEFAULT FALSE,
    has_dispatch_attrs        BOOLEAN      NOT NULL DEFAULT FALSE,
    inserted_at               TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_span_identity UNIQUE (trace_id, span_id)
);
"""

# Trailing `received_at_unix_nano DESC` on every index: the read path pages by
# keyset on (received_at_unix_nano, span_id), so every filter that can precede
# the sort needs one.
SPANS_SUBSTRATE_INDEXES: tuple[tuple[str, str], ...] = (
    (
        (
            "CREATE INDEX IF NOT EXISTS idx_spans_selector_task_class_outcome "
            "ON spans_substrate(selector, task_class, outcome, received_at_unix_nano DESC)"
        ),
        "idx_spans_selector_task_class_outcome",
    ),
    (
        (
            "CREATE INDEX IF NOT EXISTS idx_spans_service_name_recent "
            "ON spans_substrate(service_name, received_at_unix_nano DESC)"
        ),
        "idx_spans_service_name_recent",
    ),
    (
        (
            "CREATE INDEX IF NOT EXISTS idx_spans_source_type_recent "
            "ON spans_substrate(telemetry_source_type, received_at_unix_nano DESC)"
        ),
        "idx_spans_source_type_recent",
    ),
    (
        (
            "CREATE INDEX IF NOT EXISTS idx_spans_received_at_recent "
            "ON spans_substrate(received_at_unix_nano DESC)"
        ),
        "idx_spans_received_at_recent",
    ),
)

# ── `metrics_substrate` DDL ───────────────────────────────────────────────
# The metric counterpart of `spans_substrate`, in the same substrate file
# (plan `docs/plans/2026-10-27-otel-metrics-service.md`, Phase 1 / REQ-M03).
# Same idempotent inline DDL, same writer, same no-migration-runner rule
# described above — this fleet has no migration runner, so every table ships
# as `CREATE TABLE IF NOT EXISTS` executed on every boot.
#
# The identity constraint is the interesting part, and it is NOT the spans
# constraint. A span is a unique event and `span_id` names it. A metric data
# point is a *sample of a time series*, so what names it is the series
# identity plus the instant it was recorded:
#
#     (service_name, service_namespace, scope_name, metric_name, ts, attributes)
#
# `attributes` — the data point's own attribute set — is in the key because it
# is the label set: two points differing only by a label are two different
# series, not two samples of one series. `resource` is stored but deliberately
# NOT in the key; see `insert_metrics_substrate` for why.
#
# `attributes` is a JSON column inside the constraint, and DuckDB compares
# JSON *as text* — verified on the pinned 2.1.0-dev build, where
# `{"a":1,"b":2}` and `{"b":2,"a":1}` are two different rows. Text comparison
# makes the constraint exact only if every stored value is byte-stable, which
# OTLP producers do not guarantee: attribute ordering follows producer-side
# iteration order. `insert_metrics_substrate` therefore canonicalizes the
# attribute JSON before it is bound. The stored value then IS the identity —
# no hash, no collision window, and the same attribute set always lands on
# the same row however the producer serialized it.
#
# One writer exists, mirroring the span path: the akosha OTLP receiver.
# req: REQ-M03
METRICS_SUBSTRATE_DDL = """
CREATE TABLE IF NOT EXISTS metrics_substrate (
    ts                   BIGINT    NOT NULL,
    service_name         TEXT      NOT NULL,
    service_namespace    TEXT      NOT NULL,
    scope_name           TEXT      NOT NULL,
    metric_name          TEXT      NOT NULL,
    data_type            TEXT      NOT NULL,
    unit                 TEXT,
    description          TEXT,
    value_sum            DOUBLE,
    value_count          BIGINT,
    value_min            DOUBLE,
    value_max            DOUBLE,
    value_sum_of_squares DOUBLE,
    is_monotonic         BOOLEAN,
    buckets_json         JSON,
    attributes           JSON      NOT NULL,
    resource             JSON      NOT NULL,
    inserted_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_metric_point UNIQUE (
        service_name, service_namespace, scope_name, metric_name, ts, attributes
    ),
    CONSTRAINT ck_metric_data_type CHECK (
        data_type IN (
            'sum',
            'gauge',
            'histogram',
            'exponential_histogram',
            'summary'
        )
    )
);
"""

# The numeric payload is carried in the `value_*` columns under a per-type
# convention, because OTLP gives each data type a different shape:
#
#   sum / gauge -> value_sum is the sample, value_count is 1
#   histogram   -> value_sum / value_count / value_min / value_max /
#                  value_sum_of_squares, with the bucket boundaries and
#                  counts in `buckets_json`
#   summary     -> value_sum / value_count / value_min / value_max /
#                  value_sum_of_squares
#
# `is_monotonic` is meaningful only for a `sum` and stays NULL for every
# other type rather than FALSE: "not applicable" and "false" are different
# facts, and a gauge is not a non-monotonic sum.
#
# `buckets_json` is the one column beyond the plan's enumerated list. Without
# it a stored histogram cannot be reconstructed — the summary statistics do
# not determine the bucket boundaries — so the schema would have to change
# again in Phase 2, when the receiver starts writing histograms.

# Trailing `ts DESC` on every index, mirroring the span path: the read path
# pages by keyset on (ts, metric_name), so every filter that can precede the
# sort needs one.
METRICS_SUBSTRATE_INDEXES: tuple[tuple[str, str], ...] = (
    (
        (
            "CREATE INDEX IF NOT EXISTS idx_metrics_name_recent "
            "ON metrics_substrate(metric_name, ts DESC)"
        ),
        "idx_metrics_name_recent",
    ),
    (
        (
            "CREATE INDEX IF NOT EXISTS idx_metrics_service_recent "
            "ON metrics_substrate(service_name, ts DESC)"
        ),
        "idx_metrics_service_recent",
    ),
    (
        (
            "CREATE INDEX IF NOT EXISTS idx_metrics_ts_recent "
            "ON metrics_substrate(ts DESC)"
        ),
        "idx_metrics_ts_recent",
    ),
)

# The insert column list, in DDL order. The projection in
# `_metric_point_values` is driven by this tuple rather than by the caller's
# dict, because the key set varies by metric type: a gauge carries no
# `is_monotonic`, a histogram carries no `value_sum` and carries
# `buckets_json`.
METRICS_SUBSTRATE_COLUMNS: tuple[str, ...] = (
    "ts",
    "service_name",
    "service_namespace",
    "scope_name",
    "metric_name",
    "data_type",
    "unit",
    "description",
    "value_sum",
    "value_count",
    "value_min",
    "value_max",
    "value_sum_of_squares",
    "is_monotonic",
    "buckets_json",
    "attributes",
    "resource",
)

# Columns stored as JSON. Every one of them is canonicalized before it is
# bound, so the stored text is a function of the value's content alone.
METRICS_SUBSTRATE_JSON_COLUMNS: frozenset[str] = frozenset(
    {"attributes", "buckets_json", "resource"}
)

# Rows per INSERT statement. The statement binds one placeholder per column
# per row, so an unbounded batch would build an unbounded SQL string; the
# chunk also bounds how many conflict checks a single statement carries.
METRICS_SUBSTRATE_INSERT_CHUNK = 500

# ── receiver operational tables ───────────────────────────────────────────
# Spec §5.3 + §15 (the v7 "Migration framework: none" decision) place these
# two tables in the same substrate as `spans_substrate`, created by the same
# idempotent inline DDL rather than by a migrations framework. The fleet has
# no migration runner: mahavishnu uses Alembic (`migrations/versions/V*.sql`),
# akosha and oneiric have none, and building yoyo for two tiny tables would
# have introduced a third framework for no sequencing benefit. `IF NOT EXISTS`
# covers both a fresh substrate file and a pre-existing one on every boot.
#
# §5.3 draws the ownership line explicitly, and it is worth restating because
# it looks contradictory: these tables are AKOSHAs tables that happen to be
# CREATED here. `_dlq_rows` holds rows that were already rejected on their way
# into the substrate — dead-letter storage for ingest, not telemetry. The
# receiver is the only writer of both; nothing in the read path queries them.
RECEIVER_STATE_DDL = """
CREATE TABLE IF NOT EXISTS _akosha_otel_receiver_state (
    component       TEXT PRIMARY KEY,
    schema_version  INTEGER NOT NULL,
    last_applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

# `_dlq_rows` is deliberately keyed on nothing. A quarantine table holds rows
# that failed a uniqueness or NOT NULL constraint elsewhere; giving it its own
# primary key here would re-introduce the collision the DLQ exists to survive.
DLQ_ROWS_DDL = """
CREATE TABLE IF NOT EXISTS _dlq_rows (
    rejected_at  TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reason       TEXT        NOT NULL,
    field        TEXT,
    row_json     JSON        NOT NULL,
    trace_id     TEXT,
    span_id      TEXT
);
"""

# §8.1 retention sweeps `_dlq_rows` by age; without this index every sweep is
# a full scan of a table that only ever grows until the first sweep runs.
DLQ_ROWS_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_dlq_rows_recent ON _dlq_rows(rejected_at DESC)"
)

# Default embedding dimensionality when neither ``embedding_dim`` is passed
# at ``__init__`` nor a registered embedding service is available. Matches
# MiniLM-L6-v2's standard output dim — the most common cross-component choice.
DEFAULT_EMBEDDING_DIM = 384


def _to_naive_utc(dt: datetime) -> datetime:
    """Convert a possibly-tz-aware datetime to naive UTC.

    DuckDB ``TIMESTAMP`` (not ``TIMESTAMPTZ``) stores naive wall-clock
    values. The Python binding for tz-aware datetimes silently shifts
    the value to the session's local time before dropping tz info —
    the same instant in time can therefore land at different stored
    values depending on whether the caller passed naive or tz-aware.
    Normalising to naive UTC at every storage boundary makes inserts
    session-tz-invariant and matches what the column actually stores.
    """
    if dt.tzinfo is not None:
        return dt.astimezone(UTC).replace(tzinfo=None)
    return dt


def _strip_tz_suffix(s: str) -> str:
    """Strip ISO-8601 tz suffix off a timestamp string (``+HH:MM`` / ``-HH:MM`` / ``Z``).

    DuckDB currently accepts the ``+00:00`` suffix against a
    ``TIMESTAMP`` column without complaint, but stripping it is
    defense in depth — a DuckDB/ICU upgrade could regress this
    path, and ``search_similar`` is on the hot read-side of every
    Bodai component. The space-separator ``YYYY-MM-DD HH:MM:SS`` form
    (also accepted by DuckDB) is unchanged.
    """
    if "T" not in s:
        return s  # already space-separated, not ISO; leave as-is
    if s.endswith("Z"):
        return s[:-1]
    for sep in ("+", "-"):
        idx = s.rfind(sep)
        if idx > 10:  # past the date portion (YYYY-MM-DD)
            tail = s[idx:]
            if ":" in tail and len(tail) == 6:  # +HH:MM or -HH:MM form
                return s[:idx]
    return s


def _canonical_json(value: str | Mapping[str, Any], field: str) -> str:
    """Render ``value`` as byte-stable JSON text.

    Two producers describing the same attribute set can serialize it in
    different orders — OTLP attribute ordering follows producer-side
    iteration order, not a specification. DuckDB compares a JSON column as
    text, so an uncanonicalized attribute set would make one point look like
    two. Sorting the keys at every level makes the stored text a function of
    the attribute *set* alone, which is what the identity constraint needs.

    Args:
        value: JSON text, or an already-decoded mapping.
        field: Column name, used only in the error message.

    Raises:
        ValueError: If ``value`` is not valid JSON, or holds a value that
            cannot be represented in JSON.
        TypeError: If ``value`` does not describe a JSON object. The text was
            well-formed JSON, so the problem is the shape rather than the
            content — which is a different failure from unparsable text.
    """
    payload: Any
    if isinstance(value, str):
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field} is not valid JSON: {exc}") from exc
    else:
        payload = value
    if not isinstance(payload, dict):
        raise TypeError(f"{field} must be a JSON object, got {type(payload).__name__}")
    try:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
    except TypeError as exc:
        raise ValueError(
            f"{field} holds a value that cannot be represented in JSON: {exc}"
        ) from exc


def _metric_point_values(row: Mapping[str, Any]) -> list[Any]:
    """Project one row dict onto ``METRICS_SUBSTRATE_COLUMNS``, in order.

    The projection is driven by the DDL's column list rather than by the
    caller's dict, because the key set varies by metric type. Reading the
    column order off ``rows[0]`` — which is what the span path does, safely,
    because every span row carries the same keys — would silently drop a
    column whenever the first row of a batch is a different type from the
    rest.
    """
    values: list[Any] = []
    for column in METRICS_SUBSTRATE_COLUMNS:
        value = row.get(column)
        if column in METRICS_SUBSTRATE_JSON_COLUMNS and value is not None:
            value = _canonical_json(value, column)
        values.append(value)
    return values


class _SerializedResult:
    """The result DuckDB hands back from ``execute``.

    ``DuckDBPyConnection.execute`` returns the connection itself with the
    result attached — ``conn.execute(sql)`` *is* ``conn`` — and reading that
    result (``fetchone``, ``fetchall``, ``rowcount``) is a further call into
    DuckDB. A wrapper that only locked ``execute`` would let the read
    escape into the gap between the two, where it can collide with an
    in-flight write exactly like an unlocked query would.
    """

    def __init__(
        self,
        conn: duckdb.DuckDBPyConnection,
        lock: threading.RLock,
    ) -> None:
        self._conn = conn
        self._lock = lock

    def fetchone(self) -> Any:
        with self._lock:
            return self._conn.fetchone()

    def fetchall(self) -> Any:
        with self._lock:
            return self._conn.fetchall()

    def fetchdf(self, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return self._conn.fetchdf(*args, **kwargs)

    @property
    def rowcount(self) -> int:
        with self._lock:
            return self._conn.rowcount

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._conn, name)
        if not callable(attr):
            return attr

        @functools.wraps(attr)
        def locked(*args: Any, **kwargs: Any) -> Any:
            with self._lock:
                return attr(*args, **kwargs)

        return locked


class _SerializedConnection:
    """A DuckDB connection whose calls are serialized across threads.

    DuckDB's Python binding refuses concurrent use of one connection: the
    second caller gets ``Resource In Use Error: connection is busy with
    another call`` rather than waiting for the first to finish. It does not
    queue, so this is a hard failure, not a slowdown.

    The event loop used to provide that serialization for free — it was the
    only thread that ever touched the connection, because every query ran
    synchronously inside an ``async def``. Moving the substrate's work to a
    worker thread removed that free guarantee, and any caller that reaches
    for ``conn`` directly would collide with an in-flight write. akosha
    does exactly that: its retention sweep and its aging service call
    ``hot_store.conn.execute(...)`` without going through the store's API.

    So the guarantee has to be explicit. Every method takes a re-entrant
    lock. Re-entrancy is load-bearing: the store holds the lock for a whole
    operation, and the queries inside that operation re-take it on the same
    thread.
    """

    def __init__(
        self,
        conn: duckdb.DuckDBPyConnection,
        lock: threading.RLock,
    ) -> None:
        self._conn = conn
        self._lock = lock

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return _SerializedResult(self._conn.execute(*args, **kwargs), self._lock)

    def executemany(self, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return _SerializedResult(
                self._conn.executemany(*args, **kwargs), self._lock
            )

    def commit(self) -> None:
        with self._lock:
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def cursor(self) -> Any:
        with self._lock:
            return self._conn.cursor()

    def __getattr__(self, name: str) -> Any:
        """Forward anything else, under the lock.

        Without this, an unlisted method would reach the raw connection
        with no serialization at all — the exact failure this class
        exists to prevent.
        """
        attr = getattr(self._conn, name)
        if not callable(attr):
            return attr

        @functools.wraps(attr)
        def locked(*args: Any, **kwargs: Any) -> Any:
            with self._lock:
                return attr(*args, **kwargs)

        return locked


class DuckdbHotStore:
    """DuckDB-backed hot-store concrete implementation.

    Development / test backend (in-memory by default, or file-backed for
    warm starts). Production deployments use the pgvector-backed impl —
    this one is for hot-path development, integration tests, and
    ephemeral-filesystem deployments that don't require persistence.

    The class conforms to ``oneiric.adapters.vector.hot_store.HotStore``
    via duck typing — no inheritance required. AkoSHA's ``HotStore``
    extends this with code-graph sub-features; Mahavishnu's
    ``otel_ingester`` uses this directly via runtime construction.
    """

    # Table names are class attributes rather than literals so callers name the
    # surface they depend on. The OTLP receiver asserts against
    # ``spans_substrate_table`` (and, once the metrics receiver lands,
    # ``metrics_substrate_table``) to fail loud when the DDL is absent.
    conversations_table: str = "conversations"
    spans_substrate_table: str = "spans_substrate"
    metrics_substrate_table: str = "metrics_substrate"
    receiver_state_table: str = "_akosha_otel_receiver_state"
    dlq_rows_table: str = "_dlq_rows"

    def __init__(
        self,
        database_path: str | Path = ":memory:",
        embedding_dim: int | None = None,
    ) -> None:
        """Initialize the DuckDB-backed hot store.

        Args:
            database_path: DuckDB database location. ``":memory:"`` for
                ephemeral; file path for persisted dev/test.
            embedding_dim: Vector dimensionality. ``None`` resolves to
                ``DEFAULT_EMBEDDING_DIM`` (384) at init time. Pin an
                explicit ``int`` to ensure schema dim matches the
                embedding service's output.
        """
        self.db_path = database_path
        self.conn: _SerializedConnection | None = None
        self._lock = asyncio.Lock()
        # The connection's own lock, shared with ``_SerializedConnection``.
        # ``self._lock`` serializes this store's operations against each
        # other; this one serializes them against callers that reach for
        # ``conn`` directly. Both are needed — see ``_SerializedConnection``.
        self._conn_lock = threading.RLock()
        # Schema dim is baked into the CREATE TABLE DDL at initialize()
        # time — capture it now so the SQL can interpolate ``FLOAT[<dim>]``
        # as a literal. Pass an explicit int for tests that don't go
        # through the embedding service initialization path.
        self._embedding_dim: int = (
            embedding_dim if embedding_dim is not None else DEFAULT_EMBEDDING_DIM
        )

    async def _run_off_loop(self, func: Callable[[_SerializedConnection], T]) -> T:
        """Run a synchronous DuckDB call on a worker thread.

        ``duckdb.DuckDBPyConnection.execute`` blocks the calling thread until
        the query has run and its result is materialized. There is no
        awaitable underneath it, so calling it from an ``async def`` pins the
        event loop for the whole query — the coroutine looks async but is
        not.

        On the OTLP ingest path that is half a second to a second per batch,
        which is long enough to starve every other coroutine. akosha's Redis
        client (``socket_timeout=5``) began failing with ``TimeoutError``,
        and the HTTP and gRPC surfaces stopped answering while TCP still
        connected — the kernel's accept backlog hides a stalled loop.

        The work runs on a worker thread instead.

        Two locks are in play, and they guard different things:

        * ``self._lock`` (asyncio) is taken by the calling method and is
          awaited across this call, so it covers the whole operation. It
          serializes this store's operations against each other, which is
          what gives a multi-statement operation a consistent view — two
          probes racing on one connection returned inconsistent
          intermediate counts.
        * ``self._conn_lock`` (threading) is taken here, around the whole
          operation, and is what keeps the connection safe for callers that
          reach for ``conn`` directly. DuckDB refuses concurrent use of one
          connection rather than queueing, so without this the substrate's
          write and akosha's retention sweep would collide.

        Args:
            func: Callable taking the connection and returning the result.

        Returns:
            Whatever ``func`` returns.

        Raises:
            RuntimeError: If the store was never initialized.
        """
        conn = self.conn
        if conn is None:
            raise RuntimeError("Hot store not initialized")

        def runner() -> T:
            with self._conn_lock:
                return func(conn)

        return await asyncio.to_thread(runner)

    async def initialize(self) -> None:
        """Initialize database schema (conversations table + HNSW index).

        Idempotent; safe to call multiple times.
        """
        async with self._lock:
            # Opening a file-backed database replays its WAL, and the DDL
            # below runs a statement per table and index. Both block the
            # calling thread; on a database with a large WAL the replay
            # alone is seconds.
            raw = await asyncio.to_thread(duckdb.connect, str(self.db_path))
            # The proxy is what makes the connection safe to share between
            # this store's worker threads and callers that reach for
            # ``conn`` directly.
            self.conn = _SerializedConnection(raw, self._conn_lock)
            await self._run_off_loop(self._initialize_schema)

    def _initialize_schema(self, conn: _SerializedConnection) -> None:
        """Create every table and index this store owns."""
        # Create conversations table with HNSW index support.
        # ``embedding FLOAT[N]`` is interpolated at __init__ time so
        # the schema dim matches the active backend; this MUST
        # match the dim the embedding service produces or insert()
        # raises.
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS conversations (
                system_id VARCHAR,
                conversation_id VARCHAR PRIMARY KEY,
                content TEXT,
                embedding FLOAT[{self._embedding_dim}],
                timestamp TIMESTAMP,
                metadata JSON,
                content_hash VARCHAR,
                uploaded_at TIMESTAMP DEFAULT NOW()
            )
        """
        )
        # HNSW index for vector similarity search.
        try:
            conn.execute("""
                CREATE INDEX IF NOT EXISTS embedding_hnsw_index
                ON conversations USING HNSW (embedding)
                WITH (m = 16, ef_construction = 200)
            """)
        except Exception as exc:
            logger.warning("HNSW index creation failed: %s", exc)
        # Filter indexes (performance).
        for ddl, name in (
            (
                "CREATE INDEX IF NOT EXISTS system_id_index ON conversations (system_id)",
                "system_id",
            ),
            (
                "CREATE INDEX IF NOT EXISTS timestamp_index ON conversations (timestamp)",
                "timestamp",
            ),
            (
                "CREATE INDEX IF NOT EXISTS system_timestamp_index ON conversations (system_id, timestamp)",
                "composite_system_timestamp",
            ),
        ):
            try:
                conn.execute(ddl)
                logger.info("Created %s index", name)
            except Exception as exc:
                logger.warning("%s index creation failed: %s", name, exc)

        # ── spans_substrate (v7 PR-0a) ──────────────────────────────
        # The OTel span substrate. Substrate-managed per ADR 017: every
        # Bodai component inherits the access path from here.
        #
        # Deliberately not wrapped in try/except. A substrate that cannot
        # create its own table is broken, and swallowing that would surface
        # later as a read path that silently returns nothing — the exact
        # failure mode table_exists() exists to let callers detect.
        conn.execute(SPANS_SUBSTRATE_DDL)
        for index_ddl, index_name in SPANS_SUBSTRATE_INDEXES:
            conn.execute(index_ddl)
            logger.info("Created %s index", index_name)

        # ── metrics_substrate (plan Phase 1 / REQ-M03) ───────────────
        # The metric counterpart of `spans_substrate`, in the same file.
        # Created on this same path so a producer can never find the
        # table missing. Same no-try/except reasoning as above — a
        # substrate that cannot create its own tables is broken, and
        # hiding that is worse.
        #
        # The trace receiver asserts `spans_substrate_table` exists at
        # bind time; the METRICS receiver deliberately does not. Failing
        # the receiver's boot to prove a metric table is missing would
        # take the trace path down with it, and a missing table already
        # reports itself as `oneiric_metrics_substrate_insert_failed_total`
        # (see `insert_metrics_substrate`).
        conn.execute(METRICS_SUBSTRATE_DDL)
        for index_ddl, index_name in METRICS_SUBSTRATE_INDEXES:
            conn.execute(index_ddl)
            logger.info("Created %s index", index_name)

        # ── receiver operational tables (v7 §5.3) ─────────────────────
        # Created alongside the substrate table rather than by the
        # receiver itself: the receiver's ``start()`` asserts
        # ``spans_substrate_table`` exists and raises otherwise, and a
        # receiver that has to create its own DLQ on the fly would be
        # asserting something it just did. Same reasoning as the
        # no-try/except decision above — a substrate that cannot create
        # its own tables is broken, and hiding that is worse.
        conn.execute(RECEIVER_STATE_DDL)
        conn.execute(DLQ_ROWS_DDL)
        conn.execute(DLQ_ROWS_INDEX)
        logger.info("Created receiver operational tables")

        logger.info("Hot store initialized")

    # ── ingest writers ──────────────────────────────────────────────────
    # These live beside the DDL above rather than in akosha's subclass. The
    # tables are substrate-owned (ADR 017), the write path is substrate
    # access, and putting the writers next to the schema they target keeps
    # the two from drifting — a column added to ``SPANS_SUBSTRATE_DDL`` and
    # a column named in an INSERT statement in another repo is a silent
    # mismatch until a producer happens to send that field.
    #
    # akosha's ``HotStore`` inherits both, so the OTLP receiver's call sites
    # are unchanged. Its module is kept small on purpose (a CI test caps it
    # at 500 LOC) precisely so it stays a thin subclass.

    async def insert_spans_substrate(
        self,
        rows: list[dict[str, Any]],
    ) -> tuple[int, int]:
        """Bulk-INSERT validated spans; return ``(inserted, deduped)``.

        Spec §15 prescribes ``ON CONFLICT (trace_id, span_id) DO NOTHING``.
        That clause is written here WITHOUT the conflict target, which is not
        a style choice — it is the only form that satisfies the spec's stated
        intent against the spec's own DDL.

        ``SPANS_SUBSTRATE_DDL`` declares both ``span_id TEXT PRIMARY KEY`` and
        ``CONSTRAINT uq_span_identity UNIQUE (trace_id, span_id)``. A PK on
        ``span_id`` alone is strictly narrower than a unique on the pair, so
        every row that collides on the composite key has already collided on
        the PK: ``uq_span_identity`` can never be the constraint that rejects
        anything. A targeted ``ON CONFLICT (trace_id, span_id)`` handles only
        the constraint it names, so a ``span_id`` collision falls through to
        the PK and raises ``ConstraintException`` — an unhandled exception on
        the hot ingest path, in exactly the case the composite key exists to
        handle (two producers reusing a ``span_id`` under different
        ``trace_id``s, e.g. a producer that restarted its trace).

        Untargeted ``ON CONFLICT DO NOTHING`` honors every constraint, so a
        replay is a genuine no-op whichever one catches it. Verified against
        the pinned DuckDB 2.0.0.dev build. NOT NULL violations are unaffected
        and still raise, which is what keeps the table constraint a usable
        backstop for rows the receiver's validation fails to catch.

        Counting samples pre-insert existence rather than reading rows back:
        a read-back cannot distinguish "this INSERT wrote it" from "it was
        already here", so it would report a pure replay as N inserts. DuckDB's
        ``executemany`` reports no per-row outcome, so existence has to be
        probed explicitly. Both numbers are wanted — a receiver whose dedup
        count silently collapses to zero is indistinguishable from one
        receiving nothing new.

        Columns are named explicitly. The table has ~28 and the receiver's
        row dicts carry a producer-varying subset, so a positional INSERT
        would couple the caller's field order to the DDL column order.
        """
        if not rows:
            return (0, 0)
        async with self._lock:
            return await self._run_off_loop(
                lambda conn: self._insert_spans_substrate_sync(conn, rows)
            )

    def _insert_spans_substrate_sync(
        self,
        conn: _SerializedConnection,
        rows: list[dict[str, Any]],
    ) -> tuple[int, int]:
        """Write one span batch. Runs on a worker thread.

        See ``_run_off_loop`` for why the call is off the event loop.
        """
        table = self.spans_substrate_table
        columns = list(rows[0].keys())
        placeholders = ", ".join("?" for _ in columns)
        collist = ", ".join(columns)

        # Keyed on ``span_id`` alone — the narrowest constraint in the
        # DDL, and therefore an exact predictor of what the untargeted
        # ON CONFLICT will do. Probing the composite pair instead would
        # report "inserted" for rows the database silently dropped, and
        # the returned numbers would disagree with the table.
        seen: set[Any] = set()
        deduped = 0
        for row in rows:
            span_id = row.get("span_id")
            if span_id in seen:
                deduped += 1
                continue
            seen.add(span_id)
            hit = conn.execute(
                f"SELECT 1 FROM {table} WHERE span_id IS NOT DISTINCT FROM ?",
                [span_id],
            ).fetchone()
            if hit:
                deduped += 1

        conn.executemany(
            f"INSERT INTO {table} ({collist}) VALUES ({placeholders}) "
            f"ON CONFLICT DO NOTHING",
            [[r.get(c) for c in columns] for r in rows],
        )
        return (len(rows) - deduped, deduped)

    async def insert_metrics_substrate(
        self,
        rows: list[dict[str, Any]],
    ) -> tuple[int, int]:
        """Bulk-INSERT metric data points; return ``(inserted, deduped)``.

        # Implements: REQ-M03

        A metric data point is a sample of a time series, so its identity is
        the series plus the instant — not a primary key the producer
        supplies. The table's constraint is ``(service_name,
        service_namespace, scope_name, metric_name, ts, attributes)``; a
        point that collides with one already stored is a replay, and is
        dropped.

        The counts come from the statement itself rather than from a
        pre-insert existence probe. The span path has to probe, because
        DuckDB's ``executemany`` reports no per-row outcome — but a single
        multi-row ``VALUES`` statement can ``RETURNING`` the rows it
        actually wrote. That is both exact and cheaper: one statement, one
        conflict check per row, and no window between "does it exist?" and
        "write it" for a concurrent writer to slip into.

        Each statement is atomic: a row that violates a constraint rolls
        that statement back, so no statement is ever half-written. A batch
        larger than ``METRICS_SUBSTRATE_INSERT_CHUNK`` is split across
        several statements, so atomicity holds per chunk — a failure in the
        third chunk leaves the first two committed.

        ``resource`` is stored but is NOT part of the identity. It names the
        *producer*; a producer's identity for the purposes of a time series
        is ``service.name``/``service.namespace``, which is already in the
        key. Folding the whole resource in would split one logical series
        into many whenever incidental resource attributes churn — a
        changing pid, a hostname — multiplying the series the Prometheus
        bridge has to expose.

        First write wins. A replay carrying a *different* value for an
        already-stored point keeps the stored value: the substrate is an
        append-only record of what the producer reported, not a
        last-writer-wins register.

        Args:
            rows: Point dicts keyed by column name. The key set may vary by
                metric type; absent optional columns are stored as NULL.

        Returns:
            ``(inserted, deduped)`` — rows written, and rows that collided
            with an existing point or with an earlier row in the same batch.
        """
        if not rows:
            return (0, 0)
        async with self._lock:
            return await self._run_off_loop(
                lambda conn: self._insert_metrics_substrate_sync(conn, rows)
            )

    def _insert_metrics_substrate_sync(
        self,
        conn: _SerializedConnection,
        rows: list[dict[str, Any]],
    ) -> tuple[int, int]:
        """Write one metric batch. Runs on a worker thread.

        See ``_run_off_loop`` for why the call is off the event loop.
        """
        table = self.metrics_substrate_table
        collist = ", ".join(METRICS_SUBSTRATE_COLUMNS)
        slot = "(" + ", ".join(["?"] * len(METRICS_SUBSTRATE_COLUMNS)) + ")"
        inserted = 0
        try:
            for chunk in batched(rows, METRICS_SUBSTRATE_INSERT_CHUNK):
                params = [value for row in chunk for value in _metric_point_values(row)]
                returned = conn.execute(
                    f"INSERT INTO {table} ({collist}) VALUES "
                    f"{', '.join([slot] * len(chunk))} "
                    "ON CONFLICT DO NOTHING RETURNING ts",
                    params,
                ).fetchall()
                inserted += len(returned)
        except Exception:
            logger.exception("metrics_substrate insert failed")
            record_metrics_substrate_insert_failure()
            raise
        record_metrics_substrate_insert(inserted)
        return (inserted, len(rows) - inserted)

    async def insert_dlq_rows(self, rows: list[dict[str, Any]]) -> int:
        """Append rejected rows to ``_dlq_rows``; return the count written.

        No ``ON CONFLICT`` clause, because there is no uniqueness to collide
        with: the table has no primary key precisely because the rows in it
        already failed a uniqueness constraint on their way into
        ``spans_substrate``. Two distinct spans sharing an identity must both
        survive quarantine — giving the DLQ its own key would re-introduce
        the very collision it exists to absorb.

        Raises on substrate failure. The receiver wraps this call so a DLQ
        outage cannot abort a batch carrying good rows (spec §15); that
        wrapping is the receiver's contract, so a caller who wants DLQ
        failure to be fatal can still have it.
        """
        if not rows:
            return 0
        async with self._lock:
            return await self._run_off_loop(
                lambda conn: self._insert_dlq_rows_sync(conn, rows)
            )

    def _insert_dlq_rows_sync(
        self,
        conn: _SerializedConnection,
        rows: list[dict[str, Any]],
    ) -> int:
        """Append one quarantine batch. Runs on a worker thread.

        See ``_run_off_loop`` for why the call is off the event loop.
        """
        table = self.dlq_rows_table
        columns = list(rows[0].keys())
        placeholders = ", ".join("?" for _ in columns)
        collist = ", ".join(columns)
        conn.executemany(
            f"INSERT INTO {table} ({collist}) VALUES ({placeholders})",
            [[r.get(c) for c in columns] for r in rows],
        )
        return len(rows)

    async def table_exists(self, name: str) -> bool:
        """Whether table ``name`` is present in the connected database.

        Used by akosha's ``OTLPReceiver.start()`` to fail loud when the
        substrate is missing, and by the read path to return empty rather
        than raise a CatalogError before the receiver has ever run.

        ``duckdb_tables()`` is a table function — the parentheses are
        required; ``duckdb_tables`` alone parses as a relation reference.
        The catalog query is synchronous in DuckDB's Python API, so it runs
        on a worker thread; see ``_run_off_loop``.

        The lock is taken here, as it is for every other method on this
        class. It was not, originally, and that was safe by accident: the
        event loop was the only thread that touched the connection, so
        nothing could interleave. Once the substrate's work moved to a
        worker thread, an un-locked catalog query could land in the middle
        of a write.
        """
        if self.conn is None:
            return False
        async with self._lock:
            return await self._run_off_loop(
                lambda conn: bool(
                    conn.execute(
                        "SELECT 1 FROM duckdb_tables() WHERE table_name = ?", [name]
                    ).fetchone()
                )
            )

    async def insert(self, record: Any) -> None:
        """Insert a conversation record.

        ``record`` is dict-shaped with keys: ``system_id``,
        ``conversation_id``, ``content``, ``embedding``, ``timestamp``,
        ``metadata``. Shape is enforced by callers (e.g. ``HotRecord``
        in akosha). The substrate intentionally does NOT prescribe a
        typed model — keeps substrate loose, callers strict.

        Raises:
            ValueError: If ``len(record.embedding) != self._embedding_dim``.
                This is the fail-loud contract — a dim mismatch
                indicates the embedding backend changed (or was
                misconfigured) since ``__init__`` baked the schema.
        """
        actual_dim = len(record.embedding)
        if actual_dim != self._embedding_dim:
            logger.warning(
                "oneiric.hot_store.dim_mismatch",
                extra={
                    "expected": self._embedding_dim,
                    "actual": actual_dim,
                    "conversation_id": record.conversation_id,
                },
            )
            raise ValueError(
                f"DuckdbHotStore.insert: embedding dim mismatch "
                f"(expected {self._embedding_dim}, got {actual_dim})"
            )
        async with self._lock:
            await self._run_off_loop(
                lambda conn: conn.execute(
                    """
                    INSERT INTO conversations
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        record.system_id,
                        record.conversation_id,
                        record.content,
                        record.embedding,
                        _to_naive_utc(record.timestamp),
                        record.metadata,
                        self._compute_content_hash(record.content),
                        datetime.now(UTC),
                    ],
                )
            )

    async def search_similar(
        self,
        query_embedding: list[float],
        system_id: str | None = None,
        limit: int = 10,
        threshold: float = 0.7,
    ) -> list[dict[str, Any]]:
        """Vector similarity search over the conversations table.

        Args:
            query_embedding: Query vector (dim MUST match schema).
            system_id: Optional source filter.
            limit: Max records returned.
            threshold: Minimum cosine similarity in [0, 1].

        Returns:
            List of record-shaped dicts ordered by similarity
            descending.

        Raises:
            ValueError: If ``len(query_embedding) != self._embedding_dim``.
                Fails fast before hitting DuckDB so callers see a
                clear dim-mismatch signal instead of an opaque CAST
                error.
        """
        query_dim = len(query_embedding)
        if query_dim != self._embedding_dim:
            logger.warning(
                "oneiric.hot_store.dim_mismatch",
                extra={
                    "expected": self._embedding_dim,
                    "actual": query_dim,
                    "operation": "search_similar",
                },
            )
            raise ValueError(
                f"DuckdbHotStore.search_similar: query dim mismatch "
                f"(expected {self._embedding_dim}, got {query_dim})"
            )
        async with self._lock:
            return await self._run_off_loop(
                lambda conn: self._search_similar_sync(
                    conn, query_embedding, system_id, limit, threshold
                )
            )

    def _search_similar_sync(
        self,
        conn: _SerializedConnection,
        query_embedding: list[float],
        system_id: str | None,
        limit: int,
        threshold: float,
    ) -> list[dict[str, Any]]:
        """Run the vector similarity query. Runs on a worker thread.

        See ``_run_off_loop`` for why the call is off the event loop.
        """
        conditions: list[str] = []
        params: list[Any] = []
        if system_id is not None:
            conditions.append("system_id = ?")
            params.append(system_id)
        conditions.append("list_cosine_similarity(embedding, ?) >= ?")
        params.append(list(query_embedding))
        params.append(threshold)
        where_clause = " AND ".join(conditions) if conditions else "TRUE"
        rows = conn.execute(
            f"""
            SELECT system_id, conversation_id, content, timestamp, metadata,
                   list_cosine_similarity(embedding, ?) AS score
            FROM conversations
            WHERE {where_clause}
            ORDER BY score DESC
            LIMIT ?
            """,
            [list(query_embedding), *params, limit],
        ).fetchall()
        return [
            {
                "system_id": r[0],
                "conversation_id": r[1],
                "content": r[2],
                "timestamp": r[3],
                "metadata": r[4],
                "score": float(r[5]),
            }
            for r in rows
        ]

    async def close(self) -> None:
        """Close the DuckDB connection. Idempotent."""
        async with self._lock:
            conn = self.conn
            if conn is not None:
                await asyncio.to_thread(conn.close)
                logger.info("Hot store closed")

    @staticmethod
    def _compute_content_hash(content: str) -> str:
        """Stable content hash for deduplication.

        See akosha.storage.hot_store.HotStore._compute_content_hash for
        the rationale on algorithm choice (sha256 of utf-8 bytes).
        """
        return hashlib.sha256(content.encode("utf-8")).hexdigest()


__all__ = [
    "DEFAULT_EMBEDDING_DIM",
    "DLQ_ROWS_DDL",
    "DLQ_ROWS_INDEX",
    "METRICS_SUBSTRATE_COLUMNS",
    "METRICS_SUBSTRATE_DDL",
    "METRICS_SUBSTRATE_INDEXES",
    "METRICS_SUBSTRATE_INSERT_CHUNK",
    "METRICS_SUBSTRATE_JSON_COLUMNS",
    "RECEIVER_STATE_DDL",
    "SPANS_SUBSTRATE_DDL",
    "SPANS_SUBSTRATE_INDEXES",
    "DuckdbHotStore",
]
