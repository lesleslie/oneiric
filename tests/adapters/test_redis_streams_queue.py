from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

import pytest
from coredis.exceptions import ResponseError

from oneiric.adapters.queue.redis_streams import (
    RedisStreamsQueueAdapter,
    RedisStreamsQueueSettings,
)


class InMemoryPool:
    async def disconnect(self) -> None:  # pragma: no cover - trivial stub
        return None


class InMemoryRedisStreamsClient:
    def __init__(self) -> None:
        self.streams: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
        self.groups: dict[str, set[str]] = defaultdict(set)
        self.pending: dict[str, dict[str, Any]] = {}
        self._counter = 0
        self.connection_pool = InMemoryPool()

    async def ping(self) -> bool:
        return True

    async def xgroup_create(
        self, stream: str, group: str, *, id: str, mkstream: bool
    ) -> None:
        key = f"{stream}:{group}"
        if key in self.groups:
            raise ResponseError("BUSYGROUP")
        self.groups[key] = set()
        if mkstream and stream not in self.streams:
            self.streams[stream] = []

    async def xadd(self, stream: str, data: dict[str, Any], **kwargs: Any) -> str:
        self._counter += 1
        message_id = f"0-{self._counter}"
        self.streams[stream].append((message_id, dict(data)))
        self.pending.setdefault(
            message_id,
            {
                "acked": False,
                "consumer": None,
                "delivery_count": 0,
                "payload": dict(data),
            },
        )
        return message_id

    async def xreadgroup(
        self,
        group: str,
        consumer: str,
        *,
        streams: dict[str, str],
        count: int,
        block: int,
    ) -> list[Any]:
        stream = next(iter(streams.keys()))
        available = [
            entry
            for entry in self.streams[stream]
            if not self.pending[entry[0]]["acked"]
        ]
        selection = available[:count]
        results = [(stream, selection)] if selection else []
        for message_id, _ in selection:
            meta = self.pending[message_id]
            meta["consumer"] = consumer
            meta["delivery_count"] += 1
        if not results and block:
            await asyncio.sleep(block / 1000)
        return results

    async def xack(self, stream: str, group: str, *ids: str) -> int:
        acked = 0
        for message_id in ids:
            meta = self.pending.get(message_id)
            if meta and not meta["acked"]:
                meta["acked"] = True
                acked += 1
        return acked

    async def xpending_range(
        self, stream: str, group: str, *, min: str, max: str, count: int
    ) -> list[tuple[str, str | None, int, int]]:
        rows: list[tuple[str, str | None, int, int]] = []
        for message_id, meta in list(self.pending.items())[:count]:
            if not meta["acked"]:
                rows.append((message_id, meta["consumer"], meta["delivery_count"], 0))
        return rows

    def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_enqueue_read_and_ack_cycle() -> None:
    client = InMemoryRedisStreamsClient()
    adapter = RedisStreamsQueueAdapter(
        RedisStreamsQueueSettings(
            stream="jobs", group="workers", consumer="c1", auto_create_group=True
        ),
        redis_client=client,
    )
    await adapter.init()
    message_id = await adapter.enqueue({"task": "demo"})
    messages = await adapter.read(count=1)
    assert messages[0]["message_id"] == message_id
    assert messages[0]["payload"] == {"task": "demo"}
    acked = await adapter.ack([message_id])
    assert acked == 1
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_pending_reports_unacked_messages() -> None:
    client = InMemoryRedisStreamsClient()
    adapter = RedisStreamsQueueAdapter(
        RedisStreamsQueueSettings(stream="jobs", group="workers", consumer="c1"),
        redis_client=client,
    )
    await adapter.init()
    message_id = await adapter.enqueue({"task": "demo"})
    await adapter.read(count=1)
    pending = await adapter.pending()
    assert pending[0]["message_id"] == message_id
    assert pending[0]["delivery_count"] == 1
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_health_returns_true() -> None:
    client = InMemoryRedisStreamsClient()
    adapter = RedisStreamsQueueAdapter(RedisStreamsQueueSettings(), redis_client=client)
    await adapter.init()
    assert await adapter.health() is True
    await adapter.cleanup()
