from __future__ import annotations

import json

import httpx
import pytest

from oneiric.actions.event import EventDispatchAction, EventDispatchSettings


@pytest.mark.asyncio
async def test_event_dispatch_dry_run() -> None:
    action = EventDispatchAction()
    result = await action.execute(
        {
            "topic": "deploys.completed",
            "payload": {"service": "oneiric", "status": "ok"},
            "hooks": [
                {"name": "audit", "url": "https://hooks.example.com/audit"},
                {
                    "name": "ops",
                    "url": "https://hooks.example.com/ops",
                    "enabled": False,
                },
            ],
        }
    )

    assert result["status"] == "skipped"
    assert result["delivered"] == 0
    assert result["skipped"] == 2
    assert result["hooks"][0]["status"] == "skipped"


@pytest.mark.asyncio
async def test_event_dispatch_executes_hooks() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        assert body["topic"] == "deploys.completed"
        return httpx.Response(200, json={"ok": True})

    # For httpx 1.0.dev3 compatibility, use client mocking instead of transport
    from unittest.mock import AsyncMock, Mock

    # Create a mock response
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"ok": True}

    # Create a mock client without spec to allow arbitrary attributes
    mock_client = Mock()
    mock_client.request = AsyncMock(return_value=mock_response)
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.aclose = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    action = EventDispatchAction(
        EventDispatchSettings(dry_run=False),
        client_factory=lambda: mock_client,
    )
    result = await action.execute(
        {
            "topic": "deploys.completed",
            "payload": {"service": "oneiric", "status": "ok"},
            "hooks": [{"name": "audit", "url": "https://hooks.example.com/audit"}],
        }
    )

    assert result["status"] == "dispatched"
    assert result["delivered"] == 1
    assert result["failed"] == 0
    assert result["hooks"][0]["status"] == "delivered"


# ---------------------------------------------------------------------------
# Gap-fill: uncovered branches in event.py
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_dispatch_empty_topic_raises() -> None:
    action = EventDispatchAction()
    from oneiric.core.lifecycle import LifecycleError

    with pytest.raises(LifecycleError):
        await action.execute({"topic": "   "})


@pytest.mark.asyncio
async def test_event_dispatch_non_mapping_payload_raises() -> None:
    action = EventDispatchAction()
    from oneiric.core.lifecycle import LifecycleError

    with pytest.raises(LifecycleError):
        await action.execute({"topic": "test", "payload": "not-a-mapping"})


@pytest.mark.asyncio
async def test_event_dispatch_non_mapping_metadata_raises() -> None:
    action = EventDispatchAction()
    from oneiric.core.lifecycle import LifecycleError

    with pytest.raises(LifecycleError):
        await action.execute({"topic": "test", "metadata": ["list"]})


def test_event_parse_hooks_none_sentinel() -> None:
    action = EventDispatchAction()
    assert action._parse_hooks(None) == []


def test_event_parse_hooks_empty_string_sentinel() -> None:
    action = EventDispatchAction()
    assert action._parse_hooks("") == []


def test_event_parse_hooks_empty_tuple_sentinel() -> None:
    action = EventDispatchAction()
    assert action._parse_hooks(()) == []


def test_event_parse_hooks_non_iterable_raises() -> None:
    action = EventDispatchAction()
    from oneiric.core.lifecycle import LifecycleError

    with pytest.raises(LifecycleError):
        action._parse_hooks(42)


@pytest.mark.asyncio
async def test_event_dispatch_hook_limit_exceeded_raises() -> None:
    action = EventDispatchAction(EventDispatchSettings(max_hooks=2))
    from oneiric.core.lifecycle import LifecycleError

    hooks = [{"name": f"h{i}", "url": "https://example.com/hook"} for i in range(3)]
    with pytest.raises(LifecycleError):
        await action.execute({"topic": "test", "hooks": hooks})


@pytest.mark.asyncio
async def test_event_dispatch_no_hooks_returns_queued() -> None:
    action = EventDispatchAction(EventDispatchSettings(dry_run=False))
    result = await action.execute({"topic": "test"})
    assert result["hooks"] == []
    assert result["status"] == "queued"


@pytest.mark.asyncio
async def test_event_dispatch_hook_with_secret_header() -> None:
    from unittest.mock import AsyncMock, Mock

    mock_response = Mock()
    mock_response.status_code = 200
    captured_headers: dict = {}

    async def _capture_request(method, url, **kwargs):
        captured_headers.update(kwargs.get("headers", {}))
        return mock_response

    mock_client = Mock()
    mock_client.request = _capture_request
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    action = EventDispatchAction(
        EventDispatchSettings(dry_run=False),
        client_factory=lambda: mock_client,
    )
    result = await action.execute(
        {
            "topic": "test",
            "hooks": [
                {"name": "secret-hook", "url": "https://example.com/h", "secret": "my-secret"}
            ],
        }
    )
    assert result["delivered"] == 1
    assert captured_headers.get("x-hook-secret") == "my-secret"


@pytest.mark.asyncio
async def test_event_dispatch_failed_http_response() -> None:
    from unittest.mock import AsyncMock, Mock

    mock_response = Mock()
    mock_response.status_code = 500
    mock_client = Mock()
    mock_client.request = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    action = EventDispatchAction(
        EventDispatchSettings(dry_run=False),
        client_factory=lambda: mock_client,
    )
    result = await action.execute(
        {
            "topic": "test",
            "hooks": [{"name": "failing-hook", "url": "https://example.com/h"}],
        }
    )
    assert result["failed"] == 1
    assert result["hooks"][0]["status"] == "failed"


@pytest.mark.asyncio
async def test_event_dispatch_uses_default_httpx_client() -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_inner = MagicMock()
    mock_inner.request = AsyncMock(return_value=mock_response)
    mock_inner.__aenter__ = AsyncMock(return_value=mock_inner)
    mock_inner.__aexit__ = AsyncMock(return_value=None)

    with patch("oneiric.actions.event.httpx.AsyncClient") as MockClient:
        MockClient.return_value = mock_inner
        action = EventDispatchAction(EventDispatchSettings(dry_run=False))
        result = await action.execute(
            {
                "topic": "test",
                "hooks": [{"name": "h", "url": "https://example.com/h"}],
            }
        )
        assert result["delivered"] == 1
        MockClient.assert_called_once()
