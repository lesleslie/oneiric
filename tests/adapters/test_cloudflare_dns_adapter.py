from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from oneiric.adapters.dns.cloudflare import CloudflareDNSAdapter, CloudflareDNSSettings
from oneiric.core.lifecycle import LifecycleError


def _response_json(success: bool, result: Any = None) -> bytes:
    payload = {"success": success}
    if result is not None:
        payload["result"] = result
    return json.dumps(payload).encode("utf-8")


class _Recorder:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        # default success payload
        if request.method == "GET" and request.url.path.endswith("/dns_records"):
            data = _response_json(True, result=[{"id": "rec-1"}])
        elif request.method == "GET" and "zones" in request.url.path:
            data = _response_json(True, result={"id": "zone"})
        else:
            data = _response_json(True, result={"id": "rec-123"})
        return httpx.Response(200, content=data)


@pytest.mark.asyncio
async def test_cloudflare_create_and_list_records() -> None:
    recorder = _Recorder()
    transport = httpx.MockTransport(recorder.handler)
    client = httpx.AsyncClient(base_url="https://example.com", transport=transport)

    adapter = CloudflareDNSAdapter(
        CloudflareDNSSettings(zone_id="zone", api_token=SecretStr("token")),  # type: ignore[name-defined]
        client=client,
    )
    await adapter.init()

    records = await adapter.list_records()
    assert records == [{"id": "rec-1"}]

    result = await adapter.create_record(
        name="demo", content="1.1.1.1", record_type="A"
    )
    assert result["id"] == "rec-123"

    # headers set once during init when external client provided
    assert recorder.requests[0].headers["Authorization"].startswith("Bearer ")

    await adapter.cleanup()
    await client.aclose()


@pytest.mark.asyncio
async def test_cloudflare_health_failure_logs_and_returns_false(monkeypatch) -> None:
    async def failing_request(*args: Any, **kwargs: Any) -> httpx.Response:
        raise httpx.TransportError("boom")

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(500))
    )

    adapter = CloudflareDNSAdapter(
        CloudflareDNSSettings(zone_id="zone", api_token=SecretStr("token")),  # type: ignore[name-defined]
        client=client,
    )
    await adapter.init()

    # monkeypatch request to raise
    adapter._client.request = failing_request  # type: ignore[assignment]
    assert await adapter.health() is False

    await adapter.cleanup()
    await client.aclose()


@pytest.mark.asyncio
async def test_request_error_raises_lifecycle_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = {"success": False, "errors": [{"message": "invalid record"}]}
        return httpx.Response(400, content=json.dumps(payload).encode("utf-8"))

    client = httpx.AsyncClient(
        base_url="https://example.com", transport=httpx.MockTransport(handler)
    )
    adapter = CloudflareDNSAdapter(
        CloudflareDNSSettings(zone_id="zone", api_token=SecretStr("token")),  # type: ignore[name-defined]
        client=client,
    )
    await adapter.init()

    with pytest.raises(LifecycleError):
        await adapter.create_record(name="demo", content="1.1.1.1")

    await adapter.cleanup()
    await client.aclose()
