from types import SimpleNamespace

import pytest

from oneiric.adapters.queue.pubsub import PubSubQueueAdapter, PubSubQueueSettings


class _FakePublisher:
    def __init__(self) -> None:
        self.published: list[tuple[str, bytes, dict]] = []
        self.last_topic: str | None = None

    def topic_path(self, project_id: str, topic: str) -> str:
        return f"projects/{project_id}/topics/{topic}"

    def publish(self, topic_path: str, data: bytes, **attrs: str) -> SimpleNamespace:
        self.published.append((topic_path, data, attrs))
        return SimpleNamespace(result=lambda: "msg-1")

    def get_topic(self, topic_path: str) -> dict:
        self.last_topic = topic_path
        return {"name": topic_path}

    def close(self) -> None:  # pragma: no cover - defensive cleanup path
        pass


class _FakeSubscriber:
    def __init__(self) -> None:
        self.pulls: list[dict] = []
        self.acks: list[dict] = []

    def subscription_path(self, project_id: str, subscription: str) -> str:
        return f"projects/{project_id}/subscriptions/{subscription}"

    def pull(self, request: dict) -> SimpleNamespace:
        self.pulls.append(request)
        message = SimpleNamespace(
            message=SimpleNamespace(message_id="ack-1", data=b"{}", attributes={}),
            ack_id="ack-1",
        )
        return SimpleNamespace(received_messages=[message])

    def acknowledge(self, request: dict) -> None:
        self.acks.append(request)

    def close(self) -> None:  # pragma: no cover - defensive cleanup path
        pass


@pytest.mark.asyncio
async def test_pubsub_enqueue_and_read_flow() -> None:
    publisher = _FakePublisher()
    subscriber = _FakeSubscriber()
    adapter = PubSubQueueAdapter(
        settings=PubSubQueueSettings(
            project_id="demo",
            topic="workflow",
            subscription="workflow-sub",
        ),
        publisher_client=publisher,
        subscriber_client=subscriber,
    )

    await adapter.init()
    message_id = await adapter.enqueue({"dag": "demo"})
    assert message_id == "msg-1"
    assert len(publisher.published) == 1

    messages = await adapter.read(count=1)
    assert len(messages) == 1
    assert messages[0]["message_id"] == "ack-1"

    acked = await adapter.ack([messages[0]["ack_id"]])
    assert acked == 1

    healthy = await adapter.health()
    assert healthy is True


# ---------------------------------------------------------------------------
# Tests — coverage gaps
# ---------------------------------------------------------------------------


def _make_adapter(
    **settings_kwargs,
) -> tuple[PubSubQueueAdapter, _FakePublisher, _FakeSubscriber]:
    publisher = _FakePublisher()
    subscriber = _FakeSubscriber()
    adapter = PubSubQueueAdapter(
        settings=PubSubQueueSettings(
            project_id="demo",
            topic="workflow",
            subscription="workflow-sub",
            **settings_kwargs,
        ),
        publisher_client=publisher,
        subscriber_client=subscriber,
    )
    return adapter, publisher, subscriber


@pytest.mark.asyncio
async def test_pubsub_cleanup() -> None:
    """cleanup() nils publisher and subscriber clients (lines 92-101)."""
    adapter, publisher, subscriber = _make_adapter()
    await adapter.init()
    await adapter.cleanup()
    assert adapter._publisher_client is None
    assert adapter._subscriber_client is None


@pytest.mark.asyncio
async def test_pubsub_cleanup_calls_close_on_owned_clients() -> None:
    """cleanup() calls close() when adapter owns the clients (lines 93-99)."""
    pub_closed: list[bool] = []
    sub_closed: list[bool] = []

    class ClosingPublisher(_FakePublisher):
        def close(self) -> None:
            pub_closed.append(True)

    class ClosingSubscriber(_FakeSubscriber):
        def close(self) -> None:
            sub_closed.append(True)

    publisher = ClosingPublisher()
    subscriber = ClosingSubscriber()
    adapter = PubSubQueueAdapter(
        settings=PubSubQueueSettings(project_id="demo", topic="t", subscription="s"),
        publisher_client=publisher,
        subscriber_client=subscriber,
    )
    await adapter.init()
    # Force ownership so cleanup actually calls close()
    adapter._owns_publisher = True
    adapter._owns_subscriber = True
    await adapter.cleanup()
    assert pub_closed == [True]
    assert sub_closed == [True]


@pytest.mark.asyncio
async def test_pubsub_enqueue_with_ordering_key() -> None:
    """enqueue passes ordering_key attribute when set (line 119)."""
    adapter, publisher, _ = _make_adapter(ordering_key="my-key")
    await adapter.init()
    await adapter.enqueue({"x": 1})
    _, _, attrs = publisher.published[-1]
    assert attrs.get("ordering_key") == "my-key"


@pytest.mark.asyncio
async def test_pubsub_read_raises_without_subscription() -> None:
    """read() raises LifecycleError when subscription is not configured (line 132)."""
    from oneiric.core.lifecycle import LifecycleError

    adapter = PubSubQueueAdapter(
        settings=PubSubQueueSettings(project_id="p", topic="t"),
        publisher_client=_FakePublisher(),
    )
    await adapter.init()
    with pytest.raises(LifecycleError, match="pubsub-subscription-not-configured"):
        await adapter.read()


@pytest.mark.asyncio
async def test_pubsub_ack_empty_returns_zero() -> None:
    """ack() returns 0 immediately when message_ids is empty (line 150)."""
    adapter, _, _ = _make_adapter()
    await adapter.init()
    assert await adapter.ack([]) == 0


@pytest.mark.asyncio
async def test_pubsub_ack_raises_without_subscription() -> None:
    """ack() raises LifecycleError when subscription is not configured (line 154)."""
    from oneiric.core.lifecycle import LifecycleError

    adapter = PubSubQueueAdapter(
        settings=PubSubQueueSettings(project_id="p", topic="t"),
        publisher_client=_FakePublisher(),
    )
    await adapter.init()
    with pytest.raises(LifecycleError, match="pubsub-subscription-not-configured"):
        await adapter.ack(["id-1"])


@pytest.mark.asyncio
async def test_pubsub_pending_returns_subscription_info() -> None:
    """pending() returns subscription path info (lines 162-164)."""
    adapter, _, _ = _make_adapter()
    await adapter.init()
    result = await adapter.pending()
    assert len(result) == 1
    assert "subscription" in result[0]


@pytest.mark.asyncio
async def test_pubsub_pending_returns_empty_without_subscription() -> None:
    """pending() returns [] when subscription_path is None (line 162-163)."""
    adapter = PubSubQueueAdapter(
        settings=PubSubQueueSettings(project_id="p", topic="t"),
        publisher_client=_FakePublisher(),
    )
    await adapter.init()
    assert await adapter.pending() == []


@pytest.mark.asyncio
async def test_pubsub_ensure_publisher_raises_when_none() -> None:
    """_ensure_publisher raises LifecycleError when publisher is None (line 168)."""
    from oneiric.core.lifecycle import LifecycleError

    adapter = PubSubQueueAdapter(
        settings=PubSubQueueSettings(project_id="p", topic="t"),
        publisher_client=_FakePublisher(),
    )
    adapter._publisher_client = None
    with pytest.raises(LifecycleError, match="pubsub-publisher-not-initialized"):
        adapter._ensure_publisher()


@pytest.mark.asyncio
async def test_pubsub_ensure_topic_path_raises_when_none() -> None:
    """_ensure_topic_path raises LifecycleError when topic path is not set (line 173)."""
    from oneiric.core.lifecycle import LifecycleError

    adapter, _, _ = _make_adapter()
    assert adapter._topic_path is None
    with pytest.raises(LifecycleError, match="pubsub-topic-path-missing"):
        adapter._ensure_topic_path()


@pytest.mark.asyncio
async def test_pubsub_init_creates_clients_from_sdk(monkeypatch) -> None:
    """init() creates PublisherClient and SubscriberClient from google.cloud.pubsub_v1 (lines 66-76)."""
    import sys
    import types

    publisher = _FakePublisher()
    subscriber = _FakeSubscriber()

    fake_pubsub_v1 = types.ModuleType("pubsub_v1")
    fake_pubsub_v1.PublisherClient = lambda: publisher  # type: ignore[attr-defined]
    fake_pubsub_v1.SubscriberClient = lambda: subscriber  # type: ignore[attr-defined]

    fake_google_cloud = types.ModuleType("google.cloud")
    fake_google_cloud.pubsub_v1 = fake_pubsub_v1  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "google", types.ModuleType("google"))
    monkeypatch.setitem(sys.modules, "google.cloud", fake_google_cloud)
    monkeypatch.setitem(sys.modules, "google.cloud.pubsub_v1", fake_pubsub_v1)

    adapter = PubSubQueueAdapter(
        settings=PubSubQueueSettings(project_id="p", topic="t", subscription="s"),
        # No pre-provided clients — triggers SDK import
    )
    await adapter.init()
    assert adapter._publisher_client is publisher
    assert adapter._subscriber_client is subscriber
