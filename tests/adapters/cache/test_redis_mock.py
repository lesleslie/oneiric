"""Tests for RedisCacheAdapter using injected mock clients.

Uses monkeypatching to bypass the _COREDIS_AVAILABLE guard so no actual
coredis installation is required. All Redis I/O is handled by a minimal
in-memory mock client.
"""
from __future__ import annotations

import inspect
from typing import Any

import pytest

from oneiric.adapters.cache.redis import RedisCacheAdapter, RedisCacheSettings
from oneiric.core.lifecycle import LifecycleError


# ---------------------------------------------------------------------------
# Mock client helpers
# ---------------------------------------------------------------------------


class _MockPool:
    async def disconnect(self) -> None:
        pass


class MockRedisClient:
    def __init__(self) -> None:
        self._store: dict[str, Any] = {}
        self._ttls: dict[str, int] = {}
        self.connection_pool: _MockPool = _MockPool()

    async def ping(self) -> bool:
        return True

    async def get(self, key: str) -> Any:
        return self._store.get(key)

    async def set(
        self, key: str, value: Any, *, px: int | None = None, **_: Any
    ) -> None:
        self._store[key] = value
        if px is not None:
            self._ttls[key] = px

    async def delete(self, *keys: str) -> int:
        removed = 0
        for k in keys:
            if k in self._store:
                del self._store[k]
                removed += 1
        return removed

    async def flushdb(self) -> None:
        self._store.clear()
        self._ttls.clear()

    async def dbsize(self) -> int:
        return len(self._store)

    async def aclose(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _coredis_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every test in this module behave as if coredis is installed."""
    monkeypatch.setattr("oneiric.adapters.cache.redis._COREDIS_AVAILABLE", True)
    # Provide a stub TrackingCache so _create_client can reference it
    monkeypatch.setattr(
        "oneiric.adapters.cache.redis.TrackingCache",
        lambda **kw: object(),
        raising=False,
    )


def _make(
    settings: RedisCacheSettings | None = None,
    client: MockRedisClient | None = None,
) -> RedisCacheAdapter:
    client = client or MockRedisClient()
    return RedisCacheAdapter(settings or RedisCacheSettings(), redis_client=client)


# ---------------------------------------------------------------------------
# Tests — RedisCacheSettings
# ---------------------------------------------------------------------------


def test_settings_defaults() -> None:
    s = RedisCacheSettings()
    assert s.host == "localhost"
    assert s.port == 6379
    assert s.db == 0
    assert s.ssl is False
    assert s.decode_responses is True
    assert s.enable_client_cache is True
    assert s.key_prefix == ""


def test_settings_with_url() -> None:
    s = RedisCacheSettings(url="redis://myhost:6380/2")
    assert s.url is not None


def test_settings_custom_prefix() -> None:
    s = RedisCacheSettings(key_prefix="ns:")
    assert s.key_prefix == "ns:"


# ---------------------------------------------------------------------------
# Tests — Lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_init_with_injected_client() -> None:
    client = MockRedisClient()
    adapter = _make(client=client)
    await adapter.init()
    assert adapter._client is client


@pytest.mark.asyncio
async def test_cleanup_injected_client_not_closed() -> None:
    """Injected clients (_owns_client=False) are not closed on cleanup."""
    closed: list[bool] = []

    class TrackingClient(MockRedisClient):
        async def aclose(self) -> None:
            closed.append(True)

    client = TrackingClient()
    adapter = _make(client=client)
    await adapter.init()
    await adapter.cleanup()
    assert closed == []
    # Client reference is kept — adapter does not own it
    assert adapter._client is client


@pytest.mark.asyncio
async def test_cleanup_no_client_is_noop() -> None:
    adapter = _make()
    adapter._client = None
    await adapter.cleanup()  # should not raise


# ---------------------------------------------------------------------------
# Tests — CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_and_get() -> None:
    client = MockRedisClient()
    adapter = _make(client=client)
    await adapter.init()
    await adapter.set("key", "value")
    assert await adapter.get("key") == "value"


@pytest.mark.asyncio
async def test_set_with_ttl_stores_px() -> None:
    client = MockRedisClient()
    adapter = _make(client=client)
    await adapter.init()
    await adapter.set("k", "v", ttl=2.5)
    assert "k" in client._ttls
    assert client._ttls["k"] == 2500  # px = ms


@pytest.mark.asyncio
async def test_set_with_sub_ms_ttl_clamps_to_1() -> None:
    client = MockRedisClient()
    adapter = _make(client=client)
    await adapter.init()
    await adapter.set("k", "v", ttl=0.0001)
    assert client._ttls["k"] == 1


@pytest.mark.asyncio
async def test_set_negative_ttl_raises() -> None:
    adapter = _make()
    await adapter.init()
    with pytest.raises(LifecycleError):
        await adapter.set("k", "v", ttl=-1.0)


@pytest.mark.asyncio
async def test_set_zero_ttl_raises() -> None:
    adapter = _make()
    await adapter.init()
    with pytest.raises(LifecycleError):
        await adapter.set("k", "v", ttl=0.0)


@pytest.mark.asyncio
async def test_delete() -> None:
    client = MockRedisClient()
    adapter = _make(client=client)
    await adapter.init()
    await adapter.set("x", "y")
    await adapter.delete("x")
    assert await adapter.get("x") is None


@pytest.mark.asyncio
async def test_clear_flushes_all() -> None:
    client = MockRedisClient()
    adapter = _make(client=client)
    await adapter.init()
    await adapter.set("a", 1)
    await adapter.set("b", 2)
    await adapter.clear()
    assert await client.dbsize() == 0


# ---------------------------------------------------------------------------
# Tests — Key namespacing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_key_prefix_applied() -> None:
    client = MockRedisClient()
    adapter = _make(RedisCacheSettings(key_prefix="myapp:"), client)
    await adapter.init()
    await adapter.set("item", "data")
    assert "myapp:item" in client._store
    assert await adapter.get("item") == "data"


def test_namespaced_key_with_prefix() -> None:
    adapter = _make(RedisCacheSettings(key_prefix="ns:"))
    assert adapter._namespaced_key("foo") == "ns:foo"


def test_namespaced_key_no_prefix() -> None:
    adapter = _make()
    assert adapter._namespaced_key("foo") == "foo"


# ---------------------------------------------------------------------------
# Tests — Health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_true() -> None:
    adapter = _make()
    await adapter.init()
    assert await adapter.health() is True


@pytest.mark.asyncio
async def test_health_false_when_no_client() -> None:
    adapter = _make()
    adapter._client = None
    assert await adapter.health() is False


@pytest.mark.asyncio
async def test_health_false_on_ping_error() -> None:
    client = MockRedisClient()
    adapter = _make(client=client)
    await adapter.init()

    from oneiric.adapters.cache.redis import RedisError

    async def fail_ping() -> bool:
        raise RedisError("timeout")

    client.ping = fail_ping  # type: ignore[method-assign]
    assert await adapter.health() is False


# ---------------------------------------------------------------------------
# Tests — _create_client (monkeypatched)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_client_with_url(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    class FakeRedis:
        connection_pool = _MockPool()

        def __init__(self, **kw: Any) -> None:
            calls.append({"type": "direct", **kw})
            self.connection_pool = _MockPool()

        @classmethod
        def from_url(cls, url: str, **kw: Any) -> "FakeRedis":
            calls.append({"type": "from_url", "url": url, **kw})
            inst = cls.__new__(cls)
            inst.connection_pool = _MockPool()
            return inst

        async def ping(self) -> bool:
            return True

        async def aclose(self) -> None:
            pass

    monkeypatch.setattr("oneiric.adapters.cache.redis.Redis", FakeRedis)

    adapter = RedisCacheAdapter(
        RedisCacheSettings(
            url="redis://localhost:6379/1",
            enable_client_cache=False,
            username="user",
            password="pass",
            ssl=True,
        )
    )
    await adapter.init()
    assert calls[0]["type"] == "from_url"
    assert calls[0]["url"] == "redis://localhost:6379/1"
    assert calls[0]["username"] == "user"
    assert calls[0]["ssl"] is True
    adapter._owns_client = False  # prevent cleanup from closing the fake
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_create_client_direct(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    class FakeRedis:
        def __init__(self, **kw: Any) -> None:
            calls.append(kw)
            self.connection_pool = _MockPool()

        async def ping(self) -> bool:
            return True

        async def aclose(self) -> None:
            pass

    monkeypatch.setattr("oneiric.adapters.cache.redis.Redis", FakeRedis)

    adapter = RedisCacheAdapter(
        RedisCacheSettings(
            host="redis-host",
            port=6380,
            db=1,
            enable_client_cache=False,
        )
    )
    await adapter.init()
    assert calls[0]["host"] == "redis-host"
    assert calls[0]["port"] == 6380
    assert calls[0]["db"] == 1
    adapter._owns_client = False
    await adapter.cleanup()


def test_coredis_unavailable_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("oneiric.adapters.cache.redis._COREDIS_AVAILABLE", False)
    with pytest.raises(LifecycleError, match="coredis-not-installed"):
        RedisCacheAdapter(RedisCacheSettings())


# ---------------------------------------------------------------------------
# Tests — cleanup variants with owned clients
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_with_awaitable_pool_disconnect() -> None:
    disconnected: list[bool] = []

    class AsyncPool:
        async def disconnect(self) -> None:
            disconnected.append(True)

    client = MockRedisClient()
    client.connection_pool = AsyncPool()  # type: ignore[assignment]

    adapter = _make(client=client)
    # Override ownership to test the owned-client cleanup path
    adapter._owns_client = True
    await adapter.init()
    await adapter.cleanup()
    assert disconnected == [True]
    assert adapter._client is None


@pytest.mark.asyncio
async def test_cleanup_uses_sync_close_fallback() -> None:
    """When client has close() but no aclose(), the sync path is used."""
    closed: list[bool] = []

    class SyncCloseOnly:
        """Mock client with close() but no aclose()."""

        def __init__(self) -> None:
            self.connection_pool = _MockPool()

        async def ping(self) -> bool:
            return True

        def close(self) -> None:
            closed.append(True)

    client = SyncCloseOnly()
    adapter = RedisCacheAdapter(
        RedisCacheSettings(), redis_client=client  # type: ignore[arg-type]
    )
    adapter._owns_client = True
    await adapter.init()
    await adapter.cleanup()
    assert closed == [True]
    assert adapter._client is None


# ---------------------------------------------------------------------------
# Tests — _close_client / _disconnect_pool direct-call guard paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_client_no_client() -> None:
    adapter = _make()
    adapter._client = None
    await adapter._close_client()  # must not raise


@pytest.mark.asyncio
async def test_close_client_awaitable_sync_close() -> None:
    """_close_client awaits the result when close() returns a coroutine."""
    closed: list[bool] = []

    class AsyncCloseViaSyncMethod:
        def __init__(self) -> None:
            self.connection_pool = _MockPool()

        async def ping(self) -> bool:
            return True

        async def close(self) -> None:
            closed.append(True)

    client = AsyncCloseViaSyncMethod()
    adapter = RedisCacheAdapter(
        RedisCacheSettings(), redis_client=client  # type: ignore[arg-type]
    )
    adapter._owns_client = True
    await adapter.init()
    await adapter._close_client()
    assert closed == [True]


@pytest.mark.asyncio
async def test_disconnect_pool_no_client() -> None:
    adapter = _make()
    adapter._client = None
    await adapter._disconnect_pool()  # must not raise


@pytest.mark.asyncio
async def test_disconnect_pool_no_pool() -> None:
    """_disconnect_pool returns early when client has no connection_pool."""

    class NopoolClient:
        async def ping(self) -> bool:
            return True

        async def aclose(self) -> None:
            pass

    client = NopoolClient()
    adapter = RedisCacheAdapter(
        RedisCacheSettings(), redis_client=client  # type: ignore[arg-type]
    )
    await adapter.init()
    await adapter._disconnect_pool()  # must not raise


@pytest.mark.asyncio
async def test_disconnect_pool_no_disconnect_method() -> None:
    """_disconnect_pool returns early when pool has no disconnect attribute."""
    from types import SimpleNamespace

    client = MockRedisClient()
    client.connection_pool = SimpleNamespace()  # type: ignore[assignment]
    adapter = _make(client=client)
    await adapter.init()
    await adapter._disconnect_pool()  # must not raise


# ---------------------------------------------------------------------------
# Tests — _create_client with TrackingCache kwargs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_client_with_tracking_cache_kwargs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_create_client passes all optional TrackingCache kwargs when set."""
    cache_kwargs_received: list[dict[str, Any]] = []

    class FakeTrackingCache:
        def __init__(self, **kw: Any) -> None:
            cache_kwargs_received.append(kw)

    class FakeRedis:
        def __init__(self, **kw: Any) -> None:
            self.connection_pool = _MockPool()

        async def ping(self) -> bool:
            return True

        async def aclose(self) -> None:
            pass

    monkeypatch.setattr("oneiric.adapters.cache.redis.Redis", FakeRedis)
    monkeypatch.setattr("oneiric.adapters.cache.redis.TrackingCache", FakeTrackingCache)

    adapter = RedisCacheAdapter(
        RedisCacheSettings(
            enable_client_cache=True,
            client_cache_max_keys=500,
            client_cache_max_size_bytes=2048,
            client_cache_max_idle_seconds=30,
        )
    )
    await adapter.init()
    assert cache_kwargs_received == [
        {"max_keys": 500, "max_size_bytes": 2048, "max_idle_seconds": 30}
    ]
    adapter._owns_client = False
    await adapter.cleanup()
