"""Lazy-loaded messaging adapters.

The concrete adapters below are re-exported lazily (PEP 562). Importing
this package eagerly pulled in every sibling adapter in the family and
every client library they need, which cost seconds of import time -- and a consumer
importing a single concrete adapter paid that tax too, because Python
executes every parent package's ``__init__`` on the way down.

Resolution is now deferred to first attribute access, so
``from oneiric.adapters.messaging import SomeAdapter`` still works and
``import oneiric.adapters.messaging`` stays cheap.

See ``oneiric/adapters/_lazy.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = [
    "APNSPushAdapter",
    "APNSPushSettings",
    "EmailRecipient",
    "FCMPushAdapter",
    "FCMPushSettings",
    "MailgunAdapter",
    "MailgunSettings",
    "MessagingSendResult",
    "NotificationMessage",
    "OutboundEmailMessage",
    "OutboundSMSMessage",
    "SMSRecipient",
    "SendGridAdapter",
    "SendGridSettings",
    "SlackAdapter",
    "SlackSettings",
    "TeamsAdapter",
    "TeamsSettings",
    "TwilioAdapter",
    "TwilioSettings",
    "TwilioSignatureValidator",
    "WebPushAdapter",
    "WebPushSettings",
    "WebhookAdapter",
    "WebhookSettings",
]


if TYPE_CHECKING:
    from oneiric.adapters.messaging.apns import (
        APNSPushAdapter,
        APNSPushSettings,
    )
    from oneiric.adapters.messaging.fcm import (
        FCMPushAdapter,
        FCMPushSettings,
    )
    from oneiric.adapters.messaging.mailgun import (
        MailgunAdapter,
        MailgunSettings,
    )
    from oneiric.adapters.messaging.messaging_types import (
        EmailRecipient,
        MessagingSendResult,
        NotificationMessage,
        OutboundEmailMessage,
        OutboundSMSMessage,
        SMSRecipient,
    )
    from oneiric.adapters.messaging.sendgrid import (
        SendGridAdapter,
        SendGridSettings,
    )
    from oneiric.adapters.messaging.slack import (
        SlackAdapter,
        SlackSettings,
    )
    from oneiric.adapters.messaging.teams import (
        TeamsAdapter,
        TeamsSettings,
    )
    from oneiric.adapters.messaging.twilio import (
        TwilioAdapter,
        TwilioSettings,
        TwilioSignatureValidator,
    )
    from oneiric.adapters.messaging.webhook import (
        WebhookAdapter,
        WebhookSettings,
    )
    from oneiric.adapters.messaging.webpush import (
        WebPushAdapter,
        WebPushSettings,
    )


_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "APNSPushAdapter": ("oneiric.adapters.messaging.apns", "APNSPushAdapter"),
    "APNSPushSettings": ("oneiric.adapters.messaging.apns", "APNSPushSettings"),
    "EmailRecipient": ("oneiric.adapters.messaging.messaging_types", "EmailRecipient"),
    "FCMPushAdapter": ("oneiric.adapters.messaging.fcm", "FCMPushAdapter"),
    "FCMPushSettings": ("oneiric.adapters.messaging.fcm", "FCMPushSettings"),
    "MailgunAdapter": ("oneiric.adapters.messaging.mailgun", "MailgunAdapter"),
    "MailgunSettings": ("oneiric.adapters.messaging.mailgun", "MailgunSettings"),
    "MessagingSendResult": (
        "oneiric.adapters.messaging.messaging_types",
        "MessagingSendResult",
    ),
    "NotificationMessage": (
        "oneiric.adapters.messaging.messaging_types",
        "NotificationMessage",
    ),
    "OutboundEmailMessage": (
        "oneiric.adapters.messaging.messaging_types",
        "OutboundEmailMessage",
    ),
    "OutboundSMSMessage": (
        "oneiric.adapters.messaging.messaging_types",
        "OutboundSMSMessage",
    ),
    "SMSRecipient": ("oneiric.adapters.messaging.messaging_types", "SMSRecipient"),
    "SendGridAdapter": ("oneiric.adapters.messaging.sendgrid", "SendGridAdapter"),
    "SendGridSettings": ("oneiric.adapters.messaging.sendgrid", "SendGridSettings"),
    "SlackAdapter": ("oneiric.adapters.messaging.slack", "SlackAdapter"),
    "SlackSettings": ("oneiric.adapters.messaging.slack", "SlackSettings"),
    "TeamsAdapter": ("oneiric.adapters.messaging.teams", "TeamsAdapter"),
    "TeamsSettings": ("oneiric.adapters.messaging.teams", "TeamsSettings"),
    "TwilioAdapter": ("oneiric.adapters.messaging.twilio", "TwilioAdapter"),
    "TwilioSettings": ("oneiric.adapters.messaging.twilio", "TwilioSettings"),
    "TwilioSignatureValidator": (
        "oneiric.adapters.messaging.twilio",
        "TwilioSignatureValidator",
    ),
    "WebPushAdapter": ("oneiric.adapters.messaging.webpush", "WebPushAdapter"),
    "WebPushSettings": ("oneiric.adapters.messaging.webpush", "WebPushSettings"),
    "WebhookAdapter": ("oneiric.adapters.messaging.webhook", "WebhookAdapter"),
    "WebhookSettings": ("oneiric.adapters.messaging.webhook", "WebhookSettings"),
}


def __getattr__(name: str) -> Any:
    """Resolve a re-exported adapter on first attribute access (PEP 562)."""
    from oneiric.adapters._lazy import resolve_lazy_export

    value = resolve_lazy_export(__name__, name, _LAZY_EXPORTS)
    globals()[name] = value  # cache for subsequent access
    return value


def __dir__() -> list[str]:
    """Advertise the lazy exports to ``dir()`` and tab-completion."""
    return sorted(__all__)
