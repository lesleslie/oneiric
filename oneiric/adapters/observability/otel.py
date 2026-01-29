"""OpenTelemetry storage adapter implementation."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections import deque
from datetime import UTC, datetime
from typing import Any

from structlog.stdlib import BoundLogger

from oneiric.adapters.observability.embeddings import EmbeddingService
from oneiric.adapters.observability.models import TraceModel
from oneiric.adapters.observability.queries import QueryService
from oneiric.adapters.observability.settings import OTelStorageSettings
from oneiric.core.lifecycle import get_logger


class OTelStorageAdapter(ABC):
    """
    Store and query OTel telemetry data in PostgreSQL/Pgvector.

    Lifecycle:
    1. init() - Initialize database connection and validate schema
    2. health() - Check database connectivity and Pgvector extension
    3. cleanup() - Close connections and flush buffers

    Telemetry storage:
    - store_trace() - Store trace with embedding (async, buffered) ✓ IMPLEMENTED
    - store_metrics() - Store metrics in time-series storage ✓ IMPLEMENTED
    - store_log() - Store log with trace correlation ✓ IMPLEMENTED

    Querying:
    - find_similar_traces() - Vector similarity search
    - get_traces_by_error() - Filter traces by error pattern
    - search_logs() - Full-text log search with trace correlation
    """

    def __init__(self, settings: OTelStorageSettings) -> None:
        """Initialize adapter with settings."""
        self._settings = settings
        self._engine: Any = None
        self._session_factory: Any = None
        self._logger: BoundLogger = get_logger("adapter.observability.otel").bind(
            domain="adapter",
            key="observability",
            provider="otel",
        )
        self._write_buffer: deque[dict] = deque(maxlen=1000)
        self._flush_task: Any = None
        self._flush_lock = asyncio.Lock()
        self._embedding_service = EmbeddingService(model_name=settings.embedding_model)
        self._query_service: QueryService | None = None

    async def init(self) -> None:
        """
        Initialize database connection and validate schema.

        Raises:
            LifecycleError: If database connection fails or Pgvector extension missing
        """
        try:
            from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

            # Convert postgresql:// to postgresql+asyncpg://
            conn_str = self._settings.connection_string.replace(
                "postgresql://", "postgresql+asyncpg://"
            )

            self._engine = create_async_engine(
                conn_str,
                echo=False,
                pool_size=self._settings.max_retries,  # Use max_retries as pool size
                max_overflow=10,
            )

            self._session_factory = async_sessionmaker(
                bind=self._engine,
                expire_on_commit=False,
            )

            # Validate Pgvector extension exists
            from sqlalchemy import text

            from oneiric.adapters.observability.migrations import (
                create_ivfflat_index_if_ready,
            )

            async with self._session_factory() as session:
                result = await session.execute(
                    text("SELECT extname FROM pg_extension WHERE extname = 'vector';")
                )
                if not result.fetchone():
                    raise RuntimeError(
                        "Pgvector extension not installed. Run: CREATE EXTENSION vector;"
                    )

            # Create IVFFlat index if enough traces
            async with self._session_factory() as session:
                await create_ivfflat_index_if_ready(session)

            # Start background flush task
            self._flush_task = asyncio.create_task(self._flush_buffer_periodically())

            # Initialize QueryService
            self._query_service = QueryService(session_factory=self._session_factory)

            self._logger.info("adapter-init", adapter="otel-storage")

        except Exception as exc:
            self._logger.error("adapter-init-failed", error=str(exc))
            raise

    async def health(self) -> bool:
        """
        Check database connectivity and Pgvector extension.

        Returns:
            True if healthy, False otherwise
        """
        if not self._engine:
            return False

        try:
            from sqlalchemy import text

            async with self._session_factory() as session:
                await session.execute(text("SELECT 1;"))
                return True
        except Exception as exc:
            self._logger.warning("adapter-health-error", error=str(exc))
            return False

    async def cleanup(self) -> None:
        """Close database connections and flush buffers."""
        if not self._engine:
            return

        # Cancel background flush task
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        # Flush any remaining buffered traces
        await self._flush_buffer()

        await self._engine.dispose()
        self._engine = None
        self._session_factory = None
        self._query_service = None
        self._logger.info("adapter-cleanup", adapter="otel-storage")

    # Concrete method for storing traces with async buffering
    async def store_trace(self, trace: dict) -> None:
        """Store a trace with async buffering."""
        self._write_buffer.append(trace)
        if len(self._write_buffer) >= self._settings.batch_size:
            await self._flush_buffer()

    async def _flush_buffer_periodically(self) -> None:
        """Background task to flush buffer every N seconds."""
        while True:
            try:
                await asyncio.sleep(self._settings.batch_interval_seconds)
                await self._flush_buffer()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._logger.error("flush-buffer-error", error=str(exc))

    async def _flush_buffer(self) -> None:
        """Flush buffered traces to database in batch."""
        async with self._flush_lock:
            if not self._write_buffer:
                return

            # Get buffered traces and clear buffer
            traces_to_store = list(self._write_buffer)
            self._write_buffer.clear()

            try:
                # Convert dicts to TraceModel instances
                trace_models = []
                for trace_dict in traces_to_store:
                    # Generate embedding (async, cached)
                    embedding = await self._embedding_service.embed_trace(trace_dict)

                    trace_model = TraceModel(
                        id=trace_dict.get("id"),
                        trace_id=trace_dict["trace_id"],
                        parent_span_id=trace_dict.get("parent_span_id"),
                        trace_state=trace_dict.get("trace_state"),
                        name=trace_dict["name"],
                        kind=trace_dict.get("kind"),
                        start_time=datetime.fromisoformat(trace_dict["start_time"])
                        if isinstance(trace_dict["start_time"], str)
                        else trace_dict["start_time"],
                        end_time=datetime.fromisoformat(trace_dict["end_time"])
                        if trace_dict.get("end_time")
                        and isinstance(trace_dict["end_time"], str)
                        else trace_dict.get("end_time"),
                        duration_ms=trace_dict.get("duration_ms"),
                        status=trace_dict["status"],
                        attributes=trace_dict.get("attributes", {}),
                        embedding=embedding.tolist() if embedding is not None else None,
                        embedding_model="all-MiniLM-L6-v2",
                        embedding_generated_at=datetime.now(tz=UTC),
                    )
                    trace_models.append(trace_model)

                # Batch insert
                async with self._session_factory() as session:
                    session.add_all(trace_models)
                    await session.commit()

                self._logger.debug("traces-stored", count=len(trace_models))

            except Exception as exc:
                self._logger.error(
                    "trace-store-failed", error=str(exc), count=len(traces_to_store)
                )
                # Send failed writes to DLQ
                for trace in traces_to_store:
                    await self._send_to_dlq(trace, str(exc))

    async def _send_to_dlq(self, trace: dict, error_message: str) -> None:
        """Insert failed trace into DLQ table."""
        import json

        from sqlalchemy import text

        try:
            async with self._session_factory() as session:
                await session.execute(
                    text("""
                    INSERT INTO otel_telemetry_dlq (telemetry_type, raw_data, error_message, created_at)
                    VALUES ('trace', :raw_data, :error_message, NOW())
                    """),
                    {"raw_data": json.dumps(trace), "error_message": error_message},
                )
                await session.commit()
        except Exception as dlq_exc:
            self._logger.error("dlq-insert-failed", error=str(dlq_exc))

    async def store_log(self, log: dict) -> None:
        """Store log with trace correlation.

        Concrete implementation of abstract method.
        Converts log dict to LogModel and persists to database.

        Args:
            log: Log data dictionary with trace_id correlation
        """
        from oneiric.adapters.observability.models import LogModel

        try:
            log_model = LogModel(
                id=log.get(
                    "id",
                    f"log-{log['trace_id']}-{int(datetime.now(tz=UTC).timestamp())}",
                ),
                timestamp=datetime.fromisoformat(log["start_time"])
                if isinstance(log["start_time"], str)
                else log["start_time"],
                level=log["attributes"].get("log.level", "INFO"),
                message=log["attributes"].get("log.message", ""),
                trace_id=log.get("trace_id"),
                resource_attributes={
                    k: v
                    for k, v in log.get("attributes", {}).items()
                    if k not in ("log.level", "log.message")
                },
                span_attributes={},
            )

            async with self._session_factory() as session:
                session.add(log_model)
                await session.commit()

            self._logger.debug("log-stored", log_id=log.get("trace_id"))

        except Exception as exc:
            self._logger.error("log-store-failed", error=str(exc))
            raise

    async def store_metrics(self, metrics: list[dict]) -> None:
        """Store metrics in time-series storage.

        Concrete implementation of abstract method.
        Converts metric dicts to MetricModel and persists to database.

        Args:
            metrics: List of metric data dictionaries
        """
        from oneiric.adapters.observability.models import MetricModel

        try:
            metric_models = []
            for metric in metrics:
                metric_model = MetricModel(
                    id=f"metric-{metric['name']}-{int(datetime.now(tz=UTC).timestamp())}",
                    name=metric["name"],
                    type=metric.get("type", "gauge"),
                    value=metric["value"],
                    unit=metric.get("unit"),
                    labels=metric.get("labels", {}),
                    timestamp=datetime.fromisoformat(metric["timestamp"])
                    if isinstance(metric["timestamp"], str)
                    else metric["timestamp"],
                )
                metric_models.append(metric_model)

            async with self._session_factory() as session:
                session.add_all(metric_models)
                await session.commit()

            self._logger.debug("metrics-stored", count=len(metrics))

        except Exception as exc:
            self._logger.error("metrics-store-failed", error=str(exc))
            raise

    # Abstract methods for querying (to be implemented in Phase 3)
    @abstractmethod
    async def find_similar_traces(
        self, embedding: list[float], threshold: float = 0.85
    ) -> list[dict]:
        """Find traces by vector similarity."""
        raise NotImplementedError

    @abstractmethod
    async def get_traces_by_error(
        self, error_type: str, service: str | None = None
    ) -> list[dict]:
        """Get traces filtered by error."""
        raise NotImplementedError

    @abstractmethod
    async def search_logs(self, trace_id: str, level: str | None = None) -> list[dict]:
        """Search logs with trace correlation."""
        raise NotImplementedError
