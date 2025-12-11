from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import SecretStr

from oneiric.adapters.messaging.common import EmailRecipient, OutboundEmailMessage
from oneiric.adapters.messaging.mailgun import MailgunAdapter, MailgunSettings


@pytest.mark.asyncio
async def test_mailgun_send_email_builds_payload() -> None:
    captured: dict[str, str] = {}

    def handler(
        request: httpx.Request,
    ) -> httpx.Response:  # pragma: no cover - helper used via assertions
        captured["path"] = request.url.path
        captured["body"] = request.content.decode()
        return httpx.Response(200, json={"id": "<2024.demo@mailgun.org>"})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="https://api.mailgun.net")
    settings = MailgunSettings(
        api_key=SecretStr("key-test"),
        domain="example.com",
        from_email="noreply@example.com",
        from_name="Oneiric",
        tags=["demo"],
    )
    adapter = MailgunAdapter(settings=settings, client=client)

    await adapter.init()

    message = OutboundEmailMessage(
        to=[EmailRecipient(email="user@example.com", name="User One")],
        subject="Hello",
        text_body="Plain",
        html_body="<p>Plain</p>",
        custom_args={"workflow": "demo"},
        headers={"X-Env": "test"},
    )

    result = await adapter.send_email(message)

    assert result.message_id == "<2024.demo@mailgun.org>"
    assert captured["path"] == "/v3/example.com/messages"

    parsed = parse_qs(captured["body"])
    assert parsed["from"] == ["Oneiric <noreply@example.com>"]
    assert parsed["to"] == ["User One <user@example.com>"]
    assert parsed["subject"] == ["Hello"]
    assert parsed["o:tag"] == ["demo"]
    assert parsed["v:workflow"] == ["demo"]
    assert parsed["h:X-Env"] == ["test"]

    await adapter.cleanup()


@pytest.mark.asyncio
async def test_mailgun_health_hits_domain_endpoint() -> None:
    calls = {"health": 0}

    def handler(
        request: httpx.Request,
    ) -> httpx.Response:  # pragma: no cover - helper used in asserts
        if request.url.path == "/v3/domains/example.com":
            calls["health"] += 1
            return httpx.Response(200, json={"domain": "example.com"})
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="https://api.mailgun.net")
    adapter = MailgunAdapter(
        settings=MailgunSettings(
            api_key=SecretStr("key"),
            domain="example.com",
            from_email="noreply@example.com",
        ),
        client=client,
    )
    await adapter.init()

    healthy = await adapter.health()
    assert healthy is True
    assert calls["health"] == 1

    await adapter.cleanup()
