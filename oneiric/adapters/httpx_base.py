"""Shared httpx client helpers for adapters."""

from __future__ import annotations

from collections.abc import Callable

import httpx

from oneiric.core.lifecycle import LifecycleError


class HTTPXClientMixin:
    """Mixin that manages httpx.AsyncClient lifecycle."""

    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self._owns_client = client is None

    def _ensure_client(self, error_code: str) -> httpx.AsyncClient:
        if not self._client:
            raise LifecycleError(error_code)
        return self._client

    def _init_client(self, factory: Callable[[], httpx.AsyncClient]) -> None:
        if self._client is None:
            self._client = factory()
            self._owns_client = True

    async def _cleanup_client(self) -> None:
        if self._client and self._owns_client:
            await self._client.aclose()
        self._client = None
