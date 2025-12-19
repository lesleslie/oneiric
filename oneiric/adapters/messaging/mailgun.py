"""Mailgun outbound email adapter."""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlencode

import httpx
from pydantic import AnyHttpUrl, EmailStr, Field, SecretStr

from oneiric.adapters.httpx_base import HTTPXClientMixin
from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource
from oneiric.core.settings_mixins import TimeoutSettings

from .common import EmailRecipient, MessagingSendResult, OutboundEmailMessage


class MailgunSettings(TimeoutSettings):
    """Configuration for the Mailgun adapter."""

    api_key: SecretStr
    domain: str
    from_email: EmailStr
    from_name: str | None = None
    region: str = Field(
        default="us",
        pattern=r"^(us|eu)$",
        description="Controls whether api.mailgun.net or api.eu.mailgun.net is used.",
    )
    base_url: AnyHttpUrl | None = Field(
        default=None,
        description="Override the inferred Mailgun API endpoint.",
    )
    test_mode: bool = Field(
        default=False,
        description="Enable Mailgun o:testmode flag globally (overridden per message via sandbox_override).",
    )
    tags: list[str] = Field(default_factory=list)
    click_tracking: str | None = Field(
        default=None,
        description="Options accepted by Mailgun's o:tracking parameter (e.g. yes/no/htmlonly).",
    )
    require_tls: bool = Field(default=True)
    skip_verification: bool = Field(default=False)
    default_headers: dict[str, str] = Field(default_factory=dict)


class MailgunAdapter(HTTPXClientMixin):
    """Mailgun-backed email adapter using the REST API."""

    metadata = AdapterMetadata(
        category="messaging",
        provider="mailgun",
        factory="oneiric.adapters.messaging.mailgun:MailgunAdapter",
        capabilities=["email", "transactional", "templating"],
        stack_level=20,
        priority=320,
        source=CandidateSource.LOCAL_PKG,
        owner="Messaging",
        requires_secrets=True,
        settings_model=MailgunSettings,
    )

    def __init__(
        self,
        settings: MailgunSettings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(client=client)
        self._settings = settings
        self._logger = get_logger("adapter.messaging.mailgun").bind(
            domain="adapter",
            key="messaging",
            provider="mailgun",
            domain_name=settings.domain,
        )

    async def init(self) -> None:
        base_url = str(self._settings.base_url or self._default_base_url())
        auth = httpx.BasicAuth("api", self._settings.api_key.get_secret_value())
        if self._client is None:
            self._init_client(
                lambda: httpx.AsyncClient(
                    base_url=base_url,
                    timeout=self._settings.timeout,
                    auth=auth,
                    headers=self._settings.default_headers,
                )
            )
        else:
            self._client.headers.update(self._settings.default_headers)
        self._logger.info("mailgun-adapter-init", domain=self._settings.domain)

    async def cleanup(self) -> None:
        await self._cleanup_client()
        self._logger.info("mailgun-adapter-cleanup")

    async def health(self) -> bool:
        client = self._ensure_client("mailgun-client-not-initialized")
        try:
            response = await client.get(f"/v3/domains/{self._settings.domain}")
            return response.status_code < 500
        except httpx.HTTPError as exc:  # pragma: no cover - transport errors
            self._logger.warning("mailgun-health-failed", error=str(exc))
            return False

    async def send_email(self, message: OutboundEmailMessage) -> MessagingSendResult:
        client = self._ensure_client("mailgun-client-not-initialized")
        payload = self._build_payload(message)
        encoded = urlencode(payload)
        try:
            response = await client.post(
                f"/v3/{self._settings.domain}/messages",
                content=encoded,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            self._logger.error(
                "mailgun-send-failed",
                status_code=exc.response.status_code,
                body=exc.response.text,
            )
            raise LifecycleError("mailgun-send-failed") from exc
        except httpx.HTTPError as exc:  # pragma: no cover - network errors
            self._logger.error("mailgun-http-error", error=str(exc))
            raise LifecycleError("mailgun-http-error") from exc

        return MessagingSendResult(
            message_id=(message_id := response.json().get("id", "mailgun-message")),
            status_code=response.status_code,
            response_headers=dict(response.headers),
        )

    def _build_payload(self, message: OutboundEmailMessage) -> list[tuple[str, str]]:
        payload: list[tuple[str, str]] = []

        # Add sender and recipients
        self._add_sender_and_recipients(payload, message)

        # Add subject and body
        self._add_subject_and_body(payload, message)

        # Add optional headers
        self._add_reply_to(payload, message)

        # Add Mailgun options
        self._add_mailgun_options(payload, message)

        # Add custom variables and headers
        self._add_custom_fields(payload, message)

        return payload

    def _add_sender_and_recipients(
        self, payload: list[tuple[str, str]], message: OutboundEmailMessage
    ) -> None:
        """Add sender and recipient fields to payload."""
        payload.append(("from", self._format_sender()))
        payload.extend(self._format_recipients("to", message.to))

        if message.cc:
            payload.extend(self._format_recipients("cc", message.cc))
        if message.bcc:
            payload.extend(self._format_recipients("bcc", message.bcc))

    def _add_subject_and_body(
        self, payload: list[tuple[str, str]], message: OutboundEmailMessage
    ) -> None:
        """Add subject and body fields to payload."""
        payload.append(("subject", message.subject))
        if message.text_body:
            payload.append(("text", message.text_body))
        if message.html_body:
            payload.append(("html", message.html_body))

    def _add_reply_to(
        self, payload: list[tuple[str, str]], message: OutboundEmailMessage
    ) -> None:
        """Add reply-to header if present."""
        if message.reply_to:
            payload.append(("h:Reply-To", self._format_recipient(message.reply_to)))

    def _add_mailgun_options(
        self, payload: list[tuple[str, str]], message: OutboundEmailMessage
    ) -> None:
        """Add Mailgun-specific options to payload."""
        # Test mode
        sandbox = message.sandbox_override
        if sandbox is None:
            sandbox = self._settings.test_mode
        if sandbox:
            payload.append(("o:testmode", "yes"))

        # Tags
        tags = message.categories or self._settings.tags
        for tag in tags:
            payload.append(("o:tag", tag))

        # Tracking and security options
        if self._settings.click_tracking:
            payload.append(("o:tracking", self._settings.click_tracking))
        payload.extend(
            (
                ("o:require-tls", "true" if self._settings.require_tls else "false"),
                (
                    "o:skip-verification",
                    "true" if self._settings.skip_verification else "false",
                ),
            )
        )

    def _add_custom_fields(
        self, payload: list[tuple[str, str]], message: OutboundEmailMessage
    ) -> None:
        """Add custom variables and headers to payload."""
        for key, value in message.custom_args.items():
            payload.append((f"v:{key}", value))
        for header_name, header_value in message.headers.items():
            payload.append((f"h:{header_name}", header_value))

    def _format_sender(self) -> str:
        if self._settings.from_name:
            return f"{self._settings.from_name} <{self._settings.from_email}>"
        return self._settings.from_email

    def _format_recipients(
        self,
        field_name: str,
        recipients: Iterable[EmailRecipient],
    ) -> list[tuple[str, str]]:
        return [
            (field_name, self._format_recipient(recipient)) for recipient in recipients
        ]

    @staticmethod
    def _format_recipient(recipient: EmailRecipient) -> str:
        if recipient.name:
            return f"{recipient.name} <{recipient.email}>"
        return recipient.email

    def _default_base_url(self) -> str:
        if self._settings.region == "eu":
            return "https://api.eu.mailgun.net"
        return "https://api.mailgun.net"
