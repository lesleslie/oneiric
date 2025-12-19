"""Shared helpers for storage adapters."""

from __future__ import annotations

from collections.abc import Iterable


def is_not_found_error(
    exc: Exception,
    *,
    codes: Iterable[int | str] = (),
    messages: Iterable[str] = (),
) -> bool:
    code = getattr(exc, "code", None)
    if code is not None and code in set(codes):
        return True
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        error = response.get("Error")
        if isinstance(error, dict):
            response_code = error.get("Code")
            if response_code in set(codes):
                return True
    message = getattr(exc, "args", [None])[0]
    if isinstance(message, str):
        for token in messages:
            if token in message:
                return True
    return False
