"""OTel counters for the DuckDB substrate's metric tables.

Mirrors the per-domain ``metrics.py`` pattern used elsewhere in oneiric
(``oneiric/core/metrics.py``, ``oneiric/remote/metrics.py``): a module-level
meter, instruments created at import time, and small ``record_*`` helpers
that attach attributes.

Instrument names carry the ``oneiric_`` prefix like every other oneiric
instrument (25 of 26 pre-existing names do). That prefix is not cosmetic:
these counters are exported over OTLP into the same registry the substrate's
metrics land in, so an unprefixed name is a collision waiting to happen.
"""

from __future__ import annotations

from opentelemetry import metrics

METER_NAME = "oneiric.adapters.vector"

_meter = metrics.get_meter(METER_NAME)

_rows_inserted_counter = _meter.create_counter(
    "oneiric_metrics_substrate_rows_inserted_total",
    unit="1",
    description="Metric data points written to the metrics_substrate table.",
)

_insert_failed_counter = _meter.create_counter(
    "oneiric_metrics_substrate_insert_failed_total",
    unit="1",
    description="Failed insert batches against the metrics_substrate table.",
)


def record_metrics_substrate_insert(inserted: int) -> None:
    """Record rows written to ``metrics_substrate``.

    Args:
        inserted: Rows the database actually wrote. Deduped rows are NOT
            counted here — they were not written, and a counter that
            counted them would report ingest volume instead of ingest
            progress.
    """
    if inserted > 0:
        _rows_inserted_counter.add(inserted)


def record_metrics_substrate_insert_failure() -> None:
    """Record one failed ``metrics_substrate`` insert batch."""
    _insert_failed_counter.add(1)
