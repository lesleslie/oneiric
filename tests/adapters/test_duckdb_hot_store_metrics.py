"""Phase 1: ``DuckdbHotStore`` owns the ``metrics_substrate`` table.

The metric counterpart of ``test_duckdb_hot_store_spans.py``. A metric data
point is not an event like a span — it is a sample of a time series — so the
identity rules are different, and they are what most of these tests pin.

These run against a real DuckDB, not a fake connection. The DDL is the kind
of statement that only fails at parse time, and the identity constraint
depends on how the pinned DuckDB build actually compares JSON columns (it
compares them as text), which a stubbed connection could not tell us.

# req: REQ-M03
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import duckdb
import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from oneiric.adapters.vector.duckdb_hot_store import DuckdbHotStore

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def store(tmp_path: Path) -> DuckdbHotStore:
    hs = DuckdbHotStore(database_path=tmp_path / "m.duckdb", embedding_dim=384)
    await hs.initialize()
    return hs


def _point(
    ts: int = 1000,
    *,
    metric_name: str = "drift_total",
    service_name: str = "mahavishnu",
    scope_name: str = "mahavishnu.core.observability",
    data_type: str = "sum",
    attributes: Mapping[str, Any] | str = '{"a": "1"}',
    resource: Mapping[str, Any] | str = '{"service.name": "mahavishnu"}',
    **extra: Any,
) -> dict[str, Any]:
    """A minimal point satisfying every NOT NULL column of the substrate."""
    row: dict[str, Any] = {
        "ts": ts,
        "service_name": service_name,
        "service_namespace": "bodai",
        "scope_name": scope_name,
        "metric_name": metric_name,
        "data_type": data_type,
        "value_sum": 1.0,
        "value_count": 1,
        "is_monotonic": True,
        "attributes": attributes,
        "resource": resource,
    }
    row.update(extra)
    return row


def _count(store: DuckdbHotStore) -> int:
    row = store.conn.execute(  # type: ignore[union-attr]
        "SELECT count(*) FROM metrics_substrate"
    ).fetchone()
    return int(row[0])


# ── schema ────────────────────────────────────────────────────────────────


async def test_initialize_creates_metrics_substrate(store: DuckdbHotStore) -> None:
    assert await store.table_exists("metrics_substrate")


async def test_initialize_leaves_the_span_surface_alone(
    store: DuckdbHotStore,
) -> None:
    """The metric table is additive; the trace path must be untouched."""
    assert await store.table_exists("spans_substrate")
    assert await store.table_exists("_dlq_rows")


async def test_initialize_creates_the_metric_indexes(store: DuckdbHotStore) -> None:
    """Every index the read path depends on resolves."""
    names = {
        row[0]
        for row in store.conn.execute(  # type: ignore[union-attr]
            "SELECT index_name FROM duckdb_indexes() "
            "WHERE table_name = 'metrics_substrate'"
        ).fetchall()
    }
    assert {
        "idx_metrics_name_recent",
        "idx_metrics_service_recent",
        "idx_metrics_ts_recent",
    } <= names


async def test_table_name_attribute_is_exposed() -> None:
    """The receiver reads the table name from the class, not a literal."""
    assert DuckdbHotStore.metrics_substrate_table == "metrics_substrate"


async def test_the_table_survives_a_reopen(tmp_path: Path) -> None:
    """A pre-existing substrate file must not lose its metric rows.

    The inline DDL runs on every boot, so an operator who upgrades against
    an already-populated substrate gets the new table without a migration
    step and without losing rows.
    """
    hs = DuckdbHotStore(database_path=tmp_path / "r.duckdb", embedding_dim=384)
    await hs.initialize()
    await hs.insert_metrics_substrate([_point()])
    await hs.close()

    again = DuckdbHotStore(database_path=tmp_path / "r.duckdb", embedding_dim=384)
    await again.initialize()
    assert await again.table_exists("metrics_substrate")
    assert _count(again) == 1
    await again.close()


# ── identity ──────────────────────────────────────────────────────────────
# A metric point is named by its series plus the instant it was recorded.
# These are the rules that make one point one point.


async def test_attribute_order_does_not_change_the_identity(
    store: DuckdbHotStore,
) -> None:
    """The same attribute set is the same point however it was serialized.

    DuckDB compares a JSON column as text — verified on the pinned build,
    where ``{"a":1,"b":2}`` and ``{"b":2,"a":1}`` are two different rows — so
    an uncanonicalized attribute set would make one point look like two.
    OTLP attribute ordering follows producer-side iteration order, so this
    is the normal case, not an exotic one.
    """
    await store.insert_metrics_substrate([_point(attributes={"b": "2", "a": "1"})])
    result = await store.insert_metrics_substrate(
        [_point(attributes={"a": "1", "b": "2"})]
    )
    assert result == (0, 1)
    assert _count(store) == 1


async def test_a_different_timestamp_is_a_different_point(
    store: DuckdbHotStore,
) -> None:
    """A cumulative counter exported every interval is a new point each time."""
    await store.insert_metrics_substrate([_point(ts=1000)])
    await store.insert_metrics_substrate([_point(ts=2000)])
    assert _count(store) == 2


async def test_different_label_values_do_not_collide(store: DuckdbHotStore) -> None:
    """The attribute set is the label set — differing labels are differing series."""
    await store.insert_metrics_substrate([_point(attributes={"route": "/a"})])
    await store.insert_metrics_substrate([_point(attributes={"route": "/b"})])
    assert _count(store) == 2


async def test_two_producers_do_not_collide(store: DuckdbHotStore) -> None:
    """mahavishnu's and oneiric's exporters both speak OTLP to one receiver.

    They are indistinguishable on the wire, so the substrate has to keep
    them apart by the resource's service identity — otherwise one
    component's counter would silently overwrite the other's.
    """
    await store.insert_metrics_substrate([_point(service_name="mahavishnu")])
    await store.insert_metrics_substrate([_point(service_name="oneiric")])
    assert _count(store) == 2


async def test_resource_is_stored_but_not_part_of_the_identity(
    store: DuckdbHotStore,
) -> None:
    """Incidental resource churn must not split one logical series.

    The resource names the producer; ``service.name`` already carries that
    into the key. Folding the whole resource in would give a changing pid
    or hostname a fresh series on every export.
    """
    await store.insert_metrics_substrate(
        [_point(resource={"service.name": "mahavishnu"})]
    )
    result = await store.insert_metrics_substrate(
        [_point(resource={"service.name": "mahavishnu", "host.name": "other"})]
    )
    assert result == (0, 1)
    assert _count(store) == 1


# ── insert accounting ─────────────────────────────────────────────────────


async def test_empty_batch_is_a_noop_not_an_error(store: DuckdbHotStore) -> None:
    """A producer that exports zero points must not cost an empty INSERT."""
    assert await store.insert_metrics_substrate([]) == (0, 0)
    assert _count(store) == 0


async def test_fresh_rows_all_count_as_inserted(store: DuckdbHotStore) -> None:
    rows = [_point(ts=1), _point(ts=2), _point(ts=3)]
    assert await store.insert_metrics_substrate(rows) == (3, 0)
    assert _count(store) == 3


async def test_replaying_a_batch_counts_as_deduped_not_inserted(
    store: DuckdbHotStore,
) -> None:
    """A retried export must not double-count.

    The counts come from the statement's own ``RETURNING`` rows, so they
    cannot drift from what the table actually holds.
    """
    rows = [_point(ts=1), _point(ts=2), _point(ts=3)]
    await store.insert_metrics_substrate(rows)
    assert await store.insert_metrics_substrate(rows) == (0, 3)
    assert _count(store) == 3


async def test_duplicates_within_one_batch_are_counted_as_deduped(
    store: DuckdbHotStore,
) -> None:
    """Two copies of one point in a single batch are one point."""
    result = await store.insert_metrics_substrate(
        [_point(ts=1), _point(ts=1), _point(ts=2)]
    )
    assert result == (2, 1)
    assert _count(store) == 2


async def test_a_mixed_type_batch_keeps_each_row_s_own_columns(
    store: DuckdbHotStore,
) -> None:
    """A gauge, a sum and a histogram in one batch each keep their own fields.

    The key set varies by metric type, so the insert projects onto the
    DDL's column list rather than reading the column order off the first
    row. Reading it off ``rows[0]`` would silently drop a column whenever
    the first row of a batch is a different type from the rest.
    """
    rows = [
        _point(ts=1, data_type="gauge", is_monotonic=None, value_sum=2.5),
        _point(ts=2, data_type="sum", is_monotonic=True, value_sum=9.0),
        _point(
            ts=3,
            data_type="histogram",
            is_monotonic=None,
            value_sum=10.0,
            value_count=6,
            value_min=0.5,
            value_max=9.0,
            value_sum_of_squares=120.0,
            buckets_json={"explicit_bounds": [1.0], "bucket_counts": [1, 2]},
        ),
    ]
    assert await store.insert_metrics_substrate(rows) == (3, 0)
    kinds = [
        row[0]
        for row in store.conn.execute(  # type: ignore[union-attr]
            "SELECT data_type FROM metrics_substrate ORDER BY ts"
        ).fetchall()
    ]
    assert kinds == ["gauge", "sum", "histogram"]
    monotonic = [
        row[0]
        for row in store.conn.execute(  # type: ignore[union-attr]
            "SELECT is_monotonic FROM metrics_substrate ORDER BY ts"
        ).fetchall()
    ]
    assert monotonic == [None, True, None]


async def test_histogram_buckets_round_trip(store: DuckdbHotStore) -> None:
    """Bucket boundaries survive the round trip.

    The summary statistics do not determine the buckets, so a histogram
    stored without them could not be reconstructed.
    """
    buckets = {"explicit_bounds": [1.0, 5.0], "bucket_counts": [1, 2, 3]}
    await store.insert_metrics_substrate(
        [
            _point(
                data_type="histogram",
                is_monotonic=None,
                value_sum=10.0,
                value_count=6,
                value_min=0.5,
                value_max=9.0,
                value_sum_of_squares=120.0,
                buckets_json=buckets,
            )
        ]
    )
    row = store.conn.execute(  # type: ignore[union-attr]
        "SELECT value_sum, value_count, value_min, value_max, "
        "value_sum_of_squares, buckets_json FROM metrics_substrate"
    ).fetchone()
    assert row[0] == 10.0
    assert row[1] == 6
    assert row[2] == 0.5
    assert row[3] == 9.0
    assert row[4] == 120.0
    assert json.loads(row[5]) == buckets


async def test_attributes_accept_a_mapping_as_well_as_json_text(
    store: DuckdbHotStore,
) -> None:
    """A caller may hand over either form; both canonicalize identically."""
    await store.insert_metrics_substrate([_point(attributes={"a": "1"})])
    result = await store.insert_metrics_substrate([_point(attributes='{"a": "1"}')])
    assert result == (0, 1)
    assert _count(store) == 1


# ── validation and failure ────────────────────────────────────────────────


async def test_a_missing_not_null_column_raises_and_writes_nothing(
    store: DuckdbHotStore,
) -> None:
    """The table constraint stays a usable backstop, and the batch is atomic.

    The insert is one multi-row statement, so the good row in this batch
    rolls back with the bad one rather than landing in a half-written state.
    """
    bad = _point(ts=2000)
    del bad["service_name"]
    with pytest.raises(duckdb.ConstraintException):
        await store.insert_metrics_substrate([_point(ts=1000), bad])
    assert _count(store) == 0


async def test_an_unknown_data_type_is_rejected(store: DuckdbHotStore) -> None:
    """The CHECK constraint bounds ``data_type`` to the OTLP data model."""
    with pytest.raises(duckdb.ConstraintException):
        await store.insert_metrics_substrate([_point(data_type="bogus")])


async def test_malformed_attribute_json_is_rejected(store: DuckdbHotStore) -> None:
    """Unparsable attributes fail loudly instead of being stored as noise."""
    with pytest.raises(ValueError, match="attributes is not valid JSON"):
        await store.insert_metrics_substrate([_point(attributes="{not json")])


async def test_attributes_must_be_a_json_object(store: DuckdbHotStore) -> None:
    """An attribute set is an object; a JSON array is not one.

    The text parsed fine, so the failure is the shape rather than the
    content — a different failure from unparsable text, and a different
    exception to match.
    """
    with pytest.raises(TypeError, match="attributes must be a JSON object"):
        await store.insert_metrics_substrate([_point(attributes="[1, 2]")])


async def test_the_resource_is_validated_too(store: DuckdbHotStore) -> None:
    """The resource is canonicalized on the same terms as the attributes."""
    with pytest.raises(ValueError, match="resource is not valid JSON"):
        await store.insert_metrics_substrate([_point(resource="{not json")])


async def test_a_batch_larger_than_the_chunk_size_is_split_correctly(
    store: DuckdbHotStore,
) -> None:
    """A batch bigger than one statement splits without losing or duplicating.

    The split exists because the statement binds one placeholder per column
    per row, so an unbounded batch would build an unbounded SQL string. The
    counts have to survive the split — a chunk boundary is exactly where an
    off-by-one would silently drop a row.
    """
    from oneiric.adapters.vector.duckdb_hot_store import METRICS_SUBSTRATE_INSERT_CHUNK

    total = METRICS_SUBSTRATE_INSERT_CHUNK + 1
    rows = [_point(ts=i) for i in range(total)]
    assert await store.insert_metrics_substrate(rows) == (total, 0)
    assert _count(store) == total
    assert await store.insert_metrics_substrate(rows) == (0, total)
    assert _count(store) == total


# ── observability ─────────────────────────────────────────────────────────


def _counter_value(reader: InMemoryMetricReader, name: str) -> float:
    """The current value of the named counter, or 0.0 if it never fired."""
    data = reader.get_metrics_data()
    for resource_metric in data.resource_metrics:
        for scope_metric in resource_metric.scope_metrics:
            for metric in scope_metric.metrics:
                if metric.name == name:
                    return float(metric.data.data_points[0].value)
    return 0.0


async def test_the_insert_counters_report_what_happened(
    store: DuckdbHotStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 1's two counters fire on the paths they describe.

    The production instruments are created at import time against the
    global meter provider, and the OTel API allows that provider to be set
    only once per process — so the test mirrors the instrument against its
    own provider and swaps it in, rather than trying to reconfigure the
    global one.
    """
    from oneiric.adapters.vector import metrics as metrics_mod

    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    meter = provider.get_meter("oneiric.adapters.vector")
    monkeypatch.setattr(
        metrics_mod,
        "_rows_inserted_counter",
        meter.create_counter(
            name="oneiric_metrics_substrate_rows_inserted_total",
            unit="1",
            description="test mirror of the production counter",
        ),
    )
    monkeypatch.setattr(
        metrics_mod,
        "_insert_failed_counter",
        meter.create_counter(
            name="oneiric_metrics_substrate_insert_failed_total",
            unit="1",
            description="test mirror of the production counter",
        ),
    )

    await store.insert_metrics_substrate([_point(ts=1), _point(ts=2)])
    assert _counter_value(reader, "oneiric_metrics_substrate_rows_inserted_total") == 2

    bad = _point(ts=3)
    del bad["service_name"]
    with pytest.raises(duckdb.ConstraintException):
        await store.insert_metrics_substrate([bad])
    assert _counter_value(reader, "oneiric_metrics_substrate_insert_failed_total") == 1


async def test_deduped_rows_are_not_counted_as_written(
    store: DuckdbHotStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A replay writes nothing, so the counter must not claim it did.

    Counting deduped rows as written would report ingest *volume* instead
    of ingest *progress*, and a receiver replaying every export would look
    busier than one making progress.
    """
    from oneiric.adapters.vector import metrics as metrics_mod

    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    meter = provider.get_meter("oneiric.adapters.vector")
    monkeypatch.setattr(
        metrics_mod,
        "_rows_inserted_counter",
        meter.create_counter(
            name="oneiric_metrics_substrate_rows_inserted_total",
            unit="1",
            description="test mirror of the production counter",
        ),
    )

    await store.insert_metrics_substrate([_point(ts=1)])
    await store.insert_metrics_substrate([_point(ts=1)])
    assert _counter_value(reader, "oneiric_metrics_substrate_rows_inserted_total") == 1
