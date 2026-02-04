from __future__ import annotations

from sqlalchemy import text


async def create_otel_schema(session) -> None:
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
    await session.execute(text("DROP TABLE IF EXISTS otel_telemetry_dlq CASCADE"))
    await session.execute(text("DROP TABLE IF EXISTS otel_logs CASCADE"))
    await session.execute(text("DROP TABLE IF EXISTS otel_metrics CASCADE"))
    await session.execute(text("DROP TABLE IF EXISTS otel_traces CASCADE"))
    await session.commit()


async def create_vector_index(session, num_lists: int = 100) -> None:
    # Safe: num_lists from function parameter (int), CREATE INDEX doesn't support parameterized lists. # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query,python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
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
    import logging

    logger = logging.getLogger(__name__)

    try:
        result = await session.execute(text("SELECT COUNT(*) FROM otel_traces"))
        trace_count = result.scalar()

        if trace_count < 1000:
            logger.info(
                "ivfflat-index-skipped: trace_count=%s threshold=%s reason=%s",
                trace_count,
                1000,
                "Insufficient traces for IVFFlat index",
            )
            return False

        result = await session.execute(
            text("""
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'otel_traces' AND indexname LIKE '%ivfflat%'
        """)
        )
        if result.fetchone():
            logger.info("ivfflat-index-exists: Index already exists")
            return False

        await session.execute(
            text("""
            CREATE INDEX CONCURRENTLY ix_traces_embedding_ivfflat
            ON otel_traces
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100)
        """)
        )
        await session.commit()

        logger.info(
            "ivfflat-index-created: trace_count=%s index_type=%s lists=%s",
            trace_count,
            "ivfflat",
            100,
        )
        return True

    except Exception as exc:
        logger.error("ivfflat-index-failed: %s", str(exc))
        await session.rollback()
        raise


async def create_query_optimization_indexes(session) -> None:
    import logging

    logger = logging.getLogger(__name__)

    try:
        await session.execute(
            text("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_traces_start_time_status
            ON otel_traces (start_time, status)
        """)
        )

        await session.commit()
        logger.info("query-indexes-created: indexes=%s", ["start_time_status"])

    except Exception as exc:
        logger.error("query-indexes-failed: %s", str(exc))
        await session.rollback()
        raise
