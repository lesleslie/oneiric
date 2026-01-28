"""Tests for OTel telemetry database migrations.

These tests require a running PostgreSQL instance with the pgvector extension.
Tests are marked as integration tests and will be skipped by default.
"""

from __future__ import annotations

import pytest

from oneiric.adapters.observability.migrations import (
    create_otel_schema,
    create_vector_index,
    drop_otel_schema,
)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_schema_creates_tables(otel_db_session):
    """Verify that create_otel_schema creates all 4 tables."""
    # Create the schema
    await create_otel_schema(otel_db_session)

    # Query PostgreSQL's information_schema to check for tables
    result = await otel_db_session.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        AND table_name IN ('otel_traces', 'otel_metrics', 'otel_logs', 'otel_telemetry_dlq')
        ORDER BY table_name
        """
    )
    tables = [row[0] for row in result.fetchall()]

    # Verify all 4 tables exist
    assert "otel_traces" in tables
    assert "otel_metrics" in tables
    assert "otel_logs" in tables
    assert "otel_telemetry_dlq" in tables
    assert len(tables) == 4


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_schema_creates_indexes(otel_db_session):
    """Verify that create_otel_schema creates all indexes including GIN."""
    # Create the schema
    await create_otel_schema(otel_db_session)

    # Query PostgreSQL's pg_indexes to check for indexes
    result = await otel_db_session.execute(
        """
        SELECT indexname
        FROM pg_indexes
        WHERE schemaname = 'public'
        AND indexname LIKE 'ix_%'
        ORDER BY indexname
        """
    )
    indexes = [row[0] for row in result.fetchall()]

    # Verify trace indexes
    assert "ix_traces_trace_id" in indexes
    assert "ix_traces_name" in indexes
    assert "ix_traces_start_time" in indexes
    assert "ix_traces_status" in indexes
    assert "ix_traces_attributes_gin" in indexes

    # Verify metric indexes
    assert "ix_metrics_name" in indexes
    assert "ix_metrics_timestamp" in indexes
    assert "ix_metrics_type" in indexes

    # Verify log indexes
    assert "ix_logs_timestamp" in indexes
    assert "ix_logs_trace_id" in indexes
    assert "ix_logs_level" in indexes

    # Verify GIN index type for JSONB attributes
    result = await otel_db_session.execute(
        """
        SELECT amname
        FROM pg_index
        JOIN pg_class ON pg_index.indexrelid = pg_class.oid
        JOIN pg_am ON pg_class.relam = pg_am.oid
        WHERE pg_class.relname = 'ix_traces_attributes_gin'
        """
    )
    index_type = result.scalar()
    assert index_type == "gin"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_drop_schema_removes_tables(otel_db_session):
    """Verify that drop_otel_schema removes all OTel tables."""
    # Create the schema first
    await create_otel_schema(otel_db_session)

    # Verify tables exist
    result = await otel_db_session.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_schema = 'public'
        AND table_name IN ('otel_traces', 'otel_metrics', 'otel_logs', 'otel_telemetry_dlq')
        """
    )
    count_before = result.scalar()
    assert count_before == 4

    # Drop the schema
    await drop_otel_schema(otel_db_session)

    # Verify tables are gone
    result = await otel_db_session.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_schema = 'public'
        AND table_name IN ('otel_traces', 'otel_metrics', 'otel_logs', 'otel_telemetry_dlq')
        """
    )
    count_after = result.scalar()
    assert count_after == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_vector_index(otel_db_session):
    """Verify that create_vector_index creates IVFFlat index."""
    # Create the schema first
    await create_otel_schema(otel_db_session)

    # Create vector index
    await create_vector_index(otel_db_session, num_lists=100)

    # Query pg_indexes to verify vector index exists
    result = await otel_db_session.execute(
        """
        SELECT indexname
        FROM pg_indexes
        WHERE schemaname = 'public'
        AND indexname = 'ix_traces_embedding_ivfflat'
        """
    )
    index_name = result.scalar()
    assert index_name == "ix_traces_embedding_ivfflat"

    # Verify it's using IVFFlat access method
    result = await otel_db_session.execute(
        """
        SELECT amname
        FROM pg_index
        JOIN pg_class ON pg_index.indexrelid = pg_class.oid
        JOIN pg_am ON pg_class.relam = pg_am.oid
        WHERE pg_class.relname = 'ix_traces_embedding_ivfflat'
        """
    )
    access_method = result.scalar()
    assert access_method == "ivfflat"
