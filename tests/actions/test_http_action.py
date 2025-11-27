from __future__ import annotations

import httpx
import pytest

from oneiric.actions.http import HttpActionSettings, HttpFetchAction
from oneiric.core.lifecycle import LifecycleError


def _mock_response(json_payload: dict | None = None, status_code: int = 200, text: str = "") -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        if json_payload is not None:
            return httpx.Response(status_code=status_code, json=json_payload)
        return httpx.Response(status_code=status_code, text=text or "ok")

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_http_fetch_action_returns_json() -> None:
    transport = _mock_response({"ok": True})
    client = httpx.AsyncClient(transport=transport, base_url="https://api.local")
    action = HttpFetchAction(HttpActionSettings(base_url="https://api.local"), client=client)

    result = await action.execute(
        {
            "path": "/demo",
            "params": {"q": "1"},
            "headers": {"X-Test": "value"},
        }
    )

    assert result["status_code"] == 200
    assert result["json"] == {"ok": True}
    assert result["ok"] is True
    assert result["method"] == "GET"
    assert result["url"].endswith("/demo?q=1")

    await client.aclose()


@pytest.mark.asyncio
async def test_http_fetch_action_raise_for_status() -> None:
    transport = _mock_response({"error": True}, status_code=500)
    client = httpx.AsyncClient(transport=transport)
    action = HttpFetchAction(HttpActionSettings(base_url="https://api.local"), client=client)

    with pytest.raises(LifecycleError):
        await action.execute(
            {
                "path": "/demo",
                "raise_for_status": True,
            }
        )

    await client.aclose()


@pytest.mark.asyncio
async def test_http_fetch_action_requires_url() -> None:
    action = HttpFetchAction(HttpActionSettings(base_url=None))

    with pytest.raises(LifecycleError):
        await action.execute({})
