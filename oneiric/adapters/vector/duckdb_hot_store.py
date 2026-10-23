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
import hashlib
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb  # third-party; substrate ships it as an optional extra for development

logger = logging.getLogger(__name__)

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
        ("CREATE INDEX IF NOT EXISTS idx_spans_selector_task_class_outcome "
        "ON spans_substrate(selector, task_class, outcome, received_at_unix_nano DESC)"),
        "idx_spans_selector_task_class_outcome",
    ),
    (
        ("CREATE INDEX IF NOT EXISTS idx_spans_service_name_recent "
        "ON spans_substrate(service_name, received_at_unix_nano DESC)"),
        "idx_spans_service_name_recent",
    ),
    (
        ("CREATE INDEX IF NOT EXISTS idx_spans_source_type_recent "
        "ON spans_substrate(telemetry_source_type, received_at_unix_nano DESC)"),
        "idx_spans_source_type_recent",
    ),
    (
        ("CREATE INDEX IF NOT EXISTS idx_spans_received_at_recent "
        "ON spans_substrate(received_at_unix_nano DESC)"),
        "idx_spans_received_at_recent",
    ),
)

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
    "CREATE INDEX IF NOT EXISTS idx_dlq_rows_recent "
    "ON _dlq_rows(rejected_at DESC)"
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
    # ``spans_substrate_table`` to fail loud when the DDL is absent.
    conversations_table: str = "conversations"
    spans_substrate_table: str = "spans_substrate"
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
        self.conn: duckdb.DuckDBPyConnection | None = None
        self._lock = asyncio.Lock()
        # Schema dim is baked into the CREATE TABLE DDL at initialize()
        # time — capture it now so the SQL can interpolate ``FLOAT[<dim>]``
        # as a literal. Pass an explicit int for tests that don't go
        # through the embedding service initialization path.
        self._embedding_dim: int = (
            embedding_dim if embedding_dim is not None else DEFAULT_EMBEDDING_DIM
        )

    async def initialize(self) -> None:
        """Initialize database schema (conversations table + HNSW index).

        Idempotent; safe to call multiple times.
        """
        async with self._lock:
            self.conn = duckdb.connect(str(self.db_path))
            # Create conversations table with HNSW index support.
            # ``embedding FLOAT[N]`` is interpolated at __init__ time so
            # the schema dim matches the active backend; this MUST
            # match the dim the embedding service produces or insert()
            # raises.
            self.conn.execute(
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
                self.conn.execute("""
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
                    self.conn.execute(ddl)
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
            self.conn.execute(SPANS_SUBSTRATE_DDL)
            for index_ddl, index_name in SPANS_SUBSTRATE_INDEXES:
                self.conn.execute(index_ddl)
                logger.info("Created %s index", index_name)

            # ── receiver operational tables (v7 §5.3) ─────────────────────
            # Created alongside the substrate table rather than by the
            # receiver itself: the receiver's ``start()`` asserts
            # ``spans_substrate_table`` exists and raises otherwise, and a
            # receiver that has to create its own DLQ on the fly would be
            # asserting something it just did. Same reasoning as the
            # no-try/except decision above — a substrate that cannot create
            # its own tables is broken, and hiding that is worse.
            self.conn.execute(RECEIVER_STATE_DDL)
            self.conn.execute(DLQ_ROWS_DDL)
            self.conn.execute(DLQ_ROWS_INDEX)
            logger.info("Created receiver operational tables")

            logger.info("Hot store initialized")

    async def table_exists(self, name: str) -> bool:
        """Whether table ``name`` is present in the connected database.

        Used by akosha's ``OTLPReceiver.start()`` to fail loud when the
        substrate is missing, and by the read path to return empty rather
        than raise a CatalogError before the receiver has ever run.

        ``duckdb_tables()`` is a table function — the parentheses are
        required; ``duckdb_tables`` alone parses as a relation reference.
        ``conn.execute`` is synchronous in DuckDB's Python API, so it is not
        awaited; the method is async only so call sites read uniformly with
        the rest of this class's async surface.
        """
        if self.conn is None:
            return False
        row = self.conn.execute(
            "SELECT 1 FROM duckdb_tables() WHERE table_name = ?", [name]
        ).fetchone()
        return bool(row)

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
            if not self.conn:
                raise RuntimeError("Hot store not initialized")
            self.conn.execute(
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
            if not self.conn:
                raise RuntimeError("Hot store not initialized")
            conditions: list[str] = []
            params: list[Any] = []
            if system_id is not None:
                conditions.append("system_id = ?")
                params.append(system_id)
            conditions.append("list_cosine_similarity(embedding, ?) >= ?")
            params.append(list(query_embedding))
            params.append(threshold)
            where_clause = " AND ".join(conditions) if conditions else "TRUE"
            rows = self.conn.execute(
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
            if self.conn is not None:
                self.conn.close()
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
    "DuckdbHotStore",
    "RECEIVER_STATE_DDL",
    "SPANS_SUBSTRATE_DDL",
    "SPANS_SUBSTRATE_INDEXES",
]
