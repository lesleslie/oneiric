import json

import httpx
import pytest
from pydantic import SecretStr

from oneiric.adapters.messaging.common import EmailRecipient, OutboundEmailMessage
from oneiric.adapters.messaging.sendgrid import SendGridAdapter, SendGridSettings


@pytest.mark.asyncio
async def test_sendgrid_send_email_builds_payload_and_returns_message_id() -> None:
    captured: dict[str, str] = {}

    def handler(
        request: httpx.Request,
    ) -> httpx.Response:  # pragma: no cover - exercised in test assertions
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["body"] = request.content.decode()
        return httpx.Response(202, headers={"X-Message-Id": "msg-123"})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="https://api.test")
    settings = SendGridSettings(
        api_key=SecretStr("test"),
        from_email="noreply@example.com",
        from_name="Oneiric",
        categories=["demo"],
    )

    adapter = SendGridAdapter(settings=settings, client=client)
    await adapter.init()

    message = OutboundEmailMessage(
        to=[EmailRecipient(email="user@example.com", name="User")],
        subject="Hello",
        text_body="Hello world",
        html_body="<p>Hello world</p>",
        custom_args={"workflow": "demo"},
    )

    result = await adapter.send_email(message)

    assert result.message_id == "msg-123"
    assert result.status_code == 202

    payload = json.loads(captured["body"])
    personalizations = payload["personalizations"][0]
    assert personalizations["to"][0]["email"] == "user@example.com"
    assert payload["from"]["email"] == "noreply@example.com"
    assert payload["categories"] == ["demo"]

    await adapter.cleanup()


@pytest.mark.asyncio
async def test_sendgrid_health_hits_scopes_endpoint() -> None:
    calls: dict[str, int] = {"count": 0}

    def handler(
        request: httpx.Request,
    ) -> httpx.Response:  # pragma: no cover - instrumentation helper
        if request.url.path == "/scopes":
            calls["count"] += 1
            return httpx.Response(200, json={"scopes": []})
        return httpx.Response(202)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="https://api.test")
    settings = SendGridSettings(
        api_key=SecretStr("test"), from_email="noreply@example.com"
    )
    adapter = SendGridAdapter(settings=settings, client=client)
    await adapter.init()

    healthy = await adapter.health()
    assert healthy is True
    assert calls["count"] == 1

    await adapter.cleanup()


def test_outbound_message_requires_content() -> None:
    with pytest.raises(ValueError):
        OutboundEmailMessage(
            to=[EmailRecipient(email="user@example.com")],
            subject="No content",
        )
