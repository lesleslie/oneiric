from __future__ import annotations

import asyncio
from collections.abc import Callable
from functools import wraps


def with_retry(max_attempts: int = 3):
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
                        delay = min(0.1 * (2**attempt), 1.0)
                        await asyncio.sleep(delay)

            raise last_exception

        return wrapper

    return decorator
