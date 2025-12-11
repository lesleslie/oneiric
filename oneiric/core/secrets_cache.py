"""Utility cache for secret lookups."""

from __future__ import annotations

import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass
class _CacheEntry:
    value: str | None
    expires_at: float


class SecretValueCache:
    """Time-bounded cache for secret values."""

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = max(ttl_seconds, 0.0)
        self._enabled = self._ttl > 0
        self._entries: dict[tuple[str, str], _CacheEntry] = {}
        self._lock = threading.Lock()

    def get(self, provider: str, secret_id: str) -> tuple[bool, str | None]:
        if not self._enabled:
            return False, None
        key = (provider, secret_id)
        with self._lock:
            entry = self._entries.get(key)
            if not entry:
                return False, None
            if entry.expires_at < time.monotonic():
                del self._entries[key]
                return False, None
            return True, entry.value

    def set(self, provider: str, secret_id: str, value: str | None) -> None:
        if not self._enabled:
            return
        key = (provider, secret_id)
        expires_at = time.monotonic() + self._ttl
        with self._lock:
            self._entries[key] = _CacheEntry(value=value, expires_at=expires_at)

    def invalidate(
        self, keys: Sequence[str] | None = None, provider: str | None = None
    ) -> int:
        with self._lock:
            if not keys:
                return self._invalidate_all(provider)
            return self._invalidate_specific_keys(keys, provider)

    def _invalidate_all(self, provider: str | None) -> int:
        """Invalidate all entries or all entries for a specific provider."""
        if provider is None:
            count = len(self._entries)
            self._entries.clear()
            return count

        removed = 0
        for cache_key in list(self._entries):
            if cache_key[0] == provider:
                del self._entries[cache_key]
                removed += 1
        return removed

    def _invalidate_specific_keys(
        self, keys: Sequence[str], provider: str | None
    ) -> int:
        """Invalidate specific keys, optionally filtered by provider."""
        target_ids = set(keys)
        removed = 0

        for cache_key in list(self._entries):
            if self._should_invalidate_key(cache_key, target_ids, provider):
                del self._entries[cache_key]
                removed += 1

        return removed

    def _should_invalidate_key(
        self,
        cache_key: tuple[str, str],
        target_ids: set[str],
        provider: str | None,
    ) -> bool:
        """Check if a cache key should be invalidated."""
        provider_match = provider is None or cache_key[0] == provider
        return provider_match and cache_key[1] in target_ids
