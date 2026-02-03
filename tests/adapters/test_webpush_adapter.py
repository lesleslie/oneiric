from __future__ import annotations

import json

import pytest
from pydantic import SecretStr

from oneiric.adapters.messaging.messaging_types import NotificationMessage
from oneiric.adapters.messaging.webpush import WebPushAdapter, WebPushSettings
from oneiric.core.lifecycle import LifecycleError


@pytest.mark.asyncio
async def test_webpush_send_notification_builds_payload() -> None:
    captured: dict[str, object] = {}

    def sender(**kwargs: object) -> object:
        captured.update(kwargs)

        class Response:
            status_code = 201
            headers = {"Location": "msg-123"}

        return Response()

    adapter = WebPushAdapter(
        WebPushSettings(vapid_private_key=SecretStr("key")),
        sender=sender,
    )
    await adapter.init()

    message = NotificationMessage(
        text="Hello",
        title="Greeting",
        extra_payload={"subscription_info": {"endpoint": "https://push"}},
    )
    result = await adapter.send_notification(message)

    assert result.status_code == 201
    assert result.message_id == "msg-123"
    assert "subscription_info" in captured
    payload = json.loads(captured["data"])
    assert payload["title"] == "Greeting"
    assert payload["body"] == "Hello"

    await adapter.cleanup()


@pytest.mark.asyncio
async def test_webpush_requires_subscription() -> None:
    adapter = WebPushAdapter(WebPushSettings(vapid_private_key=SecretStr("key")))
    await adapter.init()
    with pytest.raises(LifecycleError):
        await adapter.send_notification(NotificationMessage(text="Hello"))
    await adapter.cleanup()
