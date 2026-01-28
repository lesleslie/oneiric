"""Query service for OTel telemetry."""

from __future__ import annotations

from datetime import datetime, UTC
from typing import Any

from numpy import ndarray
from sqlalchemy.ext.asyncio import async_sessionmaker
from structlog.stdlib import BoundLogger

from oneiric.core.lifecycle import get_logger
from oneiric.adapters.observability.models import TraceModel, LogModel, MetricModel
from oneiric.adapters.observability.types import TraceResult, LogEntry, MetricPoint


class QueryService:
    """High-level query API for OTel telemetry."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        """Initialize with SQLAlchemy session factory.

        Args:
            session_factory: Async session factory for queries
        """
        self._session_factory = session_factory
        self._logger: BoundLogger = get_logger("otel.queries")

    def _orm_to_result(self, orm_model: TraceModel) -> TraceResult:
        """Convert TraceModel to TraceResult.

        Args:
            orm_model: SQLAlchemy TraceModel instance

        Returns:
            TraceResult Pydantic model
        """
        return TraceResult(
            trace_id=orm_model.trace_id,
            span_id=orm_model.id,
            name=orm_model.name,
            service=orm_model.attributes.get("service", "unknown"),
            operation=orm_model.attributes.get("operation"),
            status=orm_model.status,
            duration_ms=orm_model.duration_ms,
            start_time=orm_model.start_time,
            end_time=orm_model.end_time,
            attributes=orm_model.attributes or {}
        )
