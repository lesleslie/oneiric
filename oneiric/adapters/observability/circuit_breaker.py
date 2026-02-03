from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any


class CircuitBreakerOpenError(Exception):
    pass


class CircuitBreaker:
    CLOSED: str = "CLOSED"
    HALF_OPEN: str = "HALF_OPEN"
    OPEN: str = "OPEN"

    def __init__(self, failure_threshold: int = 5, timeout_seconds: int = 60) -> None:
        self.state = self.CLOSED
        self.failure_count = 0
        self.last_failure_time: float | None = None
        self._threshold = failure_threshold
        self._timeout = timeout_seconds

    async def call(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        if self.state == self.OPEN:
            if self._should_attempt_reset():
                self.state = self.HALF_OPEN
            else:
                raise CircuitBreakerOpenError(
                    f"Circuit breaker is OPEN ({self._timeout - (time.time() - (self.last_failure_time or 0)):.0f}s until HALF_OPEN)"
                )

        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except Exception:
            self._on_failure()
            raise

    def _should_attempt_reset(self) -> bool:
        return (
            self.last_failure_time is not None
            and time.time() - self.last_failure_time >= self._timeout
        )

    def _on_success(self) -> None:
        if self.state == self.HALF_OPEN:
            self.state = self.CLOSED
        self.failure_count = 0

    def _on_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self._threshold:
            self.state = self.OPEN
