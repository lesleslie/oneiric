from __future__ import annotations

import pytest
import httpx

from oneiric.adapters.http import HTTPClientAdapter, HTTPClientSettings


def _mock_transport(status_code: int = 200, json_payload: dict | None = None) -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json_payload if json_payload is not None else {"path": request.url.path}
        return httpx.Response(status_code=status_code, json=payload)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_httpx_adapter_performs_requests() -> None:
    transport = _mock_transport(json_payload={"ok": True})
    adapter = HTTPClientAdapter(
        HTTPClientSettings(base_url="https://example.com"),
        transport=transport,
    )
    await adapter.init()
    response = await adapter.get("/ping")
    assert response.json() == {"ok": True}
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_httpx_adapter_health_checks_with_base_url() -> None:
    transport = _mock_transport(status_code=204)
    adapter = HTTPClientAdapter(
        HTTPClientSettings(base_url="https://example.com", healthcheck_path="/health"),
        transport=transport,
    )
    await adapter.init()
    assert await adapter.health() is True
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_httpx_adapter_health_without_base_url() -> None:
    adapter = HTTPClientAdapter(HTTPClientSettings(base_url=None))
    await adapter.init()
    assert await adapter.health() is True
    await adapter.cleanup()
