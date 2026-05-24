from __future__ import annotations

from types import SimpleNamespace

import pytest

from oneiric.adapters.messaging.fcm import FCMPushAdapter, FCMPushSettings
from oneiric.adapters.messaging.messaging_types import NotificationMessage
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


# ---------------------------------------------------------------------------
# Tests — httpx adapter (originally in this file)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_httpx_adapter_performs_requests() -> None:
    import httpx

    from oneiric.adapters.http.httpx import HTTPClientAdapter

    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"ok": True}))
    adapter = HTTPClientAdapter(transport=transport)
    await adapter.init()

    resp = await adapter.get("https://example.com/ping")
    assert resp.status_code == 200

    resp2 = await adapter.post("https://example.com/data", json={"a": 1})
    assert resp2.status_code == 200

    await adapter.cleanup()


@pytest.mark.asyncio
async def test_httpx_adapter_health_checks_with_base_url() -> None:
    import httpx

    from oneiric.adapters.http.httpx import HTTPClientAdapter, HTTPClientSettings

    transport = httpx.MockTransport(lambda req: httpx.Response(200))
    settings = HTTPClientSettings(
        base_url="https://service.local",
        healthcheck_path="/health",
    )
    adapter = HTTPClientAdapter(settings=settings, transport=transport)
    await adapter.init()
    assert await adapter.health() is True
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_httpx_adapter_health_without_base_url() -> None:
    import httpx

    from oneiric.adapters.http.httpx import HTTPClientAdapter

    transport = httpx.MockTransport(lambda req: httpx.Response(200))
    adapter = HTTPClientAdapter(transport=transport)
    await adapter.init()
    assert await adapter.health() is True
    await adapter.cleanup()


def test_init_creates_httpx_client() -> None:
    from oneiric.adapters.http.httpx import HTTPClientAdapter

    adapter = HTTPClientAdapter()
    assert adapter._client is None


# ---------------------------------------------------------------------------
# Tests — init / health / cleanup edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fcm_init_with_app_factory() -> None:
    app = object()
    calls: list[str] = []

    def factory() -> object:
        calls.append("created")
        return app

    adapter = FCMPushAdapter(FCMPushSettings(), app_factory=factory)
    await adapter.init()
    assert calls == ["created"]
    assert adapter._app is app
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_fcm_health_with_app() -> None:
    adapter = FCMPushAdapter(FCMPushSettings(), app=object())
    assert await adapter.health() is True


@pytest.mark.asyncio
async def test_fcm_health_without_app() -> None:
    adapter = FCMPushAdapter(FCMPushSettings())
    assert await adapter.health() is False


@pytest.mark.asyncio
async def test_fcm_cleanup_calls_delete_app() -> None:
    deleted: list[bool] = []

    fake_admin = SimpleNamespace(delete_app=lambda _app: deleted.append(True))
    app = object()

    adapter = FCMPushAdapter(FCMPushSettings())
    adapter._app = app
    adapter._owns_app = True
    adapter._firebase_admin = fake_admin
    await adapter.cleanup()

    assert deleted == [True]
    assert adapter._app is None


@pytest.mark.asyncio
async def test_fcm_cleanup_no_firebase_admin() -> None:
    adapter = FCMPushAdapter(FCMPushSettings())
    adapter._app = object()
    adapter._owns_app = True
    adapter._firebase_admin = None
    await adapter.cleanup()  # should not raise
    assert adapter._app is None


# ---------------------------------------------------------------------------
# Tests — _ensure_app
# ---------------------------------------------------------------------------


def test_ensure_app_raises_when_none() -> None:
    adapter = FCMPushAdapter(FCMPushSettings())
    with pytest.raises(LifecycleError, match="fcm-app-not-initialized"):
        adapter._ensure_app()


def test_ensure_app_returns_app() -> None:
    app = object()
    adapter = FCMPushAdapter(FCMPushSettings(), app=app)
    assert adapter._ensure_app() is app


# ---------------------------------------------------------------------------
# Tests — _default_sender
# ---------------------------------------------------------------------------


def test_default_sender_no_firebase_admin() -> None:
    adapter = FCMPushAdapter(FCMPushSettings())
    with pytest.raises(LifecycleError, match="fcm-firebase-admin-not-initialized"):
        adapter._default_sender(object(), object())


def test_default_sender_no_messaging() -> None:
    adapter = FCMPushAdapter(FCMPushSettings())
    adapter._firebase_admin = SimpleNamespace()  # no messaging attr
    with pytest.raises(LifecycleError, match="fcm-messaging-module-missing"):
        adapter._default_sender(object(), object())


def test_default_sender_no_send() -> None:
    adapter = FCMPushAdapter(FCMPushSettings())
    adapter._firebase_admin = SimpleNamespace(messaging=SimpleNamespace())  # no send
    with pytest.raises(LifecycleError, match="fcm-send-missing"):
        adapter._default_sender(object(), object())


def test_default_sender_success() -> None:
    sent: list[object] = []

    def send_fn(payload: object, app: object) -> str:
        sent.append(payload)
        return "response-id"

    messaging = SimpleNamespace(send=send_fn)
    adapter = FCMPushAdapter(FCMPushSettings())
    adapter._firebase_admin = SimpleNamespace(messaging=messaging)

    result = adapter._default_sender("payload", "app")
    assert result == "response-id"
    assert len(sent) == 1


# ---------------------------------------------------------------------------
# Tests — _build_message_payload
# ---------------------------------------------------------------------------


def test_build_message_payload_no_firebase_admin() -> None:
    adapter = FCMPushAdapter(FCMPushSettings())
    with pytest.raises(LifecycleError, match="fcm-firebase-admin-not-initialized"):
        adapter._build_message_payload(
            NotificationMessage(text="hi", target="tok"), "tok"
        )


def test_build_message_payload_basic() -> None:
    adapter = FCMPushAdapter(FCMPushSettings(), app=object())
    adapter._firebase_admin = SimpleNamespace(messaging=_StubMessaging)

    msg = NotificationMessage(text="body", title="Title", target="tok")
    payload = adapter._build_message_payload(msg, "tok")
    assert isinstance(payload, _StubMessaging.Message)
    assert payload.kwargs["token"] == "tok"


def test_build_message_payload_with_data() -> None:
    adapter = FCMPushAdapter(FCMPushSettings(), app=object())
    adapter._firebase_admin = SimpleNamespace(messaging=_StubMessaging)

    msg = NotificationMessage(
        text="body",
        target="tok",
        extra_payload={"data": {"key": "value"}},
    )
    payload = adapter._build_message_payload(msg, "tok")
    assert payload.kwargs["data"] == {"key": "value"}


def test_build_message_payload_invalid_data() -> None:
    adapter = FCMPushAdapter(FCMPushSettings(), app=object())
    adapter._firebase_admin = SimpleNamespace(messaging=_StubMessaging)

    msg = NotificationMessage(
        text="body",
        target="tok",
        extra_payload={"data": "not-a-dict"},
    )
    with pytest.raises(LifecycleError, match="fcm-data-must-be-dict"):
        adapter._build_message_payload(msg, "tok")


def test_build_message_payload_with_extra_notification() -> None:
    adapter = FCMPushAdapter(FCMPushSettings(), app=object())
    adapter._firebase_admin = SimpleNamespace(messaging=_StubMessaging)

    msg = NotificationMessage(
        text="body",
        target="tok",
        extra_payload={"notification": {"image": "http://img"}},
    )
    payload = adapter._build_message_payload(msg, "tok")
    assert isinstance(payload.kwargs["notification"], _StubMessaging.Notification)


# ---------------------------------------------------------------------------
# Tests — send_notification with default token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fcm_send_notification_default_token() -> None:
    captured: list[str] = []

    def sender(payload: object, app: object) -> str:
        captured.append(payload.kwargs["token"])  # type: ignore[attr-defined]
        return "msg-x"

    settings = FCMPushSettings(default_device_token="default-tok")
    adapter = FCMPushAdapter(settings, app=object(), sender=sender)
    adapter._firebase_admin = SimpleNamespace(messaging=_StubMessaging)
    await adapter.init()

    result = await adapter.send_notification(NotificationMessage(text="Hi"))
    assert result.message_id == "msg-x"
    assert captured == ["default-tok"]


# ---------------------------------------------------------------------------
# Tests — coverage gaps
# ---------------------------------------------------------------------------


def test_fcm_default_app_factory_via_sys_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_default_app_factory imports firebase_admin from sys.modules (lines 101-121)."""
    import sys
    import types

    fake_app = object()
    options_captured: list[dict] = []

    class FakeCreds:
        @staticmethod
        def ApplicationDefault() -> object:
            return object()

        @staticmethod
        def Certificate(path: str) -> object:
            return object()

    def fake_get_app(name: str) -> None:
        raise ValueError("not found")

    def fake_initialize_app(cred: object, options: dict, name: str) -> object:
        options_captured.append(dict(options))
        return fake_app

    fake_firebase = types.ModuleType("firebase_admin")
    fake_firebase.credentials = FakeCreds  # type: ignore[attr-defined]
    fake_firebase.get_app = fake_get_app  # type: ignore[attr-defined]
    fake_firebase.initialize_app = fake_initialize_app  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "firebase_admin", fake_firebase)
    monkeypatch.setitem(sys.modules, "firebase_admin.credentials", fake_firebase)

    # Test with credentials_file and project_id (lines 115, 120)
    import pathlib

    adapter = FCMPushAdapter(
        FCMPushSettings(
            credentials_file=pathlib.Path("/fake/creds.json"),
            project_id="my-project",
        )
    )
    result = adapter._default_app_factory()
    assert result is fake_app
    assert options_captured[0].get("projectId") == "my-project"


def test_build_message_payload_with_platform_config() -> None:
    """_build_message_payload includes android/apns/webpush from extra_payload (line 155)."""
    adapter = FCMPushAdapter(FCMPushSettings(), app=object())
    adapter._firebase_admin = SimpleNamespace(messaging=_StubMessaging)

    msg = NotificationMessage(
        text="body",
        target="tok",
        extra_payload={"android": {"priority": "high"}, "apns": {"headers": {}}},
    )
    payload = adapter._build_message_payload(msg, "tok")
    assert payload.kwargs["android"] == {"priority": "high"}
    assert payload.kwargs["apns"] == {"headers": {}}


def test_fcm_default_app_factory_application_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_default_app_factory uses ApplicationDefault when no credentials_file (line 117)."""
    import sys
    import types

    fake_app = object()
    app_default_calls: list[bool] = []

    class FakeCreds:
        @staticmethod
        def ApplicationDefault() -> object:
            app_default_calls.append(True)
            return object()

        @staticmethod
        def Certificate(path: str) -> object:
            return object()

    def fake_get_app(name: str) -> None:
        raise ValueError("not found")

    def fake_initialize_app(cred: object, options: dict, name: str) -> object:
        return fake_app

    fake_firebase = types.ModuleType("firebase_admin")
    fake_firebase.credentials = FakeCreds  # type: ignore[attr-defined]
    fake_firebase.get_app = fake_get_app  # type: ignore[attr-defined]
    fake_firebase.initialize_app = fake_initialize_app  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "firebase_admin", fake_firebase)
    monkeypatch.setitem(sys.modules, "firebase_admin.credentials", fake_firebase)

    adapter = FCMPushAdapter(FCMPushSettings())  # no credentials_file → else branch
    result = adapter._default_app_factory()
    assert result is fake_app
    assert app_default_calls == [True]
