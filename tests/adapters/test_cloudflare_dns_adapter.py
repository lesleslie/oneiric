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
async def test_health_success_returns_true() -> None:
    """health() returns True on a successful zone GET (lines 82-83)."""
    recorder = _Recorder()
    transport = httpx.MockTransport(recorder.handler)
    client = httpx.AsyncClient(base_url="https://example.com", transport=transport)
    adapter = CloudflareDNSAdapter(
        CloudflareDNSSettings(zone_id="zone", api_token=SecretStr("token")),
        client=client,
    )
    await adapter.init()
    result = await adapter.health()
    assert result is True
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


@pytest.mark.asyncio
async def test_init_without_client_creates_internal_client() -> None:
    """init() creates its own httpx.AsyncClient when none provided (lines 55-65)."""
    adapter = CloudflareDNSAdapter(
        CloudflareDNSSettings(zone_id="zone", api_token=SecretStr("token"))
    )
    await adapter.init()
    assert adapter._client is not None
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_list_records_with_type_and_name() -> None:
    """list_records passes type and name as query params (lines 93, 95)."""
    recorder = _Recorder()
    transport = httpx.MockTransport(recorder.handler)
    client = httpx.AsyncClient(base_url="https://example.com", transport=transport)
    adapter = CloudflareDNSAdapter(
        CloudflareDNSSettings(zone_id="zone", api_token=SecretStr("token")),
        client=client,
    )
    await adapter.init()
    await adapter.list_records(record_type="A", name="demo")
    url = recorder.requests[-1].url
    assert "type=A" in str(url)
    assert "name=demo" in str(url)
    await adapter.cleanup()
    await client.aclose()


@pytest.mark.asyncio
async def test_create_record_with_proxied_and_priority() -> None:
    """create_record includes proxied and priority when set (lines 120, 122)."""
    recorder = _Recorder()
    transport = httpx.MockTransport(recorder.handler)
    client = httpx.AsyncClient(base_url="https://example.com", transport=transport)
    adapter = CloudflareDNSAdapter(
        CloudflareDNSSettings(zone_id="zone", api_token=SecretStr("token")),
        client=client,
    )
    await adapter.init()
    await adapter.create_record(
        name="mx",
        content="mail.example.com",
        record_type="MX",
        proxied=False,
        priority=10,
    )
    body = json.loads(recorder.requests[-1].content)
    assert body["proxied"] is False
    assert body["priority"] == 10
    await adapter.cleanup()
    await client.aclose()


@pytest.mark.asyncio
async def test_update_record() -> None:
    """update_record sends PATCH with all provided fields (lines 140-156)."""
    recorder = _Recorder()
    transport = httpx.MockTransport(recorder.handler)
    client = httpx.AsyncClient(base_url="https://example.com", transport=transport)
    adapter = CloudflareDNSAdapter(
        CloudflareDNSSettings(zone_id="zone", api_token=SecretStr("token")),
        client=client,
    )
    await adapter.init()
    result = await adapter.update_record(
        "rec-1", name="new", content="2.2.2.2", ttl=300, proxied=True, priority=5
    )
    assert result.get("id") == "rec-123"
    body = json.loads(recorder.requests[-1].content)
    assert body["name"] == "new" and body["ttl"] == 300
    await adapter.cleanup()
    await client.aclose()


@pytest.mark.asyncio
async def test_delete_record() -> None:
    """delete_record sends DELETE and returns success flag (lines 159-163)."""
    recorder = _Recorder()
    transport = httpx.MockTransport(recorder.handler)
    client = httpx.AsyncClient(base_url="https://example.com", transport=transport)
    adapter = CloudflareDNSAdapter(
        CloudflareDNSSettings(zone_id="zone", api_token=SecretStr("token")),
        client=client,
    )
    await adapter.init()
    result = await adapter.delete_record("rec-1")
    assert result is True
    await adapter.cleanup()
    await client.aclose()
