"""Apple Push Notification Service (APNS) adapter."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, SecretStr

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource

from .common import MessagingSendResult, NotificationMessage


class APNSPushSettings(BaseModel):
    """Settings for the APNS adapter."""

    topic: str = Field(description="APNS topic/bundle identifier.")
    use_sandbox: bool = Field(default=False, description="Use the sandbox gateway.")
    key_id: str | None = Field(default=None, description="APNS auth key ID.")
    team_id: str | None = Field(default=None, description="Apple developer team ID.")
    auth_key: SecretStr | None = Field(
        default=None, description="APNS auth key contents (p8)."
    )
    auth_key_path: Path | None = Field(
        default=None, description="Path to APNS auth key file."
    )
    cert_file: Path | None = Field(
        default=None, description="APNS certificate file (PEM)."
    )
    key_file: Path | None = Field(
        default=None, description="APNS private key file (PEM)."
    )
    key_password: SecretStr | None = Field(
        default=None, description="Password for the APNS private key (if encrypted)."
    )
    default_device_token: str | None = Field(
        default=None, description="Fallback device token when message.target is empty."
    )
    client_kwargs: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional keyword args passed to the aioapns client.",
    )


class APNSPushAdapter:
    """Adapter that sends mobile push notifications through APNS."""

    metadata = AdapterMetadata(
        category="messaging",
        provider="apns",
        factory="oneiric.adapters.messaging.apns:APNSPushAdapter",
        capabilities=["notifications", "push"],
        stack_level=20,
        priority=370,
        source=CandidateSource.LOCAL_PKG,
        owner="Messaging",
        requires_secrets=True,
        settings_model=APNSPushSettings,
    )

    def __init__(
        self,
        settings: APNSPushSettings,
        *,
        client: Any | None = None,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._client_factory = client_factory
        self._aioapns: Any | None = None
        self._owns_client = client is None
        self._logger = get_logger("adapter.messaging.apns").bind(
            domain="adapter",
            key="messaging",
            provider="apns",
        )

    async def init(self) -> None:
        if self._client is not None:
            await self._maybe_connect()
            self._logger.info("apns-adapter-init")
            return

        if self._client_factory is not None:
            self._client = self._client_factory()
            await self._maybe_connect()
            self._logger.info("apns-adapter-init")
            return

        # Defer default client initialization until first send.
        self._logger.info("apns-adapter-init", deferred_client=True)

    async def cleanup(self) -> None:
        if self._client and self._owns_client:
            await self._maybe_disconnect()
        self._client = None
        self._logger.info("apns-adapter-cleanup")

    async def health(self) -> bool:
        return self._client is not None

    async def send_notification(
        self, message: NotificationMessage
    ) -> MessagingSendResult:
        token = message.target or self._settings.default_device_token
        if not token:
            raise LifecycleError("apns-device-token-missing")
        client = await self._ensure_client()
        payload = self._build_payload(message)
        send_kwargs = self._build_send_kwargs(message)
        response = await self._dispatch(client, token, payload, send_kwargs)
        status_code = self._resolve_status_code(response)
        response_headers = self._resolve_headers(response)
        message_id = (
            response_headers.get("apns-id")
            or getattr(response, "apns_id", None)
            or getattr(response, "id", None)
            or "apns-message"
        )
        return MessagingSendResult(
            message_id=str(message_id),
            status_code=status_code,
            response_headers=response_headers,
        )

    def _default_client_factory(self) -> Any:
        try:
            import aioapns  # type: ignore
        except ModuleNotFoundError as exc:  # pragma: no cover - optional dep
            raise LifecycleError(
                "aioapns-not-installed: install 'oneiric[messaging-apns]' to use APNSPushAdapter"
            ) from exc
        self._aioapns = aioapns
        client_cls = (
            getattr(aioapns, "APNs", None)
            or getattr(aioapns, "APNS", None)
            or getattr(aioapns, "APNSClient", None)
            or getattr(getattr(aioapns, "client", None), "APNsClient", None)
        )
        if client_cls is None:
            raise LifecycleError("aioapns-client-missing")
        kwargs = self._client_kwargs()
        filtered = self._filter_kwargs(client_cls, kwargs)
        try:
            return client_cls(**filtered)
        except TypeError as exc:  # pragma: no cover - optional dep
            raise LifecycleError("aioapns-client-init-failed") from exc

    def _client_kwargs(self) -> dict[str, Any]:
        auth_key = self._load_auth_key()
        kwargs = {
            "topic": self._settings.topic,
            "use_sandbox": self._settings.use_sandbox,
            "key_id": self._settings.key_id,
            "team_id": self._settings.team_id,
            "auth_key": auth_key,
            "cert_file": str(self._settings.cert_file)
            if self._settings.cert_file
            else None,
            "key_file": str(self._settings.key_file)
            if self._settings.key_file
            else None,
            "key_password": self._settings.key_password.get_secret_value()
            if self._settings.key_password
            else None,
        }
        kwargs.update(self._settings.client_kwargs)
        return {key: value for key, value in kwargs.items() if value is not None}

    def _load_auth_key(self) -> str | None:
        if self._settings.auth_key:
            return self._settings.auth_key.get_secret_value()
        if self._settings.auth_key_path:
            return Path(self._settings.auth_key_path).read_text().strip()
        return None

    async def _maybe_connect(self) -> None:
        client = self._client
        if client is None:
            return
        connect = getattr(client, "connect", None)
        if callable(connect):
            result = connect()
            if inspect.isawaitable(result):
                await result

    async def _maybe_disconnect(self) -> None:
        client = self._client
        if client is None:
            return
        for name in ("close", "disconnect", "shutdown"):
            closer = getattr(client, name, None)
            if callable(closer):
                result = closer()
                if inspect.isawaitable(result):
                    await result
                return

    async def _dispatch(
        self,
        client: Any,
        token: str,
        payload: dict[str, Any],
        send_kwargs: dict[str, Any],
    ) -> Any:
        if hasattr(client, "send_notification"):
            try:
                result = client.send_notification(token, payload, **send_kwargs)
                if inspect.isawaitable(result):
                    return await result
                return result
            except TypeError:
                pass
        if hasattr(client, "send"):
            try:
                result = client.send(token, payload, **send_kwargs)
                if inspect.isawaitable(result):
                    return await result
                return result
            except TypeError:
                pass
        request_cls = getattr(self._aioapns, "NotificationRequest", None)
        if request_cls is not None:
            request = request_cls(device_token=token, message=payload, **send_kwargs)
            send_notification = getattr(client, "send_notification", None)
            if callable(send_notification):
                result = send_notification(request)
                if inspect.isawaitable(result):
                    return await result
                return result
        raise LifecycleError("apns-send-not-supported")

    def _build_payload(self, message: NotificationMessage) -> dict[str, Any]:
        if message.title:
            alert: str | dict[str, Any] = {"title": message.title, "body": message.text}
        else:
            alert = message.text
        aps = {"alert": alert}
        extra_aps = message.extra_payload.get("aps")
        if isinstance(extra_aps, dict):
            aps.update(extra_aps)
        payload: dict[str, Any] = {"aps": aps}
        custom_payload = message.extra_payload.get("custom")
        if isinstance(custom_payload, dict):
            payload.update(custom_payload)
        return payload

    def _build_send_kwargs(self, message: NotificationMessage) -> dict[str, Any]:
        send_kwargs = {
            "topic": self._settings.topic,
        }
        for key in ("priority", "collapse_id", "expiration", "push_type"):
            if key in message.extra_payload:
                send_kwargs[key] = message.extra_payload[key]
        return {key: value for key, value in send_kwargs.items() if value is not None}

    async def _ensure_client(self) -> Any:
        if self._client is None:
            factory = self._client_factory or self._default_client_factory
            self._client = factory()
            self._owns_client = True
            await self._maybe_connect()
        return self._client

    def _resolve_status_code(self, response: Any) -> int:
        for attr in ("status_code", "status", "status_code"):
            value = getattr(response, attr, None)
            if isinstance(value, int):
                return value
        return 200

    def _resolve_headers(self, response: Any) -> dict[str, str]:
        headers = getattr(response, "headers", None)
        if headers:
            return dict(headers)
        return {}

    def _filter_kwargs(self, target: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
        try:
            params = inspect.signature(target).parameters
        except (TypeError, ValueError):
            return kwargs
        return {key: value for key, value in kwargs.items() if key in params}
