"""LavinMQ queue adapter supporting both AMQP and MQTT protocols.

LavinMQ is a RabbitMQ-compatible message broker built in Crystal with:
- AMQP 0-9-1 support (drop-in for RabbitMQ)
- MQTT 3.1.1 and 5.0 support
- Built-in Prometheus metrics
- No Erlang dependency

This adapter provides unified queue semantics across both protocols,
with automatic protocol selection based on the configured capabilities.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, SecretStr

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class Protocol(Enum):
    """Supported protocols for LavinMQ."""

    AMQP = "amqp"
    MQTT = "mqtt"


@dataclass
class QueueMessage:
    """Unified message format for both AMQP and MQTT."""

    body: bytes
    headers: dict[str, Any] = field(default_factory=dict)
    topic: str | None = None
    qos: int = 1
    retain: bool = False
    source_protocol: Protocol | None = None


class LavinMQSettings(BaseModel):
    """Settings for LavinMQ queue adapter.

    Configuration Loading (via Oneiric layered config):
        1. Defaults in field definitions
        2. settings/lavinmq.yaml (committed)
        3. settings/local.yaml (gitignored)
        4. Environment variables LAVINMQ_*

    Environment variable format: LAVINMQ_{FIELD} or LAVINMQ__{NESTED_FIELD}
    """

    # Connection settings
    amqp_url: str = Field(
        default="amqp://guest:guest@localhost:5672/",
        description="AMQP connection URL for LavinMQ.",
    )
    mqtt_host: str = Field(
        default="localhost",
        description="MQTT broker host.",
    )
    mqtt_port: int = Field(
        default=1883,
        ge=1,
        le=65535,
        description="MQTT broker port.",
    )
    mqtt_username: str | None = Field(
        default=None,
        description="MQTT authentication username.",
    )
    mqtt_password: str | None = Field(
        default=None,
        description="MQTT authentication password.",
    )

    # Protocol selection
    preferred_protocol: Protocol = Field(
        default=Protocol.AMQP,
        description="Preferred protocol (amqp or mqtt).",
    )
    enable_both_protocols: bool = Field(
        default=False,
        description="Enable both AMQP and MQTT for maximum flexibility.",
    )

    # Queue settings (AMQP)
    queue: str = Field(
        default="oneiric-queue",
        description="Queue name for AMQP operations.",
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

    # MQTT settings
    mqtt_topic: str = Field(
        default="oneiric/messages",
        description="MQTT topic for publish/subscribe.",
    )
    mqtt_qos: int = Field(
        default=1, ge=0, le=2, description="MQTT Quality of Service level."
    )
    mqtt_retain: bool = Field(default=False, description="MQTT message retention flag.")
    mqtt_client_id: str | None = Field(
        default=None,
        description="MQTT client identifier (auto-generated if None).",
    )

    # Connection settings
    reconnect_interval: float = Field(
        default=5.0, ge=0.0, description="Interval for reconnects."
    )
    heartbeat: float = Field(
        default=60.0, ge=0.0, description="AMQP heartbeat setting."
    )
    ssl: bool = Field(default=False, description="Enable SSL/TLS.")
    ssl_options: dict[str, Any] | None = Field(
        default=None, description="Custom SSL options."
    )
    credentials_secret: SecretStr | None = Field(
        default=None,
        description="Optional secret (AMQP URL override) loaded via Secret Manager.",
    )

    # Metrics
    metrics_port: int = Field(
        default=15692,
        ge=1024,
        le=65535,
        description="Prometheus metrics HTTP port.",
    )


class LavinMQQueueAdapter:
    """LavinMQ queue adapter supporting AMQP and MQTT protocols.

    Provides a unified interface for message queue operations with automatic
    protocol selection. MQTT is ideal for IoT/constrained clients while AMQP
    provides richer queue semantics for traditional server workloads.

    Example:
        >>> settings = LavinMQSettings(
        ...     preferred_protocol=Protocol.AMQP,
        ...     queue="my-queue",
        ...     mqtt_topic="devices/+/telemetry",
        ... )
        >>> adapter = LavinMQQueueAdapter(settings)
        >>> await adapter.init()
        >>> await adapter.publish(b"hello world")
        >>> messages = await adapter.consume(limit=10)
    """

    metadata = AdapterMetadata(
        category="queue",
        provider="lavinmq",
        factory="oneiric.adapters.queue.lavinmq: LavinMQQueueAdapter",
        capabilities=["queue", "streaming", "mqtt", "amqp"],
        stack_level=20,
        priority=330,  # Higher than RabbitMQ (320)
        source=CandidateSource.LOCAL_PKG,
        owner="Messaging",
        requires_secrets=True,
        settings_model=LavinMQSettings,
    )

    def __init__(
        self,
        settings: LavinMQSettings | None = None,
        *,
        amqp_connection_factory: Callable[..., Any] | None = None,
        amqp_channel_factory: Callable[..., Any] | None = None,
        amqp_queue_factory: Callable[..., Any] | None = None,
        mqtt_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._settings = settings or LavinMQSettings()
        self._amqp_connection_factory = amqp_connection_factory
        self._amqp_channel_factory = amqp_channel_factory
        self._amqp_queue_factory = amqp_queue_factory
        self._mqtt_factory = mqtt_factory

        # AMQP state
        self._amqp_connection: Any | None = None
        self._amqp_channel: Any | None = None
        self._amqp_queue: Any | None = None

        # MQTT state
        self._mqtt_client: Any | None = None
        self._mqtt_messages: asyncio.Queue[QueueMessage] = asyncio.Queue()

        # Active protocol tracking
        self._active_protocols: set[Protocol] = set()

        self._logger = get_logger("adapter.queue.lavinmq").bind(
            domain="adapter",
            key="queue",
            provider="lavinmq",
            queue=self._settings.queue,
            mqtt_topic=self._settings.mqtt_topic,
        )

    async def init(self) -> None:
        """Initialize the adapter and configured protocols."""
        if self._settings.preferred_protocol == Protocol.AMQP or (
            self._settings.enable_both_protocols
        ):
            await self._init_amqp()
            self._active_protocols.add(Protocol.AMQP)

        if self._settings.preferred_protocol == Protocol.MQTT or (
            self._settings.enable_both_protocols
        ):
            await self._init_mqtt()
            self._active_protocols.add(Protocol.MQTT)

        self._logger.info(
            "lavinmq-adapter-init",
            provider="lavinmq",
            protocols=[p.value for p in self._active_protocols],
        )

    async def health(self) -> bool:
        """Check health of active protocols."""
        if Protocol.AMQP in self._active_protocols:
            try:
                queue = await self._ensure_amqp_queue()
                declare = getattr(queue, "declare", None)
                if callable(declare):
                    await declare(passive=True)
                return True
            except Exception as exc:
                self._logger.warning("lavinmq-amqp-health-check-failed", error=str(exc))

        if Protocol.MQTT in self._active_protocols:
            # MQTT health: client is connected and subscribed
            if self._mqtt_client is None:
                return False
            # Check if client has active connection
            try:
                from aiomqtt import Client as MqttClient

                if isinstance(self._mqtt_client, MqttClient):
                    return True
            except ImportError:
                pass

        return bool(self._active_protocols)

    async def cleanup(self) -> None:
        """Clean up all connections."""
        # AMQP cleanup
        if self._amqp_channel:
            await self._close_component(self._amqp_channel)
            self._amqp_channel = None
        if self._amqp_connection:
            await self._close_component(self._amqp_connection)
            self._amqp_connection = None
        self._amqp_queue = None

        # MQTT cleanup
        if self._mqtt_client:
            with suppress(Exception):
                await self._mqtt_client.disconnect()
            self._mqtt_client = None

        self._logger.info("lavinmq-adapter-cleanup", provider="lavinmq")

    async def publish(
        self,
        body: bytes,
        *,
        headers: dict[str, Any] | None = None,
        topic: str | None = None,
        qos: int | None = None,
        retain: bool | None = None,
    ) -> None:
        """Publish a message using the preferred protocol.

        Args:
            body: Message body as bytes.
            headers: Optional headers for AMQP messages.
            topic: MQTT topic override (defaults to mqtt_topic setting).
            qos: MQTT QoS override (defaults to mqtt_qos setting).
            retain: MQTT retain flag override.
        """
        headers = headers or {}

        if self._settings.preferred_protocol == Protocol.AMQP or (
            self._settings.enable_both_protocols
            and Protocol.AMQP in self._active_protocols
        ):
            await self._amqp_publish(body, headers)

        if self._settings.preferred_protocol == Protocol.MQTT or (
            self._settings.enable_both_protocols
            and Protocol.MQTT in self._active_protocols
        ):
            await self._mqtt_publish(
                body,
                topic=topic,
                qos=qos,
                retain=retain,
            )

    async def consume(self, *, limit: int = 1) -> list[dict[str, Any]]:
        """Consume messages from the active protocol's queue.

        Args:
            limit: Maximum number of messages to consume.

        Returns:
            List of message dictionaries with body, headers, and protocol info.
        """
        messages: list[dict[str, Any]] = []

        if Protocol.AMQP in self._active_protocols:
            amqp_messages = await self._amqp_consume(limit)
            messages.extend(amqp_messages)

        if Protocol.MQTT in self._active_protocols:
            # Gather MQTT messages from the queue
            for _ in range(limit):
                try:
                    msg = await asyncio.wait_for(
                        self._mqtt_messages.get(),
                        timeout=self._settings.consume_timeout,
                    )
                    messages.append(
                        {
                            "body": msg.body,
                            "headers": msg.headers,
                            "topic": msg.topic,
                            "qos": msg.qos,
                            "retain": msg.retain,
                            "protocol": Protocol.MQTT.value,
                        }
                    )
                except TimeoutError:
                    break

        return messages

    async def ack(self, message: Any) -> None:
        """Acknowledge a message (AMQP only, MQTT uses QoS)."""
        ack = getattr(message, "ack", None)
        if callable(ack):
            result = ack()
            if inspect.isawaitable(result):
                await result

    async def reject(self, message: Any, *, requeue: bool = False) -> None:
        """Reject a message (AMQP only)."""
        reject = getattr(message, "reject", None)
        if callable(reject):
            result = reject(requeue=requeue)
            if inspect.isawaitable(result):
                await result

    # -------------------------------------------------------------------------
    # AMQP Methods
    # -------------------------------------------------------------------------

    async def _init_amqp(self) -> None:
        """Initialize AMQP connection and queue."""
        await self._ensure_amqp_queue()
        self._logger.debug("lavinmq-amqp-init", queue=self._settings.queue)

    async def _amqp_publish(self, body: bytes, headers: dict[str, Any]) -> None:
        """Publish via AMQP."""
        channel = await self._ensure_amqp_channel()
        message = await self._build_amqp_message(body, headers)
        exchange = await self._ensure_amqp_exchange(channel)
        routing_key = self._settings.routing_key or self._settings.queue
        await exchange.publish(message, routing_key=routing_key)
        self._logger.debug("lavinmq-amqp-publish", queue=self._settings.queue)

    async def _amqp_consume(self, limit: int) -> list[dict[str, Any]]:
        """Consume messages via AMQP."""
        queue = await self._ensure_amqp_queue()
        messages: list[dict[str, Any]] = []
        for _ in range(limit):
            try:
                message = await asyncio.wait_for(
                    queue.get(no_ack=False),
                    timeout=self._settings.consume_timeout or None,
                )
                messages.append(
                    {
                        "body": bytes(message.body),
                        "headers": dict(message.headers or {}),
                        "message": message,
                        "protocol": Protocol.AMQP.value,
                    }
                )
            except TimeoutError:
                break
        return messages

    async def _ensure_amqp_connection(self) -> Any:
        """Ensure AMQP connection is established."""
        if self._amqp_connection:
            return self._amqp_connection

        if self._amqp_connection_factory:
            connection = self._amqp_connection_factory(self._amqp_connection_kwargs())
        else:
            try:
                import aio_pika
            except ModuleNotFoundError as exc:
                raise LifecycleError(
                    "aio-pika-not-installed: install optional extra "
                    "'oneiric[queue-rabbitmq]' for AMQP support"
                ) from exc
            connection = await aio_pika.connect_robust(**self._amqp_connection_kwargs())
        if inspect.isawaitable(connection):
            connection = await connection
        self._amqp_connection = connection
        return connection

    async def _ensure_amqp_channel(self) -> Any:
        """Ensure AMQP channel is established."""
        if self._amqp_channel:
            return self._amqp_channel

        if self._amqp_channel_factory:
            channel = self._amqp_channel_factory()
            if inspect.isawaitable(channel):
                channel = await channel
        else:
            connection = await self._ensure_amqp_connection()
            channel = await connection.channel()
            await channel.set_qos(prefetch_count=self._settings.prefetch_count)
        self._amqp_channel = channel
        return channel

    async def _ensure_amqp_queue(self) -> Any:
        """Ensure AMQP queue is declared."""
        if self._amqp_queue:
            return self._amqp_queue

        if self._amqp_queue_factory:
            queue = self._amqp_queue_factory()
            if inspect.isawaitable(queue):
                queue = await queue
        else:
            channel = await self._ensure_amqp_channel()
            queue = await channel.declare_queue(
                self._settings.queue,
                durable=self._settings.durable,
                passive=self._settings.passive,
            )
        self._amqp_queue = queue
        return queue

    async def _ensure_amqp_exchange(self, channel: Any) -> Any:
        """Get or create AMQP exchange."""
        if self._settings.exchange:
            return await channel.declare_exchange(
                self._settings.exchange, auto_delete=False, durable=True
            )
        return channel.default_exchange

    async def _build_amqp_message(self, body: bytes, headers: dict[str, Any]) -> Any:
        """Build an AMQP message."""
        if self._amqp_channel_factory:
            return type("Message", (), {"body": body, "headers": headers})()
        try:
            from aio_pika import Message
        except ModuleNotFoundError as exc:
            raise LifecycleError(
                "aio-pika-not-installed: install optional extra 'oneiric[queue-rabbitmq]'"
            ) from exc
        return Message(body, headers=headers)

    def _amqp_connection_kwargs(self) -> dict[str, Any]:
        """Build connection kwargs for AMQP."""
        url = (
            self._settings.credentials_secret.get_secret_value()
            if self._settings.credentials_secret
            else self._settings.amqp_url
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

    # -------------------------------------------------------------------------
    # MQTT Methods
    # -------------------------------------------------------------------------

    async def _init_mqtt(self) -> None:
        """Initialize MQTT client and subscription."""
        try:
            import aiomqtt
        except ModuleNotFoundError as exc:
            raise LifecycleError(
                "aiomqtt-not-installed: install 'aiomqtt' for MQTT support"
            ) from exc

        client_kwargs: dict[str, Any] = {
            "hostname": self._settings.mqtt_host,
            "port": self._settings.mqtt_port,
        }

        if self._settings.mqtt_client_id:
            client_kwargs["client_id"] = self._settings.mqtt_client_id

        if self._settings.mqtt_username:
            client_kwargs["username"] = self._settings.mqtt_username
        if self._settings.mqtt_password:
            client_kwargs["password"] = self._settings.mqtt_password

        if self._mqtt_factory:
            self._mqtt_client = self._mqtt_factory(**client_kwargs)
        else:
            self._mqtt_client = aiomqtt.Client(**client_kwargs)

        # Start background subscriber
        asyncio.create_task(self._mqtt_subscriber())
        self._logger.debug(
            "lavinmq-mqtt-init",
            topic=self._settings.mqtt_topic,
            qos=self._settings.mqtt_qos,
        )

    async def _mqtt_subscriber(self) -> None:
        """Background task to subscribe to MQTT topic and queue messages."""
        if self._mqtt_client is None:
            return

        try:
            await self._mqtt_client.connect()
            async with self._mqtt_client.messages() as messages:
                await messages.subscribe(
                    self._settings.mqtt_topic, qos=self._settings.mqtt_qos
                )
                async for message in messages:
                    qos_name = {
                        0: "at-most-once",
                        1: "at-least-once",
                        2: "exactly-once",
                    }
                    self._logger.debug(
                        "lavinmq-mqtt-received",
                        topic=message.topic.value,
                        qos=qos_name.get(message.qos, "unknown"),
                    )
                    await self._mqtt_messages.put(
                        QueueMessage(
                            body=message.payload,
                            headers={},
                            topic=message.topic.value,
                            qos=message.qos,
                            retain=message.retain,
                            source_protocol=Protocol.MQTT,
                        )
                    )
        except Exception as exc:
            self._logger.warning("lavinmq-mqtt-subscriber-error", error=str(exc))
            # Attempt reconnection after delay
            await asyncio.sleep(self._settings.reconnect_interval)
            if Protocol.MQTT in self._active_protocols:
                asyncio.create_task(self._mqtt_subscriber())

    async def _mqtt_publish(
        self,
        body: bytes,
        *,
        topic: str | None = None,
        qos: int | None = None,
        retain: bool | None = None,
    ) -> None:
        """Publish via MQTT."""
        if self._mqtt_client is None:
            self._logger.warning("lavinmq-mqtt-not-connected")
            return

        publish_topic = topic or self._settings.mqtt_topic
        publish_qos = qos if qos is not None else self._settings.mqtt_qos
        publish_retain = retain if retain is not None else self._settings.mqtt_retain

        try:
            await self._mqtt_client.publish(
                publish_topic,
                body,
                qos=publish_qos,
                retain=publish_retain,
            )
            self._logger.debug(
                "lavinmq-mqtt-publish", topic=publish_topic, qos=publish_qos
            )
        except Exception as exc:
            self._logger.error("lavinmq-mqtt-publish-failed", error=str(exc))
            raise

    # -------------------------------------------------------------------------
    # Utilities
    # -------------------------------------------------------------------------

    async def _close_component(self, component: Any) -> None:
        """Safely close a component."""
        close = getattr(component, "close", None)
        if not callable(close):
            return
        result = close()
        if inspect.isawaitable(result):
            await result

    def get_metrics_url(self) -> str:
        """Get the Prometheus metrics endpoint URL."""
        return f"http://localhost:{self._settings.metrics_port}/metrics"
