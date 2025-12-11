"""RabbitMQ queue adapter built on aio-pika."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field, SecretStr

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class RabbitMQQueueSettings(BaseModel):
    """Configuration for the RabbitMQ adapter."""

    url: str = Field(
        default="amqp://guest:guest@localhost/", description="AMQP connection URL."
    )
    queue: str = Field(
        default="oneiric-queue",
        description="Queue name used for publish/consume operations.",
    )
    exchange: str = Field(default="", description="Exchange name (empty for default).")
    routing_key: str | None = Field(
        default=None, description="Routing key used when publishing."
    )
    prefetch_count: int = Field(default=10, ge=1, description="Channel prefetch count.")
    durable: bool = Field(default=True, description="Declare the queue as durable.")
    passive: bool = Field(
        default=False, description="Use passive declaration (fail if queue missing)."
    )
    consume_timeout: float = Field(
        default=1.0, ge=0.0, description="Timeout in seconds for consume operations."
    )
    reconnect_interval: float = Field(
        default=5.0, ge=0.0, description="Interval for aio-pika reconnects."
    )
    heartbeat: float = Field(
        default=60.0, ge=0.0, description="AMQP heartbeat setting."
    )
    ssl: bool = Field(default=False, description="Enable SSL/TLS.")
    ssl_options: dict[str, Any] | None = Field(
        default=None, description="Custom SSL options passed to aio-pika."
    )
    credentials_secret: SecretStr | None = Field(
        default=None,
        description="Optional secret (amqp URL override) loaded via Secret Manager.",
    )


class RabbitMQQueueAdapter:
    """Adapter that publishes to and consumes from RabbitMQ queues."""

    metadata = AdapterMetadata(
        category="queue",
        provider="rabbitmq",
        factory="oneiric.adapters.queue.rabbitmq:RabbitMQQueueAdapter",
        capabilities=["queue", "streaming"],
        stack_level=20,
        priority=320,
        source=CandidateSource.LOCAL_PKG,
        owner="Messaging",
        requires_secrets=True,
        settings_model=RabbitMQQueueSettings,
    )

    def __init__(
        self,
        settings: RabbitMQQueueSettings | None = None,
        *,
        connection_factory: Callable[..., Any] | None = None,
        channel_factory: Callable[..., Any] | None = None,
        queue_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._settings = settings or RabbitMQQueueSettings()
        self._connection_factory = connection_factory
        self._channel_factory = channel_factory
        self._queue_factory = queue_factory
        self._connection: Any | None = None
        self._channel: Any | None = None
        self._queue: Any | None = None
        self._logger = get_logger("adapter.queue.rabbitmq").bind(
            domain="adapter",
            key="queue",
            provider="rabbitmq",
            queue=self._settings.queue,
        )

    async def init(self) -> None:
        await self._ensure_queue()
        self._logger.info("queue-adapter-init", provider="rabbitmq")

    async def health(self) -> bool:
        try:
            queue = await self._ensure_queue()
            declare = getattr(queue, "declare", None)
            if callable(declare):
                await declare(passive=True)
            return True
        except Exception as exc:  # pragma: no cover - network
            self._logger.warning("rabbitmq-health-check-failed", error=str(exc))
            return False

    async def cleanup(self) -> None:
        if self._channel:
            await self._close_component(self._channel)
            self._channel = None
        if self._connection:
            await self._close_component(self._connection)
            self._connection = None
        self._queue = None
        self._logger.info("queue-adapter-cleanup", provider="rabbitmq")

    async def publish(
        self, body: bytes, *, headers: dict[str, Any] | None = None
    ) -> None:
        channel = await self._ensure_channel()
        message = await self._build_message(body, headers or {})
        exchange = await self._ensure_exchange(channel)
        routing_key = self._settings.routing_key or self._settings.queue
        await exchange.publish(message, routing_key=routing_key)
        self._logger.debug("rabbitmq-publish", queue=self._settings.queue)

    async def consume(self, *, limit: int = 1) -> list[dict[str, Any]]:
        queue = await self._ensure_queue()
        messages: list[dict[str, Any]] = []
        for _ in range(limit):
            try:
                message = await asyncio.wait_for(
                    queue.get(no_ack=False),
                    timeout=self._settings.consume_timeout or None,
                )
            except TimeoutError:
                break
            messages.append(
                {
                    "body": bytes(message.body),
                    "headers": dict(message.headers or {}),
                    "message": message,
                }
            )
        return messages

    async def ack(self, message: Any) -> None:
        ack = getattr(message, "ack", None)
        if callable(ack):
            result = ack()
            if inspect.isawaitable(result):
                await result

    async def reject(self, message: Any, *, requeue: bool = False) -> None:
        reject = getattr(message, "reject", None)
        if callable(reject):
            result = reject(requeue=requeue)
            if inspect.isawaitable(result):
                await result

    async def _ensure_connection(self) -> Any:
        if self._connection:
            return self._connection
        if self._connection_factory:
            connection = self._connection_factory(self._connection_kwargs())
        else:
            try:
                import aio_pika  # type: ignore
            except ModuleNotFoundError as exc:  # pragma: no cover - optional dep
                raise LifecycleError(
                    "aio-pika-not-installed: install optional extra 'oneiric[queue-rabbitmq]' to use RabbitMQQueueAdapter"
                ) from exc
            connection = await aio_pika.connect_robust(**self._connection_kwargs())
        if inspect.isawaitable(connection):
            connection = await connection
        self._connection = connection
        return connection

    async def _ensure_channel(self) -> Any:
        if self._channel:
            return self._channel
        if self._channel_factory:
            channel = self._channel_factory()
            if inspect.isawaitable(channel):
                channel = await channel
        else:
            connection = await self._ensure_connection()
            channel = await connection.channel()
            await channel.set_qos(prefetch_count=self._settings.prefetch_count)
        self._channel = channel
        return channel

    async def _ensure_queue(self) -> Any:
        if self._queue:
            return self._queue
        if self._queue_factory:
            queue = self._queue_factory()
            if inspect.isawaitable(queue):
                queue = await queue
        else:
            channel = await self._ensure_channel()
            queue = await channel.declare_queue(
                self._settings.queue,
                durable=self._settings.durable,
                passive=self._settings.passive,
            )
        self._queue = queue
        return queue

    async def _ensure_exchange(self, channel: Any) -> Any:
        if self._settings.exchange:
            return await channel.declare_exchange(
                self._settings.exchange, auto_delete=False, durable=True
            )
        return channel.default_exchange

    async def _build_message(self, body: bytes, headers: dict[str, Any]) -> Any:
        if self._channel_factory:  # assume tests provide message objects
            return type("Message", (), {"body": body, "headers": headers})()
        try:
            from aio_pika import Message  # type: ignore
        except ModuleNotFoundError as exc:  # pragma: no cover - optional dep
            raise LifecycleError(
                "aio-pika-not-installed: install optional extra 'oneiric[queue-rabbitmq]' to use RabbitMQQueueAdapter"
            ) from exc
        return Message(body, headers=headers)

    async def _close_component(self, component: Any) -> None:
        close = getattr(component, "close", None)
        if not callable(close):
            return
        result = close()
        if inspect.isawaitable(result):
            await result

    def _connection_kwargs(self) -> dict[str, Any]:
        url = (
            self._settings.credentials_secret.get_secret_value()
            if self._settings.credentials_secret
            else self._settings.url
        )
        kwargs: dict[str, Any] = {
            "url": url,
            "reconnect_interval": self._settings.reconnect_interval,
            "heartbeat": self._settings.heartbeat,
        }
        if self._settings.ssl:
            kwargs["ssl"] = True
            if self._settings.ssl_options:
                kwargs["ssl_options"] = self._settings.ssl_options
        return kwargs
