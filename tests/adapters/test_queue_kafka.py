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


# ---------------------------------------------------------------------------
# Tests — coverage gaps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_health_returns_true(adapter: KafkaQueueAdapter) -> None:
    """health() calls partitions_for and returns True (lines 98-105)."""
    await adapter.init()
    assert await adapter.health() is True


@pytest.mark.asyncio()
async def test_commit_empty_offsets_returns_early() -> None:
    """commit() returns immediately when offsets is empty (line 161)."""
    adapter = KafkaQueueAdapter(KafkaQueueSettings())
    # No init needed — early return before _ensure_consumer
    await adapter.commit([])


@pytest.mark.asyncio()
async def test_topic_partition_via_factory() -> None:
    """_topic_partition uses factory when provided (lines 172-173)."""
    created: list[tuple[str, int]] = []

    def tp_factory(topic: str, partition: int) -> tuple[str, int]:
        created.append((topic, partition))
        return (topic, partition)

    adapter = KafkaQueueAdapter(
        KafkaQueueSettings(),
        topic_partition_factory=tp_factory,
        producer_factory=lambda **_: FakeProducer(),
        consumer_factory=lambda **_: FakeConsumer(),
    )
    result = adapter._topic_partition("my-topic", 2)
    assert result == ("my-topic", 2)
    assert created == [("my-topic", 2)]


@pytest.mark.asyncio()
async def test_aiokafka_producer_and_consumer_via_sys_modules(monkeypatch) -> None:
    """_create_aiokafka_producer/_consumer import aiokafka from sys.modules (lines 205-220)."""
    import sys
    import types

    fake_producer = FakeProducer()
    fake_consumer = FakeConsumer()

    class FakeAIOKafkaProducer:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def start(self) -> None:
            fake_producer.started = True

        async def stop(self) -> None:
            pass

        async def send_and_wait(self, *a: Any, **kw: Any) -> None:
            pass

    class FakeAIOKafkaConsumer:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def start(self) -> None:
            fake_consumer.started = True

        async def stop(self) -> None:
            pass

        async def getmany(self, **kwargs: Any) -> dict:
            return {}

    fake_aiokafka = types.ModuleType("aiokafka")
    fake_aiokafka.AIOKafkaProducer = FakeAIOKafkaProducer  # type: ignore[attr-defined]
    fake_aiokafka.AIOKafkaConsumer = FakeAIOKafkaConsumer  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "aiokafka", fake_aiokafka)

    adapter = KafkaQueueAdapter(KafkaQueueSettings(topic="t"))
    await adapter.init()
    assert fake_producer.started is True
    assert fake_consumer.started is True


@pytest.mark.asyncio()
async def test_topic_partition_via_sys_modules(monkeypatch) -> None:
    """_topic_partition imports from aiokafka.structs (lines 172-180)."""
    import sys
    import types

    class FakeTopicPartitionCls:
        def __init__(self, topic: str, partition: int) -> None:
            self.topic = topic
            self.partition = partition

    fake_structs = types.ModuleType("aiokafka.structs")
    fake_structs.TopicPartition = FakeTopicPartitionCls  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "aiokafka.structs", fake_structs)

    adapter = KafkaQueueAdapter(KafkaQueueSettings())
    result = adapter._topic_partition("my-topic", 1)
    assert isinstance(result, FakeTopicPartitionCls)
    assert result.topic == "my-topic"


def test_security_kwargs_with_all_sasl_options() -> None:
    """_security_kwargs includes all SASL fields when set (lines 249, 251, 253, 255)."""
    from pydantic import SecretStr

    adapter = KafkaQueueAdapter(
        KafkaQueueSettings(
            security_protocol="SASL_SSL",
            sasl_mechanism="PLAIN",
            sasl_username="user",
            sasl_password=SecretStr("pass"),
        )
    )
    kwargs = adapter._security_kwargs()
    assert kwargs["security_protocol"] == "SASL_SSL"
    assert kwargs["sasl_mechanism"] == "PLAIN"
    assert kwargs["sasl_plain_username"] == "user"
    assert kwargs["sasl_plain_password"] == "pass"


@pytest.mark.asyncio()
async def test_start_component_sync_callable() -> None:
    """_start_component handles synchronous start() (line 263 — non-awaitable)."""
    started: list[bool] = []

    class SyncComponent:
        def start(self) -> None:
            started.append(True)

        def stop(self) -> None:
            pass

    adapter = KafkaQueueAdapter(KafkaQueueSettings())
    await adapter._start_component(SyncComponent())
    assert started == [True]


@pytest.mark.asyncio()
async def test_stop_component_sync_callable() -> None:
    """_stop_component handles synchronous stop() (line 271 — non-awaitable)."""
    stopped: list[bool] = []

    class SyncComponent:
        def stop(self) -> None:
            stopped.append(True)

    adapter = KafkaQueueAdapter(KafkaQueueSettings())
    await adapter._stop_component(SyncComponent())
    assert stopped == [True]


@pytest.mark.asyncio()
async def test_health_partitions_for_returns_none_raises() -> None:
    """health() raises RuntimeError when partitions_for returns None (line 104)."""

    class NonePartitionsProducer(FakeProducer):
        async def partitions_for(self, topic: str) -> None:  # type: ignore[override]
            return None

    adapter = KafkaQueueAdapter(
        KafkaQueueSettings(),
        producer_factory=lambda **_: NonePartitionsProducer(),
        consumer_factory=lambda **_: FakeConsumer(),
    )
    await adapter.init()
    # health() catches the RuntimeError internally and returns False
    assert await adapter.health() is False


@pytest.mark.asyncio()
async def test_start_component_raises_when_no_start_method() -> None:
    """_start_component raises LifecycleError when component has no start (line 263)."""
    from oneiric.core.lifecycle import LifecycleError

    class NoStartComponent:
        pass

    adapter = KafkaQueueAdapter(KafkaQueueSettings())
    with pytest.raises(LifecycleError, match="kafka-component-missing-start"):
        await adapter._start_component(NoStartComponent())


@pytest.mark.asyncio()
async def test_stop_component_returns_when_no_stop_method() -> None:
    """_stop_component returns silently when component has no stop (line 271)."""

    class NoStopComponent:
        pass

    adapter = KafkaQueueAdapter(KafkaQueueSettings())
    # Should not raise
    await adapter._stop_component(NoStopComponent())


@pytest.mark.asyncio()
async def test_ensure_producer_aiokafka_path_is_cached(monkeypatch) -> None:
    """_ensure_producer returns cached producer on second call (line 188 branch skip)."""
    import sys
    import types

    call_count = 0

    class FakeAIOKafkaProducer:
        def __init__(self, **kwargs: Any) -> None:
            nonlocal call_count
            call_count += 1

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

    fake_aiokafka = types.ModuleType("aiokafka")
    fake_aiokafka.AIOKafkaProducer = FakeAIOKafkaProducer  # type: ignore[attr-defined]
    fake_aiokafka.AIOKafkaConsumer = FakeAIOKafkaProducer  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "aiokafka", fake_aiokafka)

    adapter = KafkaQueueAdapter(KafkaQueueSettings())
    p1 = await adapter._ensure_producer()
    p2 = await adapter._ensure_producer()
    assert p1 is p2
    assert call_count == 1
