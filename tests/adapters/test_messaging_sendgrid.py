import json

import httpx
import pytest
from pydantic import SecretStr

from oneiric.adapters.messaging.messaging_types import (
    EmailRecipient,
    OutboundEmailMessage,
)
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


# ---------------------------------------------------------------------------
# Tests — coverage gaps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sendgrid_init_creates_client_when_none() -> None:
    """init() creates httpx.AsyncClient when no client provided (line 77)."""
    settings = SendGridSettings(
        api_key=SecretStr("test"), from_email="noreply@example.com"
    )
    adapter = SendGridAdapter(settings=settings)
    await adapter.init()
    assert adapter._client is not None
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_sendgrid_send_email_http_status_error_raises() -> None:
    """send_email raises LifecycleError on HTTPStatusError (lines 109-121)."""
    from oneiric.core.lifecycle import LifecycleError

    transport = httpx.MockTransport(lambda r: httpx.Response(400, json={"errors": []}))
    client = httpx.AsyncClient(transport=transport, base_url="https://api.test")
    settings = SendGridSettings(
        api_key=SecretStr("test"), from_email="noreply@example.com"
    )
    adapter = SendGridAdapter(settings=settings, client=client)
    await adapter.init()
    with pytest.raises(LifecycleError, match="sendgrid-send-failed"):
        await adapter.send_email(
            OutboundEmailMessage(
                to=[EmailRecipient(email="u@x.com")],
                subject="S",
                text_body="b",
            )
        )
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_sendgrid_send_email_fallback_message_id() -> None:
    """send_email uses Date header as fallback message_id (line 129)."""
    transport = httpx.MockTransport(
        lambda r: httpx.Response(202, headers={"Date": "Mon, 01 Jan 2024 00:00:00 GMT"})
    )
    client = httpx.AsyncClient(transport=transport, base_url="https://api.test")
    settings = SendGridSettings(
        api_key=SecretStr("test"), from_email="noreply@example.com"
    )
    adapter = SendGridAdapter(settings=settings, client=client)
    await adapter.init()
    result = await adapter.send_email(
        OutboundEmailMessage(
            to=[EmailRecipient(email="u@x.com")],
            subject="S",
            text_body="b",
        )
    )
    assert result.message_id == "Mon, 01 Jan 2024 00:00:00 GMT"
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_sendgrid_health_http_error_returns_false() -> None:
    """health() returns False on HTTPError (lines 98-100)."""

    def fail_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    transport = httpx.MockTransport(fail_handler)
    client = httpx.AsyncClient(transport=transport, base_url="https://api.test")
    settings = SendGridSettings(
        api_key=SecretStr("test"), from_email="noreply@example.com"
    )
    adapter = SendGridAdapter(settings=settings, client=client)
    await adapter.init()
    result = await adapter.health()
    assert result is False
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_sendgrid_send_email_http_error_raises() -> None:
    """send_email raises LifecycleError on HTTPError (lines 119-121)."""
    from oneiric.core.lifecycle import LifecycleError

    def fail_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    transport = httpx.MockTransport(fail_handler)
    client = httpx.AsyncClient(transport=transport, base_url="https://api.test")
    settings = SendGridSettings(
        api_key=SecretStr("test"), from_email="noreply@example.com"
    )
    adapter = SendGridAdapter(settings=settings, client=client)
    await adapter.init()
    with pytest.raises(LifecycleError, match="sendgrid-http-error"):
        await adapter.send_email(
            OutboundEmailMessage(
                to=[EmailRecipient(email="u@x.com")],
                subject="S",
                text_body="b",
            )
        )
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_sendgrid_send_email_with_cc_bcc_headers_reply_to() -> None:
    """_build_payload includes cc, bcc, headers, reply_to (lines 144, 146, 148, 171)."""
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        captured.append(_json.loads(request.content))
        return httpx.Response(202, headers={"X-Message-Id": "msg-x"})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="https://api.test")
    settings = SendGridSettings(
        api_key=SecretStr("test"), from_email="noreply@example.com"
    )
    adapter = SendGridAdapter(settings=settings, client=client)
    await adapter.init()
    await adapter.send_email(
        OutboundEmailMessage(
            to=[EmailRecipient(email="to@x.com")],
            cc=[EmailRecipient(email="cc@x.com")],
            bcc=[EmailRecipient(email="bcc@x.com")],
            headers={"X-Custom": "value"},
            reply_to=EmailRecipient(email="reply@x.com"),
            subject="S",
            text_body="b",
        )
    )
    personalization = captured[0]["personalizations"][0]
    assert "cc" in personalization
    assert "bcc" in personalization
    assert "headers" in personalization
    assert captured[0]["reply_to"]["email"] == "reply@x.com"
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_sendgrid_send_email_sandbox_mode() -> None:
    """_build_payload includes mail_settings when sandbox_mode=True (line 179)."""
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        captured.append(_json.loads(request.content))
        return httpx.Response(202, headers={"X-Message-Id": "msg-s"})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="https://api.test")
    settings = SendGridSettings(
        api_key=SecretStr("test"),
        from_email="noreply@example.com",
        sandbox_mode=True,
    )
    adapter = SendGridAdapter(settings=settings, client=client)
    await adapter.init()
    await adapter.send_email(
        OutboundEmailMessage(
            to=[EmailRecipient(email="u@x.com")],
            subject="S",
            text_body="b",
        )
    )
    assert captured[0]["mail_settings"]["sandbox_mode"]["enable"] is True
    await adapter.cleanup()
