from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from oneiric.adapters.http import HTTPClientAdapter, HTTPClientSettings


@pytest.mark.asyncio
async def test_httpx_adapter_performs_requests() -> None:
    mock_response = Mock()
    mock_response.json.return_value = {"ok": True}

    adapter = HTTPClientAdapter(HTTPClientSettings(base_url="https://example.com"))

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    adapter._client = mock_client

    response = await adapter.get("/ping")
    assert response is mock_response
    mock_client.get.assert_awaited_once_with("/ping")
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_httpx_adapter_health_checks_with_base_url() -> None:
    mock_response = Mock()
    mock_response.status_code = 204

    adapter = HTTPClientAdapter(
        HTTPClientSettings(base_url="https://example.com", healthcheck_path="/health"),
    )
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    adapter._client = mock_client

    assert await adapter.health() is True
    mock_client.get.assert_awaited_once_with("/health")
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_httpx_adapter_health_without_base_url() -> None:
    adapter = HTTPClientAdapter(HTTPClientSettings(base_url=None))
    await adapter.init()
    assert await adapter.health() is True
    await adapter.cleanup()
