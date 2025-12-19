"""Resiliency helpers backed by aiobreaker and tenacity."""

from __future__ import annotations

import inspect
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import TypeVar

from aiobreaker import CircuitBreaker as _AioCircuitBreaker
from aiobreaker import CircuitBreakerError as _AioCircuitBreakerError
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from .resiliency_metrics import (
    record_circuit_open,
    record_retry_attempt,
    record_retry_exhausted,
    record_retry_success,
)

T = TypeVar("T")


@dataclass
class AdaptiveRetryState:
    consecutive_failures: int = 0
    success_count: int = 0
    failure_count: int = 0
    last_latency_ms: float | None = None


_ADAPTIVE_RETRY_STATE: dict[str, AdaptiveRetryState] = {}


class CircuitBreakerOpen(Exception):
    """Raised when the circuit breaker prevents new calls."""

    def __init__(self, name: str, retry_after: float) -> None:
        self.name = name
        self.retry_after = max(retry_after, 0.0)
        message = f"circuit '{name}' open; retry after {self.retry_after:.2f}s"
        super().__init__(message)


class CircuitBreaker:
    """Thin wrapper around :mod:`aiobreaker` with Oneiric semantics."""

    def __init__(
        self,
        *,
        name: str,
        failure_threshold: int = 5,
        recovery_time: float = 60.0,
        adaptive_key: str | None = None,
        max_recovery_time: float | None = None,
    ) -> None:
        self.name = name
        self._adaptive_key = adaptive_key or name
        self._base_recovery = max(recovery_time, 0.1)
        self._max_recovery = max_recovery_time or (self._base_recovery * 5)
        self._open_count = 0
        self._breaker = _AioCircuitBreaker(
            fail_max=max(failure_threshold, 1),
            timeout_duration=timedelta(seconds=self._base_recovery),
            name=name,
        )

    async def call(self, func: Callable[[], Awaitable[T] | T]) -> T:
        async def _execute() -> T:
            result = func()
            if inspect.isawaitable(result):
                return await result  # type: ignore[return-value]
            return result  # type: ignore[return-value]

        try:
            return await self._breaker.call_async(_execute)
        except (
            _AioCircuitBreakerError
        ) as exc:  # pragma: no cover - exercised in runtime tests
            retry_after = getattr(exc, "time_remaining", None)
            retry_seconds = retry_after.total_seconds() if retry_after else 0.0
            self._open_count += 1
            self._tune_recovery_window()
            record_circuit_open(
                {"circuit": self.name, "adaptive_key": self._adaptive_key},
                retry_seconds,
            )
            raise CircuitBreakerOpen(self.name, retry_seconds) from exc

    @property
    def is_open(self) -> bool:
        return self._breaker.current_state.name == "OPEN"

    def _tune_recovery_window(self) -> None:
        multiplier = 1 + min(self._open_count, 5) * 0.25
        new_recovery = min(self._base_recovery * multiplier, self._max_recovery)
        try:
            setattr(self._breaker, "timeout_duration", timedelta(seconds=new_recovery))
        except Exception:
            return


async def run_with_retry(
    operation: Callable[[], Awaitable[T] | T],
    *,
    attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    jitter: float = 0.25,
    adaptive_key: str | None = None,
    attributes: dict[str, str] | None = None,
) -> T:
    """Execute an operation with exponential backoff + jitter via tenacity."""

    attempts = max(attempts, 1)
    tuned_base, tuned_max, tuned_jitter = _tune_backoff(
        adaptive_key, base_delay, max_delay, jitter
    )
    initial_delay = max(tuned_base, 0.0) or 0.1
    max_delay = max(tuned_max, initial_delay)
    wait = wait_exponential_jitter(
        initial=initial_delay, max=max_delay, jitter=tuned_jitter
    )
    attrs = attributes or {}
    attempts_used = 0

    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(attempts),
            wait=wait,
            retry=retry_if_exception_type(Exception),
            reraise=True,
        ):
            with attempt:
                attempts_used += 1
                started = time.perf_counter()
                try:
                    result = operation()
                    if inspect.isawaitable(result):
                        result = await result  # type: ignore[assignment]
                except Exception:
                    latency_ms = (time.perf_counter() - started) * 1000.0
                    _update_retry_state(
                        adaptive_key, success=False, latency_ms=latency_ms
                    )
                    record_retry_attempt(attrs)
                    raise
                latency_ms = (time.perf_counter() - started) * 1000.0
                _update_retry_state(adaptive_key, success=True, latency_ms=latency_ms)
                record_retry_success(attrs, attempts_used)
                return result
    except Exception:
        record_retry_exhausted(attrs)
        raise

    raise RuntimeError("unreachable")  # pragma: no cover - satisfied by AsyncRetrying


def _tune_backoff(
    adaptive_key: str | None,
    base_delay: float,
    max_delay: float,
    jitter: float,
) -> tuple[float, float, float]:
    if not adaptive_key:
        return base_delay, max_delay, jitter
    state = _ADAPTIVE_RETRY_STATE.setdefault(adaptive_key, AdaptiveRetryState())
    factor = 1.0 + min(state.consecutive_failures, 5) * 0.2
    if state.last_latency_ms and state.last_latency_ms > 1000:
        factor += min(state.last_latency_ms / 5000.0, 0.5)
    tuned_base = base_delay * factor
    tuned_max = max(max_delay, tuned_base)
    tuned_jitter = min(max(jitter, 0.05), 0.5)
    return tuned_base, tuned_max, tuned_jitter


def _update_retry_state(
    adaptive_key: str | None, *, success: bool, latency_ms: float
) -> None:
    if not adaptive_key:
        return
    state = _ADAPTIVE_RETRY_STATE.setdefault(adaptive_key, AdaptiveRetryState())
    state.last_latency_ms = latency_ms
    if success:
        state.success_count += 1
        state.consecutive_failures = 0
    else:
        state.failure_count += 1
        state.consecutive_failures += 1
