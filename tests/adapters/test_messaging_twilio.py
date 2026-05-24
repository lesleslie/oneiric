from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import SecretStr

from oneiric.adapters.messaging.messaging_types import OutboundSMSMessage, SMSRecipient
from oneiric.adapters.messaging.twilio import (
    TwilioAdapter,
    TwilioSettings,
    TwilioSignatureValidator,
)


@pytest.mark.asyncio
async def test_twilio_send_sms_builds_payload() -> None:
    captured: dict[str, str] = {}

    def handler(
        request: httpx.Request,
    ) -> httpx.Response:  # pragma: no cover - helper triggered within test assertions
        captured["path"] = request.url.path
        captured["body"] = request.content.decode()
        return httpx.Response(201, json={"sid": "SM123"})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="https://api.twilio.com")
    adapter = TwilioAdapter(
        settings=TwilioSettings(
            account_sid="ACabc",
            auth_token=SecretStr("auth"),
            from_number="+15551234567",
        ),
        client=client,
    )
    await adapter.init()

    message = OutboundSMSMessage(
        to=SMSRecipient(phone_number="+15557654321"),
        body="hello",
    )

    result = await adapter.send_sms(message)

    assert result.message_id == "SM123"
    assert captured["path"].endswith("/Messages.json")

    parsed = parse_qs(captured["body"])
    assert parsed["To"] == ["+15557654321"]
    assert parsed["From"] == ["+15551234567"]
    assert parsed["Body"] == ["hello"]

    await adapter.cleanup()


@pytest.mark.asyncio
async def test_twilio_dry_run_short_circuits_request() -> None:
    adapter = TwilioAdapter(
        settings=TwilioSettings(
            account_sid="ACabc",
            auth_token=SecretStr("auth"),
            from_number="+15551234567",
            dry_run=True,
        )
    )
    await adapter.init()

    message = OutboundSMSMessage(
        to=SMSRecipient(phone_number="+15557654321"),
        body="hello",
    )

    result = await adapter.send_sms(message)

    assert result.message_id == "twilio-dry-run"
    assert result.status_code == 200

    await adapter.cleanup()


def test_twilio_signature_validator_matches_reference() -> None:
    validator = TwilioSignatureValidator("auth")
    url = "https://example.com/hook"
    params = {"Body": "hello", "From": "+15551234567"}

    signature = validator.build_signature(url, params)
    assert validator.validate(url, params, signature) is True

    assert validator.validate(url, params, signature + "abc") is False


# ---------------------------------------------------------------------------
# Tests — coverage gaps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_twilio_health_dry_run() -> None:
    """health() returns True immediately when dry_run=True (line 91)."""
    adapter = TwilioAdapter(
        settings=TwilioSettings(
            account_sid="ACabc",
            auth_token=SecretStr("auth"),
            from_number="+15551234567",
            dry_run=True,
        )
    )
    assert await adapter.health() is True


@pytest.mark.asyncio
async def test_twilio_health_non_dry_run() -> None:
    """health() makes GET to /Accounts endpoint (lines 90-97)."""
    transport = httpx.MockTransport(lambda r: httpx.Response(200))
    client = httpx.AsyncClient(transport=transport, base_url="https://api.twilio.com")
    adapter = TwilioAdapter(
        settings=TwilioSettings(
            account_sid="ACabc",
            auth_token=SecretStr("auth"),
            from_number="+15551234567",
        ),
        client=client,
    )
    await adapter.init()
    assert await adapter.health() is True
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_twilio_send_sms_http_status_error_raises() -> None:
    """send_sms raises LifecycleError on HTTPStatusError (lines 122-128)."""
    from oneiric.core.lifecycle import LifecycleError

    transport = httpx.MockTransport(
        lambda r: httpx.Response(400, json={"message": "bad request"})
    )
    client = httpx.AsyncClient(transport=transport, base_url="https://api.twilio.com")
    adapter = TwilioAdapter(
        settings=TwilioSettings(
            account_sid="ACabc",
            auth_token=SecretStr("auth"),
            from_number="+15551234567",
        ),
        client=client,
    )
    await adapter.init()
    with pytest.raises(LifecycleError, match="twilio-send-failed"):
        await adapter.send_sms(
            OutboundSMSMessage(to=SMSRecipient(phone_number="+15557654321"), body="hi")
        )
    await adapter.cleanup()


def test_build_payload_with_messaging_service_sid() -> None:
    """_build_payload uses MessagingServiceSid when set (line 145)."""
    from urllib.parse import parse_qs, urlencode

    adapter = TwilioAdapter(
        settings=TwilioSettings(
            account_sid="ACabc",
            auth_token=SecretStr("auth"),
            from_number="+15551234567",
            messaging_service_sid="MG123",
        )
    )
    payload = adapter._build_payload(
        OutboundSMSMessage(to=SMSRecipient(phone_number="+15557654321"), body="hi")
    )
    parsed = parse_qs(urlencode(payload))
    assert "MessagingServiceSid" in parsed
    assert "From" not in parsed


def test_build_payload_with_status_callback() -> None:
    """_build_payload appends StatusCallback when set (line 155)."""
    from urllib.parse import parse_qs, urlencode

    adapter = TwilioAdapter(
        settings=TwilioSettings(
            account_sid="ACabc",
            auth_token=SecretStr("auth"),
            from_number="+15551234567",
        )
    )
    msg = OutboundSMSMessage(
        to=SMSRecipient(phone_number="+15557654321"),
        body="hi",
        status_callback="https://cb.example.com",
    )
    payload = adapter._build_payload(msg)
    parsed = parse_qs(urlencode(payload))
    assert "StatusCallback" in parsed


def test_build_payload_with_media_urls() -> None:
    """_build_payload appends MediaUrl for each url (line 158)."""
    from urllib.parse import parse_qs, urlencode

    adapter = TwilioAdapter(
        settings=TwilioSettings(
            account_sid="ACabc",
            auth_token=SecretStr("auth"),
            from_number="+15551234567",
        )
    )
    msg = OutboundSMSMessage(
        to=SMSRecipient(phone_number="+15557654321"),
        body="hi",
        media_urls=["https://img.example.com/pic.jpg"],
    )
    payload = adapter._build_payload(msg)
    parsed = parse_qs(urlencode(payload))
    assert "MediaUrl" in parsed


def test_build_payload_skips_dry_run_metadata() -> None:
    """_build_payload skips 'dry_run' metadata key (lines 161-163)."""
    from urllib.parse import parse_qs, urlencode

    adapter = TwilioAdapter(
        settings=TwilioSettings(
            account_sid="ACabc",
            auth_token=SecretStr("auth"),
            from_number="+15551234567",
        )
    )
    msg = OutboundSMSMessage(
        to=SMSRecipient(phone_number="+15557654321"),
        body="hi",
        metadata={"dry_run": "false", "custom_key": "custom_val"},
    )
    payload = adapter._build_payload(msg)
    parsed = parse_qs(urlencode(payload))
    assert "dry_run" not in parsed
    assert "custom_key" in parsed


# ---------------------------------------------------------------------------
# Tests — messaging_types validators
# ---------------------------------------------------------------------------


def test_outbound_sms_message_rejects_too_many_media_urls() -> None:
    """_ensure_media_count raises when >10 media_urls (line 59 of messaging_types.py)."""
    with pytest.raises(ValueError, match="at most 10 URLs"):
        OutboundSMSMessage(
            to=SMSRecipient(phone_number="+15557654321"),
            body="hi",
            media_urls=[f"https://img.example.com/{i}.jpg" for i in range(11)],
        )


def test_notification_message_rejects_empty_text() -> None:
    """_ensure_text raises when text is whitespace-only (line 80 of messaging_types.py)."""
    from oneiric.adapters.messaging.messaging_types import NotificationMessage

    with pytest.raises(ValueError, match="text cannot be empty"):
        NotificationMessage(text="   ")
