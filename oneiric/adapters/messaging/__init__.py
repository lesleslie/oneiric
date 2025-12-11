"""Messaging adapters (email/SMS providers)."""

from .common import (
    EmailRecipient,
    MessagingSendResult,
    NotificationMessage,
    OutboundEmailMessage,
    OutboundSMSMessage,
    SMSRecipient,
)
from .mailgun import MailgunAdapter, MailgunSettings
from .sendgrid import SendGridAdapter, SendGridSettings
from .slack import SlackAdapter, SlackSettings
from .teams import TeamsAdapter, TeamsSettings
from .twilio import TwilioAdapter, TwilioSettings, TwilioSignatureValidator
from .webhook import WebhookAdapter, WebhookSettings

__all__ = [
    "EmailRecipient",
    "MessagingSendResult",
    "OutboundEmailMessage",
    "OutboundSMSMessage",
    "NotificationMessage",
    "SMSRecipient",
    "SendGridAdapter",
    "SendGridSettings",
    "MailgunAdapter",
    "MailgunSettings",
    "TwilioAdapter",
    "TwilioSettings",
    "TwilioSignatureValidator",
    "SlackAdapter",
    "SlackSettings",
    "TeamsAdapter",
    "TeamsSettings",
    "WebhookAdapter",
    "WebhookSettings",
]
