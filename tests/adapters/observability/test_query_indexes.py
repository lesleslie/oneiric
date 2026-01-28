"""Tests for query optimization indexes."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from oneiric.adapters.observability.migrations import (
    create_otel_schema,
    create_query_optimization_indexes
)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_query_indexes_created(otel_db_session):
    """Test that query optimization indexes are created."""
    # Create schema first
    await create_otel_schema(otel_db_session)

    # Create query optimization indexes
    await create_query_optimization_indexes(otel_db_session)

    # Verify indexes exist
    result = await otel_db_session.execute(text("""
        SELECT indexname FROM pg_indexes
        WHERE tablename = 'otel_traces'
        AND indexname IN ('ix_traces_start_time_status', 'ix_traces_attributes_gin')
    """))
    indexes = {row[0] for row in result.fetchall()}

    assert "ix_traces_start_time_status" in indexes
    assert "ix_traces_attributes_gin" in indexes
