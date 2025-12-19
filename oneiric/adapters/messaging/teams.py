"""Microsoft Teams notification adapter."""

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


class TeamsSettings(TimeoutSettings):
    """Configuration for Teams incoming webhook notifications."""

    webhook_url: AnyHttpUrl
    default_theme_color: str = Field(default="0078D4")


class TeamsAdapter(HTTPXClientMixin):
    """Adapter that posts adaptive cards to Microsoft Teams webhooks."""

    metadata = AdapterMetadata(
        category="messaging",
        provider="teams",
        factory="oneiric.adapters.messaging.teams:TeamsAdapter",
        capabilities=["notifications", "chatops"],
        stack_level=25,
        priority=345,
        source=CandidateSource.LOCAL_PKG,
        owner="Messaging",
        requires_secrets=True,
        settings_model=TeamsSettings,
    )

    def __init__(
        self,
        settings: TeamsSettings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(client=client)
        self._settings = settings
        self._logger = get_logger("adapter.messaging.teams").bind(
            domain="adapter",
            key="messaging",
            provider="teams",
        )

    async def init(self) -> None:
        self._init_client(lambda: httpx.AsyncClient(timeout=self._settings.timeout))
        self._logger.info("teams-adapter-init")

    async def cleanup(self) -> None:
        await self._cleanup_client()
        self._logger.info("teams-adapter-cleanup")

    async def health(self) -> bool:
        # Teams webhooks do not expose a lightweight health endpoint; perform a HEAD to the webhook URL.
        client = self._ensure_client("teams-client-not-initialized")
        try:
            response = await client.head(str(self._settings.webhook_url))
            return response.status_code < 500
        except httpx.HTTPError as exc:  # pragma: no cover - network path
            self._logger.warning("teams-health-failed", error=str(exc))
            return False

    async def send_notification(
        self, message: NotificationMessage
    ) -> MessagingSendResult:
        client = self._ensure_client("teams-client-not-initialized")
        webhook_url = message.target or str(self._settings.webhook_url)
        payload = self._build_payload(message)

        try:
            response = await client.post(webhook_url, json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            self._logger.error(
                "teams-send-failed",
                status_code=exc.response.status_code,
                body=exc.response.text,
            )
            raise LifecycleError("teams-send-failed") from exc
        except httpx.HTTPError as exc:  # pragma: no cover - transport path
            self._logger.error("teams-http-error", error=str(exc))
            raise LifecycleError("teams-http-error") from exc

        return MessagingSendResult(
            message_id="teams-message",
            status_code=response.status_code,
            response_headers=dict(response.headers),
        )

    def _build_payload(self, message: NotificationMessage) -> dict[str, object]:
        sections: list[dict[str, object]] = []
        if message.title:
            sections.append({"activityTitle": message.title})
        if message.text:
            sections.append({"text": message.text})
        for attachment in message.attachments:
            sections.append(
                {"facts": [{"name": k, "value": v} for k, v in attachment.items()]}
            )

        card: dict[str, object] = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "themeColor": self._settings.default_theme_color,
            "summary": message.title or message.text[:60],
            "sections": sections or [{"text": message.text}],
        }
        if message.extra_payload:
            card.update(message.extra_payload)
        return card
