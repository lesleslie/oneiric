"""Firebase Cloud Messaging (FCM) adapter."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource

from .common import MessagingSendResult, NotificationMessage


class FCMPushSettings(BaseModel):
    """Settings for the Firebase Cloud Messaging adapter."""

    project_id: str | None = Field(default=None, description="Firebase project ID.")
    credentials_file: Path | None = Field(
        default=None, description="Path to a Firebase service account JSON file."
    )
    app_name: str = Field(
        default="oneiric-fcm",
        description="Firebase app name to register/use.",
    )
    default_device_token: str | None = Field(
        default=None, description="Fallback device token when message.target is empty."
    )


class FCMPushAdapter:
    """Adapter that sends push notifications via Firebase Cloud Messaging."""

    metadata = AdapterMetadata(
        category="messaging",
        provider="fcm",
        factory="oneiric.adapters.messaging.fcm:FCMPushAdapter",
        capabilities=["notifications", "push"],
        stack_level=20,
        priority=380,
        source=CandidateSource.LOCAL_PKG,
        owner="Messaging",
        requires_secrets=True,
        settings_model=FCMPushSettings,
    )

    def __init__(
        self,
        settings: FCMPushSettings,
        *,
        app: Any | None = None,
        app_factory: Callable[[], Any] | None = None,
        sender: Callable[..., Any] | None = None,
    ) -> None:
        self._settings = settings
        self._app = app
        self._app_factory = app_factory
        self._sender = sender
        self._firebase_admin: Any | None = None
        self._owns_app = app is None
        self._logger = get_logger("adapter.messaging.fcm").bind(
            domain="adapter",
            key="messaging",
            provider="fcm",
        )

    async def init(self) -> None:
        if self._app is None:
            factory = self._app_factory or self._default_app_factory
            self._app = factory()
        self._logger.info("fcm-adapter-init")

    async def cleanup(self) -> None:
        if self._app and self._owns_app and self._firebase_admin is not None:
            delete_app = getattr(self._firebase_admin, "delete_app", None)
            if callable(delete_app):
                delete_app(self._app)
        self._app = None
        self._logger.info("fcm-adapter-cleanup")

    async def health(self) -> bool:
        return self._app is not None

    async def send_notification(
        self, message: NotificationMessage
    ) -> MessagingSendResult:
        app = self._ensure_app()
        token = message.target or self._settings.default_device_token
        if not token:
            raise LifecycleError("fcm-device-token-missing")
        sender = self._sender or self._default_sender
        payload = self._build_message_payload(message, token)
        response = await asyncio.to_thread(sender, payload, app)
        message_id = getattr(response, "message_id", None) or str(response)
        return MessagingSendResult(
            message_id=str(message_id),
            status_code=200,
            response_headers={},
        )

    def _default_app_factory(self) -> Any:
        try:
            import firebase_admin  # type: ignore
            from firebase_admin import credentials  # type: ignore
        except ModuleNotFoundError as exc:  # pragma: no cover - optional dep
            raise LifecycleError(
                "firebase-admin-not-installed: install 'oneiric[messaging-fcm]' to use FCMPushAdapter"
            ) from exc
        self._firebase_admin = firebase_admin
        app_name = self._settings.app_name
        try:
            return firebase_admin.get_app(app_name)
        except ValueError:
            pass
        if self._settings.credentials_file:
            cred = credentials.Certificate(str(self._settings.credentials_file))
        else:
            cred = credentials.ApplicationDefault()
        options: dict[str, Any] = {}
        if self._settings.project_id:
            options["projectId"] = self._settings.project_id
        return firebase_admin.initialize_app(cred, options=options, name=app_name)

    def _default_sender(self, payload: Any, app: Any) -> Any:
        if not self._firebase_admin:
            raise LifecycleError("fcm-firebase-admin-not-initialized")
        messaging = getattr(self._firebase_admin, "messaging", None)
        if messaging is None:
            raise LifecycleError("fcm-messaging-module-missing")
        send = getattr(messaging, "send", None)
        if not callable(send):
            raise LifecycleError("fcm-send-missing")
        return send(payload, app=app)

    def _build_message_payload(self, message: NotificationMessage, token: str) -> Any:
        if not self._firebase_admin:
            raise LifecycleError("fcm-firebase-admin-not-initialized")
        messaging = self._firebase_admin.messaging
        notification_kwargs = {
            "title": message.title,
            "body": message.text,
        }
        if isinstance(message.extra_payload.get("notification"), dict):
            notification_kwargs.update(message.extra_payload["notification"])
        notification = messaging.Notification(**notification_kwargs)
        data = message.extra_payload.get("data")
        if data is not None and not isinstance(data, dict):
            raise LifecycleError("fcm-data-must-be-dict")
        message_kwargs = {
            "token": token,
            "notification": notification,
            "data": data,
        }
        for key in ("android", "apns", "webpush"):
            if key in message.extra_payload:
                message_kwargs[key] = message.extra_payload[key]
        return messaging.Message(
            **{k: v for k, v in message_kwargs.items() if v is not None}
        )

    def _ensure_app(self) -> Any:
        if self._app is None:
            raise LifecycleError("fcm-app-not-initialized")
        return self._app
