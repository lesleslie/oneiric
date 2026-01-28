"""Tests for OTelStorageAdapter lifecycle and interface."""

from __future__ import annotations

import pytest

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

        async def store_trace(self, trace_data: dict) -> str:
            """Store trace data - stub implementation."""
            return "test-trace-id"

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


def test_adapter_instantiation(concrete_adapter):
    """Test adapter can be instantiated with settings."""
    assert concrete_adapter._settings is not None
    assert concrete_adapter._engine is None  # Not initialized yet


def test_adapter_has_abstract_methods(concrete_adapter):
    """Test adapter defines abstract methods for telemetry storage and querying."""
    # Verify abstract methods exist
    assert hasattr(concrete_adapter, "store_trace")
    assert hasattr(concrete_adapter, "store_metrics")
    assert hasattr(concrete_adapter, "store_log")
    assert hasattr(concrete_adapter, "find_similar_traces")
    assert hasattr(concrete_adapter, "get_traces_by_error")
    assert hasattr(concrete_adapter, "search_logs")

    # Verify they're callable
    assert callable(concrete_adapter.store_trace)
    assert callable(concrete_adapter.store_metrics)
    assert callable(concrete_adapter.store_log)
    assert callable(concrete_adapter.find_similar_traces)
    assert callable(concrete_adapter.get_traces_by_error)
    assert callable(concrete_adapter.search_logs)
