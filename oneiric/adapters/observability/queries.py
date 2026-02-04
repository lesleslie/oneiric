from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import numpy as np
from numpy import ndarray
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker
from structlog.stdlib import BoundLogger

from oneiric.adapters.observability.errors import (
    InvalidEmbeddingError,
    InvalidSQLError,
    TraceNotFoundError,
)
from oneiric.adapters.observability.models import LogModel, MetricModel, TraceModel
from oneiric.adapters.observability.monitoring import OTelMetrics
from oneiric.adapters.observability.types import (
    LogEntry,
    MetricPoint,
    TraceContext,
    TraceResult,
)
from oneiric.core.lifecycle import get_logger


class QueryService:
    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory
        self._logger: BoundLogger = get_logger("otel.queries")
        self._metrics = OTelMetrics()

    def _orm_to_result(self, orm_model: TraceModel) -> TraceResult:
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
            attributes=orm_model.attributes or {},
            similarity=None,
        )

    async def find_similar_traces(
        self, embedding: ndarray, threshold: float = 0.85, limit: int = 10
    ) -> list[TraceResult]:
        start_time = time.time()

        if embedding.shape != (384,):
            raise InvalidEmbeddingError(
                f"Invalid embedding dimension: {embedding.shape}, expected (384,)"
            )

        async with self._session_factory() as session:
            query = (
                select(TraceModel)
                .where((1 - TraceModel.embedding.op("<=>")(embedding)) > threshold)
                .order_by(TraceModel.embedding.op("<=>")(embedding))
                .limit(limit)
            )

            result = await session.execute(query)
            orm_models = result.scalars().all()

            results = []
            for model in orm_models:
                trace_result = self._orm_to_result(model)

                model_embedding_array = np.array(model.embedding)
                similarity = float(
                    np.dot(model_embedding_array, embedding)
                    / (
                        np.linalg.norm(model_embedding_array)
                        * np.linalg.norm(embedding)
                    )
                )
                trace_result.similarity = similarity
                results.append(trace_result)

            self._logger.debug(
                "query-executed",
                method="find_similar_traces",
                result_count=len(results),
            )

            duration_ms = (time.time() - start_time) * 1000
            self._metrics.record_query("find_similar_traces", duration_ms)

            return results

    async def get_traces_by_error(
        self,
        error_pattern: str,
        service: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
    ) -> list[TraceResult]:
        async with self._session_factory() as session:
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

            params = {"error_pattern": error_pattern}
            if service:
                params["service"] = service

            result = await session.execute(query, params)
            orm_models = result.scalars().all()

            return [self._orm_to_result(model) for model in orm_models]

    async def get_trace_context(self, trace_id: str) -> TraceContext:
        async with self._session_factory() as session:
            trace_query = select(TraceModel).where(TraceModel.trace_id == trace_id)
            trace_result = await session.execute(trace_query)
            trace_model = trace_result.scalar_one_or_none()

            if not trace_model:
                raise TraceNotFoundError(f"Trace not found: {trace_id}")

            trace_pydantic = self._orm_to_result(trace_model)

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
                    span_attributes=log.span_attributes or {},
                )
                for log in log_models
            ]

            metrics_query = select(MetricModel).where(
                text("labels->>'trace_id' = :trace_id")
            )
            metrics_result = await session.execute(
                metrics_query, {"trace_id": trace_id}
            )
            metric_models = metrics_result.scalars().all()

            metrics = [
                MetricPoint(
                    name=metric.name,
                    type=metric.type,
                    value=metric.value,
                    unit=metric.unit,
                    labels=metric.labels or {},
                    timestamp=metric.timestamp,
                )
                for metric in metric_models
            ]


            from oneiric.adapters.observability.types import TraceData
            trace_data = TraceData(
                trace_id=trace_model.trace_id,
                span_id=trace_model.id,
                parent_span_id=None,
                name=trace_model.name,
                kind="INTERNAL",
                start_time=trace_model.start_time,
                end_time=trace_model.end_time or trace_model.start_time,
                duration_ms=trace_model.duration_ms or 0,
                status=trace_model.status,
                attributes=trace_model.attributes or {},
                service=trace_pydantic.service,
                operation=trace_pydantic.operation or "unknown",
            )

            return TraceContext(
                trace_id=trace_id,
                spans=[trace_data],
                logs=logs,
                metrics=metrics
            )

    async def custom_query(
        self, sql: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        sql_stripped = sql.strip().upper()

        if not sql_stripped.startswith(("SELECT", "WITH")):
            raise InvalidSQLError("Only SELECT and WITH queries allowed")

        dangerous_patterns = ["; DROP", "; DELETE", "; INSERT", "; UPDATE", "--", "/*"]
        for pattern in dangerous_patterns:
            if pattern in sql.upper():
                raise InvalidSQLError(f"Dangerous SQL pattern detected: {pattern}")

        async with self._session_factory() as session:
            result = await session.execute(sql, params or {})
            rows = result.fetchall()
            return [dict(row._mapping) for row in rows]
