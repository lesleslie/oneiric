from __future__ import annotations

import asyncio
from typing import Any

import pytest
from coredis.cache import TrackingCache
from fakeredis.aioredis import FakeRedis

from oneiric.adapters.bootstrap import register_builtin_adapters
from oneiric.adapters.cache.redis import RedisCacheAdapter, RedisCacheSettings
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.resolution import Resolver


@pytest.mark.asyncio
async def test_redis_cache_set_get_and_ttl() -> None:
    fake = FakeRedis(decode_responses=True)
    adapter = RedisCacheAdapter(
        RedisCacheSettings(key_prefix="demo:"), redis_client=fake
    )
    await adapter.init()
    await adapter.set("foo", "bar", ttl=0.1)
    assert await adapter.get("foo") == "bar"
    await asyncio.sleep(0.15)
    assert await adapter.get("foo") is None
    await adapter.cleanup()
    await fake.aclose()


@pytest.mark.asyncio
async def test_redis_cache_delete_and_clear() -> None:
    fake = FakeRedis(decode_responses=True)
    adapter = RedisCacheAdapter(RedisCacheSettings(), redis_client=fake)
    await adapter.init()
    await adapter.set("a", 1)
    await adapter.delete("a")
    assert await adapter.get("a") is None
    await adapter.set("b", 2)
    await adapter.set("c", 3)
    await adapter.clear()
    assert await fake.dbsize() == 0
    await adapter.cleanup()
    await fake.aclose()


@pytest.mark.asyncio
async def test_redis_cache_negative_ttl_raises() -> None:
    adapter = RedisCacheAdapter(RedisCacheSettings())
    await adapter.init()
    with pytest.raises(LifecycleError):
        await adapter.set("foo", "bar", ttl=-1)
    await adapter.cleanup()


def test_register_builtin_adapters_registers_redis_adapter() -> None:
    resolver = Resolver()
    register_builtin_adapters(resolver)
    candidates = resolver.list_active("adapter")
    assert any(c.provider == "redis" and c.key == "cache" for c in candidates)


@pytest.mark.asyncio
async def test_redis_cache_enables_tracking_cache(monkeypatch) -> None:
    recorded_kwargs: dict[str, Any] = {}

    class DummyPool:
        async def disconnect(self) -> None:  # pragma: no cover - simple stub
            return None

    class DummyRedis:
        def __init__(self, **kwargs: Any) -> None:
            recorded_kwargs.update(kwargs)
            self.connection_pool = DummyPool()

        @classmethod
        def from_url(cls, url: str, **kwargs: Any) -> DummyRedis:  # type: ignore[override]
            return cls(**kwargs)

        async def ping(self) -> bool:
            return True

        async def close(self) -> None:
            return None

    monkeypatch.setattr("oneiric.adapters.cache.redis.Redis", DummyRedis)

    adapter = RedisCacheAdapter(
        RedisCacheSettings(url="redis://localhost:6379/0", enable_client_cache=True),
    )
    await adapter.init()
    cache_obj = recorded_kwargs.get("cache")
    assert isinstance(cache_obj, TrackingCache)
    await adapter.cleanup()
