"""Shared models used by messaging adapters."""

from __future__ import annotations

from typing import Any

from pydantic import AnyHttpUrl, BaseModel, EmailStr, Field, model_validator


class EmailRecipient(BaseModel):
    """Represents a single recipient entry for outbound email."""

    email: EmailStr
    name: str | None = None


class OutboundEmailMessage(BaseModel):
    """Normalized outbound message payload consumed by adapters."""

    to: list[EmailRecipient]
    subject: str
    text_body: str | None = None
    html_body: str | None = None
    cc: list[EmailRecipient] = Field(default_factory=list)
    bcc: list[EmailRecipient] = Field(default_factory=list)
    reply_to: EmailRecipient | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    custom_args: dict[str, str] = Field(default_factory=dict)
    categories: list[str] = Field(default_factory=list)
    sandbox_override: bool | None = Field(
        default=None,
        description="Override adapter sandbox toggle for a single send call.",
    )

    @model_validator(mode="after")
    def _ensure_content(self) -> OutboundEmailMessage:
        if not self.text_body and not self.html_body:
            raise ValueError("OutboundEmailMessage requires text_body and/or html_body")
        return self


class MessagingSendResult(BaseModel):
    """Result returned by messaging adapters after dispatching a message."""

    message_id: str
    status_code: int
    response_headers: dict[str, str] = Field(default_factory=dict)


class SMSRecipient(BaseModel):
    """Represents a SMS destination in E.164 format."""

    phone_number: str = Field(
        pattern=r"^\+[1-9]\d{7,14}$",
        description="Phone number in E.164 format (e.g. +15551234567).",
    )


class OutboundSMSMessage(BaseModel):
    """Normalized SMS payload so adapters share validation rules."""

    to: SMSRecipient
    body: str = Field(min_length=1)
    media_urls: list[AnyHttpUrl] = Field(default_factory=list)
    status_callback: AnyHttpUrl | None = None
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _ensure_media_count(self) -> OutboundSMSMessage:
        if len(self.media_urls) > 10:
            raise ValueError("SMS media payloads support at most 10 URLs")
        return self


class NotificationMessage(BaseModel):
    """Generic notification payload consumed by Slack/Teams/webhook adapters."""

    text: str
    target: str | None = Field(
        default=None,
        description="Channel identifier or webhook URL override, depending on adapter.",
    )
    title: str | None = None
    blocks: list[dict[str, Any]] = Field(default_factory=list)
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    extra_payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Adapter-specific overrides merged into the outbound payload.",
    )

    @model_validator(mode="after")
    def _ensure_text(self) -> NotificationMessage:
        if not self.text.strip():
            raise ValueError("NotificationMessage text cannot be empty")
        return self
