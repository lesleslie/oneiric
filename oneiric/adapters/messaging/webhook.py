"""Generic webhook notification adapter."""

from __future__ import annotations

import httpx
from pydantic import AnyHttpUrl, Field

from oneiric.adapters.httpx_base import HTTPXClientMixin
from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource
from oneiric.core.settings_mixins import TimeoutSettings

from .common import MessagingSendResult, NotificationMessage


class WebhookSettings(TimeoutSettings):
    """Settings for the generic webhook adapter."""

    url: AnyHttpUrl
    method: str = Field(default="POST")
    headers: dict[str, str] = Field(default_factory=dict)


class WebhookAdapter(HTTPXClientMixin):
    """Adapter that dispatches arbitrary JSON payloads to a configurable webhook."""

    metadata = AdapterMetadata(
        category="messaging",
        provider="webhook",
        factory="oneiric.adapters.messaging.webhook:WebhookAdapter",
        capabilities=["notifications"],
        stack_level=25,
        priority=350,
        source=CandidateSource.LOCAL_PKG,
        owner="Messaging",
        requires_secrets=False,
        settings_model=WebhookSettings,
    )

    def __init__(
        self,
        settings: WebhookSettings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(client=client)
        self._settings = settings
        self._logger = get_logger("adapter.messaging.webhook").bind(
            domain="adapter",
            key="messaging",
            provider="webhook",
        )

    async def init(self) -> None:
        self._init_client(lambda: httpx.AsyncClient(timeout=self._settings.timeout))
        self._logger.info("webhook-adapter-init")

    async def cleanup(self) -> None:
        await self._cleanup_client()
        self._logger.info("webhook-adapter-cleanup")

    async def health(self) -> bool:
        client = self._ensure_client("webhook-client-not-initialized")
        try:
            response = await client.head(str(self._settings.url))
            return response.status_code < 500
        except httpx.HTTPError as exc:  # pragma: no cover - network path
            self._logger.warning("webhook-health-failed", error=str(exc))
            return False

    async def send_notification(
        self, message: NotificationMessage
    ) -> MessagingSendResult:
        client = self._ensure_client("webhook-client-not-initialized")
        url = message.target or str(self._settings.url)
        method = (message.extra_payload.get("method") or self._settings.method).upper()
        headers = self._settings.headers.copy()
        extra_headers = message.extra_payload.get("headers")
        if isinstance(extra_headers, dict):
            headers.update(extra_headers)

        body = message.extra_payload.get("body") or {
            "text": message.text,
            "title": message.title,
        }

        request_func = getattr(client, method.lower(), None)
        if not request_func:
            raise LifecycleError(f"webhook-method-unsupported: {method}")

        try:
            response = await request_func(url, json=body, headers=headers)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            self._logger.error(
                "webhook-send-failed",
                status_code=exc.response.status_code,
                body=exc.response.text,
            )
            raise LifecycleError("webhook-send-failed") from exc
        except httpx.HTTPError as exc:  # pragma: no cover - transport path
            self._logger.error("webhook-http-error", error=str(exc))
            raise LifecycleError("webhook-http-error") from exc

        return MessagingSendResult(
            message_id="webhook-message",
            status_code=response.status_code,
            response_headers=response.headers.copy(),
        )
