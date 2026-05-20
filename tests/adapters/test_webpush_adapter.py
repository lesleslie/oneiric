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


# ---------------------------------------------------------------------------
# Tests — coverage gaps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webpush_health_with_key() -> None:
    """health() returns True when vapid_private_key is set (line 72)."""
    adapter = WebPushAdapter(WebPushSettings(vapid_private_key=SecretStr("key")))
    assert await adapter.health() is True


@pytest.mark.asyncio
async def test_webpush_health_without_key() -> None:
    """health() returns False when no vapid key configured (line 72)."""
    adapter = WebPushAdapter(WebPushSettings())
    assert await adapter.health() is False


@pytest.mark.asyncio
async def test_webpush_send_raises_when_no_key() -> None:
    """send_notification raises LifecycleError when vapid key is missing (line 82)."""
    adapter = WebPushAdapter(
        WebPushSettings(
            default_subscription_info={"endpoint": "https://push.example.com"}
        ),
        sender=lambda **_: None,
    )
    with pytest.raises(LifecycleError, match="webpush-vapid-private-key-missing"):
        await adapter.send_notification(NotificationMessage(text="Hi"))


@pytest.mark.asyncio
async def test_webpush_send_fallback_message_id() -> None:
    """send_notification uses 'webpush-message' when no location header (line 105)."""

    def sender(**_: object) -> object:
        class _Resp:
            status_code = 201
            headers: dict = {}

        return _Resp()

    adapter = WebPushAdapter(
        WebPushSettings(
            vapid_private_key=SecretStr("key"),
            default_subscription_info={"endpoint": "https://push.example.com"},
        ),
        sender=sender,
    )
    result = await adapter.send_notification(NotificationMessage(text="Hi"))
    assert result.message_id == "webpush-message"


def test_webpush_resolve_subscription_from_target_json() -> None:
    """_resolve_subscription parses target as JSON dict (lines 131-136)."""
    import json

    adapter = WebPushAdapter(WebPushSettings())
    sub = {"endpoint": "https://push.example.com", "keys": {"p256dh": "x", "auth": "y"}}
    message = NotificationMessage(text="Hi", target=json.dumps(sub))
    result = adapter._resolve_subscription(message)
    assert result["endpoint"] == "https://push.example.com"


def test_webpush_resolve_subscription_from_default() -> None:
    """_resolve_subscription falls back to default_subscription_info (line 138)."""
    default_sub = {"endpoint": "https://default.example.com"}
    adapter = WebPushAdapter(
        WebPushSettings(default_subscription_info=default_sub)
    )
    message = NotificationMessage(text="Hi")
    result = adapter._resolve_subscription(message)
    assert result == default_sub


def test_webpush_build_payload_with_override() -> None:
    """_build_payload updates with extra_payload['payload'] dict (line 148)."""
    adapter = WebPushAdapter(WebPushSettings())
    message = NotificationMessage(
        text="Hi",
        extra_payload={"payload": {"custom": "field"}, "subscription_info": {}},
    )
    result = json.loads(adapter._build_payload(message))
    assert result["custom"] == "field"


def test_webpush_resolve_headers_with_extra() -> None:
    """_resolve_headers includes extra headers from extra_payload (line 155)."""
    adapter = WebPushAdapter(WebPushSettings())
    message = NotificationMessage(
        text="Hi",
        extra_payload={"headers": {"X-Custom": "value"}},
    )
    result = adapter._resolve_headers(message)
    assert result == {"X-Custom": "value"}


def test_webpush_resolve_vapid_claims_with_extra() -> None:
    """_resolve_vapid_claims merges extra_payload vapid_claims (line 162)."""
    adapter = WebPushAdapter(WebPushSettings())
    message = NotificationMessage(
        text="Hi",
        extra_payload={"vapid_claims": {"aud": "https://push.example.com"}},
    )
    claims = adapter._resolve_vapid_claims(message)
    assert claims["aud"] == "https://push.example.com"
    assert "sub" in claims


def test_webpush_resolve_subscription_invalid_json_target() -> None:
    """_resolve_subscription handles JSONDecodeError from target (lines 133-134)."""
    default_sub = {"endpoint": "https://push.example.com"}
    adapter = WebPushAdapter(WebPushSettings(default_subscription_info=default_sub))
    message = NotificationMessage(text="Hi", target="not-valid-json")
    result = adapter._resolve_subscription(message)
    assert result == default_sub


def test_webpush_load_sender_from_sys_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    """_load_sender imports pywebpush when no sender provided (lines 119-125)."""
    import sys
    import types

    sent: list[dict] = []

    def fake_webpush(**kwargs: object) -> object:
        sent.append(dict(kwargs))
        return object()

    fake_pywebpush = types.ModuleType("pywebpush")
    fake_pywebpush.webpush = fake_webpush  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pywebpush", fake_pywebpush)

    adapter = WebPushAdapter(WebPushSettings())
    loaded = adapter._load_sender()
    assert loaded is fake_webpush


def test_webpush_resolve_private_key_from_path(tmp_path: object) -> None:
    """_resolve_private_key reads key from vapid_private_key_path (lines 168-169)."""
    import pathlib

    key_file = pathlib.Path(str(tmp_path)) / "vapid.pem"  # type: ignore[arg-type]
    key_file.write_text("my-vapid-key")
    adapter = WebPushAdapter(
        WebPushSettings(vapid_private_key_path=key_file)
    )
    assert adapter._resolve_private_key() == "my-vapid-key"
