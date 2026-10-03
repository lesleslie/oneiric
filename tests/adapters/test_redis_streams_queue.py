from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

import pytest

coredis = pytest.importorskip("coredis")
ResponseError = coredis.exceptions.ResponseError

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
        self, stream: str, group: str, *, identifier: str, mkstream: bool
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
    ) -> dict[str, list[tuple[str, dict[str, Any]]]]:
        stream = next(iter(streams.keys()))
        available = [
            entry
            for entry in self.streams[stream]
            if not self.pending[entry[0]]["acked"]
        ]
        selection = available[:count]
        results: dict[str, list[tuple[str, dict[str, Any]]]] = (
            {stream: selection} if selection else {}
        )
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


class InMemoryPubSub:
    def __init__(self, messages: list[dict[str, Any]] | None = None) -> None:
        self.channels: list[str] = []
        self.patterns: list[str] = []
        self.messages = messages or []

    async def subscribe(self, channel: str) -> None:
        self.channels.append(channel)

    async def psubscribe(self, pattern: str) -> None:
        self.patterns.append(pattern)

    async def listen(self):
        for message in self.messages:
            yield message


class InMemoryPubSubRedisClient(InMemoryRedisStreamsClient):
    def __init__(self, messages: list[dict[str, Any]] | None = None) -> None:
        super().__init__()
        self._pubsub = InMemoryPubSub(messages=messages)
        self.published: list[tuple[str, bytes]] = []

    def pubsub(self) -> InMemoryPubSub:
        return self._pubsub

    async def publish(self, channel: str, payload: bytes) -> int:
        self.published.append((channel, payload))
        return len(self.published)


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


@pytest.mark.asyncio
async def test_pubsub_publish_and_subscribe_flow() -> None:
    client = InMemoryPubSubRedisClient(
        messages=[
            {"channel": b"bodai:events:workflow.started", "data": b'{"ok":true}'},
            {"channel": "bodai:events:workflow.completed", "data": '{"done":true}'},
        ]
    )
    adapter = RedisStreamsQueueAdapter(
        RedisStreamsQueueSettings(stream="jobs", group="workers", consumer="c1"),
        redis_client=client,
    )
    await adapter.init()

    published = await adapter.pubsub_publish("bodai:events:workflow.started", "hello")
    assert published == 1
    assert client.published == [("bodai:events:workflow.started", b"hello")]

    seen: list[tuple[str, bytes]] = []

    async def callback(channel: str, payload: bytes) -> None:
        seen.append((channel, payload))

    task = await adapter.pubsub_subscribe(
        pattern="bodai:events:*",
        callback=callback,
    )
    await task

    assert client._pubsub.patterns == ["bodai:events:*"]
    assert seen == [
        ("bodai:events:workflow.started", b'{"ok":true}'),
        ("bodai:events:workflow.completed", b'{"done":true}'),
    ]
    await adapter.cleanup()


# ----------------------------------------------------------------------------
# _format_entries regression tests (pin coredis 6.x dict-shaped response)
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_format_entries_dict_shape_coredis_6x() -> None:
    """_format_entries must accept coredis 6.x's dict-shaped xreadgroup response.

    coredis 6.x returns ``{stream_key: list[StreamEntry]}`` rather than the
    pre-6 list of tuples. Iterating a dict as `for stream_key, messages in
    entries` gives just the keys — unpacking would raise
    ``too many values to unpack (expected 2)``. The adapter MUST call
    ``entries.items()`` for the dict shape. Pre-1.0 — replace, not extend.
    """
    adapter = RedisStreamsQueueAdapter(
        RedisStreamsQueueSettings(stream="jobs", group="workers", consumer="c1"),
        redis_client=InMemoryRedisStreamsClient(),
    )
    await adapter.init()
    try:
        entries: dict[str, list[tuple[str, dict[str, Any]]]] = {
            "jobs": [
                ("1-0", {"task": "alpha"}),
                ("1-1", {"task": "beta"}),
            ],
        }
        formatted = adapter._format_entries(entries)
        assert formatted == [
            {"message_id": "1-0", "payload": {"task": "alpha"}},
            {"message_id": "1-1", "payload": {"task": "beta"}},
        ]
    finally:
        await adapter.cleanup()


@pytest.mark.asyncio
async def test_format_entries_none_input_returns_empty() -> None:
    """None input (e.g., coredis block-timeout with no messages) returns []."""
    adapter = RedisStreamsQueueAdapter(
        RedisStreamsQueueSettings(stream="jobs", group="workers", consumer="c1"),
        redis_client=InMemoryRedisStreamsClient(),
    )
    await adapter.init()
    try:
        assert adapter._format_entries(None) == []
        assert adapter._format_entries({}) == []
    finally:
        await adapter.cleanup()


@pytest.mark.asyncio
async def test_format_entries_filters_other_streams() -> None:
    """Multi-stream dict input — only the configured stream's entries pass."""
    adapter = RedisStreamsQueueAdapter(
        RedisStreamsQueueSettings(stream="jobs", group="workers", consumer="c1"),
        redis_client=InMemoryRedisStreamsClient(),
    )
    await adapter.init()
    try:
        entries: dict[str, list[tuple[str, dict[str, Any]]]] = {
            "jobs": [("1-0", {"task": "wanted"})],
            "audit": [("2-0", {"task": "skipped"})],
        }
        formatted = adapter._format_entries(entries)
        assert formatted == [{"message_id": "1-0", "payload": {"task": "wanted"}}]
    finally:
        await adapter.cleanup()
