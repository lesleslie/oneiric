from __future__ import annotations

import inspect

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


# ---------------------------------------------------------------------------
# Tests — init variants
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_init_with_client_factory() -> None:
    client = _FakeAPNSClient()
    calls: list[str] = []

    def factory() -> _FakeAPNSClient:
        calls.append("made")
        return client

    adapter = APNSPushAdapter(
        APNSPushSettings(topic="com.example.app"),
        client_factory=factory,
    )
    await adapter.init()
    assert calls == ["made"]
    assert adapter._client is client
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_init_deferred_no_client() -> None:
    adapter = APNSPushAdapter(APNSPushSettings(topic="com.example.app"))
    await adapter.init()
    assert adapter._client is None


# ---------------------------------------------------------------------------
# Tests — health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_with_client() -> None:
    adapter = APNSPushAdapter(
        APNSPushSettings(topic="com.example.app"),
        client=_FakeAPNSClient(),
    )
    assert await adapter.health() is True


@pytest.mark.asyncio
async def test_health_without_client() -> None:
    adapter = APNSPushAdapter(APNSPushSettings(topic="com.example.app"))
    assert await adapter.health() is False


# ---------------------------------------------------------------------------
# Tests — cleanup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_calls_close() -> None:
    closed: list[bool] = []

    class ClosingClient:
        def close(self) -> None:
            closed.append(True)

    adapter = APNSPushAdapter(APNSPushSettings(topic="com.example.app"))
    adapter._client = ClosingClient()
    adapter._owns_client = True
    await adapter.cleanup()
    assert closed == [True]
    assert adapter._client is None


@pytest.mark.asyncio
async def test_cleanup_calls_async_close() -> None:
    closed: list[bool] = []

    class AsyncClosingClient:
        async def close(self) -> None:
            closed.append(True)

    adapter = APNSPushAdapter(APNSPushSettings(topic="com.example.app"))
    adapter._client = AsyncClosingClient()
    adapter._owns_client = True
    await adapter.cleanup()
    assert closed == [True]


@pytest.mark.asyncio
async def test_cleanup_not_owns_client() -> None:
    client = _FakeAPNSClient()
    adapter = APNSPushAdapter(
        APNSPushSettings(topic="com.example.app"),
        client=client,
    )
    # _owns_client is False when client is provided directly
    await adapter.cleanup()
    # client should be set to None but close never called


# ---------------------------------------------------------------------------
# Tests — _maybe_connect
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_maybe_connect_sync_connect() -> None:
    connected: list[bool] = []

    class ConnectingClient:
        def connect(self) -> None:
            connected.append(True)

    adapter = APNSPushAdapter(APNSPushSettings(topic="com.example.app"))
    adapter._client = ConnectingClient()
    await adapter._maybe_connect()
    assert connected == [True]


@pytest.mark.asyncio
async def test_maybe_connect_async_connect() -> None:
    connected: list[bool] = []

    class AsyncConnectingClient:
        async def connect(self) -> None:
            connected.append(True)

    adapter = APNSPushAdapter(APNSPushSettings(topic="com.example.app"))
    adapter._client = AsyncConnectingClient()
    await adapter._maybe_connect()
    assert connected == [True]


@pytest.mark.asyncio
async def test_maybe_connect_no_connect_attr() -> None:
    adapter = APNSPushAdapter(APNSPushSettings(topic="com.example.app"))
    adapter._client = object()
    await adapter._maybe_connect()  # should not raise


@pytest.mark.asyncio
async def test_maybe_connect_none_client() -> None:
    adapter = APNSPushAdapter(APNSPushSettings(topic="com.example.app"))
    await adapter._maybe_connect()  # client is None, should not raise


# ---------------------------------------------------------------------------
# Tests — _maybe_disconnect
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_maybe_disconnect_uses_disconnect() -> None:
    disconnected: list[bool] = []

    class DisconnectingClient:
        def disconnect(self) -> None:
            disconnected.append(True)

    adapter = APNSPushAdapter(APNSPushSettings(topic="com.example.app"))
    adapter._client = DisconnectingClient()
    await adapter._maybe_disconnect()
    assert disconnected == [True]


@pytest.mark.asyncio
async def test_maybe_disconnect_uses_shutdown() -> None:
    shut: list[bool] = []

    class ShutdownClient:
        def shutdown(self) -> None:
            shut.append(True)

    adapter = APNSPushAdapter(APNSPushSettings(topic="com.example.app"))
    adapter._client = ShutdownClient()
    await adapter._maybe_disconnect()
    assert shut == [True]


@pytest.mark.asyncio
async def test_maybe_disconnect_async() -> None:
    closed: list[bool] = []

    class AsyncShutdownClient:
        async def close(self) -> None:
            closed.append(True)

    adapter = APNSPushAdapter(APNSPushSettings(topic="com.example.app"))
    adapter._client = AsyncShutdownClient()
    await adapter._maybe_disconnect()
    assert closed == [True]


# ---------------------------------------------------------------------------
# Tests — _try_send_notification / _try_send
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_try_send_notification_success() -> None:
    class SendNotifClient:
        async def send_notification(
            self, token: str, payload: object, **_kw: object
        ) -> str:
            return "ok"

    adapter = APNSPushAdapter(APNSPushSettings(topic="com.example.app"))
    result = await adapter._try_send_notification(
        SendNotifClient(), "tok", {}, {}
    )
    assert result == "ok"


@pytest.mark.asyncio
async def test_try_send_notification_no_attr() -> None:
    adapter = APNSPushAdapter(APNSPushSettings(topic="com.example.app"))
    result = await adapter._try_send_notification(object(), "tok", {}, {})
    assert result is None


@pytest.mark.asyncio
async def test_try_send_notification_type_error() -> None:
    class BadClient:
        def send_notification(self, *_a: object, **_kw: object) -> str:
            raise TypeError("unexpected kwargs")

    adapter = APNSPushAdapter(APNSPushSettings(topic="com.example.app"))
    result = await adapter._try_send_notification(BadClient(), "tok", {}, {})
    assert result is None


@pytest.mark.asyncio
async def test_try_send_success() -> None:
    class SendClient:
        async def send(self, token: str, payload: object, **_kw: object) -> str:
            return "sent"

    adapter = APNSPushAdapter(APNSPushSettings(topic="com.example.app"))
    result = await adapter._try_send(SendClient(), "tok", {}, {})
    assert result == "sent"


@pytest.mark.asyncio
async def test_try_send_no_attr() -> None:
    adapter = APNSPushAdapter(APNSPushSettings(topic="com.example.app"))
    result = await adapter._try_send(object(), "tok", {}, {})
    assert result is None


@pytest.mark.asyncio
async def test_try_send_type_error() -> None:
    class BadSend:
        def send(self, *_a: object, **_kw: object) -> None:
            raise TypeError("bad args")

    adapter = APNSPushAdapter(APNSPushSettings(topic="com.example.app"))
    result = await adapter._try_send(BadSend(), "tok", {}, {})
    assert result is None


# ---------------------------------------------------------------------------
# Tests — _try_notification_request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_try_notification_request_no_aioapns() -> None:
    adapter = APNSPushAdapter(APNSPushSettings(topic="com.example.app"))
    adapter._aioapns = None
    result = await adapter._try_notification_request(object(), "tok", {}, {})
    assert result is None


@pytest.mark.asyncio
async def test_try_notification_request_no_request_cls() -> None:
    from types import SimpleNamespace

    adapter = APNSPushAdapter(APNSPushSettings(topic="com.example.app"))
    adapter._aioapns = SimpleNamespace()  # no NotificationRequest attr
    result = await adapter._try_notification_request(object(), "tok", {}, {})
    assert result is None


@pytest.mark.asyncio
async def test_try_notification_request_success() -> None:
    from types import SimpleNamespace

    class FakeRequest:
        def __init__(self, **_kw: object) -> None:
            pass

    class ClientWithNotif:
        async def send_notification(self, req: object) -> str:
            return "notif-ok"

    adapter = APNSPushAdapter(APNSPushSettings(topic="com.example.app"))
    adapter._aioapns = SimpleNamespace(NotificationRequest=FakeRequest)
    result = await adapter._try_notification_request(ClientWithNotif(), "tok", {}, {})
    assert result == "notif-ok"


@pytest.mark.asyncio
async def test_try_notification_request_no_send_notification() -> None:
    from types import SimpleNamespace

    class FakeRequest:
        def __init__(self, **_kw: object) -> None:
            pass

    adapter = APNSPushAdapter(APNSPushSettings(topic="com.example.app"))
    adapter._aioapns = SimpleNamespace(NotificationRequest=FakeRequest)
    result = await adapter._try_notification_request(object(), "tok", {}, {})
    assert result is None


# ---------------------------------------------------------------------------
# Tests — _dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_falls_through_to_error() -> None:
    adapter = APNSPushAdapter(APNSPushSettings(topic="com.example.app"))
    adapter._aioapns = None
    with pytest.raises(LifecycleError, match="apns-send-not-supported"):
        await adapter._dispatch(object(), "tok", {}, {})


# ---------------------------------------------------------------------------
# Tests — _build_payload
# ---------------------------------------------------------------------------


def test_build_payload_with_title() -> None:
    adapter = APNSPushAdapter(APNSPushSettings(topic="com.example.app"))
    message = NotificationMessage(text="body", title="Title", target="tok")
    payload = adapter._build_payload(message)
    assert payload["aps"]["alert"]["title"] == "Title"


def test_build_payload_no_title() -> None:
    adapter = APNSPushAdapter(APNSPushSettings(topic="com.example.app"))
    message = NotificationMessage(text="body", target="tok")
    payload = adapter._build_payload(message)
    assert payload["aps"]["alert"] == "body"


def test_build_payload_extra_aps() -> None:
    adapter = APNSPushAdapter(APNSPushSettings(topic="com.example.app"))
    message = NotificationMessage(
        text="body",
        target="tok",
        extra_payload={"aps": {"badge": 5}, "custom": {"key": "val"}},
    )
    payload = adapter._build_payload(message)
    assert payload["aps"]["badge"] == 5
    assert payload["key"] == "val"


# ---------------------------------------------------------------------------
# Tests — _build_send_kwargs
# ---------------------------------------------------------------------------


def test_build_send_kwargs_base() -> None:
    adapter = APNSPushAdapter(APNSPushSettings(topic="com.example.app"))
    kwargs = adapter._build_send_kwargs(NotificationMessage(text="hi", target="tok"))
    assert kwargs["topic"] == "com.example.app"


def test_build_send_kwargs_extra_fields() -> None:
    adapter = APNSPushAdapter(APNSPushSettings(topic="com.example.app"))
    message = NotificationMessage(
        text="hi",
        target="tok",
        extra_payload={"priority": 10, "collapse_id": "grp"},
    )
    kwargs = adapter._build_send_kwargs(message)
    assert kwargs["priority"] == 10
    assert kwargs["collapse_id"] == "grp"


# ---------------------------------------------------------------------------
# Tests — _load_auth_key
# ---------------------------------------------------------------------------


def test_load_auth_key_from_secret() -> None:
    from pydantic import SecretStr

    settings = APNSPushSettings(topic="t", auth_key=SecretStr("my-key"))
    adapter = APNSPushAdapter(settings)
    assert adapter._load_auth_key() == "my-key"


def test_load_auth_key_from_path(tmp_path: object) -> None:
    import pathlib

    key_file = pathlib.Path(str(tmp_path)) / "key.p8"  # type: ignore[arg-type]
    key_file.write_text("FILE-KEY")
    settings = APNSPushSettings(topic="t", auth_key_path=key_file)
    adapter = APNSPushAdapter(settings)
    assert adapter._load_auth_key() == "FILE-KEY"


def test_load_auth_key_none() -> None:
    adapter = APNSPushAdapter(APNSPushSettings(topic="t"))
    assert adapter._load_auth_key() is None


# ---------------------------------------------------------------------------
# Tests — _resolve_status_code / _resolve_headers
# ---------------------------------------------------------------------------


def test_resolve_status_code_from_status() -> None:
    from types import SimpleNamespace

    adapter = APNSPushAdapter(APNSPushSettings(topic="t"))
    resp = SimpleNamespace(status=201)
    assert adapter._resolve_status_code(resp) == 201


def test_resolve_status_code_default() -> None:
    adapter = APNSPushAdapter(APNSPushSettings(topic="t"))
    assert adapter._resolve_status_code(object()) == 200


def test_resolve_headers_from_attr() -> None:
    from types import SimpleNamespace

    adapter = APNSPushAdapter(APNSPushSettings(topic="t"))
    resp = SimpleNamespace(headers={"apns-id": "x"})
    assert adapter._resolve_headers(resp) == {"apns-id": "x"}


def test_resolve_headers_no_attr() -> None:
    adapter = APNSPushAdapter(APNSPushSettings(topic="t"))
    assert adapter._resolve_headers(object()) == {}


# ---------------------------------------------------------------------------
# Tests — _filter_kwargs
# ---------------------------------------------------------------------------


def test_filter_kwargs_known_params() -> None:
    adapter = APNSPushAdapter(APNSPushSettings(topic="t"))

    def target(a: int, b: int) -> None:
        pass

    result = adapter._filter_kwargs(target, {"a": 1, "b": 2, "c": 3})
    assert "a" in result and "b" in result and "c" not in result


def test_filter_kwargs_type_error() -> None:
    adapter = APNSPushAdapter(APNSPushSettings(topic="t"))
    result = adapter._filter_kwargs(42, {"a": 1})  # type: ignore[arg-type]
    assert result == {"a": 1}


# ---------------------------------------------------------------------------
# Tests — _ensure_client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_client_creates_via_factory() -> None:
    client = _FakeAPNSClient()
    adapter = APNSPushAdapter(APNSPushSettings(topic="t"))
    adapter._client_factory = lambda: client
    result = await adapter._ensure_client()
    assert result is client


# ---------------------------------------------------------------------------
# Tests — send_notification with default token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_notification_uses_default_token() -> None:
    client = _FakeAPNSClient()
    settings = APNSPushSettings(topic="t", default_device_token="default-tok")
    adapter = APNSPushAdapter(settings, client=client)
    await adapter.init()
    msg = NotificationMessage(text="Hi")  # no target
    result = await adapter.send_notification(msg)
    assert result.message_id == "apns-123"
    assert client.calls[0]["token"] == "default-tok"


# ---------------------------------------------------------------------------
# Tests — coverage gaps
# ---------------------------------------------------------------------------


def test_apns_default_client_factory_via_sys_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_default_client_factory imports aioapns from sys.modules (lines 127-145)."""
    import sys
    import types

    created_kwargs: list[dict] = []

    class FakeAPNsClient:
        def __init__(self, **kwargs: object) -> None:
            created_kwargs.append(dict(kwargs))

    fake_aioapns = types.ModuleType("aioapns")
    fake_aioapns.APNs = FakeAPNsClient  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "aioapns", fake_aioapns)

    settings = APNSPushSettings(topic="com.example.app")
    adapter = APNSPushAdapter(settings)
    result = adapter._default_client_factory()
    assert isinstance(result, FakeAPNsClient)


def test_apns_default_client_factory_client_cls_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_default_client_factory raises LifecycleError when no APNs class found (line 141)."""
    import sys
    import types
    from oneiric.core.lifecycle import LifecycleError

    fake_aioapns = types.ModuleType("aioapns")  # no APNs, APNS, APNSClient attr
    monkeypatch.setitem(sys.modules, "aioapns", fake_aioapns)

    adapter = APNSPushAdapter(APNSPushSettings(topic="t"))
    with pytest.raises(LifecycleError, match="aioapns-client-missing"):
        adapter._default_client_factory()


def test_apns_client_kwargs_with_all_options(tmp_path: object) -> None:
    """_client_kwargs builds dict with all auth options (lines 150-168)."""
    import pathlib
    from pydantic import SecretStr

    cert_file = pathlib.Path(str(tmp_path)) / "cert.pem"  # type: ignore[arg-type]
    cert_file.write_text("cert")
    key_file = pathlib.Path(str(tmp_path)) / "key.pem"
    key_file.write_text("key")

    settings = APNSPushSettings(
        topic="com.example.app",
        key_id="KEY123",
        team_id="TEAM456",
        cert_file=cert_file,
        key_file=key_file,
        key_password=SecretStr("pass"),
        client_kwargs={"extra_option": "val"},
    )
    adapter = APNSPushAdapter(settings)
    kwargs = adapter._client_kwargs()
    assert kwargs["topic"] == "com.example.app"
    assert kwargs["key_id"] == "KEY123"
    assert kwargs["team_id"] == "TEAM456"
    assert "cert_file" in kwargs
    assert "key_file" in kwargs
    assert kwargs["key_password"] == "pass"
    assert kwargs["extra_option"] == "val"


@pytest.mark.asyncio
async def test_maybe_disconnect_none_client() -> None:
    """_maybe_disconnect returns early when client is None (line 190)."""
    adapter = APNSPushAdapter(APNSPushSettings(topic="com.example.app"))
    # client is None by default
    await adapter._maybe_disconnect()  # should not raise


@pytest.mark.asyncio
async def test_try_send_notification_sync_return() -> None:
    """_try_send_notification returns sync result when not awaitable (line 212)."""

    class SyncNotifClient:
        def send_notification(self, token: str, payload: object, **_kw: object) -> str:
            return "sync-result"

    adapter = APNSPushAdapter(APNSPushSettings(topic="t"))
    result = await adapter._try_send_notification(SyncNotifClient(), "tok", {}, {})
    assert result == "sync-result"


@pytest.mark.asyncio
async def test_try_send_sync_return() -> None:
    """_try_send returns sync result when not awaitable (line 229)."""

    class SyncSendClient:
        def send(self, token: str, payload: object, **_kw: object) -> str:
            return "sync-sent"

    adapter = APNSPushAdapter(APNSPushSettings(topic="t"))
    result = await adapter._try_send(SyncSendClient(), "tok", {}, {})
    assert result == "sync-sent"


@pytest.mark.asyncio
async def test_try_notification_request_sync_return() -> None:
    """_try_notification_request returns sync result (line 250)."""
    from types import SimpleNamespace

    class FakeRequest:
        def __init__(self, **_kw: object) -> None:
            pass

    class SyncNotifClient:
        def send_notification(self, req: object) -> str:
            return "sync-notif"

    adapter = APNSPushAdapter(APNSPushSettings(topic="t"))
    adapter._aioapns = SimpleNamespace(NotificationRequest=FakeRequest)
    result = await adapter._try_notification_request(SyncNotifClient(), "tok", {}, {})
    assert result == "sync-notif"


@pytest.mark.asyncio
async def test_dispatch_returns_from_try_send() -> None:
    """_dispatch returns result from _try_send when _try_send_notification returns None (line 265)."""

    class NoSendNotifClient:
        async def send(self, token: str, payload: object, **_kw: object) -> str:
            return "send-result"

    adapter = APNSPushAdapter(APNSPushSettings(topic="t"))
    adapter._aioapns = None
    result = await adapter._dispatch(NoSendNotifClient(), "tok", {}, {})
    assert result == "send-result"


@pytest.mark.asyncio
async def test_dispatch_returns_from_notification_request() -> None:
    """_dispatch returns result from _try_notification_request (line 271)."""
    from types import SimpleNamespace

    class FakeRequest:
        def __init__(self, **_kw: object) -> None:
            pass

    class NotifReqClient:
        async def send_notification(self, req: object) -> str:
            return "notif-req-result"

    adapter = APNSPushAdapter(APNSPushSettings(topic="t"))
    adapter._aioapns = SimpleNamespace(NotificationRequest=FakeRequest)
    result = await adapter._dispatch(NotifReqClient(), "tok", {}, {})
    assert result == "notif-req-result"
