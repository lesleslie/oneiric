from __future__ import annotations

from typing import Any

import pytest

from oneiric.adapters.http.aiohttp import AioHTTPAdapter
from oneiric.adapters.http.httpx import HTTPClientSettings


class DummyResponse:
    def __init__(
        self, status: int = 200, payload: dict[str, Any] | None = None
    ) -> None:
        self.status = status
        self._payload = payload or {}

    async def json(self) -> dict[str, Any]:
        return self._payload


class DummySession:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.closed = False
        self._last_request: dict[str, Any] | None = None

    async def request(self, method: str, url: str, **kwargs: Any) -> DummyResponse:
        self._last_request = {"method": method, "url": url, **kwargs}
        payload = kwargs.get("json") or {"url": url}
        return DummyResponse(payload=payload)

    async def close(self) -> None:
        self.closed = True

    async def get(self, url: str, **kwargs: Any) -> DummyResponse:
        return await self.request("GET", url, **kwargs)


@pytest.mark.asyncio
async def test_aiohttp_adapter_request_and_headers() -> None:
    session = DummySession()
    settings = HTTPClientSettings(
        base_url="https://example.com", headers={"X-Test": "1"}
    )
    adapter = AioHTTPAdapter(settings, session=session)
    await adapter.init()
    response = await adapter.post("/demo", json={"ok": True})
    assert await response.json() == {"ok": True}
    assert session._last_request["url"] == "https://example.com/demo"
    assert session.headers["X-Test"] == "1"
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_aiohttp_adapter_health_success() -> None:
    session = DummySession()
    settings = HTTPClientSettings(
        base_url="https://example.com", healthcheck_path="/health"
    )
    adapter = AioHTTPAdapter(settings, session=session)
    await adapter.init()
    assert await adapter.health() is True
    await adapter.cleanup()
