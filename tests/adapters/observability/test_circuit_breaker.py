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


@pytest.mark.asyncio
async def test_circuit_closed_passes_requests(circuit_breaker):
    """Test circuit in CLOSED state passes requests."""
    async def dummy_func():
        return "success"

    result = await circuit_breaker.call(dummy_func)
    assert result == "success"
    assert circuit_breaker.state == CircuitBreaker.CLOSED


@pytest.mark.asyncio
async def test_circuit_opens_after_threshold(circuit_breaker):
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


@pytest.mark.asyncio
async def test_circuit_half_opens_after_timeout(circuit_breaker):
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

    # Should attempt reset and succeed, closing the circuit
    async def dummy_func():
        return "success"

    result = await circuit_breaker.call(dummy_func)
    assert result == "success"
    # After successful call in HALF_OPEN state, circuit closes
    assert circuit_breaker.state == CircuitBreaker.CLOSED
    assert circuit_breaker.failure_count == 0


@pytest.mark.asyncio
async def test_circuit_closes_after_half_open_success(circuit_breaker):
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


@pytest.mark.asyncio
async def test_circuit_remains_open_without_timeout(circuit_breaker):
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


@pytest.mark.asyncio
async def test_circuit_resets_on_success(circuit_breaker):
    """Test circuit resets failure count on success."""
    circuit_breaker.failure_count = 3

    async def success_func():
        return "success"

    await circuit_breaker.call(success_func)
    assert circuit_breaker.failure_count == 0


@pytest.mark.asyncio
async def test_circuit_error_in_open_state(circuit_breaker):
    """Test requests fail immediately when circuit is OPEN."""
    circuit_breaker.state = CircuitBreaker.OPEN
    circuit_breaker.last_failure_time = time.time()

    async def dummy_func():
        return "success"

    with pytest.raises(CircuitBreakerOpenError):
        await circuit_breaker.call(dummy_func)
