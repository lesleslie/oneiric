"""Multi-tier cache adapter with L1 (memory) and L2 (Redis) layers.

This adapter implements a two-tier caching strategy:
- L1: In-memory LRU cache for fast access (~10ms)
- L2: Distributed Redis cache for persistence and sharing (~50ms)

Cache flow:
1. Check L1 first (fastest)
2. On L1 miss, check L2
3. On L2 hit, populate L1 for future access
4. Write-through to both tiers

Target metrics:
- Combined hit rate: 85%+
- L1 latency: ~10ms
- L2 latency: ~50ms
- Overall latency reduction: 60-80% vs. uncached
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, RedisDsn

try:
    from coredis import Redis
    from coredis.cache import TrackingCache
    from coredis.exceptions import RedisError

    _COREDIS_AVAILABLE = True
except ImportError:  # pragma: no cover
    Redis = TrackingCache = None  # type: ignore
    class RedisError(Exception):
        pass
    _COREDIS_AVAILABLE = False

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.adapters.cache.memory import MemoryCacheAdapter, MemoryCacheSettings
from oneiric.adapters.cache.redis import RedisCacheAdapter, RedisCacheSettings
from oneiric.core.client_mixins import EnsureClientMixin
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


@dataclass
class CacheMetrics:
    """Metrics for cache performance tracking."""

    l1_hits: int = 0
    l1_misses: int = 0
    l2_hits: int = 0
    l2_misses: int = 0
    l1_latency_ms: float = 0.0
    l2_latency_ms: float = 0.0
    total_requests: int = 0

    @property
    def l1_hit_rate(self) -> float:
        """Calculate L1 cache hit rate."""
        total = self.l1_hits + self.l1_misses
        return (self.l1_hits / total * 100) if total > 0 else 0.0

    @property
    def l2_hit_rate(self) -> float:
        """Calculate L2 cache hit rate."""
        total = self.l2_hits + self.l2_misses
        return (self.l2_hits / total * 100) if total > 0 else 0.0

    @property
    def combined_hit_rate(self) -> float:
        """Calculate combined cache hit rate."""
        if self.total_requests == 0:
            return 0.0
        hits = self.l1_hits + self.l2_hits
        return (hits / self.total_requests * 100)

    @property
    def avg_latency_ms(self) -> float:
        """Calculate average latency in milliseconds."""
        total_latency = self.l1_latency_ms + self.l2_latency_ms
        total_ops = self.l1_hits + self.l1_misses + self.l2_hits + self.l2_misses
        return (total_latency / total_ops) if total_ops > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert metrics to dictionary."""
        return {
            "l1_hit_rate": f"{self.l1_hit_rate:.1f}%",
            "l2_hit_rate": f"{self.l2_hit_rate:.1f}%",
            "combined_hit_rate": f"{self.combined_hit_rate:.1f}%",
            "avg_latency_ms": f"{self.avg_latency_ms:.2f}",
            "total_requests": self.total_requests,
            "l1_hits": self.l1_hits,
            "l1_misses": self.l1_misses,
            "l2_hits": self.l2_hits,
            "l2_misses": self.l2_misses,
        }


class MultiTierCacheSettings(BaseModel):
    """Settings for multi-tier cache adapter."""

    # L1 (Memory) Cache Settings
    l1_enabled: bool = Field(
        default=True,
        description="Enable L1 in-memory cache layer.",
    )
    l1_max_entries: int = Field(
        default=1000,
        ge=1,
        le=10000,
        description="Maximum entries in L1 cache (LRU eviction).",
    )
    l1_ttl_seconds: float = Field(
        default=600,  # 10 minutes
        ge=1,
        description="Default TTL for L1 cache entries in seconds.",
    )

    # L2 (Redis) Cache Settings
    l2_enabled: bool = Field(
        default=True,
        description="Enable L2 Redis cache layer.",
    )
    l2_url: RedisDsn | None = Field(
        default=None,
        description="Full Redis connection URL for L2 cache.",
    )
    l2_host: str = Field(
        default="localhost",
        description="Redis host when url is not set.",
    )
    l2_port: int = Field(
        default=6379,
        ge=1,
        le=65535,
        description="Redis server port.",
    )
    l2_db: int = Field(
        default=1,  # Use DB 1 to avoid conflicts with other Redis uses
        ge=0,
        description="Redis database index for L2 cache.",
    )
    l2_ttl_seconds: float = Field(
        default=86400,  # 24 hours
        ge=1,
        description="Default TTL for L2 cache entries in seconds.",
    )
    l2_password: str | None = Field(
        default=None,
        description="Optional Redis password.",
    )
    l2_ssl: bool = Field(
        default=False,
        description="Enable TLS/SSL for Redis connection.",
    )

    # Cache Strategy
    write_through: bool = Field(
        default=True,
        description="Write to both L1 and L2 on cache set (recommended).",
    )
    write_back_l1_on_l2_hit: bool = Field(
        default=True,
        description="Populate L1 cache on L2 hit (recommended).",
    )

    # Metrics
    enable_metrics: bool = Field(
        default=True,
        description="Enable cache performance metrics tracking.",
    )


class MultiTierCacheAdapter:
    """Multi-tier cache adapter with L1 (memory) and L2 (Redis) layers.

    Provides high-performance caching with automatic tier management:
    - L1 (Memory): Fast access, limited capacity, short TTL
    - L2 (Redis): Distributed, large capacity, long TTL

    Example:
        ```python
        from oneiric.adapters.cache.multitier import MultiTierCacheAdapter

        cache = MultiTierCacheAdapter()
        await cache.init()

        # Set value (writes to both L1 and L2)
        await cache.set("user:123", {"name": "Alice"})

        # Get value (checks L1 first, then L2)
        user = await cache.get("user:123")

        # Get metrics
        metrics = await cache.get_metrics()
        print(metrics["combined_hit_rate"])  # e.g., "85.2%"
        ```
    """

    metadata = AdapterMetadata(
        category="cache",
        provider="multitier",
        factory="oneiric.adapters.cache.multitier:MultiTierCacheAdapter",
        capabilities=["kv", "ttl", "distributed", "lru", "metrics"],
        stack_level=15,  # Higher than individual cache adapters
        priority=500,   # Highest priority cache adapter
        source=CandidateSource.LOCAL_PKG,
        owner="Platform Core",
        requires_secrets=True,
        settings_model=MultiTierCacheSettings,
    )

    def __init__(
        self,
        settings: MultiTierCacheSettings | None = None,
        *,
        l1_cache: MemoryCacheAdapter | None = None,
        l2_cache: RedisCacheAdapter | None = None,
    ) -> None:
        """Initialize multi-tier cache adapter.

        Args:
            settings: Cache configuration settings
            l1_cache: Optional custom L1 cache instance
            l2_cache: Optional custom L2 cache instance
        """
        self._settings = settings or MultiTierCacheSettings()
        self._metrics = CacheMetrics()
        self._lock = asyncio.Lock()
        self._logger = get_logger("adapter.cache.multitier").bind(
            domain="adapter",
            key="cache",
            provider="multitier",
        )

        # Initialize L1 cache (memory)
        if self._settings.l1_enabled and l1_cache is None:
            l1_settings = MemoryCacheSettings(
                max_entries=self._settings.l1_max_entries,
                default_ttl=self._settings.l1_ttl_seconds,
            )
            l1_cache = MemoryCacheAdapter(settings=l1_settings)

        self._l1 = l1_cache

        # Initialize L2 cache (Redis)
        if self._settings.l2_enabled and l2_cache is None and _COREDIS_AVAILABLE:
            l2_settings = RedisCacheSettings(
                host=self._settings.l2_host,
                port=self._settings.l2_port,
                db=self._settings.l2_db,
                password=self._settings.l2_password,
                ssl=self._settings.l2_ssl,
                key_prefix="l2:",  # Prefix to distinguish L2 keys
                enable_client_cache=True,
            )
            if self._settings.l2_url:
                l2_settings = RedisCacheSettings(url=self._settings.l2_url)
            l2_cache = RedisCacheAdapter(settings=l2_settings)

        self._l2 = l2_cache

    async def init(self) -> None:
        """Initialize cache layers."""
        if self._l1:
            await self._l1.init()
        if self._l2:
            await self._l2.init()
        self._logger.info(
            "adapter-init",
            adapter="multitier-cache",
            l1_enabled=self._settings.l1_enabled,
            l2_enabled=self._settings.l2_enabled,
        )

    async def health(self) -> bool:
        """Check health of cache layers.

        Returns True if at least one layer is healthy.
        """
        l1_healthy = bool(self._l1) and await self._l1.health()
        l2_healthy = bool(self._l2) and await self._l2.health()
        return l1_healthy or l2_healthy

    async def cleanup(self) -> None:
        """Cleanup cache layers."""
        if self._l1:
            await self._l1.cleanup()
        if self._l2:
            await self._l2.cleanup()
        self._logger.info("adapter-cleanup-complete", adapter="multitier-cache")

    async def get(self, key: str) -> Any:
        """Get value from cache, checking L1 first, then L2.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found
        """
        if self._settings.enable_metrics:
            self._metrics.total_requests += 1

        # Try L1 first (fastest)
        if self._l1:
            start = time.monotonic()
            value = await self._l1.get(key)
            l1_latency = (time.monotonic() - start) * 1000

            if value is not None:
                if self._settings.enable_metrics:
                    self._metrics.l1_hits += 1
                    self._metrics.l1_latency_ms += l1_latency
                self._logger.debug("l1-cache-hit", key=key, latency_ms=f"{l1_latency:.2f}")
                return value
            else:
                if self._settings.enable_metrics:
                    self._metrics.l1_misses += 1
                    self._metrics.l1_latency_ms += l1_latency

        # Try L2 (slower but distributed)
        if self._l2:
            start = time.monotonic()
            value = await self._l2.get(key)
            l2_latency = (time.monotonic() - start) * 1000

            if value is not None:
                if self._settings.enable_metrics:
                    self._metrics.l2_hits += 1
                    self._metrics.l2_latency_ms += l2_latency

                self._logger.debug("l2-cache-hit", key=key, latency_ms=f"{l2_latency:.2f}")

                # Write back to L1 for future access
                if self._settings.write_back_l1_on_l2_hit and self._l1:
                    await self._l1.set(key, value, ttl=self._settings.l1_ttl_seconds)

                return value
            else:
                if self._settings.enable_metrics:
                    self._metrics.l2_misses += 1
                    self._metrics.l2_latency_ms += l2_latency

        self._logger.debug("cache-miss", key=key)
        return None

    async def set(self, key: str, value: Any, *, ttl: float | None = None) -> None:
        """Set value in cache, writing to both L1 and L2.

        Args:
            key: Cache key
            value: Value to cache
            ttl: Optional TTL in seconds (defaults to layer-specific TTLs)
        """
        l1_ttl = ttl or self._settings.l1_ttl_seconds
        l2_ttl = ttl or self._settings.l2_ttl_seconds

        # Write to L1
        if self._l1:
            await self._l1.set(key, value, ttl=l1_ttl)

        # Write to L2 (write-through)
        if self._l2 and self._settings.write_through:
            await self._l2.set(key, value, ttl=l2_ttl)

        self._logger.debug("cache-set", key=key, l1_ttl=l1_ttl, l2_ttl=l2_ttl)

    async def delete(self, key: str) -> None:
        """Delete value from both cache layers.

        Args:
            key: Cache key to delete
        """
        if self._l1:
            await self._l1.delete(key)
        if self._l2:
            await self._l2.delete(key)
        self._logger.debug("cache-delete", key=key)

    async def clear(self) -> None:
        """Clear all cache layers."""
        if self._l1:
            await self._l1.clear()
        if self._l2:
            await self._l2.clear()
        self._logger.info("cache-cleared")

    def invalidate_l1(self) -> None:
        """Invalidate L1 cache (forcing L2 lookups).

        Useful when L2 data has been updated externally.
        """
        if self._l1:
            # Clear L1 by reinitializing
            l1_settings = MemoryCacheSettings(
                max_entries=self._settings.l1_max_entries,
                default_ttl=self._settings.l1_ttl_seconds,
            )
            self._l1 = MemoryCacheAdapter(settings=l1_settings)
        self._logger.info("l1-cache-invalidated")

    async def get_metrics(self) -> dict[str, Any]:
        """Get cache performance metrics.

        Returns:
            Dictionary with hit rates, latency, and request counts
        """
        if not self._settings.enable_metrics:
            return {"error": "metrics_disabled"}

        return self._metrics.to_dict()

    async def reset_metrics(self) -> None:
        """Reset all performance metrics."""
        self._metrics = CacheMetrics()
        self._logger.info("metrics-reset")

    def get_settings(self) -> MultiTierCacheSettings:
        """Get current cache settings.

        Returns:
            Current settings instance
        """
        return self._settings
