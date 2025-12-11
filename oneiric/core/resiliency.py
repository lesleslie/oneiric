"""Resiliency helpers backed by aiobreaker and tenacity."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
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

T = TypeVar("T")


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
    ) -> None:
        self.name = name
        self._breaker = _AioCircuitBreaker(
            fail_max=max(failure_threshold, 1),
            timeout_duration=timedelta(seconds=max(recovery_time, 0.1)),
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
            raise CircuitBreakerOpen(self.name, retry_seconds) from exc

    @property
    def is_open(self) -> bool:
        return self._breaker.current_state.name == "OPEN"


async def run_with_retry(
    operation: Callable[[], Awaitable[T] | T],
    *,
    attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    jitter: float = 0.25,
) -> T:
    """Execute an operation with exponential backoff + jitter via tenacity."""

    attempts = max(attempts, 1)
    initial_delay = max(base_delay, 0.0) or 0.1
    max_delay = max(max_delay, initial_delay)
    wait = wait_exponential_jitter(initial=initial_delay, max=max_delay, jitter=jitter)

    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(attempts),
        wait=wait,
        retry=retry_if_exception_type(Exception),
        reraise=True,
    ):
        with attempt:
            result = operation()
            if inspect.isawaitable(result):
                result = await result  # type: ignore[assignment]
            return result

    raise RuntimeError("unreachable")  # pragma: no cover - satisfied by AsyncRetrying
