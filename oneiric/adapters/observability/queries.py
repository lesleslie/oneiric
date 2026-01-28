"""Query service for OTel telemetry."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np
from numpy import ndarray
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker
from structlog.stdlib import BoundLogger

from oneiric.core.lifecycle import get_logger
from oneiric.adapters.observability.models import LogModel, MetricModel, TraceModel
from oneiric.adapters.observability.types import (
    LogEntry,
    MetricPoint,
    TraceContext,
    TraceResult,
)
from oneiric.adapters.observability.errors import (
    InvalidEmbeddingError,
    InvalidSQLError,
    TraceNotFoundError,
)


class QueryService:
    """High-level query API for OTel telemetry.

    Provides methods for querying and converting OTel telemetry data from
    the database into user-friendly Pydantic models.

    Methods:
        _orm_to_result: Convert ORM models to Pydantic result models
        find_similar_traces: Vector similarity search using Pgvector
        get_traces_by_error: Find traces by error pattern
        get_trace_context: Get complete trace context with correlated data
        custom_query: Execute raw SQL query (read-only)
    """

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

    async def find_similar_traces(
        self,
        embedding: ndarray,
        threshold: float = 0.85,
        limit: int = 10
    ) -> list[TraceResult]:
        """Find traces similar to the given embedding.

        Uses Pgvector cosine similarity search.

        Args:
            embedding: 384-dim vector
            threshold: Minimum similarity (0.0-1.0, default 0.85)
            limit: Max results (default 10)

        Returns:
            List of TraceResult with similarity scores

        Raises:
            InvalidEmbeddingError: If embedding dimension != 384
        """
        # Validate embedding dimension
        if embedding.shape != (384,):
            raise InvalidEmbeddingError(
                f"Invalid embedding dimension: {embedding.shape}, expected (384,)"
            )

        async with self._session_factory() as session:
            # Cosine distance: 0 = identical, 2 = opposite
            # Cosine similarity: 1 - cosine_distance
            # Use .op() to call the <=> operator from pgvector
            query = (
                select(TraceModel)
                .where(
                    (1 - TraceModel.embedding.op('<=>')(embedding)) > threshold
                )
                .order_by(TraceModel.embedding.op('<=>')(embedding))
                .limit(limit)
            )

            result = await session.execute(query)
            orm_models = result.scalars().all()

            # Convert ORM → Pydantic with similarity scores
            results = []
            for model in orm_models:
                trace_result = self._orm_to_result(model)
                # Calculate similarity score (cosine similarity)
                # model.embedding is a list, need to convert to numpy array
                model_embedding_array = np.array(model.embedding)
                similarity = float(np.dot(
                    model_embedding_array, embedding
                ) / (
                    np.linalg.norm(model_embedding_array) *
                    np.linalg.norm(embedding)
                ))
                trace_result.similarity_score = similarity
                results.append(trace_result)

            self._logger.debug(
                "query-executed",
                method="find_similar_traces",
                result_count=len(results)
            )

            return results

    async def get_traces_by_error(
        self,
        error_pattern: str,
        service: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100
    ) -> list[TraceResult]:
        """Find traces matching error pattern using SQL LIKE.

        Args:
            error_pattern: SQL LIKE pattern (e.g., "%connection timeout%")
            service: Filter by service name
            start_time: Filter traces after this time
            end_time: Filter traces before this time
            limit: Maximum results to return

        Returns:
            List of TraceResult matching error pattern
        """
        async with self._session_factory() as session:
            # Use text() for JSON field access in PostgreSQL
            query = select(TraceModel).where(
                text("attributes->>'error.message' LIKE :error_pattern")
            )

            if service:
                query = query.where(text("attributes->>'service' = :service"))
            if start_time:
                query = query.where(TraceModel.start_time >= start_time)
            if end_time:
                query = query.where(TraceModel.start_time <= end_time)

            query = query.limit(limit)

            # Build parameters dict
            params = {"error_pattern": error_pattern}
            if service:
                params["service"] = service

            result = await session.execute(query, params)
            orm_models = result.scalars().all()

            return [self._orm_to_result(model) for model in orm_models]

    async def get_trace_context(self, trace_id: str) -> TraceContext:
        """Get complete trace context with correlated logs and metrics.

        Args:
            trace_id: Trace identifier

        Returns:
            TraceContext with trace, logs, and metrics

        Raises:
            TraceNotFoundError: If trace_id not found
        """
        async with self._session_factory() as session:
            # Get trace
            trace_query = select(TraceModel).where(TraceModel.trace_id == trace_id)
            trace_result = await session.execute(trace_query)
            trace_model = trace_result.scalar_one_or_none()

            if not trace_model:
                raise TraceNotFoundError(f"Trace not found: {trace_id}")

            trace_pydantic = self._orm_to_result(trace_model)

            # Get logs
            logs_query = select(LogModel).where(LogModel.trace_id == trace_id)
            logs_result = await session.execute(logs_query)
            log_models = logs_result.scalars().all()

            logs = [
                LogEntry(
                    id=log.id,
                    timestamp=log.timestamp,
                    level=log.level,
                    message=log.message,
                    trace_id=log.trace_id,
                    resource_attributes=log.resource_attributes or {},
                    span_attributes=log.span_attributes or {}
                )
                for log in log_models
            ]

            # Get metrics
            metrics_query = select(MetricModel).where(
                text("labels->>'trace_id' = :trace_id")
            )
            metrics_result = await session.execute(metrics_query, {"trace_id": trace_id})
            metric_models = metrics_result.scalars().all()

            metrics = [
                MetricPoint(
                    name=metric.name,
                    value=metric.value,
                    unit=metric.unit,
                    labels=metric.labels or {},
                    timestamp=metric.timestamp
                )
                for metric in metric_models
            ]

            return TraceContext(trace=trace_pydantic, logs=logs, metrics=metrics)

    async def custom_query(
        self,
        sql: str,
        params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Execute raw SQL query (read-only).

        Args:
            sql: SQL query (must be SELECT or WITH)
            params: Query parameters

        Returns:
            List of result rows as dictionaries

        Raises:
            InvalidSQLError: If SQL is not read-only or contains dangerous patterns
        """
        sql_stripped = sql.strip().upper()

        if not (sql_stripped.startswith("SELECT") or sql_stripped.startswith("WITH")):
            raise InvalidSQLError("Only SELECT and WITH queries allowed")

        dangerous_patterns = ["; DROP", "; DELETE", "; INSERT", "; UPDATE", "--", "/*"]
        for pattern in dangerous_patterns:
            if pattern in sql.upper():
                raise InvalidSQLError(f"Dangerous SQL pattern detected: {pattern}")

        async with self._session_factory() as session:
            result = await session.execute(sql, params or {})
            rows = result.fetchall()
            return [dict(row._mapping) for row in rows]
