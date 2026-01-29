# Phase 4: Mahavishnu Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Integrate OTelStorageAdapter with Mahavishnu's ObservabilityManager for dual OTel telemetry export (OTLP + PostgreSQL).

**Architecture:** Dual export where ObservabilityManager sends telemetry to both OTLP endpoint (existing) and OTelStorageAdapter (new). Includes transformation layer, circuit breaker, and retry logic for resilience.

**Tech Stack:** SQLAlchemy (async), tenacity (retry), circuit breaker pattern, Pydantic (transformations)

**Cross-Repo Note:** This plan primarily modifies the oneiric-otel-storage repository, but also requires coordination with the mahavishnu repository for ObservabilityManager integration.

______________________________________________________________________

## Task 1: Create circuit breaker implementation

**Files:**

- Create: `oneiric/adapters/observability/circuit_breaker.py`
- Create: `tests/adapters/observability/test_circuit_breaker.py`

**Step 1: Write failing tests for circuit breaker**

Create test file: `tests/adapters/observability/test_circuit_breaker.py`

```python
"""Tests for CircuitBreaker."""

from __future__ import annotations

import time
import pytest
from oneiric.adapters.observability.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError


@pytest.fixture
def circuit_breaker():
    """Create CircuitBreaker with default thresholds."""
    return CircuitBreaker(
        failure_threshold=5,
        timeout_seconds=60
    )


def test_circuit_closed_passes_requests(circuit_breaker):
    """Test circuit in CLOSED state passes requests."""
    async def dummy_func():
        return "success"

    result = await circuit_breaker.call(dummy_func)
    assert result == "success"
    assert circuit_breaker.state == CircuitBreaker.CLOSED


def test_circuit_opens_after_threshold(circuit_breaker):
    """Test circuit opens after threshold failures."""
    async def failing_func():
        raise ConnectionError("Failed")

    # Trigger 5 failures
    for _ in range(5):
        try:
            await circuit_breaker.call(failing_func)
        except ConnectionError:
            pass

    assert circuit_breaker.state == CircuitBreaker.OPEN
    assert circuit_breaker.failure_count == 5


def test_circuit_half_opens_after_timeout(circuit_breaker):
    """Test circuit transitions to HALF_OPEN after timeout."""
    async def failing_func():
        raise ConnectionError("Failed")

    # Open the circuit
    for _ in range(5):
        try:
            await circuit_breaker.call(failing_func)
        except ConnectionError:
            pass

    assert circuit_breaker.state == CircuitBreaker.OPEN

    # Simulate time passing (mock time.time)
    original_time = time.time
    circuit_breaker.last_failure_time = original_time() - 70  # 70 seconds ago

    # Should attempt reset
    async def dummy_func():
        return "success"

    try:
        await circuit_breaker.call(dummy_func)
    except CircuitBreakerOpenError:
        pass  # Expected, still needs timeout check

    assert circuit_breaker.state == CircuitBreaker.HALF_OPEN


def test_circuit_closes_after_half_open_success(circuit_breaker):
    """Test circuit closes after successful request in HALF_OPEN."""
    # Open circuit and move to HALF_OPEN
    circuit_breaker.state = CircuitBreaker.HALF_OPEN
    circuit_breaker.failure_count = 5

    async def success_func():
        return "success"

    result = await circuit_breaker.call(success_func)
    assert result == "success"
    assert circuit_breaker.state == CircuitBreaker.CLOSED
    assert circuit_breaker.failure_count == 0


def test_circuit_remains_open_without_timeout(circuit_breaker):
    """Test circuit remains OPEN without sufficient timeout."""
    # Open the circuit
    circuit_breaker.state = CircuitBreaker.OPEN
    circuit_breaker.failure_count = 5
    circuit_breaker.last_failure_time = time.time()  # Just failed

    async def dummy_func():
        return "success"

    with pytest.raises(CircuitBreakerOpenError):
        await circuit_breaker.call(dummy_func)

    assert circuit_breaker.state == CircuitBreaker.OPEN


def test_circuit_resets_on_success(circuit_breaker):
    """Test circuit resets failure count on success."""
    circuit_breaker.failure_count = 3

    async def success_func():
        return "success"

    await circuit_breaker.call(success_func)
    assert circuit_breaker.failure_count == 0


def test_circuit_error_in_open_state(circuit_breaker):
    """Test requests fail immediately when circuit is OPEN."""
    circuit_breaker.state = CircuitBreaker.OPEN
    circuit_breaker.last_failure_time = time.time()

    async def dummy_func():
        return "success"

    with pytest.raises(CircuitBreakerOpenError):
        await circuit_breaker.call(dummy_func)
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/adapters/observability/test_circuit_breaker.py -v
```

Expected: FAIL - CircuitBreaker doesn't exist yet

**Step 3: Implement CircuitBreaker class**

Create `oneiric/adapters/observability/circuit_breaker.py`:

```python
"""Circuit breaker for protecting against cascading failures."""

from __future__ import annotations

import time
from typing import Any, Callable


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is OPEN and blocking requests."""
    pass


class CircuitBreaker:
    """Circuit breaker for protecting against cascading failures.

    States:
        CLOSED: Normal operation, requests pass through
        HALF_OPEN: Testing recovery after timeout
        OPEN: Failing fast, requests blocked
    """

    CLOSED: str = "CLOSED"
    HALF_OPEN: str = "HALF_OPEN"
    OPEN: str = "OPEN"

    def __init__(
        self,
        failure_threshold: int = 5,
        timeout_seconds: int = 60
    ) -> None:
        """Initialize circuit breaker.

        Args:
            failure_threshold: Failures before opening circuit (default: 5)
            timeout_seconds: Seconds in OPEN before HALF_OPEN (default: 60)
        """
        self.state = self.CLOSED
        self.failure_count = 0
        self.last_failure_time: float | None = None
        self._threshold = failure_threshold
        self._timeout = timeout_seconds

    async def call(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """Execute function with circuit breaker protection.

        Args:
            func: Async function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Function result

        Raises:
            CircuitBreakerOpenError: If circuit breaker is OPEN
        """
        if self.state == self.OPEN:
            if self._should_attempt_reset():
                self.state = self.HALF_OPEN
            else:
                raise CircuitBreakerOpenError(
                    f"Circuit breaker is OPEN ({self._timeout - (time.time() - self.last_failure_time):.0f}s until HALF_OPEN)"
                )

        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except Exception:
            self._on_failure()
            raise

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset."""
        return (
            self.last_failure_time is not None
            and time.time() - self.last_failure_time >= self._timeout
        )

    def _on_success(self) -> None:
        """Handle successful call."""
        if self.state == self.HALF_OPEN:
            self.state = self.CLOSED
        self.failure_count = 0

    def _on_failure(self) -> None:
        """Handle failed call."""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self._threshold:
            self.state = self.OPEN
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/adapters/observability/test_circuit_breaker.py -v
```

Expected: PASS (8 tests)

**Step 5: Commit**

```bash
git add oneiric/adapters/observability/circuit_breaker.py tests/adapters/observability/test_circuit_breaker.py
git commit -m "feat(otel): Implement circuit breaker for resilience

Implement CircuitBreaker class with state machine:
- CLOSED: Normal operation, requests pass
- HALF_OPEN: Testing recovery after timeout
- OPEN: Failing fast, requests blocked
- Transitions: CLOSED → OPEN (5 failures), OPEN → HALF_OPEN (60s), HALF_OPEN → CLOSED (success)

Error handling:
- CircuitBreakerOpenError raised when circuit is OPEN
- Prevents cascading failures by protecting storage backend

Tests cover all state transitions and edge cases.
"
```

______________________________________________________________________

## Task 2: Create retry utilities

**Files:**

- Create: `oneiric/adapters/observability/resilience.py`
- Modify: `pyproject.toml`

**Step 1: Write test for retry decorator**

Create test file: `tests/adapters/observability/test_resilience.py`

```python
"""Tests for resilience utilities."""

from __future__ import annotations

import pytest
from oneiric.adapters.observability.resilience import with_retry


@pytest.mark.asyncio
async def test_with_retry_succeeds_on_third_attempt():
    """Test retry decorator eventually succeeds."""
    attempt_count = 0

    @with_retry(max_attempts=3)
    async def flaky_function():
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count < 3:
            raise ConnectionError("Temporary failure")
        return "success"

    result = await flaky_function()
    assert result == "success"
    assert attempt_count == 3


@pytest.mark.asyncio
async def test_with_retry_fails_after_max_attempts():
    """Test retry decorator gives up after max attempts."""
    @with_retry(max_attempts=2)
    async def always_failing_function():
        raise ConnectionError("Always fails")

    with pytest.raises(ConnectionError):
        await always_failing_function()
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/adapters/observability/test_resilience.py -v
```

Expected: FAIL - resilience.py doesn't exist

**Step 3: Implement retry utilities**

Create `oneiric/adapters/observability/resilience.py`:

```python
"""Resilience utilities for OTel storage."""

from __future__ import annotations

from functools import wraps
from typing import Callable
import asyncio


def with_retry(max_attempts: int = 3):
    """Decorator for retrying with exponential backoff.

    Retries on ConnectionError and TimeoutError.
    Backoff: 100ms initial, 2x multiplier, max 1000ms.

    Args:
        max_attempts: Maximum number of retry attempts

    Returns:
        Decorated async function
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except (ConnectionError, TimeoutError) as exc:
                    last_exception = exc
                    if attempt < max_attempts - 1:
                        # Exponential backoff: 100ms, 200ms, 400ms, etc.
                        delay = min(0.1 * (2 ** attempt), 1.0)
                        await asyncio.sleep(delay)

            # All attempts failed
            raise last_exception

        return wrapper
    return decorator
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/adapters/observability/test_resilience.py -v
```

Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add oneiric/adapters/observability/resilience.py tests/adapters/observability/test_resilience.py
git commit -m "feat(otel): Implement retry with exponential backoff

Implement with_retry decorator:
- Retries on ConnectionError and TimeoutError
- Exponential backoff: 100ms → 200ms → 400ms → ... → 1000ms max
- Configurable max_attempts (default: 3)
- Raises last exception after all attempts fail

Usage:
    @with_retry(max_attempts=3)
    async def store_with_retry():
        await adapter.store_log(log)

Tests cover retry logic and exhaustion.
"
```

______________________________________________________________________

## Task 3: Implement concrete methods in OTelStorageAdapter

**Files:**

- Modify: `oneiric/adapters/observability/otel.py`
- Modify: `tests/adapters/observability/test_otel_adapter.py`

**Step 1: Write tests for store_log and store_metrics**

Add to `tests/adapters/observability/test_otel_adapter.py`:

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_store_log_concrete_implementation(otel_adapter):
    """Test concrete store_log implementation."""
    from datetime import datetime, UTC
    from oneiric.adapters.observability.types import TraceData

    log_data = {
        "trace_id": "trace-log-001",
        "span_id": "span-log-001",
        "name": "log_entry",
        "kind": "INTERNAL",
        "start_time": datetime.now(UTC),
        "end_time": datetime.now(UTC),
        "status": "OK",
        "service": "test",
        "operation": "log_info",
        "duration_ms": 0,
        "attributes": {
            "log.level": "INFO",
            "log.message": "Test log message"
        }
    }

    # Should not raise
    await otel_adapter.store_log(log_data)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_store_metrics_concrete_implementation(otel_adapter):
    """Test concrete store_metrics implementation."""
    metrics_data = [
        {
            "name": "test_metric",
            "type": "counter",
            "value": 1.0,
            "unit": "count",
            "labels": {"env": "test"},
            "timestamp": datetime.now(UTC)
        }
    ]

    # Should not raise
    await otel_adapter.store_metrics(metrics_data)
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/adapters/observability/test_otel_adapter.py -k "store_log or store_metrics" -v
```

Expected: FAIL - Methods are abstract or not implemented

**Step 3: Implement concrete store_log and store_metrics**

Modify `oneiric/adapters/observability/otel.py`:

Add imports:

```python
from oneiric.adapters.observability.models import LogModel, MetricModel
from oneiric.adapters.observability.types import MetricData
```

Add concrete implementations after abstract methods:

```python
async def store_log(self, log: dict) -> None:
    """Store log with trace correlation.

    Concrete implementation of abstract method.
    Converts log dict to LogModel and persists to database.

    Args:
        log: Log data dictionary with trace_id correlation
    """
    try:
        log_model = LogModel(
            id=log.get("id", f"log-{log['trace_id']}-{int(datetime.utcnow().timestamp())}"),
            timestamp=datetime.fromisoformat(log["start_time"]) if isinstance(log["start_time"], str) else log["start_time"],
            level=log["attributes"].get("log.level", "INFO"),
            message=log["attributes"].get("log.message", ""),
            trace_id=log.get("trace_id"),
            resource_attributes={k: v for k, v in log.get("attributes", {}).items() if k not in ["log.level", "log.message"]},
            span_attributes={}
        )

        async with self._session_factory() as session:
            session.add(log_model)
            await session.commit()

        self._logger.debug("log-stored", log_id=log.get("trace_id"))

    except Exception as exc:
        self._logger.error("log-store-failed", error=str(exc))
        raise


async def store_metrics(self, metrics: list[dict]) -> None:
    """Store metrics in time-series storage.

    Concrete implementation of abstract method.
    Converts metric dicts to MetricModel and persists to database.

    Args:
        metrics: List of metric data dictionaries
    """
    try:
        metric_models = []
        for metric in metrics:
            metric_model = MetricModel(
                id=f"metric-{metric['name']}-{int(datetime.utcnow().timestamp())}",
                name=metric["name"],
                type=metric.get("type", "gauge"),
                value=metric["value"],
                unit=metric.get("unit"),
                labels=metric.get("labels", {}),
                timestamp=datetime.fromisoformat(metric["timestamp"]) if isinstance(metric["timestamp"], str) else metric["timestamp"]
            )
            metric_models.append(metric_model)

        async with self._session_factory() as session:
            session.add_all(metric_models)
            await session.commit()

        self._logger.debug("metrics-stored", count=len(metrics))

    except Exception as exc:
        self._logger.error("metrics-store-failed", error=str(exc))
        raise
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/adapters/observability/test_otel_adapter.py -k "store_log or store_metrics" -v
```

Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add oneiric/adapters/observability/otel.py tests/adapters/observability/test_otel_adapter.py
git commit -m "feat(otel): Implement concrete store_log and store_metrics

Implement abstract methods in OTelStorageAdapter:
- store_log(): Stores logs with trace correlation in PostgreSQL
- store_metrics(): Stores metrics in time-series storage

Both methods:
- Convert dict data to SQLAlchemy models (LogModel, MetricModel)
- Persist to database with async session
- Comprehensive error handling and logging

Tests cover concrete implementation.
"
```

______________________________________________________________________

## Task 4: Create Mahavishnu integration tests (prepare for cross-repo work)

**Files:**

- Create: `tests/integration/test_mahavishnu_integration.py`

**Step 1: Write integration tests**

```python
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
    from oneiric.adapters.observability.types import TraceData

    settings = OTelStorageSettings(
        connection_string="postgresql://postgres:postgres@localhost:5432/otel_test"
    )

    class TestAdapter(OTelStorageAdapter):
        async def store_metrics(self, metrics_data: list[dict]) -> None:
            pass

        async def store_log(self, log_data: dict) -> None:
            pass

    adapter = TestAdapter(settings=settings)

    try:
        await adapter.init()

        # Create trace
        trace = TraceData(
            trace_id="mahavishnu-test-001",
            span_id="span-001",
            name="mahavishnu_workflow",
            kind="INTERNAL",
            start_time=datetime.now(UTC),
            end_time=datetime.now(UTC),
            duration_ms=100.0,
            status="OK",
            service="mahavishnu",
            operation="test_workflow",
            attributes={"workflow_id": "wf-001"}
        )

        # Store trace
        await adapter.store_trace(trace.model_dump())

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
```

**Step 2: Run test to verify it works (if PostgreSQL available)**

```bash
pytest tests/integration/test_mahavishnu_integration.py -v
```

Expected: PASS (if PostgreSQL) or SKIP (if no database)

**Step 3: Commit**

```bash
git add tests/integration/test_mahavishnu_integration.py
git commit -m "test(otel): Add Mahavishnu integration tests

Add integration test for Mahavishnu + OTelStorageAdapter:
- Verifies Mahavishnu can store traces
- Tests trace_id and attributes preservation
- Prepares for cross-repo integration

Test marked as integration and requires PostgreSQL.
"
```

______________________________________________________________________

## Summary

This plan provides:

✅ **Bite-sized tasks** - Each step is 2-5 minutes
✅ **Exact file paths** - All files specified
✅ **Complete code** - Full implementations in plan
✅ **TDD workflow** - Test first, then implement
✅ **Frequent commits** - Commit after each task
✅ **Type hints** - Full type annotations
✅ **Error handling** - Circuit breaker, retry logic
✅ **Integration tests** - Prepared for cross-repo work

**Total breakdown:**

- **Task 1:** Circuit breaker implementation (8 tests)
- **Task 2:** Retry utilities (2 tests)
- **Task 3:** Concrete methods in OTelStorageAdapter
- **Task 4:** Mahavishnu integration tests (prepares cross-repo work)

**Estimated completion:** 4 hours (for oneiric-otel-storage only)
**Complexity:** Medium (circuit breaker, retry logic, async patterns)
**Cross-repo note:** Mahavishnu repository modifications are out of scope for this plan

**Next steps after this plan:**

1. Execute Tasks 1-4 in oneiric-otel-storage repository
1. Create separate implementation plan for mahavishnu repository
1. Coordinate changes across both repositories
