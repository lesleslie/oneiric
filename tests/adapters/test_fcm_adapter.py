from __future__ import annotations

from types import SimpleNamespace

import pytest

from oneiric.adapters.messaging.messaging_types import NotificationMessage
from oneiric.adapters.messaging.fcm import FCMPushAdapter, FCMPushSettings
from oneiric.core.lifecycle import LifecycleError


class _StubMessaging:
    class Notification:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    class Message:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs


@pytest.mark.asyncio
async def test_fcm_send_notification_builds_message() -> None:
    captured: dict[str, object] = {}

    def sender(payload: object, app: object) -> object:
        captured["payload"] = payload
        captured["app"] = app
        return "msg-1"

    adapter = FCMPushAdapter(
        FCMPushSettings(),
        app=object(),
        sender=sender,
    )
    adapter._firebase_admin = SimpleNamespace(messaging=_StubMessaging)
    await adapter.init()

    message = NotificationMessage(text="Hello", title="Title", target="token-1")
    result = await adapter.send_notification(message)

    assert result.message_id == "msg-1"
    payload = captured["payload"]
    assert isinstance(payload, _StubMessaging.Message)
    assert payload.kwargs["token"] == "token-1"

    await adapter.cleanup()


@pytest.mark.asyncio
async def test_fcm_requires_token() -> None:
    adapter = FCMPushAdapter(FCMPushSettings(), app=object())
    adapter._firebase_admin = SimpleNamespace(messaging=_StubMessaging)
    await adapter.init()
    with pytest.raises(LifecycleError):
        await adapter.send_notification(NotificationMessage(text="Hello"))
    await adapter.cleanup()
