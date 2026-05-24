"""Tests for RedisStreamsQueueAdapter using injected mock clients.

These tests do NOT require coredis to be installed — they exercise all code
paths by injecting a minimal in-memory client via the redis_client parameter.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import pytest

from oneiric.adapters.queue.redis_streams import (
    RedisStreamsQueueAdapter,
    RedisStreamsQueueSettings,
)
from oneiric.core.lifecycle import LifecycleError

# ---------------------------------------------------------------------------
# Minimal mock Redis client
# ---------------------------------------------------------------------------


class MockPool:
    def disconnect(self) -> None:
        return None


class MockRedisClient:
    def __init__(self) -> None:
        self.streams: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
        self.groups: set[str] = set()
        self._counter = 0
        self.connection_pool = MockPool()
        self._ping_raises: Exception | None = None

    async def ping(self) -> bool:
        if self._ping_raises:
            raise self._ping_raises
        return True

    async def xgroup_create(
        self, stream: str, group: str, *, id: str, mkstream: bool
    ) -> None:
        key = f"{stream}:{group}"
        if key in self.groups:
            # Simulate BUSYGROUP error via a generic exception carrying that text
            raise Exception("BUSYGROUP Consumer Group name already exists")
        self.groups.add(key)

    async def xadd(self, stream: str, data: dict[str, Any], **kwargs: Any) -> str:
        self._counter += 1
        msg_id = f"0-{self._counter}"
        self.streams[stream].append((msg_id, dict(data)))
        return msg_id

    async def xreadgroup(
        self,
        group: str,
        consumer: str,
        *,
        streams: dict[str, str],
        count: int,
        block: int,
    ) -> list[Any]:
        stream = next(iter(streams))
        entries = self.streams[stream][:count]
        return [(stream, entries)] if entries else []

    async def xack(self, stream: str, group: str, *ids: str) -> int:
        return len(ids)

    async def xpending_range(
        self, stream: str, group: str, *, min: str, max: str, count: int
    ) -> list[tuple[str, str, int, int]]:
        entries = self.streams.get(stream, [])
        return [(msg_id, "consumer", 1, 0) for msg_id, _ in entries[:count]]

    async def publish(self, channel: str, payload: bytes) -> int:
        return 1

    def close(self) -> None:
        pass


class MockPubSub:
    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self.subscribed: list[str] = []
        self.psubscribed: list[str] = []
        self._messages = messages

    async def subscribe(self, channel: str) -> None:
        self.subscribed.append(channel)

    async def psubscribe(self, pattern: str) -> None:
        self.psubscribed.append(pattern)

    async def listen(self):
        for msg in self._messages:
            yield msg


class MockPubSubRedisClient(MockRedisClient):
    def __init__(self, messages: list[dict[str, Any]] | None = None) -> None:
        super().__init__()
        self._pubsub = MockPubSub(messages or [])

    def pubsub(self) -> MockPubSub:
        return self._pubsub


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_init_creates_group() -> None:
    client = MockRedisClient()
    adapter = RedisStreamsQueueAdapter(
        RedisStreamsQueueSettings(
            stream="s", group="g", consumer="c", auto_create_group=True
        ),
        redis_client=client,
    )
    await adapter.init()
    assert "s:g" in client.groups


@pytest.mark.asyncio
async def test_init_busygroup_is_ignored() -> None:
    client = MockRedisClient()
    # Pre-register group so second init raises BUSYGROUP
    client.groups.add("s:g")
    adapter = RedisStreamsQueueAdapter(
        RedisStreamsQueueSettings(
            stream="s", group="g", consumer="c", auto_create_group=True
        ),
        redis_client=client,
    )
    # Should not raise — BUSYGROUP is swallowed
    await adapter.init()


@pytest.mark.asyncio
async def test_init_other_error_propagates() -> None:
    client = MockRedisClient()

    async def bad_xgroup_create(*a: Any, **kw: Any) -> None:
        raise Exception("NOGROUP something else")

    client.xgroup_create = bad_xgroup_create  # type: ignore[method-assign]
    adapter = RedisStreamsQueueAdapter(
        RedisStreamsQueueSettings(auto_create_group=True),
        redis_client=client,
    )
    with pytest.raises(Exception, match="NOGROUP"):
        await adapter.init()


@pytest.mark.asyncio
async def test_init_skip_group_creation() -> None:
    client = MockRedisClient()
    adapter = RedisStreamsQueueAdapter(
        RedisStreamsQueueSettings(auto_create_group=False),
        redis_client=client,
    )
    await adapter.init()
    assert len(client.groups) == 0


@pytest.mark.asyncio
async def test_enqueue_and_read_cycle() -> None:
    client = MockRedisClient()
    adapter = RedisStreamsQueueAdapter(
        RedisStreamsQueueSettings(stream="jobs", group="workers", consumer="c1"),
        redis_client=client,
    )
    await adapter.init()
    msg_id = await adapter.enqueue({"task": "work"})
    assert msg_id.startswith("0-")
    messages = await adapter.read(count=5)
    assert len(messages) == 1
    assert messages[0]["message_id"] == msg_id
    assert messages[0]["payload"] == {"task": "work"}


@pytest.mark.asyncio
async def test_enqueue_with_maxlen() -> None:
    client = MockRedisClient()
    adapter = RedisStreamsQueueAdapter(
        RedisStreamsQueueSettings(stream="s", maxlen=100),
        redis_client=client,
    )
    await adapter.init()
    msg_id = await adapter.enqueue({"x": "y"})
    assert msg_id


@pytest.mark.asyncio
async def test_ack_returns_count() -> None:
    client = MockRedisClient()
    adapter = RedisStreamsQueueAdapter(RedisStreamsQueueSettings(), redis_client=client)
    await adapter.init()
    acked = await adapter.ack(["id-1", "id-2"])
    assert acked == 2


@pytest.mark.asyncio
async def test_ack_empty_list() -> None:
    client = MockRedisClient()
    adapter = RedisStreamsQueueAdapter(RedisStreamsQueueSettings(), redis_client=client)
    await adapter.init()
    acked = await adapter.ack([])
    assert acked == 0


@pytest.mark.asyncio
async def test_pending() -> None:
    client = MockRedisClient()
    client.streams["oneiric-queue"].append(("0-1", {"k": "v"}))
    adapter = RedisStreamsQueueAdapter(RedisStreamsQueueSettings(), redis_client=client)
    await adapter.init()
    pending = await adapter.pending(count=10)
    assert len(pending) == 1
    assert pending[0]["message_id"] == "0-1"
    assert pending[0]["delivery_count"] == 1


@pytest.mark.asyncio
async def test_health_true() -> None:
    client = MockRedisClient()
    adapter = RedisStreamsQueueAdapter(RedisStreamsQueueSettings(), redis_client=client)
    await adapter.init()
    assert await adapter.health() is True


@pytest.mark.asyncio
async def test_health_false_on_ping_failure() -> None:
    client = MockRedisClient()
    adapter = RedisStreamsQueueAdapter(RedisStreamsQueueSettings(), redis_client=client)
    await adapter.init()

    async def bad_ping() -> bool:
        raise Exception("connection refused")

    client.ping = bad_ping  # type: ignore[method-assign]
    assert await adapter.health() is False


@pytest.mark.asyncio
async def test_cleanup_with_owned_client() -> None:
    closed = []

    class ClosingClient(MockRedisClient):
        def close(self) -> None:
            closed.append(True)

    client = ClosingClient()
    adapter = RedisStreamsQueueAdapter(RedisStreamsQueueSettings(), redis_client=client)
    adapter._owns_client = True  # override to exercise owned-client path
    await adapter.cleanup()
    assert adapter._client is None


@pytest.mark.asyncio
async def test_cleanup_not_owned_does_not_close() -> None:
    client = MockRedisClient()
    adapter = RedisStreamsQueueAdapter(RedisStreamsQueueSettings(), redis_client=client)
    # redis_client injected → _owns_client=False — cleanup does NOT null the ref
    await adapter.cleanup()
    assert adapter._client is client


@pytest.mark.asyncio
async def test_pubsub_publish() -> None:
    client = MockPubSubRedisClient()
    adapter = RedisStreamsQueueAdapter(RedisStreamsQueueSettings(), redis_client=client)
    await adapter.init()
    result = await adapter.pubsub_publish("chan", "hello")
    assert result == 1


@pytest.mark.asyncio
async def test_pubsub_publish_bytes() -> None:
    client = MockPubSubRedisClient()
    adapter = RedisStreamsQueueAdapter(RedisStreamsQueueSettings(), redis_client=client)
    await adapter.init()
    result = await adapter.pubsub_publish("chan", b"raw")
    assert result == 1


@pytest.mark.asyncio
async def test_pubsub_subscribe_channel() -> None:
    messages = [{"channel": b"events:x", "data": b"payload"}]
    client = MockPubSubRedisClient(messages=messages)
    adapter = RedisStreamsQueueAdapter(RedisStreamsQueueSettings(), redis_client=client)
    await adapter.init()

    received: list[tuple[str, bytes]] = []

    async def cb(channel: str, data: bytes) -> None:
        received.append((channel, data))

    task = await adapter.pubsub_subscribe(channel="events:x", callback=cb)
    await task
    assert ("events:x", b"payload") in received


@pytest.mark.asyncio
async def test_pubsub_subscribe_pattern() -> None:
    messages = [{"channel": "events:y", "data": "text-data"}]
    client = MockPubSubRedisClient(messages=messages)
    adapter = RedisStreamsQueueAdapter(RedisStreamsQueueSettings(), redis_client=client)
    await adapter.init()

    received: list[tuple[str, bytes]] = []

    def sync_cb(channel: str, data: bytes) -> None:
        received.append((channel, data))

    task = await adapter.pubsub_subscribe(pattern="events:*", callback=sync_cb)
    await task
    assert ("events:y", b"text-data") in received


@pytest.mark.asyncio
async def test_pubsub_skips_invalid_messages() -> None:
    """Messages missing channel or data are silently skipped."""
    messages = [
        {"channel": None, "data": b"orphan"},
        {"channel": b"ch", "data": None},
        "not-a-mapping",  # type: ignore[list-item]
        {"channel": b"ok", "data": b"good"},
    ]
    client = MockPubSubRedisClient(messages=messages)  # type: ignore[arg-type]
    adapter = RedisStreamsQueueAdapter(RedisStreamsQueueSettings(), redis_client=client)
    await adapter.init()

    received: list[tuple[str, bytes]] = []

    async def cb(channel: str, data: bytes) -> None:
        received.append((channel, data))

    task = await adapter.pubsub_subscribe(channel="ok", callback=cb)
    await task
    assert received == [("ok", b"good")]


@pytest.mark.asyncio
async def test_pubsub_no_pubsub_factory_raises() -> None:
    """Adapter raises if the client has no pubsub() method."""
    client = MockRedisClient()  # no pubsub()
    adapter = RedisStreamsQueueAdapter(RedisStreamsQueueSettings(), redis_client=client)
    await adapter.init()

    async def cb(channel: str, data: bytes) -> None:
        pass

    with pytest.raises(LifecycleError):
        await adapter.pubsub_subscribe(channel="x", callback=cb)


@pytest.mark.asyncio
async def test_format_entries_skips_wrong_stream() -> None:
    client = MockRedisClient()
    adapter = RedisStreamsQueueAdapter(
        RedisStreamsQueueSettings(stream="correct"), redis_client=client
    )
    await adapter.init()
    raw = [("wrong-stream", [("0-1", {"k": "v"})]), ("correct", [("0-2", {"k": "v"})])]
    result = adapter._format_entries(raw)
    assert len(result) == 1
    assert result[0]["message_id"] == "0-2"


@pytest.mark.asyncio
async def test_read_uses_default_block_ms() -> None:
    client = MockRedisClient()
    adapter = RedisStreamsQueueAdapter(
        RedisStreamsQueueSettings(block_ms=500), redis_client=client
    )
    await adapter.init()
    # No messages — returns empty list (our mock doesn't actually sleep)
    msgs = await adapter.read()
    assert msgs == []


def test_settings_defaults() -> None:
    s = RedisStreamsQueueSettings()
    assert s.stream == "oneiric-queue"
    assert s.group == "oneiric"
    assert s.auto_create_group is True
    assert s.block_ms == 1000


# ---------------------------------------------------------------------------
# Tests — coverage gaps (lines 98, 138, 144)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_init_from_url_when_no_client_injected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """init() calls Redis.from_url when no client is injected (line 98)."""
    client = MockRedisClient()

    class FakeRedis:
        @classmethod
        def from_url(cls, url: str, **kw: Any) -> MockRedisClient:
            return client

    monkeypatch.setattr("oneiric.adapters.queue.redis_streams.Redis", FakeRedis)

    adapter = RedisStreamsQueueAdapter(
        RedisStreamsQueueSettings(url="redis://localhost:6379/0")
    )
    await adapter.init()
    assert adapter._client is client
    adapter._owns_client = False
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_close_client_connection_awaitable_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_close_client_connection awaits close() when it returns a coroutine (line 138)."""
    closed: list[bool] = []

    class AsyncCloseClient(MockRedisClient):
        async def close(self) -> None:
            closed.append(True)

    client = AsyncCloseClient()
    adapter = RedisStreamsQueueAdapter(RedisStreamsQueueSettings(), redis_client=client)
    adapter._owns_client = True
    await adapter.init()
    await adapter._close_client_connection()
    assert closed == [True]


@pytest.mark.asyncio
async def test_disconnect_pool_awaitable_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_disconnect_connection_pool awaits disconnect() when it returns a coroutine (line 144)."""
    disconnected: list[bool] = []

    class AsyncPool:
        async def disconnect(self) -> None:
            disconnected.append(True)

    client = MockRedisClient()
    client.connection_pool = AsyncPool()  # type: ignore[assignment]
    adapter = RedisStreamsQueueAdapter(RedisStreamsQueueSettings(), redis_client=client)
    adapter._owns_client = True
    await adapter.init()
    await adapter._disconnect_connection_pool()
    assert disconnected == [True]
