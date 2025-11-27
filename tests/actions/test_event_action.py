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
                {"name": "ops", "url": "https://hooks.example.com/ops", "enabled": False},
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

    transport = httpx.MockTransport(handler)
    action = EventDispatchAction(
        EventDispatchSettings(dry_run=False),
        client_factory=lambda: httpx.AsyncClient(transport=transport),
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
