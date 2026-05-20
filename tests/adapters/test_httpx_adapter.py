from __future__ import annotations

import pytest
import httpx

from oneiric.adapters.http.httpx import HTTPClientAdapter, HTTPClientSettings
from oneiric.core.lifecycle import LifecycleError


# ---------------------------------------------------------------------------
# Tests — init
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_init_minimal() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(200))
    adapter = HTTPClientAdapter(transport=transport)
    await adapter.init()
    assert adapter._client is not None
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_init_with_base_url_and_headers() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(200))
    settings = HTTPClientSettings(
        base_url="https://api.example.com",
        headers={"Authorization": "Bearer tok"},
        timeout=5.0,
    )
    adapter = HTTPClientAdapter(settings=settings, transport=transport)
    await adapter.init()
    assert adapter._client is not None
    await adapter.cleanup()


# ---------------------------------------------------------------------------
# Tests — health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_no_client() -> None:
    adapter = HTTPClientAdapter()
    assert await adapter.health() is False


@pytest.mark.asyncio
async def test_health_no_base_url() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(200))
    adapter = HTTPClientAdapter(transport=transport)
    await adapter.init()
    assert await adapter.health() is True
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_health_base_url_ok() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(200))
    settings = HTTPClientSettings(base_url="https://svc.local", healthcheck_path="/up")
    adapter = HTTPClientAdapter(settings=settings, transport=transport)
    await adapter.init()
    assert await adapter.health() is True
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_health_base_url_server_error() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(503))
    settings = HTTPClientSettings(base_url="https://svc.local")
    adapter = HTTPClientAdapter(settings=settings, transport=transport)
    await adapter.init()
    assert await adapter.health() is False
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_health_http_error() -> None:
    def raise_error(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=req)

    transport = httpx.MockTransport(raise_error)
    settings = HTTPClientSettings(base_url="https://svc.local")
    adapter = HTTPClientAdapter(settings=settings, transport=transport)
    await adapter.init()
    assert await adapter.health() is False
    await adapter.cleanup()


# ---------------------------------------------------------------------------
# Tests — cleanup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_no_client() -> None:
    adapter = HTTPClientAdapter()
    await adapter.cleanup()  # should not raise


@pytest.mark.asyncio
async def test_cleanup_closes_client() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(200))
    adapter = HTTPClientAdapter(transport=transport)
    await adapter.init()
    await adapter.cleanup()
    assert adapter._client is None


@pytest.mark.asyncio
async def test_cleanup_sync_close_fallback() -> None:
    closed: list[bool] = []

    class SyncOnlyClient:
        def close(self) -> None:
            closed.append(True)

    adapter = HTTPClientAdapter()
    adapter._client = SyncOnlyClient()
    await adapter.cleanup()
    assert closed == [True]
    assert adapter._client is None


# ---------------------------------------------------------------------------
# Tests — request / get / post
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_method() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(201, json={"id": 1}))
    adapter = HTTPClientAdapter(transport=transport)
    await adapter.init()

    resp = await adapter.request("GET", "https://api.example.com/items")
    assert resp.status_code == 201
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_get_method() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(200, text="ok"))
    adapter = HTTPClientAdapter(transport=transport)
    await adapter.init()

    resp = await adapter.get("https://api.example.com/status")
    assert resp.status_code == 200
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_post_method() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(201))
    adapter = HTTPClientAdapter(transport=transport)
    await adapter.init()

    resp = await adapter.post("https://api.example.com/items", json={"name": "x"})
    assert resp.status_code == 201
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_request_with_headers() -> None:
    received: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        received.append(req)
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    adapter = HTTPClientAdapter(transport=transport)
    await adapter.init()

    await adapter.request("GET", "https://api.example.com/", headers={"X-Test": "1"})
    assert len(received) == 1
    await adapter.cleanup()


# ---------------------------------------------------------------------------
# Tests — _ensure_client
# ---------------------------------------------------------------------------


def test_ensure_client_raises_when_none() -> None:
    adapter = HTTPClientAdapter()
    with pytest.raises(LifecycleError, match="httpx-client-not-initialized"):
        adapter._ensure_client()


# ---------------------------------------------------------------------------
# Tests — _AsyncClientShim
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_client_shim_request() -> None:
    from oneiric.adapters.http.httpx import _AsyncClientShim

    transport = httpx.MockTransport(lambda req: httpx.Response(200))
    shim = _AsyncClientShim(
        base_url=None,
        timeout=5.0,
        verify=True,
        headers=None,
        transport=transport,
    )
    resp = await shim.request("GET", "https://example.com/")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_async_client_shim_get_post() -> None:
    from oneiric.adapters.http.httpx import _AsyncClientShim

    transport = httpx.MockTransport(lambda req: httpx.Response(200))
    shim = _AsyncClientShim(
        base_url=None,
        timeout=5.0,
        verify=True,
        headers={"X-H": "v"},
        transport=transport,
    )
    resp = await shim.get("https://example.com/a")
    assert resp.status_code == 200

    resp2 = await shim.post("https://example.com/b")
    assert resp2.status_code == 200
    await shim.aclose()


# ---------------------------------------------------------------------------
# Tests — coverage gaps
# ---------------------------------------------------------------------------


def test_async_client_shim_with_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """_AsyncClientShim sets client_kwargs['url'] when base_url is provided (line 51)."""
    from oneiric.adapters.http.httpx import _AsyncClientShim

    captured: list[dict] = []

    class _FakeClient:
        def __init__(self, **kwargs: object) -> None:
            captured.append(dict(kwargs))

        def close(self) -> None:
            pass

    monkeypatch.setattr("oneiric.adapters.http.httpx.httpx.Client", _FakeClient)
    _AsyncClientShim(
        base_url="https://example.com",
        timeout=5.0,
        verify=True,
        headers=None,
        transport=None,
    )
    assert captured[0].get("url") == "https://example.com"


@pytest.mark.asyncio
async def test_request_fallback_without_caller() -> None:
    """_request falls back to client.request() when caller=None (line 200)."""
    transport = httpx.MockTransport(lambda req: httpx.Response(200))
    adapter = HTTPClientAdapter(transport=transport)
    await adapter.init()
    resp = await adapter._request("GET", "https://example.com/", caller=None)
    assert resp.status_code == 200
    await adapter.cleanup()


def test_httpx_mixin_ensure_client_raises_when_no_client() -> None:
    """HTTPXClientMixin._ensure_client raises LifecycleError when _client is None (line 17)."""
    from oneiric.adapters.httpx_base import HTTPXClientMixin
    from oneiric.core.lifecycle import LifecycleError

    mixin = HTTPXClientMixin()
    with pytest.raises(LifecycleError, match="no-client"):
        mixin._ensure_client("no-client")


