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
