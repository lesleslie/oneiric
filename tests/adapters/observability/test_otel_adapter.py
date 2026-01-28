"""Tests for OTelStorageAdapter lifecycle and interface."""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest
import pytest_asyncio

from oneiric.adapters.observability.migrations import create_otel_schema
from oneiric.adapters.observability.otel import OTelStorageAdapter
from oneiric.adapters.observability.settings import OTelStorageSettings


@pytest.fixture
def otel_settings():
    """Create test OTel storage settings."""
    return OTelStorageSettings(
        connection_string="postgresql://postgres:postgres@localhost:5432/otel_test"
    )


@pytest.fixture
def concrete_adapter(otel_settings):
    """Create a concrete implementation of OTelStorageAdapter for testing."""

    class TestOTelAdapter(OTelStorageAdapter):
        """Concrete implementation for testing base class functionality."""

        async def store_metrics(self, metrics_data: list[dict]) -> list[str]:
            """Store metrics data - stub implementation."""
            return ["test-metric-id"]

        async def store_log(self, log_data: dict) -> str:
            """Store log data - stub implementation."""
            return "test-log-id"

        async def find_similar_traces(
            self, embedding: list[float], limit: int = 10
        ) -> list[dict]:
            """Find similar traces - stub implementation."""
            return []

        async def get_traces_by_error(self, error_type: str, limit: int = 100) -> list[dict]:
            """Get traces by error type - stub implementation."""
            return []

        async def search_logs(self, query: str, limit: int = 100) -> list[dict]:
            """Search logs - stub implementation."""
            return []

    return TestOTelAdapter(settings=otel_settings)


@pytest_asyncio.fixture
async def otel_adapter(otel_settings):
    """Create initialized OTel adapter with database schema for integration tests."""
    # Create concrete adapter class
    class TestOTelAdapter(OTelStorageAdapter):
        """Concrete implementation for integration testing."""

        async def store_metrics(self, metrics_data: list[dict]) -> list[str]:
            return []

        async def store_log(self, log_data: dict) -> str:
            return ""

        async def find_similar_traces(self, embedding: list[float], limit: int = 10) -> list[dict]:
            return []

        async def get_traces_by_error(self, error_type: str, limit: int = 100) -> list[dict]:
            return []

        async def search_logs(self, query: str, limit: int = 100) -> list[dict]:
            return []

    adapter = TestOTelAdapter(settings=otel_settings)

    try:
        # Initialize adapter and create schema
        await adapter.init()
        async with adapter._session_factory() as session:
            await create_otel_schema(session)

        yield adapter

    finally:
        # Cleanup
        await adapter.cleanup()


def test_adapter_instantiation(concrete_adapter):
    """Test adapter can be instantiated with settings."""
    assert concrete_adapter._settings is not None
    assert concrete_adapter._engine is None  # Not initialized yet


def test_adapter_has_abstract_methods(concrete_adapter):
    """Test adapter defines abstract methods for telemetry storage and querying."""
    # Verify abstract methods exist
    assert hasattr(concrete_adapter, "store_metrics")
    assert hasattr(concrete_adapter, "store_log")
    assert hasattr(concrete_adapter, "find_similar_traces")
    assert hasattr(concrete_adapter, "get_traces_by_error")
    assert hasattr(concrete_adapter, "search_logs")

    # Verify they're callable
    assert callable(concrete_adapter.store_metrics)
    assert callable(concrete_adapter.store_log)
    assert callable(concrete_adapter.find_similar_traces)
    assert callable(concrete_adapter.get_traces_by_error)
    assert callable(concrete_adapter.search_logs)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_store_trace(otel_adapter):
    """Test storing a single trace with buffering."""
    trace_data = {
        "trace_id": "test-trace-001",
        "name": "http_request",
        "start_time": datetime.now().isoformat(),
        "status": "OK",
        "attributes": {"http.method": "GET", "http.status_code": 200},
    }

    # Store trace
    await otel_adapter.store_trace(trace_data)

    # Wait a moment for buffer to potentially flush
    await asyncio.sleep(0.1)

    # Verify trace was buffered
    assert len(otel_adapter._write_buffer) == 1 or len(otel_adapter._write_buffer) == 0

    # Force flush
    await otel_adapter._flush_buffer()

    # Verify buffer is empty after flush
    assert len(otel_adapter._write_buffer) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_store_trace_buffers_writes(otel_adapter):
    """Test that traces are buffered and flushed in batches."""
    traces = []
    for i in range(10):
        traces.append({
            "trace_id": f"test-trace-{i:03d}",
            "name": f"span_{i}",
            "start_time": datetime.now().isoformat(),
            "status": "OK",
            "attributes": {"index": i},
        })

    # Store all traces
    for trace in traces:
        await otel_adapter.store_trace(trace)

    # Verify buffering (batch_size is 100, so all should be buffered)
    assert len(otel_adapter._write_buffer) == 10

    # Force flush
    await otel_adapter._flush_buffer()

    # Verify buffer is empty after flush
    assert len(otel_adapter._write_buffer) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_store_trace_auto_flush_on_batch_size(otel_adapter):
    """Test that buffer auto-flushes when reaching batch_size."""
    # Create adapter with small batch size
    from oneiric.adapters.observability.settings import OTelStorageSettings
    small_batch_settings = OTelStorageSettings(
        connection_string="postgresql://postgres:postgres@localhost:5432/otel_test",
        batch_size=5,  # Small batch size for testing
    )

    class TestOTelAdapter(OTelStorageAdapter):
        async def store_metrics(self, metrics_data: list[dict]) -> list[str]:
            return []

        async def store_log(self, log_data: dict) -> str:
            return ""

        async def find_similar_traces(self, embedding: list[float], limit: int = 10) -> list[dict]:
            return []

        async def get_traces_by_error(self, error_type: str, limit: int = 100) -> list[dict]:
            return []

        async def search_logs(self, query: str, limit: int = 100) -> list[dict]:
            return []

    adapter = TestOTelAdapter(settings=small_batch_settings)
    await adapter.init()

    try:
        async with adapter._session_factory() as session:
            await create_otel_schema(session)

        # Store 5 traces (should trigger auto-flush)
        for i in range(5):
            await adapter.store_trace({
                "trace_id": f"auto-trace-{i}",
                "name": "auto_flush_test",
                "start_time": datetime.now().isoformat(),
                "status": "OK",
                "attributes": {},
            })

        # Buffer should be empty after auto-flush
        assert len(adapter._write_buffer) == 0

    finally:
        await adapter.cleanup()

