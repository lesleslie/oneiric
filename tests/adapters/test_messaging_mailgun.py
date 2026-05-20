from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import SecretStr

from oneiric.adapters.messaging.mailgun import MailgunAdapter, MailgunSettings
from oneiric.adapters.messaging.messaging_types import (
    EmailRecipient,
    OutboundEmailMessage,
)


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


# ---------------------------------------------------------------------------
# Tests — coverage gaps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mailgun_init_creates_client_when_none() -> None:
    """init() creates httpx.AsyncClient when no client provided (line 80)."""
    settings = MailgunSettings(
        api_key=SecretStr("key"), domain="example.com", from_email="noreply@example.com"
    )
    adapter = MailgunAdapter(settings=settings)
    await adapter.init()
    assert adapter._client is not None
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_mailgun_send_email_http_status_error_raises() -> None:
    """send_email raises LifecycleError on HTTPStatusError (lines 116-122)."""
    from oneiric.core.lifecycle import LifecycleError

    transport = httpx.MockTransport(lambda r: httpx.Response(400, json={"message": "err"}))
    client = httpx.AsyncClient(transport=transport, base_url="https://api.mailgun.net")
    adapter = MailgunAdapter(
        settings=MailgunSettings(
            api_key=SecretStr("key"), domain="example.com", from_email="noreply@example.com"
        ),
        client=client,
    )
    await adapter.init()
    with pytest.raises(LifecycleError, match="mailgun-send-failed"):
        await adapter.send_email(
            OutboundEmailMessage(
                to=[EmailRecipient(email="u@x.com")], subject="S", text_body="b"
            )
        )
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_mailgun_send_email_with_cc_bcc_reply_to_sandbox() -> None:
    """_build_payload includes cc, bcc, reply_to, and sandbox mode (lines 155, 157, 172, 181)."""
    parsed_body: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        from urllib.parse import parse_qs
        parsed_body.append(parse_qs(request.content.decode()))
        return httpx.Response(200, json={"id": "msg-1"})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="https://api.mailgun.net")
    adapter = MailgunAdapter(
        settings=MailgunSettings(
            api_key=SecretStr("key"),
            domain="example.com",
            from_email="noreply@example.com",
            test_mode=True,
        ),
        client=client,
    )
    await adapter.init()
    await adapter.send_email(
        OutboundEmailMessage(
            to=[EmailRecipient(email="to@x.com")],
            cc=[EmailRecipient(email="cc@x.com")],
            bcc=[EmailRecipient(email="bcc@x.com")],
            reply_to=EmailRecipient(email="reply@x.com"),
            subject="S",
            text_body="b",
        )
    )
    body = parsed_body[0]
    assert "cc" in body
    assert "bcc" in body
    assert "h:Reply-To" in body
    assert body.get("o:testmode") == ["yes"]
    await adapter.cleanup()


def test_mailgun_format_sender_no_name() -> None:
    """_format_sender returns raw email when from_name is unset (line 210)."""
    adapter = MailgunAdapter(
        MailgunSettings(
            api_key=SecretStr("key"), domain="x.com", from_email="noreply@x.com"
        )
    )
    assert adapter._format_sender() == "noreply@x.com"


def test_mailgun_format_recipient_no_name() -> None:
    """_format_recipient returns raw email when name is unset (line 225)."""
    adapter = MailgunAdapter(
        MailgunSettings(
            api_key=SecretStr("key"), domain="x.com", from_email="noreply@x.com"
        )
    )
    result = adapter._format_recipient(EmailRecipient(email="user@x.com"))
    assert result == "user@x.com"


def test_mailgun_eu_region_base_url() -> None:
    """_default_base_url returns EU endpoint when region='eu' (line 229)."""
    adapter = MailgunAdapter(
        MailgunSettings(
            api_key=SecretStr("key"), domain="x.com", from_email="noreply@x.com", region="eu"
        )
    )
    assert adapter._default_base_url() == "https://api.eu.mailgun.net"


@pytest.mark.asyncio
async def test_mailgun_send_email_with_click_tracking() -> None:
    """_add_mailgun_options appends o:tracking when click_tracking is set (line 188)."""
    parsed_body: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        from urllib.parse import parse_qs
        parsed_body.append(parse_qs(request.content.decode()))
        return httpx.Response(200, json={"id": "msg-ct"})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="https://api.mailgun.net")
    adapter = MailgunAdapter(
        settings=MailgunSettings(
            api_key=SecretStr("key"),
            domain="example.com",
            from_email="noreply@example.com",
            click_tracking="yes",
        ),
        client=client,
    )
    await adapter.init()
    await adapter.send_email(
        OutboundEmailMessage(
            to=[EmailRecipient(email="u@x.com")], subject="S", text_body="b"
        )
    )
    assert parsed_body[0].get("o:tracking") == ["yes"]
    await adapter.cleanup()
