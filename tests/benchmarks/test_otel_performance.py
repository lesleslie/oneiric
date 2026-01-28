"""Performance benchmarks for OTel adapter."""

from __future__ import annotations

import pytest
import numpy as np
from datetime import datetime, UTC
from sqlalchemy import text

pytest_plugins = ("pytest_benchmark",)


@pytest.mark.benchmark
@pytest.mark.asyncio
@pytest.mark.integration
async def bench_vector_similarity_1k(benchmark, otel_adapter_with_1k_traces):
    """Benchmark vector similarity search with 1K traces."""
    query_embedding = np.random.rand(384)

    async def search():
        return await otel_adapter_with_1k_traces._query_service.find_similar_traces(
            embedding=query_embedding,
            threshold=0.75,
            limit=10
        )

    result = await benchmark(search)
    assert len(result) <= 10


@pytest.mark.benchmark
@pytest.mark.asyncio
@pytest.mark.integration
async def bench_error_search_1k(benchmark, otel_adapter_with_1k_traces):
    """Benchmark error pattern search with 1K traces."""
    async def search():
        return await otel_adapter_with_1k_traces._query_service.get_traces_by_error(
            error_pattern="%timeout%",
            limit=100
        )

    result = await benchmark(search)
    assert isinstance(result, list)


@pytest.fixture
async def otel_adapter_with_1k_traces(otel_db_session):
    """Create adapter with 1K synthetic traces for benchmarking."""
    from oneiric.adapters.observability.migrations import create_otel_schema

    # Create schema
    await create_otel_schema(otel_db_session)

    # Insert 1K traces with embeddings
    for i in range(1000):
        embedding = np.random.rand(384).tolist()
        await otel_db_session.execute(
            text("""
                INSERT INTO otel_traces (id, trace_id, name, start_time, status, attributes, embedding)
                VALUES (:id, :trace_id, :name, :start_time, :status, :attributes, :embedding)
            """),
            {
                "id": f"bench-span-{i}",
                "trace_id": f"bench-trace-{i}",
                "name": f"bench_operation_{i % 50}",  # 50 unique operations
                "start_time": datetime.now(UTC),
                "status": "ERROR" if i % 10 == 0 else "OK",  # 10% error rate
                "attributes": {
                    "service": f"service-{i % 20}",
                    "error.message": "Connection timeout" if i % 10 == 0 else None
                },
                "embedding": embedding
            }
        )
    await otel_db_session.commit()

    # Create a mock adapter with QueryService
    from oneiric.adapters.observability.queries import QueryService

    class MockAdapter:
        def __init__(self, session):
            self._query_service = QueryService(lambda: session)

    mock_adapter = MockAdapter(otel_db_session)
    yield mock_adapter
