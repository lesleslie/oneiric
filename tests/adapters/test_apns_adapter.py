from __future__ import annotations

import pytest

from oneiric.adapters.messaging.apns import APNSPushAdapter, APNSPushSettings
from oneiric.adapters.messaging.messaging_types import NotificationMessage
from oneiric.core.lifecycle import LifecycleError


class _FakeAPNSClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def send_notification(
        self, token: str, payload: dict[str, object], **kwargs: object
    ) -> object:
        self.calls.append({"token": token, "payload": payload, "kwargs": kwargs})

        class Response:
            status = 200
            headers = {"apns-id": "apns-123"}

        return Response()


@pytest.mark.asyncio
async def test_apns_send_notification() -> None:
    client = _FakeAPNSClient()
    adapter = APNSPushAdapter(
        APNSPushSettings(topic="com.example.app"),
        client=client,
    )
    await adapter.init()

    message = NotificationMessage(text="Hello", title="Hi", target="token-1")
    result = await adapter.send_notification(message)

    assert result.message_id == "apns-123"
    assert client.calls[0]["token"] == "token-1"

    await adapter.cleanup()


@pytest.mark.asyncio
async def test_apns_requires_token() -> None:
    adapter = APNSPushAdapter(APNSPushSettings(topic="com.example.app"))
    await adapter.init()
    with pytest.raises(LifecycleError):
        await adapter.send_notification(NotificationMessage(text="Hello"))
    await adapter.cleanup()
