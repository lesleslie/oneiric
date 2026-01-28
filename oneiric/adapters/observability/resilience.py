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
