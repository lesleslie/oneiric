"""OpenTelemetry storage adapter implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from structlog.stdlib import BoundLogger

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
    - store_trace() - Store trace with embedding (async, buffered)
    - store_metrics() - Store metrics in time-series storage
    - store_log() - Store log with trace correlation

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
            async with self._session_factory() as session:
                result = await session.execute("SELECT extname FROM pg_extension WHERE extname = 'vector';")
                if not result.fetchone():
                    raise RuntimeError("Pgvector extension not installed. Run: CREATE EXTENSION vector;")

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
            async with self._session_factory() as session:
                await session.execute("SELECT 1;")
                return True
        except Exception as exc:
            self._logger.warning("adapter-health-error", error=str(exc))
            return False

    async def cleanup(self) -> None:
        """Close database connections and flush buffers."""
        if not self._engine:
            return

        await self._engine.dispose()
        self._engine = None
        self._session_factory = None
        self._logger.info("adapter-cleanup", adapter="otel-storage")

    # Abstract methods for storing telemetry (to be implemented in Task 4-6)
    @abstractmethod
    async def store_trace(self, trace: dict) -> None:
        """Store a trace with embedding."""
        raise NotImplementedError

    @abstractmethod
    async def store_metrics(self, metrics: list[dict]) -> None:
        """Store metrics in time-series storage."""
        raise NotImplementedError

    @abstractmethod
    async def store_log(self, log: dict) -> None:
        """Store log with trace correlation."""
        raise NotImplementedError

    # Abstract methods for querying (to be implemented in Phase 3)
    @abstractmethod
    async def find_similar_traces(self, embedding: list[float], threshold: float = 0.85) -> list[dict]:
        """Find traces by vector similarity."""
        raise NotImplementedError

    @abstractmethod
    async def get_traces_by_error(self, error_type: str, service: str | None = None) -> list[dict]:
        """Get traces filtered by error."""
        raise NotImplementedError

    @abstractmethod
    async def search_logs(self, trace_id: str, level: str | None = None) -> list[dict]:
        """Search logs with trace correlation."""
        raise NotImplementedError
