"""Tests for IVFFlat index migration."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from oneiric.adapters.observability.migrations import (
    create_otel_schema,
    create_ivfflat_index_if_ready
)
from oneiric.adapters.observability.otel import OTelStorageAdapter
from oneiric.adapters.observability.settings import OTelStorageSettings


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ivfflat_index_not_created_below_threshold(otel_db_session):
    """Test that IVFFlat index is not created with fewer than 1000 traces."""
    # Create schema
    await create_otel_schema(otel_db_session)

    # Insert only 100 traces (below threshold)
    from datetime import datetime, UTC

    for i in range(100):
        await otel_db_session.execute(
            text("""
                INSERT INTO otel_traces (id, trace_id, name, start_time, status, attributes, embedding)
                VALUES (:id, :trace_id, :name, :start_time, :status, :attributes, :embedding)
            """),
            {
                "id": f"span-{i}",
                "trace_id": f"trace-{i}",
                "name": f"test_span_{i}",
                "start_time": datetime.now(UTC),
                "status": "OK",
                "attributes": {},
                "embedding": None
            }
        )
    await otel_db_session.commit()

    # Attempt to create index (should skip)
    await create_ivfflat_index_if_ready(otel_db_session)

    # Verify index does NOT exist
    result = await otel_db_session.execute(text("""
        SELECT indexname FROM pg_indexes
        WHERE tablename = 'otel_traces' AND indexname LIKE '%ivfflat%'
    """))
    index_exists = result.fetchone()

    assert index_exists is None, "IVFFlat index should not exist below threshold"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ivfflat_index_created_above_threshold(otel_db_session):
    """Test that IVFFlat index is created with 1000+ traces."""
    # Create schema
    await create_otel_schema(otel_db_session)

    # Insert 1500 traces (above threshold)
    from datetime import datetime, UTC
    import numpy as np

    for i in range(1500):
        embedding = np.random.rand(384).tolist()
        await otel_db_session.execute(
            text("""
                INSERT INTO otel_traces (id, trace_id, name, start_time, status, attributes, embedding)
                VALUES (:id, :trace_id, :name, :start_time, :status, :attributes, :embedding)
            """),
            {
                "id": f"span-{i}",
                "trace_id": f"trace-{i}",
                "name": f"test_span_{i}",
                "start_time": datetime.now(UTC),
                "status": "OK",
                "attributes": {},
                "embedding": embedding
            }
        )
    await otel_db_session.commit()

    # Create index
    await create_ivfflat_index_if_ready(otel_db_session)

    # Verify index exists
    result = await otel_db_session.execute(text("""
        SELECT indexname FROM pg_indexes
        WHERE tablename = 'otel_traces' AND indexname LIKE '%ivfflat%'
    """))
    index_exists = result.fetchone()

    assert index_exists is not None, "IVFFlat index should exist above threshold"
