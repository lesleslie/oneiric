"""Tests for Kafka queue adapter."""

from __future__ import annotations

from typing import Any

import pytest

from oneiric.adapters.queue.kafka import KafkaQueueAdapter, KafkaQueueSettings


class FakeProducer:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.sent: list[dict[str, Any]] = []

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def send_and_wait(
        self,
        topic: str,
        value: bytes,
        key: bytes | None,
        headers: list,
        timeout: float,
    ) -> None:
        self.sent.append(
            {
                "topic": topic,
                "value": value,
                "key": key,
                "headers": headers,
                "timeout": timeout,
            }
        )

    async def partitions_for(self, topic: str) -> list[int]:
        return [0]


class FakeMessage:
    def __init__(
        self, topic: str, partition: int, offset: int, key: bytes, value: bytes
    ) -> None:
        self.topic = topic
        self.partition = partition
        self.offset = offset
        self.key = key
        self.value = value
        self.timestamp = 0
        self.headers = [("x", b"1")]


class FakeTopicPartition:
    def __init__(self, topic: str, partition: int) -> None:
        self.topic = topic
        self.partition = partition


class FakeConsumer:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.records: dict[Any, list[FakeMessage]] = {}
        self.committed: dict[Any, int] = {}

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def getmany(self, timeout_ms: int, max_records: int) -> dict[Any, list[Any]]:
        return self.records

    async def commit(self, offsets: dict[Any, int]) -> None:
        self.committed.update(offsets)


@pytest.fixture()
def fake_producer() -> FakeProducer:
    return FakeProducer()


@pytest.fixture()
def fake_consumer() -> FakeConsumer:
    return FakeConsumer()


@pytest.fixture()
def adapter(
    fake_producer: FakeProducer, fake_consumer: FakeConsumer
) -> KafkaQueueAdapter:
    settings = KafkaQueueSettings(topic="demo-topic")

    def producer_factory(**_: Any) -> FakeProducer:
        return fake_producer

    def consumer_factory(**_: Any) -> FakeConsumer:
        fake_consumer.records = {
            FakeTopicPartition("demo-topic", 0): [
                FakeMessage("demo-topic", 0, 1, b"k", b"payload"),
            ]
        }
        return fake_consumer

    def tp_factory(topic: str, partition: int) -> tuple[str, int]:
        return (topic, partition)

    return KafkaQueueAdapter(
        settings,
        producer_factory=producer_factory,
        consumer_factory=consumer_factory,
        topic_partition_factory=tp_factory,
    )


@pytest.mark.asyncio()
async def test_publish_and_consume(
    adapter: KafkaQueueAdapter, fake_producer: FakeProducer, fake_consumer: FakeConsumer
) -> None:
    await adapter.init()
    await adapter.publish(b"hello", key=b"id", headers={"h": b"1"})
    messages = await adapter.consume()

    assert fake_producer.started is True
    assert fake_consumer.started is True
    assert fake_producer.sent[0]["value"] == b"hello"
    assert messages[0]["value"] == b"payload"


@pytest.mark.asyncio()
async def test_commit(adapter: KafkaQueueAdapter, fake_consumer: FakeConsumer) -> None:
    await adapter.init()
    await adapter.commit([{"topic": "demo-topic", "partition": 0, "offset": 5}])
    assert fake_consumer.committed[("demo-topic", 0)] == 5


@pytest.mark.asyncio()
async def test_cleanup(
    adapter: KafkaQueueAdapter, fake_producer: FakeProducer, fake_consumer: FakeConsumer
) -> None:
    await adapter.init()
    await adapter.cleanup()
    assert fake_producer.stopped is True
    assert fake_consumer.stopped is True
