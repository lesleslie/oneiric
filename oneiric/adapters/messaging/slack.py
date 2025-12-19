"""Slack notification adapter."""

from __future__ import annotations

import httpx
from pydantic import AnyHttpUrl, Field, SecretStr

from oneiric.adapters.httpx_base import HTTPXClientMixin
from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource
from oneiric.core.settings_mixins import TimeoutSettings

from .common import MessagingSendResult, NotificationMessage


class SlackSettings(TimeoutSettings):
    """Configuration for Slack chat.postMessage calls."""

    token: SecretStr
    default_channel: str | None = Field(
        default=None,
        description="Channel fallback when NotificationMessage.target is unset.",
    )
    base_url: AnyHttpUrl = Field(default="https://slack.com/api")
    default_username: str | None = None
    default_icon_emoji: str | None = None


class SlackAdapter(HTTPXClientMixin):
    """Slack adapter that posts messages via chat.postMessage."""

    metadata = AdapterMetadata(
        category="messaging",
        provider="slack",
        factory="oneiric.adapters.messaging.slack:SlackAdapter",
        capabilities=["notifications", "chatops"],
        stack_level=25,
        priority=340,
        source=CandidateSource.LOCAL_PKG,
        owner="Messaging",
        requires_secrets=True,
        settings_model=SlackSettings,
    )

    def __init__(
        self,
        settings: SlackSettings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(client=client)
        self._settings = settings
        self._logger = get_logger("adapter.messaging.slack").bind(
            domain="adapter",
            key="messaging",
            provider="slack",
        )

    async def init(self) -> None:
        if self._client is None:
            headers = {
                "Authorization": f"Bearer {self._settings.token.get_secret_value()}",
                "Content-Type": "application/json; charset=utf-8",
            }
            self._init_client(
                lambda: httpx.AsyncClient(
                    base_url=str(self._settings.base_url),
                    timeout=self._settings.timeout,
                    headers=headers,
                )
            )
        else:
            self._client.headers.update(
                {
                    "Authorization": f"Bearer {self._settings.token.get_secret_value()}",
                }
            )
        self._logger.info("slack-adapter-init")

    async def cleanup(self) -> None:
        await self._cleanup_client()
        self._logger.info("slack-adapter-cleanup")

    async def health(self) -> bool:
        client = self._ensure_client("slack-client-not-initialized")
        try:
            response = await client.post("/auth.test")
            return response.status_code < 500
        except httpx.HTTPError as exc:  # pragma: no cover - network path
            self._logger.warning("slack-health-failed", error=str(exc))
            return False

    async def send_notification(
        self, message: NotificationMessage
    ) -> MessagingSendResult:
        client = self._ensure_client("slack-client-not-initialized")
        channel = message.target or self._settings.default_channel
        if not channel:
            raise LifecycleError("slack-channel-missing")

        # Build and send payload
        payload = self._build_slack_payload(message, channel)
        response = await self._send_slack_request(client, payload)

        # Validate and extract response
        self._validate_slack_response(response)
        ts = response.json().get("ts", "slack-message")

        return MessagingSendResult(
            message_id=str(ts),
            status_code=response.status_code,
            response_headers=dict(response.headers),
        )

    def _build_slack_payload(
        self, message: NotificationMessage, channel: str
    ) -> dict[str, object]:
        """Build Slack API payload from message."""
        payload: dict[str, object] = {
            "channel": channel,
            "text": message.text,
        }

        # Add optional content
        if message.blocks:
            payload["blocks"] = message.blocks
        if message.attachments:
            payload["attachments"] = message.attachments
        if message.title:
            payload.setdefault("title", message.title)

        # Add default settings
        if self._settings.default_username:
            payload.setdefault("username", self._settings.default_username)
        if self._settings.default_icon_emoji:
            payload.setdefault("icon_emoji", self._settings.default_icon_emoji)

        # Merge extra payload
        if message.extra_payload:
            payload.update(message.extra_payload)

        return payload

    async def _send_slack_request(
        self, client: httpx.AsyncClient, payload: dict[str, object]
    ) -> httpx.Response:
        """Send request to Slack API with error handling."""
        try:
            response = await client.post("/chat.postMessage", json=payload)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            self._logger.error(
                "slack-send-failed",
                status_code=exc.response.status_code,
                body=exc.response.text,
            )
            raise LifecycleError("slack-send-failed") from exc
        except httpx.HTTPError as exc:  # pragma: no cover - transport path
            self._logger.error("slack-http-error", error=str(exc))
            raise LifecycleError("slack-http-error") from exc

    def _validate_slack_response(self, response: httpx.Response) -> None:
        """Validate Slack API response for errors."""
        payload_json = response.json()
        if not payload_json.get("ok", False):
            error_msg = payload_json.get("error", "unknown-error")
            self._logger.error("slack-send-error", error=error_msg)
            raise LifecycleError(f"slack-send-error: {error_msg}")
