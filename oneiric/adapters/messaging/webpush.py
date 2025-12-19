"""Web push notification adapter."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, SecretStr

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource

from .common import MessagingSendResult, NotificationMessage


class WebPushSettings(BaseModel):
    """Settings for the web push adapter."""

    vapid_private_key: SecretStr | None = Field(
        default=None, description="VAPID private key contents."
    )
    vapid_private_key_path: Path | None = Field(
        default=None, description="Path to the VAPID private key file."
    )
    vapid_claims_subject: str = Field(
        default="mailto:notifications@oneiric.local",
        description="VAPID claims subject (mailto: or https://).",
    )
    default_subscription_info: dict[str, Any] | None = Field(
        default=None, description="Optional default subscription payload."
    )
    ttl: int = Field(default=60, ge=0)
    timeout: float = Field(default=10.0, ge=0.5)


class WebPushAdapter:
    """Adapter that sends browser push notifications via Web Push."""

    metadata = AdapterMetadata(
        category="messaging",
        provider="webpush",
        factory="oneiric.adapters.messaging.webpush:WebPushAdapter",
        capabilities=["notifications", "push"],
        stack_level=20,
        priority=360,
        source=CandidateSource.LOCAL_PKG,
        owner="Messaging",
        requires_secrets=True,
        settings_model=WebPushSettings,
    )

    def __init__(
        self,
        settings: WebPushSettings,
        *,
        sender: Callable[..., Any] | None = None,
    ) -> None:
        self._settings = settings
        self._sender = sender
        self._logger = get_logger("adapter.messaging.webpush").bind(
            domain="adapter",
            key="messaging",
            provider="webpush",
        )

    async def init(self) -> None:
        self._logger.info("webpush-adapter-init")

    async def cleanup(self) -> None:
        self._logger.info("webpush-adapter-cleanup")

    async def health(self) -> bool:
        return self._resolve_private_key() is not None

    async def send_notification(
        self, message: NotificationMessage
    ) -> MessagingSendResult:
        subscription = self._resolve_subscription(message)
        payload = self._build_payload(message)
        headers = self._resolve_headers(message)
        vapid_private_key = self._resolve_private_key()
        if vapid_private_key is None:
            raise LifecycleError("webpush-vapid-private-key-missing")
        vapid_claims = self._resolve_vapid_claims(message)
        ttl = int(message.extra_payload.get("ttl", self._settings.ttl))
        content_encoding = message.extra_payload.get("content_encoding")
        response = await asyncio.to_thread(
            self._send,
            subscription_info=subscription,
            data=payload,
            vapid_private_key=vapid_private_key,
            vapid_claims=vapid_claims,
            ttl=ttl,
            headers=headers,
            timeout=self._settings.timeout,
            content_encoding=content_encoding,
        )
        status_code = getattr(response, "status_code", 200)
        response_headers = {}
        if hasattr(response, "headers"):
            response_headers = dict(response.headers)
        message_id = response_headers.get("location") or response_headers.get(
            "Location"
        )
        if not message_id:
            message_id = "webpush-message"
        return MessagingSendResult(
            message_id=message_id,
            status_code=status_code,
            response_headers=response_headers,
        )

    def _send(self, **kwargs: Any) -> Any:
        sender = self._sender or self._load_sender()
        return sender(
            **{key: value for key, value in kwargs.items() if value is not None}
        )

    def _load_sender(self) -> Callable[..., Any]:
        try:
            from pywebpush import webpush  # type: ignore
        except ModuleNotFoundError as exc:  # pragma: no cover - optional dep
            raise LifecycleError(
                "pywebpush-not-installed: install 'oneiric[messaging-webpush]' to use WebPushAdapter"
            ) from exc
        return webpush

    def _resolve_subscription(self, message: NotificationMessage) -> dict[str, Any]:
        if isinstance(message.extra_payload.get("subscription_info"), dict):
            return message.extra_payload["subscription_info"]
        if message.target:
            try:
                parsed = json.loads(message.target)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                return parsed
        if self._settings.default_subscription_info:
            return self._settings.default_subscription_info
        raise LifecycleError("webpush-subscription-info-missing")

    def _build_payload(self, message: NotificationMessage) -> str:
        payload = {
            "title": message.title or "Notification",
            "body": message.text,
            "data": message.extra_payload.get("data", {}),
        }
        if isinstance(message.extra_payload.get("payload"), dict):
            payload.update(message.extra_payload["payload"])
        return json.dumps(payload)

    def _resolve_headers(self, message: NotificationMessage) -> dict[str, str] | None:
        headers = {}
        extra_headers = message.extra_payload.get("headers")
        if isinstance(extra_headers, dict):
            headers.update({str(k): str(v) for k, v in extra_headers.items()})
        return headers or None

    def _resolve_vapid_claims(self, message: NotificationMessage) -> dict[str, str]:
        claims = {"sub": self._settings.vapid_claims_subject}
        extra_claims = message.extra_payload.get("vapid_claims")
        if isinstance(extra_claims, dict):
            claims.update({str(k): str(v) for k, v in extra_claims.items()})
        return claims

    def _resolve_private_key(self) -> str | None:
        if self._settings.vapid_private_key:
            return self._settings.vapid_private_key.get_secret_value()
        if self._settings.vapid_private_key_path:
            return Path(self._settings.vapid_private_key_path).read_text().strip()
        return None
