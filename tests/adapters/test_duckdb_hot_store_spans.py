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
from typing import Any

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
    assert DuckdbHotStore.dlq_rows_table == "_dlq_rows"
    assert DuckdbHotStore.receiver_state_table == "_akosha_otel_receiver_state"


# ── receiver operational tables (spec §5.3) ─────────────────────────────


async def test_initialize_creates_both_receiver_tables(store: DuckdbHotStore) -> None:
    """``_dlq_rows`` and ``_akosha_otel_receiver_state`` ship with the substrate.

    Created here rather than by the receiver's own first-write path: the
    receiver's ``start()`` asserts its tables exist and refuses to bind
    otherwise, so a receiver that creates them on demand would be asserting
    something it just did.
    """
    assert await store.table_exists("_dlq_rows")
    assert await store.table_exists("_akosha_otel_receiver_state")


async def test_dlq_rows_rejects_an_unknown_reason(store: DuckdbHotStore) -> None:
    """``reason`` is NOT NULL — a quarantine row without one is unqueryable.

    This is the one DLQ column worth a constraint. Everything else is
    nullable on purpose: ``field`` is absent for whole-row JSON failures and
    ``trace_id``/``span_id`` are absent for rows that failed before identity
    could be parsed.
    """
    with pytest.raises(duckdb.ConstraintException):
        store.conn.execute(  # type: ignore[union-attr]
            "INSERT INTO _dlq_rows (reason, row_json) VALUES (NULL, '{}')"
        )

    store.conn.execute(  # type: ignore[union-attr]
        "INSERT INTO _dlq_rows (reason, row_json) VALUES ('not_null', '{}')"
    )


async def test_dlq_rows_holds_no_primary_key(store: DuckdbHotStore) -> None:
    """The DLQ must be able to hold two identical rejected rows.

    A primary key here would re-introduce exactly the collision the DLQ
    exists to survive — the rows in it already failed a uniqueness
    constraint on their way into ``spans_substrate``. Two distinct spans
    that both arrived with the same ``(trace_id, span_id)`` produce two
    quarantine rows, and both must be retained.
    """
    for _ in range(2):
        store.conn.execute(  # type: ignore[union-attr]
            "INSERT INTO _dlq_rows (reason, field, row_json, trace_id, span_id) "
            "VALUES ('not_null', 'service_name', '{}', 't1', 's1')"
        )
    count = store.conn.execute(  # type: ignore[union-attr]
        "SELECT count(*) FROM _dlq_rows"
    ).fetchone()
    assert count[0] == 2


async def test_dlq_recent_index_exists(store: DuckdbHotStore) -> None:
    """§8.1's retention sweep filters ``_dlq_rows`` by age.

    Without this index every sweep is a full scan of a table that only grows
    until the first sweep runs — the sweep is what keeps that growth bounded.
    """
    names = {
        row[0]
        for row in store.conn.execute(  # type: ignore[union-attr]
            "SELECT index_name FROM duckdb_indexes() WHERE table_name = '_dlq_rows'"
        ).fetchall()
    }
    assert "idx_dlq_rows_recent" in names


async def test_receiver_state_is_keyed_on_component(store: DuckdbHotStore) -> None:
    """One version-stamp row per component; re-stamping is an upsert, not a dup."""
    store.conn.execute(  # type: ignore[union-attr]
        "INSERT INTO _akosha_otel_receiver_state (component, schema_version) "
        "VALUES ('akosha', 7)"
    )
    with pytest.raises(duckdb.ConstraintException):
        store.conn.execute(  # type: ignore[union-attr]
            "INSERT INTO _akosha_otel_receiver_state (component, schema_version) "
            "VALUES ('akosha', 8)"
        )


async def test_receiver_tables_are_idempotent_across_reopen(tmp_path: Path) -> None:
    """A pre-existing substrate file must not fail to re-open.

    The inline DDL runs on every boot, so an operator who upgrades akosha
    against an already-populated substrate gets the new tables without a
    migration step and without losing rows.
    """
    hs = DuckdbHotStore(database_path=tmp_path / "r.duckdb", embedding_dim=384)
    await hs.initialize()
    hs.conn.execute(  # type: ignore[union-attr]
        "INSERT INTO _dlq_rows (reason, row_json) VALUES ('not_null', '{}')"
    )
    await hs.close()

    again = DuckdbHotStore(database_path=tmp_path / "r.duckdb", embedding_dim=384)
    await again.initialize()
    assert await again.table_exists("_dlq_rows")
    kept = again.conn.execute(  # type: ignore[union-attr]
        "SELECT count(*) FROM _dlq_rows"
    ).fetchone()
    assert kept[0] == 1, "re-opening the substrate must not drop existing DLQ rows"
    await again.close()

# ── ingest writers ───────────────────────────────────────────────────────
# These cover DuckDB behaviour — constraint resolution and affected-row
# accounting — rather than receiver policy, so they live with the substrate
# whose DDL they are reasoning about. akosha keeps a consumer-side test
# proving the receiver reaches these through inheritance.


def _span(
    span_id: str,
    trace_id: str = "t1",
    *,
    service_name: str = "mahavishnu",
) -> dict[str, Any]:
    """A minimal row satisfying every NOT NULL column of the substrate."""
    return {
        "span_id": span_id,
        "trace_id": trace_id,
        "service_name": service_name,
        "service_namespace": "bodai",
        "span_name": "unit-test-span",
        "start_time_unix_nano": 1,
        "received_at_unix_nano": 2,
        "attributes": "{}",
        "resource": "{}",
    }


def _count(store: DuckdbHotStore, sql: str) -> int:
    row = store.conn.execute(sql).fetchone()  # type: ignore[union-attr]
    return int(row[0])


async def test_empty_batch_is_a_noop_not_an_error(store: DuckdbHotStore) -> None:
    """A producer that exports zero spans must not cost an empty INSERT."""
    assert await store.insert_spans_substrate([]) == (0, 0)
    assert _count(store, "SELECT count(*) FROM spans_substrate") == 0


async def test_fresh_rows_all_count_as_inserted(store: DuckdbHotStore) -> None:
    rows = [_span("a"), _span("b"), _span("c", trace_id="t2")]
    assert await store.insert_spans_substrate(rows) == (3, 0)
    assert _count(store, "SELECT count(*) FROM spans_substrate") == 3


async def test_replaying_a_batch_counts_as_deduped_not_inserted(
    store: DuckdbHotStore,
) -> None:
    """Reading rows back after the INSERT cannot tell "I wrote this" from
    "this was already here", so a naive implementation reports a pure replay
    as 3 inserts and 0 dedups. An operator watching that counter sees a
    healthy ingest forever while the substrate holds exactly one span.
    """
    rows = [_span("a"), _span("b"), _span("c")]
    await store.insert_spans_substrate(rows)
    assert await store.insert_spans_substrate(rows) == (0, 3)
    assert _count(store, "SELECT count(*) FROM spans_substrate") == 3


async def test_a_span_id_collision_across_trace_ids_is_deduped_not_fatal(
    store: DuckdbHotStore,
) -> None:
    """The case §5.1's DDL gets wrong.

    The table declares BOTH ``span_id TEXT PRIMARY KEY`` and
    ``UNIQUE (trace_id, span_id)``. The PK is narrower, so it fires first and
    the composite constraint can never reject anything — which makes the
    spec's own prescribed ``ON CONFLICT (trace_id, span_id)`` clause handle
    only an unreachable constraint, raising on the hot path instead of
    no-op'ing. The untargeted clause used here honors both.

    The returned count must agree with what the database actually did:
    probing the composite pair would predict "inserted" while the row was
    silently dropped, and the two numbers would disagree.
    """
    rows = [_span("shared", "t1"), _span("shared", "t2")]
    assert await store.insert_spans_substrate(rows) == (1, 1)
    assert _count(store, "SELECT count(*) FROM spans_substrate") == 1


async def test_duplicates_within_one_batch_are_counted_as_deduped(
    store: DuckdbHotStore,
) -> None:
    """Sampling existence before the INSERT alone would miss an in-batch
    duplicate: neither copy is in the table when the batch starts. Folding
    each classified span_id into a ``seen`` set is what catches the second.
    """
    assert await store.insert_spans_substrate(
        [_span("a"), _span("a"), _span("b")]
    ) == (2, 1)
    assert _count(store, "SELECT count(*) FROM spans_substrate") == 2


async def test_a_null_trace_id_still_dedups(store: DuckdbHotStore) -> None:
    """``trace_id`` is nullable and ``NULL = NULL`` is never true in SQL.

    A probe written ``WHERE trace_id = ?`` would report every null-trace span
    as new on every batch, so the dedup counter would sit at zero for a
    producer that never sets ``trace_id`` — the receiver would look healthy
    while its dedup total never moved. ``IS NOT DISTINCT FROM`` is null-safe.
    """
    span = _span("a")
    span["trace_id"] = None
    assert await store.insert_spans_substrate([span]) == (1, 0)
    assert await store.insert_spans_substrate([span]) == (0, 1)
    assert _count(store, "SELECT count(*) FROM spans_substrate") == 1


async def test_a_row_missing_a_not_null_column_raises(store: DuckdbHotStore) -> None:
    """The table constraint stays a usable backstop.

    Validation is the receiver's job; if ``pre_validate`` ever lets a row
    through, DuckDB must refuse it rather than storing a span the read path
    later chokes on. Untargeted ON CONFLICT does not weaken NOT NULL.
    """
    bad = _span("bad")
    del bad["service_name"]
    with pytest.raises(duckdb.ConstraintException):
        await store.insert_spans_substrate([bad])


async def test_dlq_accepts_two_rows_sharing_an_identity(store: DuckdbHotStore) -> None:
    """Quarantining under a key that enforces the same uniqueness would make
    the second rejection uncatchable: the insert would raise, the receiver's
    DLQ wrapper would log it, and the second span would be lost with no
    record anywhere.
    """
    row = {
        "reason": "not_null",
        "field": "service_name",
        "row_json": "{}",
        "trace_id": "t1",
        "span_id": "s1",
    }
    assert await store.insert_dlq_rows([dict(row), dict(row)]) == 2
    assert _count(store, "SELECT count(*) FROM _dlq_rows") == 2


async def test_dlq_empty_batch_is_a_noop(store: DuckdbHotStore) -> None:
    assert await store.insert_dlq_rows([]) == 0


async def test_dlq_failure_raises_so_the_receiver_can_decide(
    store: DuckdbHotStore,
) -> None:
    """A substrate failure propagates.

    The receiver wraps this call, but that wrapping is the receiver's
    contract. Swallowing the error here would remove its ability to notice.
    """
    with pytest.raises(duckdb.ConstraintException):
        await store.insert_dlq_rows([{"reason": None, "row_json": "{}"}])
