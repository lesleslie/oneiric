"""Kafka queue adapter built on aiokafka."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from pydantic import BaseModel, Field, SecretStr

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class KafkaQueueSettings(BaseModel):
    """Configuration for the Kafka adapter."""

    bootstrap_servers: Sequence[str] | str = Field(
        default_factory=lambda: ["localhost:9092"],
        description="Kafka bootstrap servers.",
    )
    topic: str = Field(
        default="oneiric-events",
        description="Topic used for publish/consume operations.",
    )
    group_id: str = Field(
        default="oneiric-consumer", description="Consumer group identifier."
    )
    client_id: str = Field(default="oneiric", description="Kafka client identifier.")
    auto_offset_reset: str = Field(
        default="latest",
        description="Offset reset policy (latest or earliest).",
    )
    security_protocol: str | None = Field(
        default=None, description="Kafka security protocol (e.g., SASL_SSL)."
    )
    sasl_mechanism: str | None = Field(
        default=None, description="SASL mechanism when using SASL_* protocols."
    )
    sasl_username: str | None = Field(default=None, description="SASL username.")
    sasl_password: SecretStr | None = Field(
        default=None, description="SASL password/secret."
    )
    produce_timeout: float = Field(
        default=30.0, gt=0.0, description="Timeout (seconds) for publish operations."
    )
    consume_timeout_ms: int = Field(
        default=1000,
        ge=0,
        description="Timeout (milliseconds) for consumer getmany calls.",
    )
    consume_max_records: int = Field(
        default=50,
        ge=1,
        description="Maximum records to fetch per getmany call.",
    )


class KafkaQueueAdapter:
    """Adapter that publishes to and consumes from Kafka topics."""

    metadata = AdapterMetadata(
        category="queue",
        provider="kafka",
        factory="oneiric.adapters.queue.kafka:KafkaQueueAdapter",
        capabilities=["queue", "streaming", "fanout"],
        stack_level=20,
        priority=310,
        source=CandidateSource.LOCAL_PKG,
        owner="Messaging",
        requires_secrets=True,
        settings_model=KafkaQueueSettings,
    )

    def __init__(
        self,
        settings: KafkaQueueSettings | None = None,
        *,
        producer_factory: Callable[..., Any] | None = None,
        consumer_factory: Callable[..., Any] | None = None,
        topic_partition_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._settings = settings or KafkaQueueSettings()
        self._producer_factory = producer_factory
        self._consumer_factory = consumer_factory
        self._topic_partition_factory = topic_partition_factory
        self._producer: Any | None = None
        self._consumer: Any | None = None
        self._logger = get_logger("adapter.queue.kafka").bind(
            domain="adapter",
            key="queue",
            provider="kafka",
            topic=self._settings.topic,
        )

    async def init(self) -> None:
        await self._ensure_producer()
        await self._ensure_consumer()
        self._logger.info("queue-adapter-init", provider="kafka")

    async def health(self) -> bool:
        try:
            producer = await self._ensure_producer()
            get_partitions = getattr(producer, "partitions_for", None)
            if callable(get_partitions):
                partitions = await get_partitions(self._settings.topic)
                if partitions is None:
                    raise RuntimeError("topic-not-found")
            return True
        except Exception as exc:  # pragma: no cover - network
            self._logger.warning("kafka-health-check-failed", error=str(exc))
            return False

    async def cleanup(self) -> None:
        if self._producer:
            await self._stop_component(self._producer)
            self._producer = None
        if self._consumer:
            await self._stop_component(self._consumer)
            self._consumer = None
        self._logger.info("queue-adapter-cleanup", provider="kafka")

    async def publish(
        self,
        value: bytes,
        *,
        key: bytes | None = None,
        headers: Mapping[str, bytes] | None = None,
    ) -> None:
        producer = await self._ensure_producer()
        header_list = list((headers or {}).items())
        await producer.send_and_wait(
            self._settings.topic,
            value=value,
            key=key,
            headers=header_list,
            timeout=self._settings.produce_timeout,
        )
        self._logger.debug("kafka-publish", topic=self._settings.topic, key=key)

    async def consume(self) -> list[dict[str, Any]]:
        consumer = await self._ensure_consumer()
        records = await consumer.getmany(
            timeout_ms=self._settings.consume_timeout_ms,
            max_records=self._settings.consume_max_records,
        )
        messages: list[dict[str, Any]] = []
        for tp, msgs in records.items():
            for msg in msgs:
                messages.append(
                    {
                        "topic": tp.topic,
                        "partition": tp.partition,
                        "offset": msg.offset,
                        "key": msg.key,
                        "value": msg.value,
                        "timestamp": msg.timestamp,
                        "headers": dict(msg.headers or []),
                    }
                )
        return messages

    async def commit(self, offsets: Sequence[dict[str, Any]]) -> None:
        if not offsets:
            return
        consumer = await self._ensure_consumer()
        tp_offsets = {
            self._topic_partition(item["topic"], item["partition"]): item["offset"]
            for item in offsets
        }
        await consumer.commit(offsets=tp_offsets)

    def _topic_partition(self, topic: str, partition: int) -> Any:
        if self._topic_partition_factory:
            return self._topic_partition_factory(topic, partition)
        try:
            from aiokafka.structs import (
                TopicPartition,  # type: ignore  # pragma: no cover - optional dep
            )
        except ModuleNotFoundError as exc:  # pragma: no cover - optional dep
            raise LifecycleError(
                "aiokafka-not-installed: install optional extra 'oneiric[queue-kafka]' to use KafkaQueueAdapter"
            ) from exc
        return TopicPartition(topic, partition)

    async def _ensure_producer(self) -> Any:
        if self._producer:
            return self._producer
        if self._producer_factory:
            producer = self._producer_factory(**self._producer_kwargs())
        else:
            producer = self._create_aiokafka_producer()
        await self._start_component(producer)
        self._producer = producer
        return producer

    async def _ensure_consumer(self) -> Any:
        if self._consumer:
            return self._consumer
        if self._consumer_factory:
            consumer = self._consumer_factory(**self._consumer_kwargs())
        else:
            consumer = self._create_aiokafka_consumer()
        await self._start_component(consumer)
        self._consumer = consumer
        return consumer

    def _create_aiokafka_producer(self) -> Any:
        try:
            from aiokafka import AIOKafkaProducer  # type: ignore
        except ModuleNotFoundError as exc:  # pragma: no cover - optional dep
            raise LifecycleError(
                "aiokafka-not-installed: install optional extra 'oneiric[queue-kafka]' to use KafkaQueueAdapter"
            ) from exc
        return AIOKafkaProducer(**self._producer_kwargs())

    def _create_aiokafka_consumer(self) -> Any:
        try:
            from aiokafka import AIOKafkaConsumer  # type: ignore
        except ModuleNotFoundError as exc:  # pragma: no cover - optional dep
            raise LifecycleError(
                "aiokafka-not-installed: install optional extra 'oneiric[queue-kafka]' to use KafkaQueueAdapter"
            ) from exc
        return AIOKafkaConsumer(**self._consumer_kwargs())

    def _producer_kwargs(self) -> dict[str, Any]:
        kwargs = self._security_kwargs()
        kwargs.update(
            {
                "bootstrap_servers": self._settings.bootstrap_servers,
                "client_id": self._settings.client_id,
            }
        )
        return kwargs

    def _consumer_kwargs(self) -> dict[str, Any]:
        kwargs = self._security_kwargs()
        kwargs.update(
            {
                "bootstrap_servers": self._settings.bootstrap_servers,
                "client_id": self._settings.client_id,
                "group_id": self._settings.group_id,
                "auto_offset_reset": self._settings.auto_offset_reset,
                "enable_auto_commit": False,
                "topics": [self._settings.topic],
            }
        )
        return kwargs

    def _security_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if self._settings.security_protocol:
            kwargs["security_protocol"] = self._settings.security_protocol
        if self._settings.sasl_mechanism:
            kwargs["sasl_mechanism"] = self._settings.sasl_mechanism
        if self._settings.sasl_username:
            kwargs["sasl_plain_username"] = self._settings.sasl_username
        if self._settings.sasl_password:
            kwargs["sasl_plain_password"] = (
                self._settings.sasl_password.get_secret_value()
            )
        return kwargs

    async def _start_component(self, component: Any) -> None:
        start = getattr(component, "start", None)
        if not callable(start):
            raise LifecycleError("kafka-component-missing-start")
        result = start()
        if inspect.isawaitable(result):
            await result

    async def _stop_component(self, component: Any) -> None:
        stop = getattr(component, "stop", None)
        if not callable(stop):
            return
        result = stop()
        if inspect.isawaitable(result):
            await result
