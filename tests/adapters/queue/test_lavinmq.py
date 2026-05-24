"""Tests for LavinMQQueueAdapter using injected mock factories.

No aio_pika or aiomqtt installation required. All protocol factories are
injected via the constructor's factory parameters.
"""

from __future__ import annotations

import asyncio
import sys
import types
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _mock_aiomqtt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the aiomqtt module so MQTT paths work without installing the package."""
    fake = types.ModuleType("aiomqtt")

    class _FakeClient:
        def __init__(self, **kw: Any) -> None:
            pass

        async def publish(self, *a: Any, **kw: Any) -> None:
            pass

        async def subscribe(self, *a: Any, **kw: Any) -> None:
            pass

        async def disconnect(self) -> None:
            pass

    fake.Client = _FakeClient  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "aiomqtt", fake)


from oneiric.adapters.queue.lavinmq import (
    LavinMQQueueAdapter,
    LavinMQSettings,
    Protocol,
    QueueMessage,
)

# ---------------------------------------------------------------------------
# Mock AMQP components
# ---------------------------------------------------------------------------


class MockAMQPMessage:
    def __init__(self, body: bytes, headers: dict[str, Any] | None = None) -> None:
        self.body = body
        self.headers = headers or {}
        self._acked = False
        self._rejected = False

    def ack(self) -> None:
        self._acked = True

    def reject(self, *, requeue: bool = False) -> None:
        self._rejected = True


class MockExchange:
    def __init__(self) -> None:
        self.published: list[tuple[Any, str]] = []

    async def publish(self, message: Any, *, routing_key: str) -> None:
        self.published.append((message, routing_key))


class MockChannel:
    def __init__(self, messages: list[MockAMQPMessage] | None = None) -> None:
        self._messages = list(messages or [])
        self._exchange = MockExchange()
        self.default_exchange = MockExchange()
        self._qos_set = False

    async def set_qos(self, *, prefetch_count: int) -> None:
        self._qos_set = True

    async def declare_queue(
        self, name: str, *, durable: bool, passive: bool
    ) -> MockQueue:
        return MockQueue(name, self._messages)

    async def declare_exchange(
        self, name: str, *, auto_delete: bool, durable: bool
    ) -> MockExchange:
        return self._exchange

    async def close(self) -> None:
        pass


class MockQueue:
    def __init__(self, name: str, messages: list[MockAMQPMessage]) -> None:
        self.name = name
        self._messages = messages

    async def declare(self, *, passive: bool = False) -> None:
        pass

    async def get(self, *, no_ack: bool) -> MockAMQPMessage:
        if self._messages:
            return self._messages.pop(0)
        raise TimeoutError("queue empty")


class MockConnection:
    def __init__(self, channel: MockChannel) -> None:
        self._channel = channel

    async def channel(self) -> MockChannel:
        return self._channel

    async def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Tests — QueueMessage dataclass
# ---------------------------------------------------------------------------


def test_queue_message_defaults() -> None:
    msg = QueueMessage(body=b"hello")
    assert msg.body == b"hello"
    assert msg.headers == {}
    assert msg.topic is None
    assert msg.qos == 1
    assert msg.retain is False
    assert msg.source_protocol is None


def test_queue_message_full() -> None:
    msg = QueueMessage(
        body=b"data",
        headers={"x": "y"},
        topic="devices/sensor",
        qos=2,
        retain=True,
        source_protocol=Protocol.MQTT,
    )
    assert msg.qos == 2
    assert msg.source_protocol == Protocol.MQTT


# ---------------------------------------------------------------------------
# Tests — LavinMQSettings
# ---------------------------------------------------------------------------


def test_settings_defaults() -> None:
    s = LavinMQSettings()
    assert s.preferred_protocol == Protocol.AMQP
    assert s.enable_both_protocols is False
    assert s.queue == "oneiric-queue"
    assert s.durable is True


def test_protocol_enum_values() -> None:
    assert Protocol.AMQP.value == "amqp"
    assert Protocol.MQTT.value == "mqtt"


# ---------------------------------------------------------------------------
# Tests — AMQP init + health + publish + consume
# ---------------------------------------------------------------------------


def _amqp_adapter(
    messages: list[MockAMQPMessage] | None = None,
    settings: LavinMQSettings | None = None,
) -> tuple[LavinMQQueueAdapter, MockChannel, MockConnection]:
    channel = MockChannel(messages)
    connection = MockConnection(channel)

    adapter = LavinMQQueueAdapter(
        settings or LavinMQSettings(preferred_protocol=Protocol.AMQP),
        amqp_connection_factory=lambda kwargs: connection,
        amqp_channel_factory=lambda: channel,
        amqp_queue_factory=lambda: MockQueue("q", list(messages or [])),
    )
    return adapter, channel, connection


@pytest.mark.asyncio
async def test_amqp_init() -> None:
    adapter, _, _ = _amqp_adapter()
    await adapter.init()
    assert Protocol.AMQP in adapter._active_protocols


@pytest.mark.asyncio
async def test_amqp_health_via_passive_declare() -> None:
    adapter, _, _ = _amqp_adapter()
    await adapter.init()
    assert await adapter.health() is True


@pytest.mark.asyncio
async def test_amqp_health_on_error() -> None:
    MockChannel()

    class BrokenQueue:
        async def declare(self, *, passive: bool = False) -> None:
            raise RuntimeError("broker down")

    adapter = LavinMQQueueAdapter(
        LavinMQSettings(preferred_protocol=Protocol.AMQP),
        amqp_queue_factory=lambda: BrokenQueue(),
    )
    await adapter.init()
    adapter._amqp_queue = BrokenQueue()
    # AMQP passive-declare fails → logs warning and falls through to
    # len(active_protocols) > 0, which is True
    result = await adapter.health()
    assert result is True


@pytest.mark.asyncio
async def test_amqp_publish() -> None:
    adapter, channel, _ = _amqp_adapter()
    await adapter.init()
    await adapter.publish(b"hello", headers={"h": "v"})
    # No named exchange → _ensure_amqp_exchange returns channel.default_exchange
    assert len(channel.default_exchange.published) == 1
    _, routing_key = channel.default_exchange.published[0]
    assert routing_key == "oneiric-queue"


@pytest.mark.asyncio
async def test_amqp_publish_with_named_exchange() -> None:
    settings = LavinMQSettings(
        preferred_protocol=Protocol.AMQP,
        exchange="my-exchange",
        routing_key="my-key",
    )
    adapter, channel, _ = _amqp_adapter(settings=settings)
    await adapter.init()
    await adapter.publish(b"msg")
    assert channel._exchange.published[0][1] == "my-key"


@pytest.mark.asyncio
async def test_amqp_consume() -> None:
    messages = [MockAMQPMessage(b"body1"), MockAMQPMessage(b"body2")]
    adapter, _, _ = _amqp_adapter(messages)
    await adapter.init()
    consumed = await adapter.consume(limit=2)
    assert len(consumed) == 2
    assert consumed[0]["body"] == b"body1"
    assert consumed[0]["protocol"] == "amqp"


@pytest.mark.asyncio
async def test_amqp_consume_stops_on_timeout() -> None:
    """consume() returns partial results when queue is exhausted."""
    messages = [MockAMQPMessage(b"only")]
    adapter, _, _ = _amqp_adapter(messages)
    await adapter.init()
    consumed = await adapter.consume(limit=5)
    assert len(consumed) == 1


@pytest.mark.asyncio
async def test_ack_message() -> None:
    msg = MockAMQPMessage(b"data")
    adapter, _, _ = _amqp_adapter()
    await adapter.init()
    await adapter.ack(msg)
    assert msg._acked is True


@pytest.mark.asyncio
async def test_ack_non_message_is_noop() -> None:
    adapter, _, _ = _amqp_adapter()
    await adapter.init()
    await adapter.ack("not-a-message")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_reject_message() -> None:
    msg = MockAMQPMessage(b"data")
    adapter, _, _ = _amqp_adapter()
    await adapter.init()
    await adapter.reject(msg, requeue=True)
    assert msg._rejected is True


@pytest.mark.asyncio
async def test_cleanup_amqp() -> None:
    adapter, _, _ = _amqp_adapter()
    await adapter.init()
    await adapter.cleanup()
    assert adapter._amqp_connection is None
    assert adapter._amqp_channel is None
    assert adapter._amqp_queue is None


# ---------------------------------------------------------------------------
# Tests — MQTT (mock factory)
# ---------------------------------------------------------------------------


class MockMqttClient:
    def __init__(self) -> None:
        self.published: list[tuple[str, bytes, int, bool]] = []
        self.subscriptions: list[str] = []

    async def publish(
        self, topic: str, payload: bytes, *, qos: int, retain: bool
    ) -> None:
        self.published.append((topic, payload, qos, retain))

    async def subscribe(self, topic: str, *, qos: int) -> None:
        self.subscriptions.append(topic)

    async def disconnect(self) -> None:
        pass


def _mqtt_adapter(
    settings: LavinMQSettings | None = None,
) -> tuple[LavinMQQueueAdapter, MockMqttClient]:
    mqtt_client = MockMqttClient()
    settings = settings or LavinMQSettings(preferred_protocol=Protocol.MQTT)

    adapter = LavinMQQueueAdapter(
        settings,
        mqtt_factory=lambda **kw: mqtt_client,
    )
    return adapter, mqtt_client


@pytest.mark.asyncio
async def test_mqtt_init() -> None:
    adapter, _ = _mqtt_adapter()
    await adapter.init()
    assert Protocol.MQTT in adapter._active_protocols


@pytest.mark.asyncio
async def test_mqtt_publish() -> None:
    adapter, mqtt_client = _mqtt_adapter()
    await adapter.init()
    await adapter.publish(b"mqtt-msg", topic="sensor/data", qos=2, retain=True)
    assert len(mqtt_client.published) == 1
    topic, payload, qos, retain = mqtt_client.published[0]
    assert topic == "sensor/data"
    assert payload == b"mqtt-msg"
    assert qos == 2
    assert retain is True


@pytest.mark.asyncio
async def test_mqtt_publish_defaults() -> None:
    settings = LavinMQSettings(
        preferred_protocol=Protocol.MQTT, mqtt_topic="default/topic", mqtt_qos=1
    )
    adapter, mqtt_client = _mqtt_adapter(settings)
    await adapter.init()
    await adapter.publish(b"data")
    assert mqtt_client.published[0][0] == "default/topic"
    assert mqtt_client.published[0][2] == 1


@pytest.mark.asyncio
async def test_mqtt_consume_from_queue() -> None:
    adapter, _ = _mqtt_adapter()
    await adapter.init()

    # Inject a message directly into the internal queue
    msg = QueueMessage(body=b"from-mqtt", topic="t/1", source_protocol=Protocol.MQTT)
    await adapter._mqtt_messages.put(msg)

    consumed = await adapter.consume(limit=1)
    assert len(consumed) == 1
    assert consumed[0]["body"] == b"from-mqtt"
    assert consumed[0]["protocol"] == "mqtt"


@pytest.mark.asyncio
async def test_mqtt_consume_timeout() -> None:
    settings = LavinMQSettings(preferred_protocol=Protocol.MQTT, consume_timeout=0.05)
    adapter, _ = _mqtt_adapter(settings)
    await adapter.init()
    # No messages — should time out and return empty
    consumed = await adapter.consume(limit=3)
    assert consumed == []


@pytest.mark.asyncio
async def test_mqtt_cleanup() -> None:
    adapter, mqtt_client = _mqtt_adapter()
    await adapter.init()
    await adapter.cleanup()
    assert adapter._mqtt_client is None


# ---------------------------------------------------------------------------
# Tests — Both protocols
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_both_protocols_init() -> None:
    channel = MockChannel()
    connection = MockConnection(channel)
    mqtt_client = MockMqttClient()

    adapter = LavinMQQueueAdapter(
        LavinMQSettings(enable_both_protocols=True),
        amqp_connection_factory=lambda kwargs: connection,
        amqp_channel_factory=lambda: channel,
        amqp_queue_factory=lambda: MockQueue("q", []),
        mqtt_factory=lambda **kw: mqtt_client,
    )
    await adapter.init()
    assert Protocol.AMQP in adapter._active_protocols
    assert Protocol.MQTT in adapter._active_protocols


@pytest.mark.asyncio
async def test_both_protocols_publish() -> None:
    channel = MockChannel()
    connection = MockConnection(channel)
    mqtt_client = MockMqttClient()

    adapter = LavinMQQueueAdapter(
        LavinMQSettings(enable_both_protocols=True),
        amqp_connection_factory=lambda kwargs: connection,
        amqp_channel_factory=lambda: channel,
        amqp_queue_factory=lambda: MockQueue("q", []),
        mqtt_factory=lambda **kw: mqtt_client,
    )
    await adapter.init()
    await adapter.publish(b"both")
    # AMQP published on default_exchange (no named exchange configured)
    assert len(channel.default_exchange.published) == 1
    # MQTT published
    assert len(mqtt_client.published) == 1


# ---------------------------------------------------------------------------
# Tests — Awaitable factory support
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_awaitable_connection_factory() -> None:
    channel = MockChannel()
    connection = MockConnection(channel)

    async def async_conn_factory(kwargs: Any) -> MockConnection:
        return connection

    # No channel/queue factory — forces the full chain:
    # _ensure_amqp_queue → _ensure_amqp_channel → _ensure_amqp_connection
    adapter = LavinMQQueueAdapter(
        LavinMQSettings(preferred_protocol=Protocol.AMQP),
        amqp_connection_factory=async_conn_factory,
    )
    await adapter.init()
    assert adapter._amqp_connection is connection


@pytest.mark.asyncio
async def test_awaitable_channel_factory() -> None:
    channel = MockChannel()

    async def async_chan_factory() -> MockChannel:
        return channel

    # No queue factory — forces: _ensure_amqp_queue → _ensure_amqp_channel
    adapter = LavinMQQueueAdapter(
        LavinMQSettings(preferred_protocol=Protocol.AMQP),
        amqp_channel_factory=async_chan_factory,
    )
    await adapter.init()
    assert adapter._amqp_channel is channel


@pytest.mark.asyncio
async def test_awaitable_queue_factory() -> None:
    queue = MockQueue("q", [])

    async def async_queue_factory() -> MockQueue:
        return queue

    adapter = LavinMQQueueAdapter(
        LavinMQSettings(preferred_protocol=Protocol.AMQP),
        amqp_queue_factory=async_queue_factory,
    )
    await adapter.init()
    assert adapter._amqp_queue is queue


# ---------------------------------------------------------------------------
# Tests — Health edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_no_active_protocols() -> None:
    adapter = LavinMQQueueAdapter(LavinMQSettings(preferred_protocol=Protocol.AMQP))
    # Don't call init — no active protocols
    assert await adapter.health() is False


@pytest.mark.asyncio
async def test_health_mqtt_client_connected() -> None:
    adapter, mqtt_client = _mqtt_adapter()
    await adapter.init()
    # MQTT adapter without aiomqtt — falls through to len(active_protocols) > 0
    result = await adapter.health()
    assert result is True


@pytest.mark.asyncio
async def test_health_mqtt_client_none() -> None:
    adapter, _ = _mqtt_adapter()
    await adapter.init()
    adapter._mqtt_client = None
    # MQTT active but client is None → health returns False
    result = await adapter.health()
    assert result is False


# ---------------------------------------------------------------------------
# Tests — ack/reject with awaitable methods
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ack_awaitable_method() -> None:
    acked: list[bool] = []

    class AsyncAckMessage:
        async def ack(self) -> None:
            acked.append(True)

    adapter, _, _ = _amqp_adapter()
    await adapter.init()
    await adapter.ack(AsyncAckMessage())
    assert acked == [True]


@pytest.mark.asyncio
async def test_reject_awaitable_method() -> None:
    rejected: list[bool] = []

    class AsyncRejectMessage:
        async def reject(self, *, requeue: bool = False) -> None:
            rejected.append(requeue)

    adapter, _, _ = _amqp_adapter()
    await adapter.init()
    await adapter.reject(AsyncRejectMessage(), requeue=False)
    assert rejected == [False]


# ---------------------------------------------------------------------------
# Tests — coverage gaps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_mqtt_isinstance_true() -> None:
    """health() returns True when mqtt_client is an aiomqtt.Client instance (line 260)."""
    adapter, _ = _mqtt_adapter()
    await adapter.init()
    # Replace client with actual aiomqtt.Client instance (mocked by fixture)
    adapter._mqtt_client = sys.modules["aiomqtt"].Client()
    assert await adapter.health() is True


@pytest.mark.asyncio
async def test_cleanup_with_channel_and_connection_set() -> None:
    """cleanup() closes channel and connection when they are set (lines 270-271, 273-274)."""
    channel = MockChannel()
    connection = MockConnection(channel)

    # Use only connection factory (no channel/queue factories) to force full chain
    adapter = LavinMQQueueAdapter(
        LavinMQSettings(preferred_protocol=Protocol.AMQP),
        amqp_connection_factory=lambda kwargs: connection,
        # no channel/queue factories → _ensure_amqp_queue calls _ensure_amqp_channel
        # which calls _ensure_amqp_connection
    )
    await adapter.init()
    # After init, both channel and connection are set
    assert adapter._amqp_channel is channel
    assert adapter._amqp_connection is connection
    await adapter.cleanup()
    assert adapter._amqp_channel is None
    assert adapter._amqp_connection is None


@pytest.mark.asyncio
async def test_cleanup_mqtt_disconnect_raises() -> None:
    """cleanup() swallows exceptions from mqtt_client.disconnect() (lines 281-282)."""

    class FailingMqttClient(MockMqttClient):
        async def disconnect(self) -> None:
            raise OSError("connection lost")

    adapter = LavinMQQueueAdapter(
        LavinMQSettings(preferred_protocol=Protocol.MQTT),
        mqtt_factory=lambda **kw: FailingMqttClient(),
    )
    await adapter.init()
    # Should not raise even though disconnect() raises
    await adapter.cleanup()
    assert adapter._mqtt_client is None


@pytest.mark.asyncio
async def test_ensure_amqp_connection_returns_cached() -> None:
    """_ensure_amqp_connection returns cached connection on second call (line 421)."""
    channel = MockChannel()
    connection = MockConnection(channel)

    adapter = LavinMQQueueAdapter(
        LavinMQSettings(preferred_protocol=Protocol.AMQP),
        amqp_connection_factory=lambda kwargs: connection,
    )
    await adapter.init()
    c1 = await adapter._ensure_amqp_connection()
    c2 = await adapter._ensure_amqp_connection()
    assert c1 is c2 is connection


@pytest.mark.asyncio
async def test_ensure_amqp_connection_via_aio_pika(monkeypatch: Any) -> None:
    """_ensure_amqp_connection imports aio_pika when no factory (lines 426-433)."""
    channel = MockChannel()
    connection = MockConnection(channel)

    class FakeAioPika:
        @staticmethod
        async def connect_robust(**kwargs: Any) -> MockConnection:
            return connection

    fake_aio_pika = types.ModuleType("aio_pika")
    fake_aio_pika.connect_robust = FakeAioPika.connect_robust  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "aio_pika", fake_aio_pika)

    adapter = LavinMQQueueAdapter(
        LavinMQSettings(preferred_protocol=Protocol.AMQP),
        # no connection/channel/queue factories → full aio_pika path
    )
    await adapter.init()
    assert adapter._amqp_connection is connection


@pytest.mark.asyncio
async def test_ensure_amqp_channel_returns_cached() -> None:
    """_ensure_amqp_channel returns cached channel on second call (line 442)."""
    channel = MockChannel()
    connection = MockConnection(channel)

    adapter = LavinMQQueueAdapter(
        LavinMQSettings(preferred_protocol=Protocol.AMQP),
        amqp_connection_factory=lambda kwargs: connection,
    )
    await adapter.init()
    ch1 = await adapter._ensure_amqp_channel()
    ch2 = await adapter._ensure_amqp_channel()
    assert ch1 is ch2 is channel


@pytest.mark.asyncio
async def test_build_amqp_message_via_aio_pika(monkeypatch: Any) -> None:
    """_build_amqp_message imports aio_pika.Message when no channel factory (lines 486-492)."""
    messages_built: list[tuple[bytes, dict]] = []

    class FakeMessage:
        def __init__(self, body: bytes, headers: dict[str, Any]) -> None:
            messages_built.append((body, headers))

    fake_aio_pika = types.ModuleType("aio_pika")
    fake_aio_pika.Message = FakeMessage  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "aio_pika", fake_aio_pika)

    channel = MockChannel()
    connection = MockConnection(channel)

    adapter = LavinMQQueueAdapter(
        LavinMQSettings(preferred_protocol=Protocol.AMQP),
        amqp_connection_factory=lambda kwargs: connection,
        # no channel_factory → _build_amqp_message uses aio_pika.Message
    )
    await adapter.init()
    msg = await adapter._build_amqp_message(b"data", {"h": "v"})
    assert isinstance(msg, FakeMessage)
    assert messages_built[0] == (b"data", {"h": "v"})


def test_amqp_connection_kwargs_with_ssl_options() -> None:
    """_amqp_connection_kwargs includes ssl_options when ssl=True (lines 507-509)."""
    adapter = LavinMQQueueAdapter(
        LavinMQSettings(ssl=True, ssl_options={"certfile": "/cert.pem"})
    )
    kwargs = adapter._amqp_connection_kwargs()
    assert kwargs["ssl"] is True
    assert kwargs["ssl_options"] == {"certfile": "/cert.pem"}


@pytest.mark.asyncio
async def test_init_mqtt_with_all_optional_settings() -> None:
    """_init_mqtt sets client_id, username, and password when configured (lines 520-521, 531, 534, 536)."""
    client_kwargs_captured: list[dict] = []

    def capturing_factory(**kwargs: Any) -> MockMqttClient:
        client_kwargs_captured.append(kwargs)
        return MockMqttClient()

    adapter = LavinMQQueueAdapter(
        LavinMQSettings(
            preferred_protocol=Protocol.MQTT,
            mqtt_client_id="my-client",
            mqtt_username="user",
            mqtt_password="pass",
        ),
        mqtt_factory=capturing_factory,
    )
    await adapter.init()
    assert client_kwargs_captured[0]["client_id"] == "my-client"
    assert client_kwargs_captured[0]["username"] == "user"
    assert client_kwargs_captured[0]["password"] == "pass"


@pytest.mark.asyncio
async def test_init_mqtt_without_factory_uses_aiomqtt() -> None:
    """_init_mqtt uses aiomqtt.Client directly when no mqtt_factory (line 541)."""
    adapter = LavinMQQueueAdapter(
        LavinMQSettings(preferred_protocol=Protocol.MQTT),
        # no mqtt_factory → uses sys.modules["aiomqtt"].Client
    )
    await adapter.init()
    # The autouse fixture mocks aiomqtt.Client = _FakeClient
    assert adapter._mqtt_client is not None
    assert isinstance(adapter._mqtt_client, sys.modules["aiomqtt"].Client)


@pytest.mark.asyncio
async def test_mqtt_publish_when_client_none() -> None:
    """_mqtt_publish logs warning and returns when mqtt_client is None (lines 600-601)."""
    adapter, _ = _mqtt_adapter()
    await adapter.init()
    adapter._mqtt_client = None
    # Should not raise — just logs warning and returns
    await adapter._mqtt_publish(b"data")


@pytest.mark.asyncio
async def test_mqtt_publish_exception_propagates() -> None:
    """_mqtt_publish re-raises exceptions from client.publish() (lines 617-619)."""

    class FailPublishClient(MockMqttClient):
        async def publish(self, *args: Any, **kwargs: Any) -> None:
            raise OSError("network error")

    adapter = LavinMQQueueAdapter(
        LavinMQSettings(preferred_protocol=Protocol.MQTT),
        mqtt_factory=lambda **kw: FailPublishClient(),
    )
    await adapter.init()
    with pytest.raises(OSError, match="network error"):
        await adapter._mqtt_publish(b"data")


@pytest.mark.asyncio
async def test_close_component_with_callable_close() -> None:
    """_close_component calls close() when it exists and is callable (lines 627-632)."""
    closed: list[bool] = []

    class CloseableComponent:
        def close(self) -> None:
            closed.append(True)

    adapter = LavinMQQueueAdapter(LavinMQSettings())
    await adapter._close_component(CloseableComponent())
    assert closed == [True]


@pytest.mark.asyncio
async def test_close_component_with_async_close() -> None:
    """_close_component awaits close() when it's a coroutine (lines 631-632)."""
    closed: list[bool] = []

    class AsyncCloseableComponent:
        async def close(self) -> None:
            closed.append(True)

    adapter = LavinMQQueueAdapter(LavinMQSettings())
    await adapter._close_component(AsyncCloseableComponent())
    assert closed == [True]


def test_get_metrics_url() -> None:
    """get_metrics_url() returns correct Prometheus endpoint (line 636)."""
    adapter = LavinMQQueueAdapter(LavinMQSettings(metrics_port=15692))
    assert adapter.get_metrics_url() == "http://localhost:15692/metrics"


@pytest.mark.asyncio
async def test_close_component_no_close_method() -> None:
    """_close_component returns early when component has no callable close (line 629)."""

    class NoCloseComponent:
        pass

    adapter = LavinMQQueueAdapter(LavinMQSettings())
    # Should not raise — just returns
    await adapter._close_component(NoCloseComponent())


@pytest.mark.asyncio
async def test_health_aiomqtt_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """health() swallows ImportError when aiomqtt is not importable (lines 261-262)."""
    adapter, _ = _mqtt_adapter()
    await adapter.init()
    # Replace client with non-aiomqtt object, then make aiomqtt unimportable
    adapter._mqtt_client = MockMqttClient()
    monkeypatch.setitem(sys.modules, "aiomqtt", None)  # type: ignore[arg-type]
    # health() except ImportError → pass → falls through to len(active_protocols)
    result = await adapter.health()
    assert result is True


@pytest.mark.asyncio
async def test_ensure_amqp_connection_aio_pika_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_ensure_amqp_connection raises LifecycleError when aio_pika not installed (lines 428-429)."""
    from oneiric.core.lifecycle import LifecycleError

    monkeypatch.setitem(sys.modules, "aio_pika", None)  # type: ignore[arg-type]

    adapter = LavinMQQueueAdapter(
        LavinMQSettings(preferred_protocol=Protocol.AMQP),
        # no factory → tries to import aio_pika
    )
    with pytest.raises(LifecycleError, match="aio-pika-not-installed"):
        await adapter._ensure_amqp_connection()


@pytest.mark.asyncio
async def test_build_amqp_message_aio_pika_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_build_amqp_message raises LifecycleError when aio_pika not installed (lines 488-489)."""
    from oneiric.core.lifecycle import LifecycleError

    monkeypatch.setitem(sys.modules, "aio_pika", None)  # type: ignore[arg-type]

    adapter = LavinMQQueueAdapter(
        LavinMQSettings(preferred_protocol=Protocol.AMQP),
        # no channel_factory → _build_amqp_message tries from aio_pika import Message
    )
    with pytest.raises(LifecycleError, match="aio-pika-not-installed"):
        await adapter._build_amqp_message(b"data", {})


@pytest.mark.asyncio
async def test_init_mqtt_aiomqtt_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """_init_mqtt raises LifecycleError when aiomqtt is not installed (lines 520-521)."""
    from oneiric.core.lifecycle import LifecycleError

    monkeypatch.setitem(sys.modules, "aiomqtt", None)  # type: ignore[arg-type]

    adapter = LavinMQQueueAdapter(
        LavinMQSettings(preferred_protocol=Protocol.MQTT),
        # no mqtt_factory → tries import aiomqtt
    )
    with pytest.raises(LifecycleError, match="aiomqtt-not-installed"):
        await adapter.init()


@pytest.mark.asyncio
async def test_mqtt_subscriber_processes_message() -> None:
    """_mqtt_subscriber processes MQTT messages into the internal queue (lines 558-573)."""
    from types import SimpleNamespace

    class _FakeCtxMessages:
        def __init__(self) -> None:
            self._pending: list[Any] = [
                SimpleNamespace(
                    topic=SimpleNamespace(value="test/topic"),
                    qos=1,
                    payload=b"hello",
                    retain=False,
                )
            ]

        async def __aenter__(self) -> _FakeCtxMessages:
            return self

        async def __aexit__(self, *a: Any) -> None:
            pass

        async def subscribe(self, topic: str, qos: int) -> None:
            pass

        def __aiter__(self) -> _FakeCtxMessages:
            return self

        async def __anext__(self) -> Any:
            if self._pending:
                return self._pending.pop(0)
            raise StopAsyncIteration

    class _FullMqttClient(MockMqttClient):
        async def connect(self) -> None:
            pass

        def messages(self) -> _FakeCtxMessages:
            return _FakeCtxMessages()

    adapter = LavinMQQueueAdapter(
        LavinMQSettings(preferred_protocol=Protocol.MQTT),
        mqtt_factory=lambda **kw: _FullMqttClient(),
    )
    adapter._mqtt_client = _FullMqttClient()
    adapter._active_protocols.add(Protocol.MQTT)
    # Call directly to get coverage (background tasks bypass coverage tracking)
    await adapter._mqtt_subscriber()
    msg = adapter._mqtt_messages.get_nowait()
    assert msg.body == b"hello"
    assert msg.source_protocol == Protocol.MQTT


@pytest.mark.asyncio
async def test_mqtt_subscriber_reconnects_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_mqtt_subscriber creates reconnect task after connection failure (lines 587-588)."""
    tasks_created: list[asyncio.Task] = []
    real_create_task = asyncio.create_task

    def capturing_create_task(coro: Any, **kw: Any) -> asyncio.Task:
        task = real_create_task(coro, **kw)
        tasks_created.append(task)
        task.cancel()  # prevent infinite retry loop
        return task

    monkeypatch.setattr(asyncio, "create_task", capturing_create_task)

    async def instant_sleep(_: float) -> None:
        pass

    monkeypatch.setattr(asyncio, "sleep", instant_sleep)

    class _FailConnectClient(MockMqttClient):
        async def connect(self) -> None:
            raise OSError("connection refused")

    adapter = LavinMQQueueAdapter(
        LavinMQSettings(preferred_protocol=Protocol.MQTT, reconnect_interval=0),
    )
    adapter._mqtt_client = _FailConnectClient()
    adapter._active_protocols.add(Protocol.MQTT)
    await adapter._mqtt_subscriber()
    # Reconnect task must have been created
    assert len(tasks_created) >= 1
