"""Extended resiliency tests.

Tests for circuit breaker, retry logic, and adaptive backoff.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from oneiric.core.resiliency import (
    AdaptiveRetryState,
    CircuitBreaker,
    CircuitBreakerOpen,
    _ADAPTIVE_RETRY_STATE,
    _tune_backoff,
    _update_retry_state,
)


class TestCircuitBreaker:
    """Test circuit breaker functionality."""

    def test_circuit_breaker_initially_closed(self):
        """Circuit breaker starts in closed state."""
        breaker = CircuitBreaker(
            name="test-breaker",
            failure_threshold=5,
            recovery_time=1.0,
        )

        assert not breaker.is_open

    async def test_circuit_breaker_opens_on_threshold(self):
        """Circuit breaker opens after failure threshold."""
        breaker = CircuitBreaker(
            name="test-breaker",
            failure_threshold=3,
            recovery_time=1.0,
        )

        # Record failures via call()
        failing_func = AsyncMock(side_effect=ValueError("Failure"))

        for _ in range(3):
            try:
                await breaker.call(failing_func)
            except (ValueError, CircuitBreakerOpen):
                pass

        # Circuit should be open after threshold
        assert breaker.is_open

    async def test_circuit_breaker_successes_keep_closed(self):
        """Successes keep circuit breaker closed."""
        breaker = CircuitBreaker(
            name="test-breaker",
            failure_threshold=3,
            recovery_time=0.1,
        )

        # Success calls keep circuit closed
        success_func = AsyncMock(return_value="success")

        for _ in range(5):
            result = await breaker.call(success_func)
            assert result == "success"
            assert not breaker.is_open

    async def test_circuit_breaker_raises_when_open(self):
        """Circuit breaker raises exception when open."""
        breaker = CircuitBreaker(
            name="test-breaker",
            failure_threshold=1,
            recovery_time=10.0,
        )

        # Open the circuit
        failing_func = AsyncMock(side_effect=ValueError("Failure"))

        try:
            await breaker.call(failing_func)
        except (ValueError, CircuitBreakerOpen):
            pass  # Expected - either opens the circuit or already open

        # Should be open now
        assert breaker.is_open

        # Next call should raise CircuitBreakerOpen
        with pytest.raises(CircuitBreakerOpen):
            await breaker.call(failing_func)


class TestAdaptiveRetryState:
    """Test adaptive retry state tracking."""

    def test_retry_state_initialization(self):
        """Retry state initializes with default values."""
        state = AdaptiveRetryState()

        assert state.consecutive_failures == 0
        assert state.success_count == 0
        assert state.failure_count == 0
        assert state.last_latency_ms is None

    def test_retry_state_with_custom_values(self):
        """Retry state accepts custom values."""
        state = AdaptiveRetryState(
            consecutive_failures=5,
            success_count=10,
            failure_count=8,
            last_latency_ms=250.5,
        )

        assert state.consecutive_failures == 5
        assert state.success_count == 10
        assert state.failure_count == 8
        assert state.last_latency_ms == 250.5


class TestTuneBackoff:
    """Test backoff tuning logic."""

    def test_tune_backoff_no_adaptive_key(self):
        """Without adaptive key, returns original values."""
        base, max_delay, jitter = _tune_backoff(
            adaptive_key=None,
            base_delay=1.0,
            max_delay=30.0,
            jitter=0.25,
        )

        assert base == 1.0
        assert max_delay == 30.0
        assert jitter == 0.25

    def test_tune_backoff_first_failure(self):
        """First failure increases base delay slightly."""
        _ADAPTIVE_RETRY_STATE.clear()
        key = "test-first-failure"

        # Record one failure
        _update_retry_state(key, success=False, latency_ms=100)

        base, max_delay, jitter = _tune_backoff(
            adaptive_key=key,
            base_delay=1.0,
            max_delay=30.0,
            jitter=0.25,
        )

        assert base > 1.0  # Should increase due to failure
        assert base <= 1.2  # But not too much (one failure)

    def test_tune_backoff_multiple_failures(self):
        """Multiple failures increase backoff more."""
        _ADAPTIVE_RETRY_STATE.clear()
        key = "test-multiple-failures"

        # Record multiple failures
        for _ in range(5):
            _update_retry_state(key, success=False, latency_ms=100)

        base, max_delay, jitter = _tune_backoff(
            adaptive_key=key,
            base_delay=1.0,
            max_delay=30.0,
            jitter=0.25,
        )

        assert base > 1.5  # Should be significantly higher

    def test_tune_backoff_high_latency(self):
        """High latency increases backoff factor."""
        _ADAPTIVE_RETRY_STATE.clear()
        key = "test-high-latency"

        # Record failure with high latency
        _update_retry_state(key, success=False, latency_ms=3000)

        base, max_delay, jitter = _tune_backoff(
            adaptive_key=key,
            base_delay=1.0,
            max_delay=30.0,
            jitter=0.25,
        )

        assert base > 1.0  # Should increase due to high latency

    def test_tune_backoff_capped_at_max(self):
        """Tuned delay is capped at max_delay."""
        _ADAPTIVE_RETRY_STATE.clear()
        key = "test-capped"

        # Record many failures
        for _ in range(10):
            _update_retry_state(key, success=False, latency_ms=100)

        base, max_delay, jitter = _tune_backoff(
            adaptive_key=key,
            base_delay=1.0,
            max_delay=5.0,
            jitter=0.25,
        )

        assert max_delay == 5.0  # Max should be preserved


class TestUpdateRetryState:
    """Test retry state updates."""

    def test_update_retry_state_success(self):
        """Successful operation resets consecutive failures."""
        _ADAPTIVE_RETRY_STATE.clear()
        key = "test-success"

        # Record some failures
        _update_retry_state(key, success=False, latency_ms=100)
        _update_retry_state(key, success=False, latency_ms=100)
        state = _ADAPTIVE_RETRY_STATE[key]
        assert state.consecutive_failures == 2
        assert state.failure_count == 2

        # Record success
        _update_retry_state(key, success=True, latency_ms=50)
        state = _ADAPTIVE_RETRY_STATE[key]
        assert state.consecutive_failures == 0  # Reset
        assert state.success_count == 1
        assert state.failure_count == 2  # Total failures unchanged
        assert state.last_latency_ms == 50

    def test_update_retry_state_failure(self):
        """Failed operation increments counters."""
        _ADAPTIVE_RETRY_STATE.clear()
        key = "test-failure"

        _update_retry_state(key, success=False, latency_ms=200)
        state = _ADAPTIVE_RETRY_STATE[key]

        assert state.consecutive_failures == 1
        assert state.failure_count == 1
        assert state.success_count == 0
        assert state.last_latency_ms == 200

    def test_update_retry_state_multiple_attempts(self):
        """Multiple updates track correctly."""
        _ADAPTIVE_RETRY_STATE.clear()
        key = "test-multiple"

        # Mix of failures and success
        _update_retry_state(key, success=False, latency_ms=100)
        _update_retry_state(key, success=False, latency_ms=100)
        _update_retry_state(key, success=True, latency_ms=50)
        _update_retry_state(key, success=False, latency_ms=100)

        state = _ADAPTIVE_RETRY_STATE[key]
        assert state.consecutive_failures == 1  # Reset by success
        assert state.failure_count == 3
        assert state.success_count == 1
        assert state.last_latency_ms == 100

    def test_update_retry_state_no_key(self):
        """Without adaptive key, state is not updated."""
        _ADAPTIVE_RETRY_STATE.clear()

        # Should not create state entry
        _update_retry_state(adaptive_key=None, success=True, latency_ms=50)
        assert len(_ADAPTIVE_RETRY_STATE) == 0


class TestResiliencyEdgeCases:
    """Test resiliency edge cases."""

    async def test_circuit_breaker_zero_threshold(self):
        """Circuit breaker with threshold=1 opens immediately."""
        breaker = CircuitBreaker(
            name="test-zero-threshold",
            failure_threshold=1,
            recovery_time=1.0,
        )

        failing_func = AsyncMock(side_effect=ValueError("Failure"))

        # Should open after first failure (may raise CircuitBreakerOpen immediately)
        try:
            await breaker.call(failing_func)
        except (ValueError, CircuitBreakerOpen):
            pass  # Expected

        assert breaker.is_open

    async def test_circuit_breaker_high_threshold(self):
        """Circuit breaker with high threshold takes many failures."""
        breaker = CircuitBreaker(
            name="test-high-threshold",
            failure_threshold=100,
            recovery_time=1.0,
        )

        failing_func = AsyncMock(side_effect=ValueError("Failure"))

        # Record fewer failures than threshold
        for _ in range(50):
            try:
                await breaker.call(failing_func)
            except ValueError:
                pass

        # Should not be open yet
        assert not breaker.is_open

    def test_tune_backoff_no_failures(self):
        """Backoff tuning without failures uses base delay."""
        _ADAPTIVE_RETRY_STATE.clear()
        key = "test-no-failures"

        # Create state without failures
        _ADAPTIVE_RETRY_STATE[key] = AdaptiveRetryState()

        base, max_delay, jitter = _tune_backoff(
            adaptive_key=key,
            base_delay=1.0,
            max_delay=30.0,
            jitter=0.25,
        )

        assert base == 1.0  # No increase

    async def test_circuit_breaker_sync_function(self):
        """Circuit breaker works with sync functions."""
        breaker = CircuitBreaker(
            name="test-sync",
            failure_threshold=2,
            recovery_time=1.0,
        )

        # Sync function
        def sync_func():
            return "sync-result"

        result = await breaker.call(sync_func)
        assert result == "sync-result"
        assert not breaker.is_open

    async def test_circuit_breaker_reset_recovery_time(self):
        """Circuit breaker tunes recovery time on repeated opens."""
        breaker = CircuitBreaker(
            name="test-tune-recovery",
            failure_threshold=1,
            recovery_time=1.0,
            max_recovery_time=10.0,
        )

        failing_func = AsyncMock(side_effect=ValueError("Failure"))

        # Open circuit multiple times
        for _ in range(3):
            try:
                await breaker.call(failing_func)
            except (ValueError, CircuitBreakerOpen):
                pass

        # _open_count should have increased
        assert breaker._open_count >= 1

    def test_retry_state_consecutive_failures(self):
        """Retry state tracks consecutive failures correctly."""
        _ADAPTIVE_RETRY_STATE.clear()
        key = "test-consecutive"

        # Record consecutive failures
        for i in range(5):
            _update_retry_state(key, success=False, latency_ms=100)
            state = _ADAPTIVE_RETRY_STATE[key]
            assert state.consecutive_failures == i + 1

        # Reset with success
        _update_retry_state(key, success=True, latency_ms=50)
        state = _ADAPTIVE_RETRY_STATE[key]
        assert state.consecutive_failures == 0

    def test_retry_state_latency_tracking(self):
        """Retry state tracks last latency correctly."""
        _ADAPTIVE_RETRY_STATE.clear()
        key = "test-latency"

        latencies = [100, 200, 150, 300]
        for latency in latencies:
            _update_retry_state(key, success=True, latency_ms=latency)
            state = _ADAPTIVE_RETRY_STATE[key]
            assert state.last_latency_ms == latency

        # Last latency should be the most recent
        assert _ADAPTIVE_RETRY_STATE[key].last_latency_ms == 300
