"""Internal security utilities for the LLM module."""

from __future__ import annotations

import re

_SECRET_PATTERNS = [
    re.compile(
        r"sk-[a-zA-Z0-9\-]{20,}"
    ),  # Anthropic / OpenAI sk- keys (may contain hyphens)
    re.compile(
        r"eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}"
    ),  # JWT / MiniMax Token Plan keys
    re.compile(r"Bearer [a-zA-Z0-9\-._~+/]{20,}"),  # Bearer header values
    re.compile(r'["\'][\w\-]{32,}["\']'),  # quoted long secrets
]


def sanitize_error(msg: str) -> str:
    """Strip secrets from error messages before logging."""
    for pattern in _SECRET_PATTERNS:
        msg = pattern.sub("<redacted>", msg)
    return msg
