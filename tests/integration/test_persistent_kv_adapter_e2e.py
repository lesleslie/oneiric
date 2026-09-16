"""End-to-end tests for the file-backed PersistentKVCacheAdapter.

These tests exercise the real on-disk JSON store under tmp_path (no mocking)
and cover the same operations Dhara's ``AsyncKVTimeSeriesStore`` /
``KVTimeSeriesStore`` exposed via ``dhara.mcp.kv_timeseries``.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from oneiric.adapters.cache.persistent_kv import (
    PersistentKVCacheAdapter,
    PersistentKVCacheSettings,
)


def _new_adapter(tmp_path: Path) -> PersistentKVCacheAdapter:
    store_path = tmp_path / "kv_store.json"
    settings = PersistentKVCacheSettings(storage_path=str(store_path))
    return PersistentKVCacheAdapter(settings)


@pytest.mark.asyncio
async def test_persistent_kv_put_get_roundtrip(tmp_path: Path) -> None:
    adapter = _new_adapter(tmp_path)
    await adapter.init()

    put_result = await adapter.put("greeting", "hello world")
    assert put_result == {"ok": True, "key": "greeting"}

    fetched = await adapter.get("greeting")
    assert fetched["ok"] is True
    assert fetched["key"] == "greeting"
    assert fetched["value"] == "hello world"
    assert "expired" not in fetched

    await adapter.close()

    # Reopen against the same file — value must have persisted.
    adapter2 = _new_adapter(tmp_path)
    await adapter2.init()
    fetched2 = await adapter2.get("greeting")
    assert fetched2["value"] == "hello world"
    await adapter2.close()


@pytest.mark.asyncio
async def test_persistent_kv_list_prefix(tmp_path: Path) -> None:
    adapter = _new_adapter(tmp_path)
    await adapter.init()

    await adapter.put("component_endpoint/akosha", {"url": "http://akosha:8682"})
    await adapter.put("component_endpoint/mahavishnu", {"url": "http://mahavishnu:8680"})
    await adapter.put("component_endpoint/session_buddy", {"url": "http://sb:8678"})
    await adapter.put("unrelated/other", {"value": 1})

    results = await adapter.list_prefix("component_endpoint/")
    keys = sorted(r["key"] for r in results)
    assert keys == [
        "component_endpoint/akosha",
        "component_endpoint/mahavishnu",
        "component_endpoint/session_buddy",
    ]
    assert results[0]["value"] == {"url": "http://akosha:8682"}

    # Prefix with no matches returns empty list (not None).
    empty = await adapter.list_prefix("nothing/")
    assert empty == []

    await adapter.close()


@pytest.mark.asyncio
async def test_persistent_kv_record_query_time_series(tmp_path: Path) -> None:
    adapter = _new_adapter(tmp_path)
    await adapter.init()

    now = datetime.now(UTC)
    base = (now - timedelta(hours=3)).isoformat()
    middle = (now - timedelta(hours=2)).isoformat()
    recent = (now - timedelta(minutes=5)).isoformat()

    await adapter.record_time_series(
        "fitness_failure", "akosha",
        record={"pattern": "boom", "duration_ms": 42},
        timestamp=base,
    )
    await adapter.record_time_series(
        "fitness_failure", "akosha",
        record={"pattern": "boom", "duration_ms": 17},
        timestamp=middle,
    )
    await adapter.record_time_series(
        "fitness_failure", "akosha",
        record={"pattern": "boom", "duration_ms": 99},
        timestamp=recent,
    )

    queried = await adapter.query_time_series("fitness_failure", "akosha")
    assert len(queried) == 3
    assert [q["duration_ms"] for q in queried] == [42, 17, 99]

    limited = await adapter.query_time_series(
        "fitness_failure", "akosha", limit=2
    )
    assert len(limited) == 2
    assert [q["duration_ms"] for q in limited] == [17, 99]

    start_iso = (now - timedelta(hours=2, minutes=30)).isoformat()
    windowed = await adapter.query_time_series(
        "fitness_failure", "akosha", start_date=start_iso
    )
    assert [q["duration_ms"] for q in windowed] == [17, 99]

    # Different entity_id is isolated.
    await adapter.record_time_series(
        "fitness_failure", "mahavishnu",
        record={"pattern": "boom", "duration_ms": 7},
        timestamp=recent,
    )
    only_akosha = await adapter.query_time_series("fitness_failure", "akosha")
    assert all(item.get("pattern") == "boom" for item in only_akosha)
    assert len(only_akosha) == 3

    await adapter.close()


@pytest.mark.asyncio
async def test_persistent_kv_ttl_expiry(tmp_path: Path) -> None:
    adapter = _new_adapter(tmp_path)
    await adapter.init()

    # Use a 1-second TTL and sleep past it.
    put_result = await adapter.put("ephemeral", "transient", ttl=1)
    assert put_result["ok"] is True

    immediate = await adapter.get("ephemeral")
    assert immediate["value"] == "transient"
    assert "expired" not in immediate

    await asyncio.sleep(1.2)

    expired = await adapter.get("ephemeral")
    assert expired["value"] is None
    assert expired["expired"] is True

    await adapter.close()


@pytest.mark.asyncio
async def test_persistent_kv_aggregate_patterns(tmp_path: Path) -> None:
    adapter = _new_adapter(tmp_path)
    await adapter.init()

    now = datetime.now(UTC)
    # Two patterns, with different occurrence counts.
    for i in range(5):
        await adapter.record_time_series(
            "incidents", "akosha",
            record={"pattern": "circuit_open", "n": i},
            timestamp=(now - timedelta(minutes=i + 1)).isoformat(),
        )
    for i in range(3):
        await adapter.record_time_series(
            "incidents", "mahavishnu",
            record={"pattern": "timeout", "n": i},
            timestamp=(now - timedelta(minutes=i + 1)).isoformat(),
        )
    for i in range(2):
        await adapter.record_time_series(
            "incidents", "crackerjack",
            # `issue_type` is also a recognized pattern key.
            record={"issue_type": "lint_failure", "n": i},
            timestamp=(now - timedelta(minutes=i + 1)).isoformat(),
        )
    # Single occurrence — must be filtered out by min_occurrences=2.
    await adapter.record_time_series(
        "incidents", "session_buddy",
        record={"pattern": "lonely"},
        timestamp=(now - timedelta(seconds=10)).isoformat(),
    )

    aggregated = await adapter.aggregate_patterns(
        (now - timedelta(hours=1)).isoformat(), min_occurrences=2
    )
    assert aggregated == [
        {"pattern": "circuit_open", "count": 5},
        {"pattern": "timeout", "count": 3},
        {"pattern": "lint_failure", "count": 2},
    ]

    # With min_occurrences=1 the singleton is included.
    with_singletons = await adapter.aggregate_patterns(
        (now - timedelta(hours=1)).isoformat(), min_occurrences=1
    )
    patterns = {row["pattern"]: row["count"] for row in with_singletons}
    assert patterns == {
        "circuit_open": 5,
        "timeout": 3,
        "lint_failure": 2,
        "lonely": 1,
    }

    await adapter.close()


@pytest.mark.asyncio
async def test_persistent_kv_health_after_init(tmp_path: Path) -> None:
    adapter = _new_adapter(tmp_path)
    # Before init, the storage path is not initialized — health returns False.
    pre_init_health = await adapter.health()
    assert pre_init_health is False

    await adapter.init()
    healthy = await adapter.health()
    assert healthy is True
    await adapter.close()


@pytest.mark.asyncio
async def test_persistent_kv_default_ttl_via_settings(tmp_path: Path) -> None:
    """When settings.key_ttl_seconds is set, every put() applies it."""
    store_path = tmp_path / "kv_default_ttl.json"
    settings = PersistentKVCacheSettings(
        storage_path=str(store_path), key_ttl_seconds=1
    )
    adapter = PersistentKVCacheAdapter(settings)
    await adapter.init()

    # No per-call ttl → default ttl applies.
    await adapter.put("default_ttl_key", "value")
    immediate = await adapter.get("default_ttl_key")
    assert immediate["value"] == "value"

    await asyncio.sleep(1.2)
    expired = await adapter.get("default_ttl_key")
    assert expired["value"] is None
    assert expired["expired"] is True

    await adapter.close()


@pytest.mark.asyncio
async def test_persistent_kv_delete(tmp_path: Path) -> None:
    adapter = _new_adapter(tmp_path)
    await adapter.init()
    await adapter.put("to_remove", 42)

    removed = await adapter.delete("to_remove")
    assert removed is True

    second = await adapter.delete("to_remove")
    assert second is False

    after = await adapter.get("to_remove")
    assert after["value"] is None
    await adapter.close()


@pytest.mark.asyncio
async def test_persistent_kv_corrupt_file_recovers(tmp_path: Path) -> None:
    """If the on-disk file is corrupt, init() still succeeds and starts empty."""
    store_path = tmp_path / "kv_corrupt.json"
    store_path.write_text("not valid json {[", encoding="utf-8")

    adapter = PersistentKVCacheAdapter(
        PersistentKVCacheSettings(storage_path=str(store_path))
    )
    await adapter.init()

    # Init should not raise; we can write fresh data over the corrupt file.
    await adapter.put("fresh", "value")
    fetched = await adapter.get("fresh")
    assert fetched["value"] == "value"

    await adapter.close()


@pytest.mark.asyncio
async def test_persistent_kv_persists_across_instances(tmp_path: Path) -> None:
    """Two adapters pointed at the same file share state after init."""
    store_path = tmp_path / "kv_shared.json"
    first = PersistentKVCacheAdapter(
        PersistentKVCacheSettings(storage_path=str(store_path))
    )
    await first.init()
    await first.put("shared_key", {"a": 1})
    await first.record_time_series(
        "metric", "entity", record={"pattern": "x"}, timestamp=datetime.now(UTC).isoformat()
    )
    await first.close()

    second = PersistentKVCacheAdapter(
        PersistentKVCacheSettings(storage_path=str(store_path))
    )
    await second.init()
    fetched = await second.get("shared_key")
    assert fetched["value"] == {"a": 1}
    ts = await second.query_time_series("metric", "entity")
    assert len(ts) == 1
    assert ts[0]["pattern"] == "x"
    await second.close()


@pytest.mark.asyncio
async def test_persistent_kv_storage_path_expanded(tmp_path: Path) -> None:
    """`~` in storage_path is expanded by the adapter."""
    home = tmp_path / "fakehome"
    home.mkdir()
    target = home / ".oneiric" / "persistent_kv" / "data.json"
    settings = PersistentKVCacheSettings(storage_path=str(target))
    adapter = PersistentKVCacheAdapter(settings)
    await adapter.init()
    assert adapter.storage_path == target
    assert target.exists()
    await adapter.close()


@pytest.mark.asyncio
async def test_persistent_kv_retention_purges_old_entries(tmp_path: Path) -> None:
    """Old time-series entries are dropped on insert past retention cutoff."""
    settings = PersistentKVCacheSettings(
        storage_path=str(tmp_path / "kv_retention.json"),
        retention_days=1,
    )
    adapter = PersistentKVCacheAdapter(settings)
    await adapter.init()

    # Two entries with timestamps spanning the retention boundary.
    very_old = (datetime.now(UTC) - timedelta(days=5)).isoformat()
    fresh = datetime.now(UTC).isoformat()

    await adapter.record_time_series(
        "m", "e", record={"pattern": "old"}, timestamp=very_old
    )
    # Old entry still inside retention window (retention_days=1 cutoff is 1 day
    # ago). Because we record AFTER the very_old entry, the purge will drop it.
    await adapter.record_time_series(
        "m", "e", record={"pattern": "fresh"}, timestamp=fresh
    )

    queried = await adapter.query_time_series("m", "e")
    patterns = [q["pattern"] for q in queried]
    assert "fresh" in patterns
    assert "old" not in patterns

    await adapter.close()


@pytest.mark.asyncio
async def test_persistent_kv_concurrent_writes_safe(tmp_path: Path) -> None:
    """Concurrent put() calls must serialize through the asyncio lock."""
    adapter = _new_adapter(tmp_path)
    await adapter.init()

    async def writer(idx: int) -> None:
        await adapter.put(f"key_{idx}", idx)

    await asyncio.gather(*(writer(i) for i in range(20)))

    for i in range(20):
        fetched = await adapter.get(f"key_{i}")
        assert fetched["value"] == i

    await adapter.close()


@pytest.mark.asyncio
async def test_persistent_kv_list_prefix_filters_expired(tmp_path: Path) -> None:
    """Expired entries under a prefix are skipped, not returned."""
    adapter = _new_adapter(tmp_path)
    await adapter.init()

    await adapter.put("prefix/keep", 1)
    await adapter.put("prefix/expire", 2, ttl=1)
    await asyncio.sleep(1.2)

    rows = await adapter.list_prefix("prefix/")
    keys = sorted(r["key"] for r in rows)
    assert keys == ["prefix/keep"]
    await adapter.close()
