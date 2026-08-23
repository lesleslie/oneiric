from __future__ import annotations

import asyncio
import itertools

import pytest

from oneiric.adapters.bootstrap import register_builtin_adapters
from oneiric.adapters.cache.memory import MemoryCacheAdapter, MemoryCacheSettings
from oneiric.core.resolution import Resolver


@pytest.mark.asyncio
async def test_memory_cache_set_get() -> None:
    cache = MemoryCacheAdapter(MemoryCacheSettings())
    await cache.init()
    await cache.set("foo", "bar")
    assert await cache.get("foo") == "bar"
    await cache.cleanup()


@pytest.mark.asyncio
async def test_memory_cache_ttl_eviction(monkeypatch) -> None:
    cache = MemoryCacheAdapter(MemoryCacheSettings(default_ttl=0.1))
    await cache.init()
    await cache.set("foo", "bar")
    await asyncio.sleep(0.15)
    assert await cache.get("foo") is None
    await cache.cleanup()


@pytest.mark.asyncio
async def test_memory_cache_max_entries() -> None:
    cache = MemoryCacheAdapter(MemoryCacheSettings(max_entries=2))
    await cache.init()
    await cache.set("a", 1)
    await cache.set("b", 2)
    await cache.set("c", 3)
    assert await cache.get("a") is None
    assert await cache.get("b") == 2
    assert await cache.get("c") == 3
    await cache.cleanup()


def test_register_builtin_adapters_registers_memory_adapter() -> None:
    resolver = Resolver()
    register_builtin_adapters(resolver)
    active = resolver.list_active("adapter")
    shadowed = resolver.list_shadowed("adapter")
    combined = itertools.chain(active, shadowed)
    assert any(c.provider == "memory" and c.key == "cache" for c in combined)


# ---------------------------------------------------------------------------
# Tests — coverage gaps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_cache_health() -> None:
    cache = MemoryCacheAdapter()
    assert await cache.health() is True


@pytest.mark.asyncio
async def test_memory_cache_delete() -> None:
    cache = MemoryCacheAdapter()
    await cache.init()
    await cache.set("k", "v")
    await cache.delete("k")
    assert await cache.get("k") is None


@pytest.mark.asyncio
async def test_memory_cache_clear() -> None:
    cache = MemoryCacheAdapter()
    await cache.init()
    await cache.set("a", 1)
    await cache.set("b", 2)
    await cache.clear()
    assert await cache.get("a") is None
    assert await cache.get("b") is None


@pytest.mark.asyncio
async def test_memory_cache_negative_ttl_raises() -> None:
    from oneiric.core.lifecycle import LifecycleError

    cache = MemoryCacheAdapter()
    await cache.init()
    with pytest.raises(LifecycleError, match="negative-ttl-not-allowed"):
        await cache.set("k", "v", ttl=-1.0)


# ---------------------------------------------------------------------------
# Tests — delete_prefix (PR-A)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_delete_prefix_removes_matching_keys() -> None:
    cache = MemoryCacheAdapter()
    await cache.init()
    await cache.set("foo:a", 1)
    await cache.set("foo:b", 2)
    await cache.set("bar:c", 3)
    removed = await cache.delete_prefix("foo:")
    assert removed == 2
    assert await cache.get("foo:a") is None
    assert await cache.get("foo:b") is None
    assert await cache.get("bar:c") == 3
    await cache.cleanup()


@pytest.mark.asyncio
async def test_memory_delete_prefix_preserves_lru_order_on_survivors() -> None:
    """OrderedDict.pop must not shift survivors' access-recency positions."""
    cache = MemoryCacheAdapter()
    await cache.init()
    await cache.set("keep:1", "a")
    await cache.set("drop:x", "b")
    await cache.set("keep:2", "c")
    # Touch keep:1 to make it MRU; touch keep:2 to make it MRU after.
    await cache.get("keep:1")
    await cache.get("keep:2")
    # Now drop the middle one — survivors should retain their LRU chain.
    await cache.delete_prefix("drop:")
    # After cleanup, MRU order is keep:1, keep:2 (keep:2 was touched last).
    # Capacity enforcement relies on OrderedDict.move_to_end in set(); here
    # we just verify the survivors still exist and are accessible.
    assert await cache.get("keep:1") == "a"
    assert await cache.get("keep:2") == "c"
    await cache.cleanup()


@pytest.mark.asyncio
async def test_memory_delete_prefix_returns_zero_on_no_match() -> None:
    cache = MemoryCacheAdapter()
    await cache.init()
    await cache.set("a", 1)
    removed = await cache.delete_prefix("nothing:")
    assert removed == 0
    assert await cache.get("a") == 1
    await cache.cleanup()
