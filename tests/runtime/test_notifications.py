"""Tests for NotificationRouter helpers."""

from __future__ import annotations

import pytest

from oneiric.adapters import AdapterBridge
from oneiric.adapters.messaging.common import MessagingSendResult, NotificationMessage
from oneiric.core.config import LayerSettings
from oneiric.core.lifecycle import LifecycleManager
from oneiric.core.resolution import Candidate, Resolver
from oneiric.runtime.notifications import NotificationRoute, NotificationRouter


class DummyNotificationAdapter:
    """Adapter stub that records the last NotificationMessage."""

    last_message: NotificationMessage | None = None

    async def send_notification(
        self, message: NotificationMessage
    ) -> MessagingSendResult:
        DummyNotificationAdapter.last_message = message
        return MessagingSendResult(message_id="demo", status_code=200)


@pytest.mark.asyncio
async def test_notification_router_sends_via_adapter(tmp_path):
    resolver = Resolver()
    resolver.register(
        Candidate(
            domain="adapter",
            key="notifications.demo",
            provider="cli",
            factory=DummyNotificationAdapter,
            stack_level=10,
        )
    )
    lifecycle = LifecycleManager(
        resolver, status_snapshot_path=str(tmp_path / "status.json")
    )
    bridge = AdapterBridge(
        resolver, lifecycle, LayerSettings(selections={"notifications.demo": "cli"})
    )
    router = NotificationRouter(bridge)
    route = NotificationRoute(
        adapter_key="notifications.demo",
        title_template="[{level}] {channel}",
    )
    record = {
        "message": "Deploy complete",
        "channel": "deploys",
        "level": "info",
        "context": {"service": "demo", "revision": "abc123"},
    }

    result = await router.send(record, route)

    assert isinstance(result, MessagingSendResult)
    message = DummyNotificationAdapter.last_message
    assert message is not None
    assert "Deploy complete" in message.text
    assert "service" in message.text
    assert message.title == "[INFO] deploys"


@pytest.mark.asyncio
async def test_notification_router_without_adapter(tmp_path):
    resolver = Resolver()
    lifecycle = LifecycleManager(
        resolver, status_snapshot_path=str(tmp_path / "status.json")
    )
    bridge = AdapterBridge(resolver, lifecycle, LayerSettings())
    router = NotificationRouter(bridge)

    result = await router.send(
        {"message": "noop", "channel": "demo", "level": "info"},
        NotificationRoute(),
    )

    assert result is None
