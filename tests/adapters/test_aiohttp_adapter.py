from __future__ import annotations

from typing import Any

import pytest

from oneiric.adapters.http.aiohttp import AioHTTPAdapter
from oneiric.adapters.http.httpx import HTTPClientSettings
from oneiric.core.lifecycle import LifecycleError


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


# ---------------------------------------------------------------------------
# Tests — init creates session when none provided
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_init_creates_session() -> None:
    import aiohttp

    settings = HTTPClientSettings(timeout=5.0)
    adapter = AioHTTPAdapter(settings)
    await adapter.init()
    assert adapter._session is not None
    assert adapter._owns_session is True
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_init_with_base_url_creates_session() -> None:
    import aiohttp

    settings = HTTPClientSettings(
        base_url="http://localhost:9999",
        headers={"X-Custom": "val"},
        timeout=3.0,
    )
    adapter = AioHTTPAdapter(settings)
    await adapter.init()
    assert adapter._session is not None
    await adapter.cleanup()


# ---------------------------------------------------------------------------
# Tests — health without base_url returns True immediately
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_no_base_url() -> None:
    session = DummySession()
    settings = HTTPClientSettings()  # no base_url
    adapter = AioHTTPAdapter(settings, session=session)
    await adapter.init()
    assert await adapter.health() is True
    await adapter.cleanup()


# ---------------------------------------------------------------------------
# Tests — health with 5xx response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_server_error() -> None:
    class ErrorSession(DummySession):
        async def request(self, method: str, url: str, **kwargs: Any) -> DummyResponse:
            return DummyResponse(status=503)

    session = ErrorSession()
    settings = HTTPClientSettings(base_url="https://svc.local")
    adapter = AioHTTPAdapter(settings, session=session)
    await adapter.init()
    assert await adapter.health() is False
    await adapter.cleanup()


# ---------------------------------------------------------------------------
# Tests — cleanup closes session when owns_session=True
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_closes_owned_session() -> None:
    import aiohttp

    settings = HTTPClientSettings()
    adapter = AioHTTPAdapter(settings)
    await adapter.init()
    assert adapter._owns_session is True
    await adapter.cleanup()
    assert adapter._session is None


@pytest.mark.asyncio
async def test_cleanup_does_not_close_injected_session() -> None:
    session = DummySession()
    adapter = AioHTTPAdapter(session=session)
    await adapter.init()
    await adapter.cleanup()
    assert not session.closed  # _owns_session=False → not closed


# ---------------------------------------------------------------------------
# Tests — _ensure_session raises when no session
# ---------------------------------------------------------------------------


def test_ensure_session_raises() -> None:
    adapter = AioHTTPAdapter()
    with pytest.raises(LifecycleError, match="aiohttp-session-not-initialized"):
        adapter._ensure_session()


# ---------------------------------------------------------------------------
# Tests — _resolve_url
# ---------------------------------------------------------------------------


def test_resolve_url_relative_with_base() -> None:
    settings = HTTPClientSettings(base_url="https://api.example.com")
    adapter = AioHTTPAdapter(settings)
    assert adapter._resolve_url("/users") == "https://api.example.com/users"


def test_resolve_url_absolute_ignores_base() -> None:
    settings = HTTPClientSettings(base_url="https://api.example.com")
    adapter = AioHTTPAdapter(settings)
    result = adapter._resolve_url("https://other.com/path")
    assert result == "https://other.com/path"


def test_resolve_url_no_base() -> None:
    adapter = AioHTTPAdapter()
    assert adapter._resolve_url("/path") == "/path"


# ---------------------------------------------------------------------------
# Tests — request GET helper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_calls_request() -> None:
    session = DummySession()
    adapter = AioHTTPAdapter(session=session)
    await adapter.init()
    resp = await adapter.get("/ping")
    assert resp.status == 200


# ---------------------------------------------------------------------------
# Tests — request TimeoutError propagates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_timeout_propagates() -> None:
    class TimeoutSession(DummySession):
        async def request(self, method: str, url: str, **kwargs: Any) -> DummyResponse:
            raise TimeoutError("timed out")

    session = TimeoutSession()
    adapter = AioHTTPAdapter(session=session)
    await adapter.init()
    with pytest.raises(TimeoutError):
        await adapter.request("GET", "/slow")


# ---------------------------------------------------------------------------
# Tests — request generic exception propagates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_generic_exception_propagates() -> None:
    class BoomSession(DummySession):
        async def request(self, method: str, url: str, **kwargs: Any) -> DummyResponse:
            raise ConnectionError("refused")

    session = BoomSession()
    adapter = AioHTTPAdapter(session=session)
    await adapter.init()
    with pytest.raises(ConnectionError):
        await adapter.request("GET", "/boom")


# ---------------------------------------------------------------------------
# Tests — aiohttp not installed guard
# ---------------------------------------------------------------------------


def test_init_raises_when_aiohttp_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Constructor raises LifecycleError when aiohttp is not installed."""
    monkeypatch.setattr("oneiric.adapters.http.aiohttp._AIOHTTP_AVAILABLE", False)
    with pytest.raises(LifecycleError, match="aiohttp-not-installed"):
        AioHTTPAdapter()
