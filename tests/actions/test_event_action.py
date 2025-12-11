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
