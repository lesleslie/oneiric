from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import SecretStr

from oneiric.adapters.messaging.common import OutboundSMSMessage, SMSRecipient
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
