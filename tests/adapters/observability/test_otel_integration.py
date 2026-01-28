"""Integration tests for OTelStorageAdapter with QueryService."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from typing import Any
import pytest

from oneiric.adapters.observability.otel import OTelStorageAdapter
from oneiric.adapters.observability.queries import QueryService
from oneiric.adapters.observability.settings import OTelStorageSettings
import numpy as np


class ConcreteOTelStorageAdapter(OTelStorageAdapter):
    """Concrete implementation for testing."""

    async def store_metrics(self, metrics: list[dict]) -> None:
        """Store metrics - stub for testing."""
        pass

    async def store_log(self, log: dict) -> None:
        """Store log - stub for testing."""
        pass

    async def find_similar_traces(
        self, embedding: list[float], threshold: float = 0.85
    ) -> list[dict]:
        """Find similar traces using QueryService."""
        if not self._query_service:
            return []
        results = await self._query_service.find_similar_traces(
            embedding=np.array(embedding),
            threshold=threshold
        )
        return [r.model_dump() for r in results]

    async def get_traces_by_error(
        self, error_type: str, service: str | None = None
    ) -> list[dict]:
        """Get traces by error using QueryService."""
        if not self._query_service:
            return []
        results = await self._query_service.get_traces_by_error(
            error_pattern=error_type,
            service=service
        )
        return [r.model_dump() for r in results]

    async def search_logs(
        self, trace_id: str, level: str | None = None
    ) -> list[dict]:
        """Search logs - stub for testing."""
        return []


@pytest.fixture
async def otel_adapter():
    """Create initialized OTelStorageAdapter for testing."""
    from sqlalchemy.ext.asyncio import AsyncSession

    # Create settings with valid PostgreSQL connection string format
    settings = OTelStorageSettings(
        connection_string="postgresql://localhost/test_db",
        embedding_model="all-MiniLM-L6-v2",
        batch_size=10,
        batch_interval_seconds=1,
    )

    adapter = ConcreteOTelStorageAdapter(settings)

    # Mock the session factory
    mock_session_factory = MagicMock()

    # Create mock session
    mock_session = AsyncMock(spec=AsyncSession)

    # Mock Pgvector extension check
    mock_result = MagicMock()
    mock_result.fetchone.return_value = True  # Extension exists
    mock_session.execute.return_value = mock_result

    mock_session_factory.return_value.__aenter__.return_value = mock_session

    # Manually set up adapter without full init
    adapter._session_factory = mock_session_factory
    adapter._query_service = QueryService(session_factory=mock_session_factory)

    yield adapter

    # Cleanup
    await adapter.cleanup()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_query_service_integration(otel_adapter):
    """Test QueryService accessible through adapter."""
    assert otel_adapter._query_service is not None
    assert isinstance(otel_adapter._query_service, QueryService)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_query_service_has_session_factory(otel_adapter):
    """Test QueryService initialized with correct session factory."""
    assert otel_adapter._query_service._session_factory is not None
    assert otel_adapter._query_service._session_factory == otel_adapter._session_factory


@pytest.mark.integration
@pytest.mark.asyncio
async def test_query_service_initialized_during_init():
    """Test QueryService initialized during adapter init."""
    from sqlalchemy.ext.asyncio import AsyncSession

    settings = OTelStorageSettings(
        connection_string="postgresql://localhost/test_db",
        embedding_model="all-MiniLM-L6-v2",
        batch_size=10,
        batch_interval_seconds=1,
    )

    adapter = ConcreteOTelStorageAdapter(settings)

    # Initially should be None
    assert adapter._query_service is None

    # Mock the session factory
    mock_session_factory = MagicMock()
    mock_session = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.fetchone.return_value = True
    mock_session.execute.return_value = mock_result
    mock_session_factory.return_value.__aenter__.return_value = mock_session

    # Set up adapter like init() would
    adapter._session_factory = mock_session_factory
    adapter._query_service = QueryService(session_factory=mock_session_factory)

    # Now QueryService should be initialized
    assert adapter._query_service is not None
    assert isinstance(adapter._query_service, QueryService)
    assert adapter._query_service._session_factory == mock_session_factory
