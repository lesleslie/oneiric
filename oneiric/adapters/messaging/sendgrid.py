"""SendGrid email adapter with httpx client."""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import AnyHttpUrl, EmailStr, Field, SecretStr

from oneiric.adapters.httpx_base import HTTPXClientMixin
from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource
from oneiric.core.settings_mixins import TimeoutSettings

from .common import EmailRecipient, MessagingSendResult, OutboundEmailMessage


class SendGridSettings(TimeoutSettings):
    """Configuration for the SendGrid adapter."""

    api_key: SecretStr
    from_email: EmailStr
    from_name: str | None = None
    base_url: AnyHttpUrl = Field(default="https://api.sendgrid.com/v3")
    sandbox_mode: bool = Field(
        default=False,
        description="Enable SendGrid sandbox mode (no-op sends) by default.",
    )
    default_headers: dict[str, str] = Field(
        default_factory=dict,
        description="Additional headers merged into every message payload.",
    )
    default_custom_args: dict[str, str] = Field(
        default_factory=dict,
        description="Base custom args merged into each send request.",
    )
    categories: list[str] = Field(
        default_factory=list,
        description="Default SendGrid categories applied to every message.",
    )


class SendGridAdapter(HTTPXClientMixin):
    """SendGrid-backed messaging adapter using the REST API."""

    metadata = AdapterMetadata(
        category="messaging",
        provider="sendgrid",
        factory="oneiric.adapters.messaging.sendgrid:SendGridAdapter",
        capabilities=["email", "transactional", "templating"],
        stack_level=20,
        priority=300,
        source=CandidateSource.LOCAL_PKG,
        owner="Messaging",
        requires_secrets=True,
        settings_model=SendGridSettings,
    )

    def __init__(
        self,
        settings: SendGridSettings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(client=client)
        self._settings = settings
        self._logger = get_logger("adapter.messaging.sendgrid").bind(
            domain="adapter",
            key="messaging",
            provider="sendgrid",
        )

    async def init(self) -> None:
        headers = {
            "Authorization": f"Bearer {self._settings.api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }
        headers.update(self._settings.default_headers)

        if self._client is None:
            self._init_client(
                lambda: httpx.AsyncClient(
                    base_url=str(self._settings.base_url),
                    timeout=self._settings.timeout,
                    headers=headers,
                )
            )
        else:
            self._client.headers.update(headers)

        self._logger.info("sendgrid-adapter-init", sandbox=self._settings.sandbox_mode)

    async def cleanup(self) -> None:
        await self._cleanup_client()
        self._logger.info("sendgrid-adapter-cleanup")

    async def health(self) -> bool:
        client = self._ensure_client("sendgrid-client-not-initialized")
        try:
            response = await client.get("/scopes")
            return response.status_code < 500
        except httpx.HTTPError as exc:
            self._logger.warning("sendgrid-health-failed", error=str(exc))
            return False

    async def send_email(self, message: OutboundEmailMessage) -> MessagingSendResult:
        client = self._ensure_client("sendgrid-client-not-initialized")
        payload = self._build_payload(message)

        try:
            response = await client.post("/mail/send", json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            error_body = exc.response.text
            self._logger.error(
                "sendgrid-send-failed",
                status_code=exc.response.status_code,
                body=error_body,
            )
            raise LifecycleError(
                f"sendgrid-send-failed: {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            self._logger.error("sendgrid-http-error", error=str(exc))
            raise LifecycleError("sendgrid-http-error") from exc

        message_id = (
            response.headers.get("X-Message-Id")
            or response.headers.get("X-Message-ID")
            or ""
        )
        if not message_id:
            message_id = response.headers.get("Date", "sendgrid-message")

        return MessagingSendResult(
            message_id=message_id,
            status_code=response.status_code,
            response_headers=response.headers.copy(),
        )

    def _build_payload(self, message: OutboundEmailMessage) -> dict[str, Any]:
        personalization: dict[str, Any] = {
            "to": self._format_recipients(message.to),
            "subject": message.subject,
        }

        if message.cc:
            personalization["cc"] = self._format_recipients(message.cc)
        if message.bcc:
            personalization["bcc"] = self._format_recipients(message.bcc)
        if message.headers:
            personalization["headers"] = message.headers

        custom_args = self._settings.default_custom_args.copy()
        custom_args.update(message.custom_args)
        if custom_args:
            personalization["custom_args"] = custom_args

        payload: dict[str, Any] = {
            "personalizations": [personalization],
            "from": self._format_recipient(
                EmailRecipient(
                    email=self._settings.from_email, name=self._settings.from_name
                )
            ),
            "content": self._build_content(message),
        }

        categories = message.categories or self._settings.categories
        if categories:
            payload["categories"] = categories

        reply_to = message.reply_to
        if reply_to:
            payload["reply_to"] = self._format_recipient(reply_to)

        sandbox_enabled = (
            message.sandbox_override
            if message.sandbox_override is not None
            else self._settings.sandbox_mode
        )
        if sandbox_enabled:
            payload["mail_settings"] = {"sandbox_mode": {"enable": True}}

        return payload

    def _build_content(self, message: OutboundEmailMessage) -> list[dict[str, str]]:
        content: list[dict[str, str]] = []
        if message.text_body:
            content.append({"type": "text/plain", "value": message.text_body})
        if message.html_body:
            content.append({"type": "text/html", "value": message.html_body})
        return content

    def _format_recipients(
        self, recipients: list[EmailRecipient]
    ) -> list[dict[str, str]]:
        return [self._format_recipient(recipient) for recipient in recipients]

    @staticmethod
    def _format_recipient(recipient: EmailRecipient) -> dict[str, str]:
        entry = {"email": recipient.email}
        if recipient.name:
            entry["name"] = recipient.name
        return entry
