from __future__ import annotations

from typing import Any

import pytest

from oneiric.adapters.queue.nats import NATSQueueAdapter, NATSQueueSettings


class DummyNATS:
    def __init__(self) -> None:
        self.is_connected = True
        self.published: list[tuple[str, bytes]] = []
        self.subscriptions: list[tuple[str, str]] = []
        self.closed = False

    async def publish(self, subject: str, payload: bytes, headers: dict[str, str] | None = None) -> None:
        self.published.append((subject, payload))

    async def subscribe(self, subject: str, queue: str | None = None, cb: Any | None = None) -> str:
        self.subscriptions.append((subject, queue or ""))
        await cb(None)  # type: ignore[arg-type]
        return "sid-1"

    async def request(self, subject: str, payload: bytes, timeout: float | None = None) -> str:
        return "response"

    async def drain(self) -> None:
        return None

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_publish_and_subscribe(monkeypatch: pytest.MonkeyPatch) -> None:
    dummy = DummyNATS()

    async def _connect(**kwargs: Any) -> DummyNATS:
        return dummy

    monkeypatch.setattr("oneiric.adapters.queue.nats.nats.connect", _connect)

    adapter = NATSQueueAdapter(NATSQueueSettings())
    await adapter.init()
    await adapter.publish("demo", b"payload")

    async def _cb(msg: Any) -> None:
        return None

    await adapter.subscribe("demo", cb=_cb)
    assert dummy.published == [("demo", b"payload")]
    assert dummy.subscriptions[0][0] == "demo"
    await adapter.cleanup()
    assert dummy.closed is True


@pytest.mark.asyncio
async def test_health_reflects_connection() -> None:
    dummy = DummyNATS()
    adapter = NATSQueueAdapter(NATSQueueSettings(), client=dummy)
    await adapter.init()
    assert await adapter.health() is True
    dummy.is_connected = False
    assert await adapter.health() is False
    await adapter.cleanup()
