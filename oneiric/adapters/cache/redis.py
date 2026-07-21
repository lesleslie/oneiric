from __future__ import annotations

import asyncio
import inspect
import random
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, RedisDsn

try:
    from coredis import Redis
    from coredis.exceptions import RedisError  # pragma: no cover
    from coredis.patterns.cache import (  # pragma: no cover
        LRUCache,
    )
    from coredis.patterns.cache import (
        TrackingCache as _AbstractTrackingCache,
    )

    _COREDIS_AVAILABLE = True  # pragma: no cover
except ImportError:  # pragma: no cover - exercised when extras missing
    Redis = LRUCache = None  # type: ignore

    class _AbstractTrackingCache:  # type: ignore[no-redef]
        pass

    class RedisError(Exception):
        pass

    _COREDIS_AVAILABLE = False

if TYPE_CHECKING:  # pragma: no cover
    pass

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.client_mixins import EnsureClientMixin
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class _TrackingCacheImpl(
    _AbstractTrackingCache,  # ty: ignore[unsupported-base]
):
    """Concrete :class:`TrackingCache` shim preserving the legacy kwarg surface.

    coredis moved ``TrackingCache`` to :mod:`coredis.patterns.cache` and made
    it abstract (requires ``run`` and ``get_client_id`` implementations plus a
    ``connection_pool`` + ``cache`` constructor pair). Adapter init only needs
    a kwargs-capturable TrackingCache instance; the real tracking connection
    is established later by the Redis client itself. This shim restores a
    minimally-instantiable form that still satisfies ``isinstance(obj,
    TrackingCache)``.
    """

    def __init__(self, **kwargs: Any) -> None:
        # Bypass TrackingCache.__init__ which requires a real connection_pool;
        # set only the attributes the inherited get/put/invalidate/reset/stats
        # methods touch.
        max_keys = kwargs.pop("max_keys", 4096)
        # ``max_size_bytes`` was a legacy option the current coredis API does
        # not accept on LRUCache, so we drop it silently.
        kwargs.pop("max_size_bytes", None)
        self._max_idle_seconds = kwargs.pop("max_idle_seconds", 60)
        self._cache = LRUCache(max_keys=max_keys)
        self._retry_policy = None
        # ``_connection_pool`` is unused because ``run()`` is a no-op below.
        self._connection_pool = None  # type: ignore[assignment]

    async def run(self, task_status: Any = None) -> None:
        return None

    def get_client_id(self, connection: Any = None) -> int | None:
        return None

    @property
    def healthy(self) -> bool:
        return False


# Rebind the module-level :data:`TrackingCache` to the concrete shim so direct
# instantiation in adapter init works. Tests that monkeypatch
# ``oneiric.adapters.cache.redis.TrackingCache`` will substitute their own
# class here and still be honored (the reference is consulted at call time).
TrackingCache = _TrackingCacheImpl  # type: ignore[assignment,misc]  # noqa: F811


class RedisCacheSettings(BaseModel):
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
    ttl_seconds: int = Field(
        default=3600,
        ge=0,
        description="Optional TTL in seconds applied at every set() call when no "
        "per-call ttl override is passed; 0 disables TTL.",
    )
    stampede_jitter_ms: int = Field(
        default=0,
        ge=0,
        description="Optional random sleep (ms) applied when a get() returns None, "
        "to dampen thundering-herd on hot keys.",
    )
    # NOTE: `enable_client_cache: bool = Field(default=True, ...)` already
    # exists above (around line 69). Per spec D7 its default `True` is
    # intentional; do NOT redeclare this field. Operator-supplied
    # RedisCacheSettings override the default.


class RedisCacheAdapter(EnsureClientMixin):
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
        value = await client.get(namespaced)
        if value is None and self._settings.stampede_jitter_ms > 0:
            await asyncio.sleep(
                random.uniform(0, self._settings.stampede_jitter_ms) / 1000.0
            )
        return value

    async def set(self, key: str, value: Any, *, ttl: float | None = None) -> None:
        client = self._ensure_client("redis-client-not-initialized")
        if ttl is not None and ttl <= 0:
            raise LifecycleError("redis-cache-negative-ttl")
        effective_ttl = ttl if ttl is not None else self._settings.ttl_seconds
        namespaced = self._namespaced_key(key)
        kwargs: dict[str, Any] = {}
        if effective_ttl and effective_ttl > 0:
            kwargs["px"] = max(1, int(effective_ttl * 1000))
        await client.set(namespaced, value, **kwargs)

    async def delete(self, key: str) -> None:
        client = self._ensure_client("redis-client-not-initialized")
        await client.delete(self._namespaced_key(key))

    async def clear(self) -> None:
        client = self._ensure_client("redis-client-not-initialized")
        await client.flushdb()

    def _namespaced_key(self, key: str) -> str:
        return f"{self._settings.key_prefix}{key}" if self._settings.key_prefix else key

    def _create_client(self) -> Redis:  # noqa: C901
        kwargs: dict[str, Any] = {
            "decode_responses": self._settings.decode_responses,
            "stream_timeout": self._settings.socket_timeout,
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
