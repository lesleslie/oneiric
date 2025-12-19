"""Twilio SMS adapter."""

from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Mapping
from urllib.parse import urlencode

import httpx
from pydantic import AnyHttpUrl, Field, SecretStr

from oneiric.adapters.httpx_base import HTTPXClientMixin
from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource
from oneiric.core.settings_mixins import TimeoutSettings

from .common import MessagingSendResult, OutboundSMSMessage


class TwilioSettings(TimeoutSettings):
    """Configuration for Twilio REST API interactions."""

    account_sid: str
    auth_token: SecretStr
    from_number: str = Field(
        pattern=r"^\+[1-9]\d{7,14}$",
        description="Sender number or short code in E.164 format.",
    )
    base_url: AnyHttpUrl = Field(default="https://api.twilio.com")
    api_version: str = Field(default="2010-04-01")
    messaging_service_sid: str | None = Field(
        default=None,
        description="Optional Messaging Service SID to use instead of a From number.",
    )
    default_status_callback: AnyHttpUrl | None = None
    dry_run: bool = Field(
        default=False,
        description="Skip outbound calls and return synthetic message IDs.",
    )


class TwilioAdapter(HTTPXClientMixin):
    """Adapter that sends SMS messages through the Twilio REST API."""

    metadata = AdapterMetadata(
        category="messaging",
        provider="twilio",
        factory="oneiric.adapters.messaging.twilio:TwilioAdapter",
        capabilities=["sms", "notifications"],
        stack_level=20,
        priority=330,
        source=CandidateSource.LOCAL_PKG,
        owner="Messaging",
        requires_secrets=True,
        settings_model=TwilioSettings,
    )

    def __init__(
        self,
        settings: TwilioSettings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(client=client)
        self._settings = settings
        self._logger = get_logger("adapter.messaging.twilio").bind(
            domain="adapter",
            key="messaging",
            provider="twilio",
        )

    async def init(self) -> None:
        auth = httpx.BasicAuth(
            self._settings.account_sid,
            self._settings.auth_token.get_secret_value(),
        )
        if self._client is None:
            self._init_client(
                lambda: httpx.AsyncClient(
                    base_url=str(self._settings.base_url),
                    timeout=self._settings.timeout,
                    auth=auth,
                )
            )
        self._logger.info("twilio-adapter-init")

    async def cleanup(self) -> None:
        await self._cleanup_client()
        self._logger.info("twilio-adapter-cleanup")

    async def health(self) -> bool:
        if self._settings.dry_run:
            return True
        client = self._ensure_client("twilio-client-not-initialized")
        try:
            response = await client.get(
                f"/{self._settings.api_version}/Accounts/{self._settings.account_sid}.json"
            )
            return response.status_code < 500
        except httpx.HTTPError as exc:  # pragma: no cover - network path
            self._logger.warning("twilio-health-failed", error=str(exc))
            return False

    async def send_sms(self, message: OutboundSMSMessage) -> MessagingSendResult:
        if self._settings.dry_run or message.metadata.get("dry_run") == "true":
            message_id = "twilio-dry-run"
            return MessagingSendResult(
                message_id=message_id,
                status_code=200,
                response_headers={},
            )

        client = self._ensure_client("twilio-client-not-initialized")
        payload = self._build_payload(message)
        encoded = urlencode(payload)
        path = f"/{self._settings.api_version}/Accounts/{self._settings.account_sid}/Messages.json"
        try:
            response = await client.post(
                path,
                content=encoded,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            self._logger.error(
                "twilio-send-failed",
                status_code=exc.response.status_code,
                body=exc.response.text,
            )
            raise LifecycleError("twilio-send-failed") from exc
        except httpx.HTTPError as exc:  # pragma: no cover - transport errors
            self._logger.error("twilio-http-error", error=str(exc))
            raise LifecycleError("twilio-http-error") from exc

        return MessagingSendResult(
            message_id=(message_id := response.json().get("sid", "twilio-message")),
            status_code=response.status_code,
            response_headers=dict(response.headers),
        )

    def _build_payload(self, message: OutboundSMSMessage) -> list[tuple[str, str]]:
        payload: list[tuple[str, str]] = [
            ("To", message.to.phone_number),
            ("Body", message.body),
        ]
        if self._settings.messaging_service_sid:
            payload.append(
                ("MessagingServiceSid", self._settings.messaging_service_sid)
            )
        else:
            payload.append(("From", self._settings.from_number))

        status_callback = (
            message.status_callback or self._settings.default_status_callback
        )
        if status_callback:
            payload.append(("StatusCallback", str(status_callback)))

        for media_url in message.media_urls:
            payload.append(("MediaUrl", str(media_url)))

        for key, value in message.metadata.items():
            if key.lower() == "dry_run":
                continue
            payload.append((key, value))
        return payload


class TwilioSignatureValidator:
    """Validates webhook signatures from Twilio callbacks."""

    def __init__(self, auth_token: str) -> None:
        self._auth_token = auth_token

    def build_signature(self, url: str, params: Mapping[str, str]) -> str:
        message = self._build_message(url, params)
        digest = hmac.new(
            self._auth_token.encode(), message.encode(), hashlib.sha1
        ).digest()
        return base64.b64encode(digest).decode()

    def validate(self, url: str, params: Mapping[str, str], signature: str) -> bool:
        expected = self.build_signature(url, params)
        return hmac.compare_digest(signature, expected)

    @staticmethod
    def _build_message(url: str, params: Mapping[str, str]) -> str:
        from operator import itemgetter

        sorted_items = sorted(params.items(), key=itemgetter(0))
        serialized = "".join(f"{key}{value}" for key, value in sorted_items)
        return f"{url}{serialized}"
