"""Database migration scripts for OTel telemetry storage.

This module provides functions to create and drop the database schema
for OpenTelemetry traces, metrics, logs, and dead-letter queue tables.
Includes vector index creation for semantic similarity search.
"""

from __future__ import annotations

from sqlalchemy import text


async def create_otel_schema(session) -> None:
    """Create all OTel telemetry tables and indexes.

    Creates the following tables:
    - otel_traces: Distributed trace spans with vector embeddings
    - otel_metrics: Time-series metric data points
    - otel_logs: Log entries with trace correlation
    - otel_telemetry_dlq: Dead-letter queue for failed telemetry

    Args:
        session: SQLAlchemy async session
    """
    # Create otel_traces table
    await session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS otel_traces (
                id VARCHAR(36) PRIMARY KEY,
                trace_id VARCHAR(64) UNIQUE NOT NULL,
                parent_span_id VARCHAR(64),
                trace_state VARCHAR(256),
                name VARCHAR(255) NOT NULL,
                kind VARCHAR(50),
                start_time TIMESTAMP NOT NULL,
                end_time TIMESTAMP,
                duration_ms INTEGER,
                status VARCHAR(50) NOT NULL,
                attributes JSONB NOT NULL DEFAULT '{}',
                embedding VECTOR(384),
                embedding_model VARCHAR(100),
                embedding_generated_at TIMESTAMP
            )
        """
        )
    )

    # Create otel_metrics table
    await session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS otel_metrics (
                id VARCHAR(36) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                type VARCHAR(50) NOT NULL,
                value FLOAT NOT NULL,
                unit VARCHAR(50),
                labels JSONB NOT NULL DEFAULT '{}',
                timestamp TIMESTAMP NOT NULL
            )
        """
        )
    )

    # Create otel_logs table
    await session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS otel_logs (
                id VARCHAR(36) PRIMARY KEY,
                timestamp TIMESTAMP NOT NULL,
                level VARCHAR(50) NOT NULL,
                message TEXT NOT NULL,
                trace_id VARCHAR(64),
                resource_attributes JSONB,
                span_attributes JSONB
            )
        """
        )
    )

    # Create otel_telemetry_dlq table
    await session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS otel_telemetry_dlq (
                id SERIAL PRIMARY KEY,
                telemetry_type VARCHAR(50) NOT NULL,
                raw_data JSONB NOT NULL,
                error_message TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                processed_at TIMESTAMP,
                retry_count INTEGER DEFAULT 0
            )
        """
        )
    )

    # Create indexes for otel_traces
    await session.execute(
        text("CREATE INDEX IF NOT EXISTS ix_traces_trace_id ON otel_traces(trace_id)")
    )
    await session.execute(
        text("CREATE INDEX IF NOT EXISTS ix_traces_name ON otel_traces(name)")
    )
    await session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_traces_start_time ON otel_traces(start_time)"
        )
    )
    await session.execute(
        text("CREATE INDEX IF NOT EXISTS ix_traces_status ON otel_traces(status)")
    )
    await session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_traces_attributes_gin ON otel_traces USING GIN (attributes)"
        )
    )

    # Create indexes for otel_metrics
    await session.execute(
        text("CREATE INDEX IF NOT EXISTS ix_metrics_name ON otel_metrics(name)")
    )
    await session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_metrics_timestamp ON otel_metrics(timestamp)"
        )
    )
    await session.execute(
        text("CREATE INDEX IF NOT EXISTS ix_metrics_type ON otel_metrics(type)")
    )

    # Create indexes for otel_logs
    await session.execute(
        text("CREATE INDEX IF NOT EXISTS ix_logs_timestamp ON otel_logs(timestamp)")
    )
    await session.execute(
        text("CREATE INDEX IF NOT EXISTS ix_logs_trace_id ON otel_logs(trace_id)")
    )
    await session.execute(
        text("CREATE INDEX IF NOT EXISTS ix_logs_level ON otel_logs(level)")
    )

    await session.commit()


async def drop_otel_schema(session) -> None:
    """Drop all OTel telemetry tables.

    This is primarily intended for testing purposes.

    Args:
        session: SQLAlchemy async session
    """
    await session.execute(text("DROP TABLE IF EXISTS otel_telemetry_dlq CASCADE"))
    await session.execute(text("DROP TABLE IF EXISTS otel_logs CASCADE"))
    await session.execute(text("DROP TABLE IF EXISTS otel_metrics CASCADE"))
    await session.execute(text("DROP TABLE IF EXISTS otel_traces CASCADE"))
    await session.commit()


async def create_vector_index(session, num_lists: int = 100) -> None:
    """Create IVFFlat vector index for similarity search.

    Creates an approximate nearest neighbor index on the embedding column
    using the IVFFlat access method for efficient vector similarity search.

    Args:
        session: SQLAlchemy async session
        num_lists: Number of lists for IVFFlat (default: 100)
                   Recommendation: num_lists = num_rows / 1000
    """
    await session.execute(
        text(
            f"""
            CREATE INDEX IF NOT EXISTS ix_traces_embedding_ivfflat
            ON otel_traces
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = {num_lists})
        """
        )
    )
    await session.commit()


async def create_ivfflat_index_if_ready(session) -> bool:
    """Create IVFFlat index if sufficient traces exist.

    IVFFlat indexes require 1000+ vectors to be effective.
    This function checks trace count and creates index if threshold met.

    Args:
        session: SQLAlchemy async session

    Returns:
        True if index created, False if skipped
    """
    import logging

    logger = logging.getLogger(__name__)

    try:
        # Check trace count
        result = await session.execute(text("SELECT COUNT(*) FROM otel_traces"))
        trace_count = result.scalar()

        if trace_count < 1000:
            logger.info(
                "ivfflat-index-skipped",
                trace_count=trace_count,
                threshold=1000,
                reason="Insufficient traces for IVFFlat index"
            )
            return False

        # Check if index already exists
        result = await session.execute(text("""
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'otel_traces' AND indexname LIKE '%ivfflat%'
        """))
        if result.fetchone():
            logger.info("ivfflat-index-exists", message="Index already exists")
            return False

        # Create IVFFlat index
        await session.execute(text("""
            CREATE INDEX CONCURRENTLY ix_traces_embedding_ivfflat
            ON otel_traces
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100)
        """))
        await session.commit()

        logger.info(
            "ivfflat-index-created",
            trace_count=trace_count,
            index_type="ivfflat",
            lists=100
        )
        return True

    except Exception as exc:
        logger.error("ivfflat-index-failed", error=str(exc))
        await session.rollback()
        raise


async def create_query_optimization_indexes(session) -> None:
    """Create indexes for common query patterns.

    Creates composite and GIN indexes for optimized error search
    and time-range queries.
    """
    import logging

    logger = logging.getLogger(__name__)

    try:
        # Composite index for time-range error queries
        await session.execute(text("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_traces_start_time_status
            ON otel_traces (start_time, status)
        """))

        # GIN index for JSON attribute queries (already exists in schema, skip)
        # Note: ix_traces_attributes_gin is already created in create_otel_schema

        await session.commit()
        logger.info("query-indexes-created", indexes=["start_time_status"])

    except Exception as exc:
        logger.error("query-indexes-failed", error=str(exc))
        await session.rollback()
        raise
