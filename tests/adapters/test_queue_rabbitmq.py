"""Tests for RabbitMQ queue adapter."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from oneiric.adapters.queue.rabbitmq import RabbitMQQueueAdapter, RabbitMQQueueSettings


class FakeMessage:
    def __init__(self, body: bytes, headers: dict[str, Any] | None = None) -> None:
        self.body = body
        self.headers = headers or {}
        self.acked = False
        self.rejections: list[bool] = []

    async def ack(self) -> None:
        self.acked = True

    async def reject(self, requeue: bool = False) -> None:
        self.rejections.append(requeue)


class FakeQueue:
    def __init__(self) -> None:
        self.messages: asyncio.Queue[FakeMessage] = asyncio.Queue()
        self.declared_passive = False

    async def declare(self, passive: bool = False, **_: Any) -> None:
        if passive:
            self.declared_passive = True

    async def get(self, no_ack: bool = False) -> FakeMessage:
        message = await self.messages.get()
        if no_ack:
            message.acked = True
        return message

    def put(self, message: FakeMessage) -> None:
        self.messages.put_nowait(message)


class FakeExchange:
    def __init__(self) -> None:
        self.published: list[dict[str, Any]] = []

    async def publish(self, message: Any, routing_key: str) -> None:
        self.published.append({"message": message, "routing_key": routing_key})


class FakeChannel:
    def __init__(self, queue: FakeQueue) -> None:
        self.queue = queue
        self.default_exchange = FakeExchange()
        self.prefetch = None

    async def declare_queue(self, name: str, **kwargs: Any) -> FakeQueue:
        return self.queue

    async def declare_exchange(self, name: str, **kwargs: Any) -> FakeExchange:
        exchange = FakeExchange()
        self.default_exchange = exchange
        return exchange

    async def set_qos(self, prefetch_count: int) -> None:
        self.prefetch = prefetch_count

    async def close(self) -> None:
        return None


class FakeConnection:
    def __init__(self, channel: FakeChannel) -> None:
        self.channel_obj = channel
        self.closed = False

    async def channel(self) -> FakeChannel:
        return self.channel_obj

    async def close(self) -> None:
        self.closed = True


@pytest.fixture()
def fake_queue() -> FakeQueue:
    return FakeQueue()


@pytest.fixture()
def adapter(fake_queue: FakeQueue) -> RabbitMQQueueAdapter:
    channel = FakeChannel(fake_queue)
    connection = FakeConnection(channel)

    def connection_factory(kwargs: dict[str, Any]) -> FakeConnection:
        return connection

    def channel_factory() -> FakeChannel:
        return channel

    def queue_factory() -> FakeQueue:
        return fake_queue

    settings = RabbitMQQueueSettings(url="amqp://guest:guest@localhost/", queue="demo")
    return RabbitMQQueueAdapter(
        settings,
        connection_factory=connection_factory,
        channel_factory=channel_factory,
        queue_factory=queue_factory,
    )


@pytest.mark.asyncio()
async def test_publish_and_consume(
    adapter: RabbitMQQueueAdapter, fake_queue: FakeQueue
) -> None:
    await adapter.init()
    await adapter.publish(b"hello", headers={"x": "1"})
    assert adapter._channel.default_exchange.published[0]["message"].body == b"hello"

    fake_queue.put(FakeMessage(b"payload", {"y": "2"}))
    messages = await adapter.consume()
    assert messages[0]["body"] == b"payload"
    await adapter.ack(messages[0]["message"])
    assert messages[0]["message"].acked is True


@pytest.mark.asyncio()
async def test_reject(adapter: RabbitMQQueueAdapter, fake_queue: FakeQueue) -> None:
    await adapter.init()
    fake_queue.put(FakeMessage(b"payload"))
    msg = (await adapter.consume())[0]
    await adapter.reject(msg["message"], requeue=True)
    assert msg["message"].rejections == [True]


@pytest.mark.asyncio()
async def test_cleanup(adapter: RabbitMQQueueAdapter) -> None:
    await adapter.init()
    await adapter.cleanup()
    assert adapter._connection is None
    assert adapter._channel is None


# ---------------------------------------------------------------------------
# Tests — coverage gaps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_rabbitmq_health(
    adapter: RabbitMQQueueAdapter, fake_queue: FakeQueue
) -> None:
    """health() calls declare(passive=True) on queue (lines 93-98)."""
    await adapter.init()
    assert await adapter.health() is True
    assert fake_queue.declared_passive is True


@pytest.mark.asyncio()
async def test_rabbitmq_consume_timeout(adapter: RabbitMQQueueAdapter) -> None:
    """consume() breaks on TimeoutError when queue is empty (lines 132-133)."""
    await adapter.init()
    messages = await adapter.consume(limit=2)
    assert messages == []


@pytest.mark.asyncio()
async def test_rabbitmq_cleanup_closes_channel_and_connection() -> None:
    """cleanup() closes both _channel and _connection when set (lines 105-106, 108-109)."""
    fake_queue = FakeQueue()
    channel = FakeChannel(fake_queue)
    connection = FakeConnection(channel)

    # No channel/queue factory — forces _ensure_connection path, sets _connection and _channel
    adapter = RabbitMQQueueAdapter(
        RabbitMQQueueSettings(url="amqp://guest:guest@localhost/", queue="demo"),
        connection_factory=lambda kwargs: connection,
    )
    await adapter.init()
    assert adapter._channel is channel
    assert adapter._connection is connection
    await adapter.cleanup()
    assert adapter._channel is None
    assert adapter._connection is None


@pytest.mark.asyncio()
async def test_rabbitmq_ensure_connection_caches_result() -> None:
    """_ensure_connection returns cached connection on second call (line 158-159)."""
    channel = FakeChannel(FakeQueue())
    connection = FakeConnection(channel)

    adapter = RabbitMQQueueAdapter(
        RabbitMQQueueSettings(),
        connection_factory=lambda kwargs: connection,
    )
    conn1 = await adapter._ensure_connection()
    conn2 = await adapter._ensure_connection()
    assert conn1 is conn2


@pytest.mark.asyncio()
async def test_rabbitmq_awaitable_connection_factory() -> None:
    """_ensure_connection awaits when connection_factory returns a coroutine (line 170-171)."""
    channel = FakeChannel(FakeQueue())
    connection = FakeConnection(channel)

    async def async_factory(kwargs: dict) -> FakeConnection:
        return connection

    adapter = RabbitMQQueueAdapter(
        RabbitMQQueueSettings(),
        connection_factory=async_factory,
    )
    conn = await adapter._ensure_connection()
    assert conn is connection


@pytest.mark.asyncio()
async def test_rabbitmq_awaitable_channel_factory() -> None:
    """_ensure_channel awaits when channel_factory returns a coroutine (line 180-181)."""
    fake_queue = FakeQueue()
    channel = FakeChannel(fake_queue)

    async def async_channel_factory() -> FakeChannel:
        return channel

    adapter = RabbitMQQueueAdapter(
        RabbitMQQueueSettings(),
        channel_factory=async_channel_factory,
        queue_factory=lambda: fake_queue,
    )
    await adapter.init()
    chan = await adapter._ensure_channel()
    assert chan is channel


@pytest.mark.asyncio()
async def test_rabbitmq_awaitable_queue_factory() -> None:
    """_ensure_queue awaits when queue_factory returns a coroutine (line 194-195)."""
    fake_queue = FakeQueue()

    async def async_queue_factory() -> FakeQueue:
        return fake_queue

    channel = FakeChannel(fake_queue)
    adapter = RabbitMQQueueAdapter(
        RabbitMQQueueSettings(),
        channel_factory=lambda: channel,
        queue_factory=async_queue_factory,
    )
    await adapter.init()
    assert adapter._queue is fake_queue


@pytest.mark.asyncio()
async def test_rabbitmq_ensure_channel_no_factory_uses_connection() -> None:
    """_ensure_channel without channel_factory calls _ensure_connection (lines 183-185)."""
    fake_queue = FakeQueue()
    channel = FakeChannel(fake_queue)
    connection = FakeConnection(channel)

    adapter = RabbitMQQueueAdapter(
        RabbitMQQueueSettings(),
        connection_factory=lambda kwargs: connection,
        queue_factory=lambda: fake_queue,
    )
    await adapter.init()
    chan = await adapter._ensure_channel()
    assert chan is channel
    assert adapter._connection is connection


@pytest.mark.asyncio()
async def test_rabbitmq_ensure_queue_no_factory_uses_channel() -> None:
    """_ensure_queue without queue_factory calls declare_queue via channel (lines 197-202)."""
    fake_queue = FakeQueue()
    channel = FakeChannel(fake_queue)

    adapter = RabbitMQQueueAdapter(
        RabbitMQQueueSettings(),
        channel_factory=lambda: channel,
        # no queue_factory — forces declare_queue path
    )
    await adapter.init()
    assert adapter._queue is fake_queue


@pytest.mark.asyncio()
async def test_rabbitmq_ensure_queue_returns_cached() -> None:
    """_ensure_queue returns cached queue on second call (line 190-191)."""
    fake_queue = FakeQueue()
    adapter = RabbitMQQueueAdapter(
        RabbitMQQueueSettings(),
        queue_factory=lambda: fake_queue,
    )
    q1 = await adapter._ensure_queue()
    q2 = await adapter._ensure_queue()
    assert q1 is q2


@pytest.mark.asyncio()
async def test_rabbitmq_ensure_exchange_named() -> None:
    """_ensure_exchange returns declared exchange when settings.exchange is set (line 208)."""
    fake_queue = FakeQueue()
    channel = FakeChannel(fake_queue)

    adapter = RabbitMQQueueAdapter(
        RabbitMQQueueSettings(exchange="my-exchange"),
        channel_factory=lambda: channel,
        queue_factory=lambda: fake_queue,
    )
    await adapter.init()
    exchange = await adapter._ensure_exchange(channel)
    assert exchange is channel.default_exchange


@pytest.mark.asyncio()
async def test_rabbitmq_close_component_sync_close() -> None:
    """_close_component handles sync close() method (lines 225-230)."""
    closed: list[bool] = []

    class SyncCloseable:
        def close(self) -> None:
            closed.append(True)

    adapter = RabbitMQQueueAdapter(RabbitMQQueueSettings())
    await adapter._close_component(SyncCloseable())
    assert closed == [True]


@pytest.mark.asyncio()
async def test_rabbitmq_close_component_no_close() -> None:
    """_close_component skips objects without close() (line 226-227)."""
    adapter = RabbitMQQueueAdapter(RabbitMQQueueSettings())
    await adapter._close_component(object())  # must not raise


def test_rabbitmq_connection_kwargs_with_ssl_and_options() -> None:
    """_connection_kwargs includes ssl and ssl_options when ssl=True (lines 243-246)."""
    adapter = RabbitMQQueueAdapter(
        RabbitMQQueueSettings(ssl=True, ssl_options={"ca_certs": "/path/ca.pem"})
    )
    kwargs = adapter._connection_kwargs()
    assert kwargs["ssl"] is True
    assert kwargs["ssl_options"] == {"ca_certs": "/path/ca.pem"}


def test_rabbitmq_connection_kwargs_with_credentials_secret() -> None:
    """_connection_kwargs uses credentials_secret.get_secret_value() when set (line 234-236)."""
    from pydantic import SecretStr

    adapter = RabbitMQQueueAdapter(
        RabbitMQQueueSettings(credentials_secret=SecretStr("amqp://secret-url/"))
    )
    kwargs = adapter._connection_kwargs()
    assert kwargs["url"] == "amqp://secret-url/"


@pytest.mark.asyncio()
async def test_rabbitmq_ensure_channel_returns_cached_on_second_call() -> None:
    """_ensure_channel returns cached _channel without re-creating (line 177)."""
    fake_queue = FakeQueue()
    channel = FakeChannel(fake_queue)

    adapter = RabbitMQQueueAdapter(
        RabbitMQQueueSettings(),
        channel_factory=lambda: channel,
        queue_factory=lambda: fake_queue,
    )
    chan1 = await adapter._ensure_channel()
    chan2 = await adapter._ensure_channel()  # hits line 177 (early return)
    assert chan1 is chan2


@pytest.mark.asyncio()
async def test_rabbitmq_ensure_connection_uses_aio_pika(monkeypatch) -> None:
    """_ensure_connection imports aio_pika when no factory (lines 163-169)."""
    import sys

    fake_queue = FakeQueue()
    channel = FakeChannel(fake_queue)
    connection = FakeConnection(channel)

    class FakeAioPika:
        @staticmethod
        async def connect_robust(**kwargs: Any) -> FakeConnection:
            return connection

    monkeypatch.setitem(sys.modules, "aio_pika", FakeAioPika)  # type: ignore[arg-type]

    adapter = RabbitMQQueueAdapter(
        RabbitMQQueueSettings(),
        channel_factory=lambda: channel,
        queue_factory=lambda: fake_queue,
        # No connection_factory — forces aio_pika import path
    )
    conn = await adapter._ensure_connection()
    assert conn is connection


@pytest.mark.asyncio()
async def test_rabbitmq_build_message_uses_aio_pika(monkeypatch) -> None:
    """_build_message imports aio_pika.Message when no channel_factory (lines 216-222)."""
    import sys

    fake_queue = FakeQueue()

    class FakeMessage:
        def __init__(self, body: bytes, headers: dict) -> None:
            self.body = body
            self.headers = headers

    class FakeAioPika:
        Message = FakeMessage

        @staticmethod
        async def connect_robust(**kwargs: Any) -> Any:
            raise RuntimeError("should not be called")

    monkeypatch.setitem(sys.modules, "aio_pika", FakeAioPika)  # type: ignore[arg-type]

    channel = FakeChannel(fake_queue)
    adapter = RabbitMQQueueAdapter(
        RabbitMQQueueSettings(),
        # No channel_factory — forces aio_pika.Message path
        queue_factory=lambda: fake_queue,
        channel_factory=lambda: channel,
    )
    # Call _build_message with no channel_factory set
    adapter._channel_factory = None  # clear it to force aio_pika path
    msg = await adapter._build_message(b"hi", {"k": "v"})
    assert isinstance(msg, FakeMessage)
    assert msg.body == b"hi"


def test_rabbitmq_connection_kwargs_ssl_no_options() -> None:
    """_connection_kwargs sets ssl=True without ssl_options when ssl_options is None (line 244)."""
    adapter = RabbitMQQueueAdapter(RabbitMQQueueSettings(ssl=True))
    kwargs = adapter._connection_kwargs()
    assert kwargs["ssl"] is True
    assert "ssl_options" not in kwargs
