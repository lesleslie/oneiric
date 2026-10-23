"""PR-0a: ``DuckdbHotStore`` owns the ``spans_substrate`` DDL.

Per ADR 017 the persistence substrate lives with oneiric, so the OTel span
table ships here rather than in akosha. Before this, every akosha read-path
test carried its own copy of the DDL — the copy now also lives here, and the
two must stay in step.

These tests run against a real DuckDB, not a fake connection: the DDL is the
kind of statement that only fails at parse time, and a stubbed connection
would happily accept DDL the pinned DuckDB build rejects. §5.1a of the v7 spec
records which DuckDB constructs are unsupported; those notes are only worth
anything if something actually executes them.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from oneiric.adapters.vector.duckdb_hot_store import DuckdbHotStore

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def store(tmp_path: Path) -> DuckdbHotStore:
    hs = DuckdbHotStore(database_path=tmp_path / "s.duckdb", embedding_dim=384)
    await hs.initialize()
    return hs


async def test_initialize_creates_spans_substrate(store: DuckdbHotStore) -> None:
    assert await store.table_exists("spans_substrate")


async def test_initialize_still_creates_conversations(
    store: DuckdbHotStore,
) -> None:
    """The pre-existing surface must survive the addition."""
    assert await store.table_exists("conversations")


async def test_table_exists_is_false_for_an_unknown_table(
    store: DuckdbHotStore,
) -> None:
    assert not await store.table_exists("nope")


async def test_initialize_is_idempotent(tmp_path: Path) -> None:
    """``initialize()`` is documented as safe to call more than once."""
    hs = DuckdbHotStore(database_path=tmp_path / "i.duckdb", embedding_dim=384)
    await hs.initialize()
    await hs.close()
    again = DuckdbHotStore(database_path=tmp_path / "i.duckdb", embedding_dim=384)
    await again.initialize()
    assert await again.table_exists("spans_substrate")
    await again.close()


async def test_required_not_null_columns_are_enforced(store: DuckdbHotStore) -> None:
    """``service_name``, ``start_time_unix_nano`` and ``attributes`` are NOT NULL.

    A span missing them cannot be written — the receiver's validation should
    reject it, not the table silently accept it.
    """
    with pytest.raises(duckdb.ConstraintException):
        store.conn.execute(  # type: ignore[union-attr]
            "INSERT INTO spans_substrate (span_id, service_namespace, "
            "span_name, start_time_unix_nano, received_at_unix_nano, "
            "attributes, resource) "
            "VALUES ('no-service-name', 'bodai', 'n', 1, 1, '{}', '{}')"
        )

    store.conn.execute(  # type: ignore[union-attr]
        "INSERT INTO spans_substrate (span_id, service_name, "
        "service_namespace, span_name, start_time_unix_nano, "
        "received_at_unix_nano, attributes, resource) "
        "VALUES ('ok', 'mahavishnu', 'bodai', 'n', 1, 1, '{}', '{}')"
    )


async def test_composite_span_identity_constraint_is_enforced(
    store: DuckdbHotStore,
) -> None:
    """``uq_span_identity (trace_id, span_id)`` rejects a replayed span.

    v2 used ``ON CONFLICT (span_id)`` alone, which silently dropped
    cross-producer pairs sharing a ``span_id`` under different ``trace_id``s.
    The composite constraint is what makes a replay a genuine no-op.
    """
    store.conn.execute(  # type: ignore[union-attr]
        "INSERT INTO spans_substrate (span_id, trace_id, service_name, "
        "service_namespace, span_name, start_time_unix_nano, "
        "received_at_unix_nano, attributes, resource) "
        "VALUES ('a', 't1', 'mahavishnu', 'bodai', 'n', 1, 1, '{}', '{}')"
    )
    with pytest.raises(duckdb.ConstraintException):
        store.conn.execute(  # type: ignore[union-attr]
            "INSERT INTO spans_substrate (span_id, trace_id, service_name, "
            "service_namespace, span_name, start_time_unix_nano, "
            "received_at_unix_nano, attributes, resource) "
            "VALUES ('a', 't1', 'mahavishnu', 'bodai', 'n', 1, 2, '{}', '{}')"
        )


async def test_read_path_indexes_exist(store: DuckdbHotStore) -> None:
    """All four indexes the read path depends on resolve.

    No ``WHERE`` clause on any of them: DuckDB raises ``NotImplementedException``
    for partial indexes on both 1.5.6 and 2.0.0-dev (spec §5.1a).
    """
    names = {
        row[0]
        for row in store.conn.execute(  # type: ignore[union-attr]
            "SELECT index_name FROM duckdb_indexes() WHERE table_name = 'spans_substrate'"
        ).fetchall()
    }
    assert {
        "idx_spans_selector_task_class_outcome",
        "idx_spans_service_name_recent",
        "idx_spans_source_type_recent",
        "idx_spans_received_at_recent",
    } <= names


async def test_table_name_attributes_are_exposed() -> None:
    """The receiver reads the table name from the class, not a literal."""
    assert DuckdbHotStore.spans_substrate_table == "spans_substrate"
    assert DuckdbHotStore.conversations_table == "conversations"