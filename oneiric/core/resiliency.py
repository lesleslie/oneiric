"""Resiliency helpers (circuit breaker + retry utilities)."""

from __future__ import annotations

import asyncio
import inspect
import random
import time
from typing import Awaitable, Callable, Optional, TypeVar

T = TypeVar("T")


class CircuitBreakerOpen(Exception):
    """Raised when the circuit breaker prevents new calls."""

    def __init__(self, name: str, retry_after: float) -> None:
        self.name = name
        self.retry_after = max(retry_after, 0.0)
        message = f"circuit '{name}' open; retry after {self.retry_after:.2f}s"
        super().__init__(message)


class CircuitBreaker:
    """Simple async-aware circuit breaker."""

    def __init__(
        self,
        *,
        name: str,
        failure_threshold: int = 5,
        recovery_time: float = 60.0,
    ) -> None:
        self.name = name
        self.failure_threshold = max(failure_threshold, 1)
        self.recovery_time = max(recovery_time, 1.0)
        self._failures = 0
        self._opened_at: Optional[float] = None
        self._lock = asyncio.Lock()

    async def call(self, func: Callable[[], Awaitable[T] | T]) -> T:
        await self._ensure_available()
        try:
            result = func()
            if inspect.isawaitable(result):
                result = await result  # type: ignore[assignment]
        except Exception:
            await self._record_failure()
            raise
        await self._record_success()
        return result

    async def _ensure_available(self) -> None:
        async with self._lock:
            if self._opened_at is None:
                return
            elapsed = time.monotonic() - self._opened_at
            if elapsed >= self.recovery_time:
                self._opened_at = None
                self._failures = 0
                return
            raise CircuitBreakerOpen(self.name, retry_after=self.recovery_time - elapsed)

    async def _record_failure(self) -> None:
        async with self._lock:
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._opened_at = time.monotonic()

    async def _record_success(self) -> None:
        async with self._lock:
            self._failures = 0
            self._opened_at = None

    @property
    def is_open(self) -> bool:
        return self._opened_at is not None


async def run_with_retry(
    operation: Callable[[], Awaitable[T] | T],
    *,
    attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    jitter: float = 0.25,
) -> T:
    """Execute operation with exponential backoff + jitter."""

    delay = max(base_delay, 0.0)
    max_delay = max(max_delay, delay or 0.1)
    last_error: Optional[Exception] = None
    for attempt in range(1, max(attempts, 1) + 1):
        try:
            result = operation()
            if inspect.isawaitable(result):
                result = await result  # type: ignore[assignment]
            return result
        except Exception as exc:  # pragma: no cover - exercised via callers
            last_error = exc
            if attempt >= attempts:
                raise
            sleep_for = min(max_delay, delay * (2 ** (attempt - 1)))
            jitter_offset = random.uniform(0, jitter) if jitter else 0.0
            await asyncio.sleep(sleep_for + jitter_offset)
    assert last_error is not None  # pragma: no cover - guarded above
    raise last_error
