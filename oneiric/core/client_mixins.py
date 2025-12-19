"""Reusable client lifecycle helpers."""

from __future__ import annotations

from typing import Any

from oneiric.core.lifecycle import LifecycleError


class EnsureClientMixin:
    """Provide a shared _ensure_client helper."""

    def _ensure_client(self, error_code: str) -> Any:
        client = getattr(self, "_client", None)
        if not client:
            raise LifecycleError(error_code)
        return client
