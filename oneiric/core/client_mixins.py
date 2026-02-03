from __future__ import annotations

from typing import Any

from oneiric.core.lifecycle import LifecycleError


class EnsureClientMixin:
    def _ensure_client(self, error_code: str) -> Any:
        client = getattr(self, "_client", None)
        if not client:
            raise LifecycleError(error_code)
        return client
