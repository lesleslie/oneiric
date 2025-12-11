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
