"""In-memory cache adapter with lifecycle hooks."""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Any

from pydantic import BaseModel, Field

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class MemoryCacheSettings(BaseModel):
    """Provider settings for the memory cache adapter."""

    default_ttl: float | None = Field(
        default=None,
        ge=0.0,
        description="Optional default TTL (seconds) applied when set() receives no ttl value.",
    )
    max_entries: int | None = Field(
        default=None,
        ge=1,
        description="Optional cap on stored entries; oldest entries are evicted when exceeded.",
    )


class MemoryCacheAdapter:
    """Async-friendly in-memory cache with optional TTL and max entry count."""

    metadata = AdapterMetadata(
        category="cache",
        provider="memory",
        factory="oneiric.adapters.cache.memory:MemoryCacheAdapter",
        capabilities=["kv", "ttl"],
        stack_level=5,
        priority=100,
        source=CandidateSource.LOCAL_PKG,
        owner="Platform Core",
        requires_secrets=False,
        settings_model=MemoryCacheSettings,
    )

    def __init__(self, settings: MemoryCacheSettings | None = None) -> None:
        self._settings = settings or MemoryCacheSettings()
        self._store: OrderedDict[str, tuple[Any, float | None]] = OrderedDict()
        self._lock = asyncio.Lock()
        self._logger = get_logger("adapter.cache.memory").bind(
            domain="adapter",
            key="cache",
            provider="memory",
        )

    async def init(self) -> None:
        self._logger.info("adapter-init", adapter="memory-cache")

    async def health(self) -> bool:
        return True

    async def cleanup(self) -> None:
        async with self._lock:
            self._store.clear()
        self._logger.info("adapter-cleanup-complete", adapter="memory-cache")

    async def get(self, key: str) -> Any:
        async with self._lock:
            self._purge_expired_locked()
            value = self._store.get(key)
            return None if value is None else value[0]

    async def set(self, key: str, value: Any, *, ttl: float | None = None) -> None:
        expiry = self._expiry_from_ttl(ttl)
        async with self._lock:
            self._purge_expired_locked()
            self._store[key] = (value, expiry)
            self._store.move_to_end(key)
            self._enforce_capacity_locked()

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._store.pop(key, None)

    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()

    def _expiry_from_ttl(self, ttl: float | None) -> float | None:
        target_ttl = ttl if ttl is not None else self._settings.default_ttl
        if target_ttl is None:
            return None
        if target_ttl < 0:
            raise LifecycleError("negative-ttl-not-allowed")
        return time.monotonic() + target_ttl

    def _purge_expired_locked(self) -> None:
        if not self._store:
            return
        now = time.monotonic()
        expired = [
            key
            for key, (_, expiry) in self._store.items()
            if expiry is not None and expiry <= now
        ]
        for key in expired:
            self._store.pop(key, None)

    def _enforce_capacity_locked(self) -> None:
        max_entries = self._settings.max_entries
        if max_entries is None:
            return
        while len(self._store) > max_entries:
            self._store.popitem(last=False)
