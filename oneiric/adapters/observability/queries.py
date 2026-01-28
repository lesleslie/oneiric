"""Query service for OTel telemetry."""

from __future__ import annotations

import numpy as np
from numpy import ndarray
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker
from structlog.stdlib import BoundLogger

from oneiric.core.lifecycle import get_logger
from oneiric.adapters.observability.models import TraceModel
from oneiric.adapters.observability.types import TraceResult
from oneiric.adapters.observability.errors import InvalidEmbeddingError


class QueryService:
    """High-level query API for OTel telemetry.

    Provides methods for querying and converting OTel telemetry data from
    the database into user-friendly Pydantic models.

    Methods:
        _orm_to_result: Convert ORM models to Pydantic result models
        find_similar_traces: Vector similarity search using Pgvector

    Note:
        This service uses async SQLAlchemy sessions for database queries.
        Future tasks will add error pattern detection and trace context correlation.
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
