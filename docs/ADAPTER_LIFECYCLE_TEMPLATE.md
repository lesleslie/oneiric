# Adapter Lifecycle Template

Use this template when porting an ACB adapter into Oneiric. It demonstrates how to
wire provider metadata, typed settings, structlog-based logging, and lifecycle hooks
so the adapter can be registered with the resolver and orchestrated by the lifecycle
manager.

```python
from __future__ import annotations

from typing import Any, Optional

import redis.asyncio as redis
from pydantic import BaseModel, Field, HttpUrl, SecretStr

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class RedisCacheSettings(BaseModel):
    url: HttpUrl
    password: Optional[SecretStr] = None
    db: int = Field(default=0, ge=0)
    client_name: str = "oneiric-cache"
    connect_timeout: float = Field(default=5.0, ge=0.1)
    health_timeout: float = Field(default=1.0, ge=0.1)


class RedisCacheAdapter:
    metadata = AdapterMetadata(
        category="cache",
        provider="redis",
        factory="oneiric.adapters.redis.cache:RedisCacheAdapter",
        capabilities=["kv", "ttl", "metrics"],
        stack_level=50,
        priority=500,
        source=CandidateSource.LOCAL_PKG,
        owner="Platform Core",
        requires_secrets=True,
        settings_model=RedisCacheSettings,
    )

    def __init__(self, settings: RedisCacheSettings) -> None:
        self._settings = settings
        self._client: Optional[redis.Redis] = None
        self._logger = get_logger("adapter.redis").bind(
            domain="adapter",
            key="cache",
            provider="redis",
        )

    async def init(self) -> None:
        self._logger.info("adapter-init", url=str(self._settings.url))
        try:
            self._client = redis.Redis.from_url(
                str(self._settings.url),
                password=self._settings.password.get_secret_value()
                if self._settings.password
                else None,
                client_name=self._settings.client_name,
                socket_connect_timeout=self._settings.connect_timeout,
                health_check_interval=int(self._settings.health_timeout),
            )
            await self._client.ping()
        except Exception as exc:  # noqa: BLE001
            self._logger.error("adapter-init-failed", error=str(exc))
            raise LifecycleError("redis-cache-init-failed") from exc

    async def health(self) -> bool:
        if not self._client:
            return False
        try:
            await self._client.ping()
            return True
        except redis.RedisError as exc:
            self._logger.warning("adapter-health-failed", error=str(exc))
            return False

    async def cleanup(self) -> None:
        if self._client:
            await self._client.close()
            self._logger.info("adapter-cleanup-complete")

    # Adapter-specific API surface below:
    async def get(self, key: str) -> Any:
        if not self._client:
            raise LifecycleError("redis-client-not-ready")
        return await self._client.get(key)

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        if not self._client:
            raise LifecycleError("redis-client-not-ready")
        await self._client.set(key, value, ex=ttl)
```

### Usage Checklist

1. Define a `BaseModel` settings class for provider-specific knobs.
1. Bind structured logging context inside `__init__` so lifecycle + resolver metadata appears in every log.
1. Implement `init`, `health`, and `cleanup` (and optional `pause`, `resume`, `drain`) methods.
1. Raise `LifecycleError` when initialization or critical calls fail.
1. Register the adapter via `AdapterMetadata.to_candidate()` + `resolver.register_from_pkg` or the adapters bridge.
