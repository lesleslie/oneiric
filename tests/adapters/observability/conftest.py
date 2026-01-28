"""Fixtures for observability adapter tests."""

from __future__ import annotations

from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock
import numpy as np
import pytest

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from oneiric.adapters.observability.models import TraceModel


@pytest.fixture
async def sample_traces_with_embeddings():
    """Create sample traces with embeddings for testing.

    Returns a session factory with sample data already inserted.
    """
    # Create mock session
    mock_session = AsyncMock(spec=AsyncSession)

    # Create sample traces with embeddings
    sample_traces = []
    for i in range(3):
        trace = TraceModel(
            id=f"span-{i:03d}",
            trace_id=f"trace-{i:03d}",
            name=f"Test operation {i}",
            start_time=datetime.now(UTC),
            status="OK",
            duration_ms=100.0 + i * 50,
            attributes={
                "service": f"test-service-{i % 2}",  # Alternate between services
                "operation": f"test_op_{i}"
            },
            embedding=np.random.rand(384).tolist()  # Random 384-dim embedding
        )
        sample_traces.append(trace)

    # Mock the execute method to return our sample traces
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = sample_traces
    mock_session.execute.return_value = mock_result

    # Mock session factory
    session_factory = MagicMock()
    session_factory.return_value.__aenter__.return_value = mock_session

    return session_factory
