"""Messaging adapters (email/SMS providers)."""

from .apns import APNSPushAdapter, APNSPushSettings
from .common import (
    EmailRecipient,
    MessagingSendResult,
    NotificationMessage,
    OutboundEmailMessage,
    OutboundSMSMessage,
    SMSRecipient,
)
from .fcm import FCMPushAdapter, FCMPushSettings
from .mailgun import MailgunAdapter, MailgunSettings
from .sendgrid import SendGridAdapter, SendGridSettings
from .slack import SlackAdapter, SlackSettings
from .teams import TeamsAdapter, TeamsSettings
from .twilio import TwilioAdapter, TwilioSettings, TwilioSignatureValidator
from .webhook import WebhookAdapter, WebhookSettings
from .webpush import WebPushAdapter, WebPushSettings

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
    "APNSPushAdapter",
    "APNSPushSettings",
    "FCMPushAdapter",
    "FCMPushSettings",
    "TwilioAdapter",
    "TwilioSettings",
    "TwilioSignatureValidator",
    "SlackAdapter",
    "SlackSettings",
    "TeamsAdapter",
    "TeamsSettings",
    "WebhookAdapter",
    "WebhookSettings",
    "WebPushAdapter",
    "WebPushSettings",
]
