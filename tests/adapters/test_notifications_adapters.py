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


# ---------------------------------------------------------------------------
# Tests — coverage gaps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slack_init_without_client_creates_internal_client() -> None:
    """init() creates httpx.AsyncClient when none provided (lines 57-67)."""
    from pydantic import SecretStr

    adapter = SlackAdapter(
        settings=SlackSettings(token=SecretStr("xoxb-test"), default_channel="#gen"),
    )
    await adapter.init()
    assert adapter._client is not None
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_slack_health_returns_true_on_200() -> None:
    """health() calls /auth.test and returns True on non-500 response (lines 81-84)."""
    from pydantic import SecretStr

    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True}))
    client = httpx.AsyncClient(transport=transport, base_url="https://slack.test")
    adapter = SlackAdapter(
        settings=SlackSettings(token=SecretStr("xoxb-key")),
        client=client,
    )
    await adapter.init()
    assert await adapter.health() is True
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_slack_send_notification_missing_channel_raises() -> None:
    """send_notification raises LifecycleError when no channel set (line 95)."""
    from pydantic import SecretStr

    from oneiric.core.lifecycle import LifecycleError

    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True}))
    client = httpx.AsyncClient(transport=transport, base_url="https://slack.test")
    adapter = SlackAdapter(
        settings=SlackSettings(token=SecretStr("xoxb-key")),
        client=client,
    )
    await adapter.init()
    with pytest.raises(LifecycleError, match="slack-channel-missing"):
        await adapter.send_notification(NotificationMessage(text="hi"))
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_slack_payload_with_attachments_and_title() -> None:
    """_build_slack_payload includes attachments and title when set (lines 120, 122)."""
    import json

    from pydantic import SecretStr

    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "ts": "1234.56"})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="https://slack.test")
    adapter = SlackAdapter(
        settings=SlackSettings(token=SecretStr("xoxb-key")),
        client=client,
    )
    await adapter.init()
    await adapter.send_notification(
        NotificationMessage(
            target="#chan",
            text="msg",
            title="My Title",
            attachments=[{"fallback": "att"}],
        )
    )
    assert captured[0]["attachments"] == [{"fallback": "att"}]
    assert captured[0]["title"] == "My Title"
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_slack_payload_with_default_username_emoji_extra() -> None:
    """_build_slack_payload applies default_username, icon_emoji, extra_payload (lines 125, 127, 130)."""
    import json

    from pydantic import SecretStr

    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "ts": "1"})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="https://slack.test")
    adapter = SlackAdapter(
        settings=SlackSettings(
            token=SecretStr("xoxb-key"),
            default_username="BotUser",
            default_icon_emoji=":robot_face:",
        ),
        client=client,
    )
    await adapter.init()
    await adapter.send_notification(
        NotificationMessage(
            target="#chan",
            text="msg",
            extra_payload={"custom_key": "custom_val"},
        )
    )
    assert captured[0]["username"] == "BotUser"
    assert captured[0]["icon_emoji"] == ":robot_face:"
    assert captured[0]["custom_key"] == "custom_val"
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_slack_http_status_error_raises_lifecycle_error() -> None:
    """_send_slack_request converts HTTPStatusError to LifecycleError (lines 141-147)."""
    from pydantic import SecretStr

    from oneiric.core.lifecycle import LifecycleError

    transport = httpx.MockTransport(
        lambda r: httpx.Response(429, json={"error": "ratelimited"})
    )
    client = httpx.AsyncClient(transport=transport, base_url="https://slack.test")
    adapter = SlackAdapter(
        settings=SlackSettings(token=SecretStr("xoxb-key"), default_channel="#c"),
        client=client,
    )
    await adapter.init()
    with pytest.raises(LifecycleError, match="slack-send-failed"):
        await adapter.send_notification(NotificationMessage(text="hi"))
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_slack_validate_response_ok_false_raises() -> None:
    """_validate_slack_response raises LifecycleError when ok=False (lines 155-157)."""
    from pydantic import SecretStr

    from oneiric.core.lifecycle import LifecycleError

    transport = httpx.MockTransport(
        lambda r: httpx.Response(200, json={"ok": False, "error": "channel_not_found"})
    )
    client = httpx.AsyncClient(transport=transport, base_url="https://slack.test")
    adapter = SlackAdapter(
        settings=SlackSettings(token=SecretStr("xoxb-key"), default_channel="#c"),
        client=client,
    )
    await adapter.init()
    with pytest.raises(LifecycleError, match="slack-send-error"):
        await adapter.send_notification(NotificationMessage(text="hi"))
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_teams_health_returns_true() -> None:
    """health() calls HEAD on webhook_url and returns True (lines 58-61)."""
    transport = httpx.MockTransport(lambda r: httpx.Response(200))
    client = httpx.AsyncClient(transport=transport)
    from oneiric.adapters.messaging.teams import TeamsAdapter, TeamsSettings

    adapter = TeamsAdapter(
        settings=TeamsSettings(webhook_url="https://teams.test/webhook"),
        client=client,
    )
    await adapter.init()
    assert await adapter.health() is True
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_teams_send_notification_http_error_raises() -> None:
    """send_notification raises LifecycleError on HTTPStatusError (lines 76-82)."""
    from oneiric.adapters.messaging.teams import TeamsAdapter, TeamsSettings
    from oneiric.core.lifecycle import LifecycleError

    transport = httpx.MockTransport(lambda r: httpx.Response(429))
    client = httpx.AsyncClient(transport=transport)
    adapter = TeamsAdapter(
        settings=TeamsSettings(webhook_url="https://teams.test/webhook"),
        client=client,
    )
    await adapter.init()
    with pytest.raises(LifecycleError, match="teams-send-failed"):
        await adapter.send_notification(NotificationMessage(text="hi"))
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_teams_payload_with_attachments_and_extra() -> None:
    """_build_payload handles attachments and extra_payload (lines 100, 112)."""
    import json

    from oneiric.adapters.messaging.teams import TeamsAdapter, TeamsSettings

    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = TeamsAdapter(
        settings=TeamsSettings(webhook_url="https://teams.test/webhook"),
        client=client,
    )
    await adapter.init()
    await adapter.send_notification(
        NotificationMessage(
            text="msg",
            attachments=[{"key": "val"}],
            extra_payload={"potentialAction": []},
        )
    )
    assert captured[0]["potentialAction"] == []
    sections = captured[0]["sections"]
    assert any("facts" in s for s in sections)
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_webhook_health_returns_true() -> None:
    """health() calls HEAD on url and returns True (lines 59-62)."""
    transport = httpx.MockTransport(lambda r: httpx.Response(200))
    client = httpx.AsyncClient(transport=transport)
    adapter = WebhookAdapter(
        settings=WebhookSettings(url="https://hooks.test/ping"),
        client=client,
    )
    await adapter.init()
    assert await adapter.health() is True
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_webhook_unsupported_method_raises() -> None:
    """send_notification raises LifecycleError when method is unsupported (line 85)."""
    from oneiric.core.lifecycle import LifecycleError

    transport = httpx.MockTransport(lambda r: httpx.Response(200))
    client = httpx.AsyncClient(transport=transport)
    adapter = WebhookAdapter(
        settings=WebhookSettings(url="https://hooks.test/notify", method="POST"),
        client=client,
    )
    await adapter.init()
    with pytest.raises(LifecycleError, match="webhook-method-unsupported"):
        await adapter.send_notification(
            NotificationMessage(text="hi", extra_payload={"method": "BADMETHOD"})
        )
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_webhook_http_status_error_raises() -> None:
    """send_notification raises LifecycleError on HTTPStatusError (lines 90-96)."""
    from oneiric.core.lifecycle import LifecycleError

    transport = httpx.MockTransport(lambda r: httpx.Response(503))
    client = httpx.AsyncClient(transport=transport)
    adapter = WebhookAdapter(
        settings=WebhookSettings(url="https://hooks.test/notify"),
        client=client,
    )
    await adapter.init()
    with pytest.raises(LifecycleError, match="webhook-send-failed"):
        await adapter.send_notification(NotificationMessage(text="hi"))
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
