import httpx
import pytest
from pydantic import SecretStr

from oneiric.adapters.messaging.messaging_types import NotificationMessage
from oneiric.adapters.messaging.slack import SlackAdapter, SlackSettings
from oneiric.adapters.messaging.teams import TeamsAdapter, TeamsSettings
from oneiric.adapters.messaging.webhook import WebhookAdapter, WebhookSettings


@pytest.mark.asyncio
async def test_slack_send_notification_includes_blocks_and_channel() -> None:
    captured: dict[str, str] = {}

    def handler(
        request: httpx.Request,
    ) -> httpx.Response:  # pragma: no cover - helper used in assertions
        captured["url"] = str(request.url)
        captured["body"] = request.content.decode()
        return httpx.Response(200, json={"ok": True, "ts": "1700.01"})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="https://slack.test")
    adapter = SlackAdapter(
        settings=SlackSettings(token=SecretStr("xoxb-key"), default_channel="#general"),
        client=client,
    )
    await adapter.init()

    message = NotificationMessage(
        target="#alerts",
        text="Deployment complete",
        blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": "Done"}}],
    )

    result = await adapter.send_notification(message)

    assert result.message_id == "1700.01"
    assert captured["url"].endswith("/chat.postMessage")
    assert "#alerts" in captured["body"]

    await adapter.cleanup()


@pytest.mark.asyncio
async def test_teams_send_notification_builds_card() -> None:
    captured: dict[str, str] = {}

    def handler(
        request: httpx.Request,
    ) -> httpx.Response:  # pragma: no cover - helper used in assertions
        captured["url"] = str(request.url)
        captured["body"] = request.content.decode()
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = TeamsAdapter(
        settings=TeamsSettings(webhook_url="https://teams.test/webhook"),
        client=client,
    )
    await adapter.init()

    message = NotificationMessage(text="Hello Teams", title="Greeting")
    result = await adapter.send_notification(message)

    assert result.status_code == 200
    assert "Greeting" in captured["body"]
    assert captured["url"] == "https://teams.test/webhook"

    await adapter.cleanup()


@pytest.mark.asyncio
async def test_webhook_adapter_respects_method_override() -> None:
    captured: dict[str, str] = {}

    def handler(
        request: httpx.Request,
    ) -> httpx.Response:  # pragma: no cover - helper used in assertions
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["body"] = request.content.decode()
        return httpx.Response(202)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = WebhookAdapter(
        settings=WebhookSettings(url="https://hooks.test/notify", method="POST"),
        client=client,
    )
    await adapter.init()

    message = NotificationMessage(
        text="payload",
        extra_payload={
            "method": "put",
            "headers": {"X-Debug": "1"},
            "body": {"text": "payload"},
        },
    )

    result = await adapter.send_notification(message)

    assert result.status_code == 202
    assert captured["method"] == "PUT"
    assert captured["url"] == "https://hooks.test/notify"

    await adapter.cleanup()
