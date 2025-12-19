"""Redis cache adapter with lifecycle integration."""

from __future__ import annotations

import asyncio
import inspect
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, RedisDsn

try:  # Optional dependency – only required when the Redis adapter is used.
    from coredis import Redis
    from coredis.cache import TrackingCache
    from coredis.exceptions import RedisError

    _COREDIS_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised when extras missing
    Redis = TrackingCache = None  # type: ignore

    class RedisError(Exception):
        """Fallback RedisError when coredis is unavailable."""

    _COREDIS_AVAILABLE = False

if TYPE_CHECKING:  # pragma: no cover
    pass

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.client_mixins import EnsureClientMixin
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class RedisCacheSettings(BaseModel):
    """Settings for the Redis cache adapter."""

    url: RedisDsn | None = Field(
        default=None,
        description="Full Redis connection URL; overrides host/port/db when provided.",
    )
    host: str = Field(
        default="localhost", description="Redis host when url is not set."
    )
    port: int = Field(default=6379, ge=1, le=65535, description="Redis server port.")
    db: int = Field(default=0, ge=0, description="Database index to use.")
    username: str | None = Field(
        default=None, description="Optional username when ACLs are enabled."
    )
    password: str | None = Field(
        default=None, description="Optional password or token."
    )
    ssl: bool = Field(default=False, description="Enable TLS/SSL for the connection.")
    socket_timeout: float = Field(
        default=5.0, gt=0.0, description="Socket timeout in seconds."
    )
    client_name: str = Field(
        default="oneiric",
        description="Name reported to Redis for monitoring + tracking.",
    )
    healthcheck_timeout: float = Field(
        default=2.0,
        gt=0.0,
        description="Timeout used for health checks (PING).",
    )
    decode_responses: bool = Field(
        default=True,
        description="Decode responses as UTF-8 strings instead of returning bytes.",
    )
    key_prefix: str = Field(
        default="", description="Optional prefix applied to every cache key."
    )
    enable_client_cache: bool = Field(
        default=True,
        description="Enable Redis server-assisted client-side caching via coredis TrackingCache.",
    )
    client_cache_max_keys: int | None = Field(
        default=None,
        ge=1,
        description="Override for TrackingCache max tracked keys (defaults to coredis value).",
    )
    client_cache_max_size_bytes: int | None = Field(
        default=None,
        ge=1024,
        description="Override for TrackingCache max size in bytes (defaults to coredis value).",
    )
    client_cache_max_idle_seconds: int | None = Field(
        default=None,
        ge=1,
        description="Override for TrackingCache idle eviction threshold in seconds.",
    )


class RedisCacheAdapter(EnsureClientMixin):
    """Redis cache adapter implementing the lifecycle contract."""

    metadata = AdapterMetadata(
        category="cache",
        provider="redis",
        factory="oneiric.adapters.cache.redis:RedisCacheAdapter",
        capabilities=["kv", "ttl", "distributed"],
        stack_level=10,
        priority=400,
        source=CandidateSource.LOCAL_PKG,
        owner="Platform Core",
        requires_secrets=True,
        settings_model=RedisCacheSettings,
    )

    def __init__(
        self,
        settings: RedisCacheSettings | None = None,
        *,
        redis_client: Redis | None = None,
    ) -> None:
        if not _COREDIS_AVAILABLE:
            raise LifecycleError("coredis-not-installed: pip install oneiric[cache]")
        self._settings = settings or RedisCacheSettings()
        self._client: Redis | None = redis_client
        self._owns_client = redis_client is None
        self._tracking_cache: TrackingCache | None = None
        self._logger = get_logger("adapter.cache.redis").bind(
            domain="adapter",
            key="cache",
            provider="redis",
        )

    async def init(self) -> None:
        if not self._client:
            self._client = self._create_client()
        try:
            await asyncio.wait_for(
                self._client.ping(), timeout=self._settings.healthcheck_timeout
            )
        except RedisError as exc:  # pragma: no cover - defensive log path
            self._logger.error("adapter-init-failed", error=str(exc))
            raise LifecycleError("redis-init-failed") from exc
        self._logger.info("adapter-init", adapter="redis-cache")

    async def health(self) -> bool:
        if not self._client:
            return False
        try:
            await asyncio.wait_for(
                self._client.ping(), timeout=self._settings.healthcheck_timeout
            )
            return True
        except RedisError as exc:
            self._logger.warning("adapter-health-failed", error=str(exc))
            return False

    async def cleanup(self) -> None:
        if not (self._client and self._owns_client):
            self._logger.info("adapter-cleanup-complete", adapter="redis-cache")
            return

        try:
            await self._close_client()
            await self._disconnect_pool()
        finally:
            self._client = None
        self._logger.info("adapter-cleanup-complete", adapter="redis-cache")

    async def _close_client(self) -> None:
        """Close the Redis client connection."""
        if not self._client:
            return

        close = getattr(self._client, "aclose", None)
        if close:
            await close()
            return

        close_sync = getattr(self._client, "close", None)
        if close_sync:
            result = close_sync()
            if inspect.isawaitable(result):
                await result

    async def _disconnect_pool(self) -> None:
        """Disconnect the connection pool."""
        if not self._client:
            return

        pool = getattr(self._client, "connection_pool", None)
        if not pool:
            return

        disconnect = getattr(pool, "disconnect", None)
        if not disconnect:
            return

        result = disconnect()
        if inspect.isawaitable(result):
            await result

    async def get(self, key: str) -> Any:
        client = self._ensure_client("redis-client-not-initialized")
        namespaced = self._namespaced_key(key)
        return await client.get(namespaced)

    async def set(self, key: str, value: Any, *, ttl: float | None = None) -> None:
        client = self._ensure_client("redis-client-not-initialized")
        namespaced = self._namespaced_key(key)
        kwargs: dict[str, Any] = {}
        if ttl is not None:
            if ttl <= 0:
                raise LifecycleError("redis-cache-negative-ttl")
            milliseconds = max(1, int(ttl * 1000))
            kwargs["px"] = milliseconds
        await client.set(namespaced, value, **kwargs)

    async def delete(self, key: str) -> None:
        client = self._ensure_client("redis-client-not-initialized")
        await client.delete(self._namespaced_key(key))

    async def clear(self) -> None:
        client = self._ensure_client("redis-client-not-initialized")
        await client.flushdb()

    def _namespaced_key(self, key: str) -> str:
        return f"{self._settings.key_prefix}{key}" if self._settings.key_prefix else key

    def _create_client(self) -> Redis:
        kwargs: dict[str, Any] = {
            "decode_responses": self._settings.decode_responses,
            "socket_timeout": self._settings.socket_timeout,
            "client_name": self._settings.client_name,
        }
        if self._settings.enable_client_cache:
            cache_kwargs: dict[str, Any] = {}
            if self._settings.client_cache_max_keys is not None:
                cache_kwargs["max_keys"] = self._settings.client_cache_max_keys
            if self._settings.client_cache_max_size_bytes is not None:
                cache_kwargs["max_size_bytes"] = (
                    self._settings.client_cache_max_size_bytes
                )
            if self._settings.client_cache_max_idle_seconds is not None:
                cache_kwargs["max_idle_seconds"] = (
                    self._settings.client_cache_max_idle_seconds
                )
            self._tracking_cache = TrackingCache(**cache_kwargs)
            kwargs["cache"] = self._tracking_cache
        if self._settings.username:
            kwargs["username"] = self._settings.username
        if self._settings.password:
            kwargs["password"] = self._settings.password
        if self._settings.ssl:
            kwargs["ssl"] = True
        if self._settings.url:
            return Redis.from_url(str(self._settings.url), **kwargs)
        return Redis(
            host=self._settings.host,
            port=self._settings.port,
            db=self._settings.db,
            **kwargs,
        )
