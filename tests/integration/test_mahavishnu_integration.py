"""Integration tests for Mahavishnu OTel storage."""

from __future__ import annotations

import pytest
from datetime import datetime, UTC


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mahavishnu_can_store_traces():
    """Test that Mahavishnu can store traces via OTelStorageAdapter.

    This test prepares for Mahavishnu integration by verifying
    the adapter interface is compatible.
    """
    from oneiric.adapters.observability.otel import OTelStorageAdapter
    from oneiric.adapters.observability.settings import OTelStorageSettings
    from oneiric.adapters.observability.migrations import create_otel_schema

    settings = OTelStorageSettings(
        connection_string="postgresql://postgres:postgres@localhost:5432/otel_test"
    )

    class TestAdapter(OTelStorageAdapter):
        async def find_similar_traces(self, embedding: list[float], limit: int = 10) -> list[dict]:
            return []

        async def get_traces_by_error(self, error_type: str, limit: int = 100) -> list[dict]:
            return []

        async def search_logs(self, query: str, limit: int = 100) -> list[dict]:
            return []

    adapter = TestAdapter(settings=settings)

    try:
        await adapter.init()

        # Create schema
        async with adapter._session_factory() as session:
            await create_otel_schema(session)

        # Create trace
        trace = {
            "trace_id": "mahavishnu-test-001",
            "span_id": "span-001",
            "name": "mahavishnu_workflow",
            "kind": "INTERNAL",
            "start_time": datetime.now(UTC),
            "end_time": datetime.now(UTC),
            "duration_ms": 100.0,
            "status": "OK",
            "service": "mahavishnu",
            "operation": "test_workflow",
            "attributes": {"workflow_id": "wf-001"}
        }

        # Store trace
        await adapter.store_trace(trace)

        # Flush buffer
        await adapter._flush_buffer()

        # Verify stored
        from sqlalchemy import select
        async with adapter._session_factory() as session:
            from oneiric.adapters.observability.models import TraceModel
            result = await session.execute(
                select(TraceModel).filter_by(trace_id="mahavishnu-test-001")
            )
            stored_trace = result.scalar_one()

        assert stored_trace is not None
        assert stored_trace.service == "mahavishnu"

    finally:
        await adapter.cleanup()
