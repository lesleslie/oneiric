from __future__ import annotations

from typing import Any

import pytest

from oneiric.adapters.secrets.infisical import (
    InfisicalSecretAdapter,
    InfisicalSecretSettings,
)


class _DummyResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"error {self.status_code}")


class _DummyHTTPClient:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.closed = False

    async def post(
        self, url: str, json: dict[str, Any], headers: dict[str, str]
    ) -> _DummyResponse:
        self.requests.append({"url": url, "json": json, "headers": headers})
        if json["secretName"] == "missing":
            return _DummyResponse(404, {})
        return _DummyResponse(200, {"secretValue": f"value:{json['secretName']}"})

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_infisical_adapter_fetches_and_caches_secrets() -> None:
    client = _DummyHTTPClient()
    settings = InfisicalSecretSettings(
        base_url="https://example.com",
        token="token",
        environment="dev",
        secret_path="/",
        cache_ttl_seconds=60,
    )
    adapter = InfisicalSecretAdapter(settings, http_client=client)
    await adapter.init()
    value = await adapter.get_secret("API_KEY")
    assert value == "value:API_KEY"
    value2 = await adapter.get_secret("API_KEY")
    assert value2 == value
    assert len(client.requests) == 1  # cached
    missing = await adapter.get_secret("missing", allow_missing=True)
    assert missing is None
    await adapter.cleanup()


# ---------------------------------------------------------------------------
# Tests — coverage gaps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_infisical_init_creates_http_client() -> None:
    """init() creates httpx.AsyncClient when none provided (line 65)."""
    adapter = InfisicalSecretAdapter(
        InfisicalSecretSettings(
            base_url="https://example.com",
            token="tok",
            environment="dev",
        )
    )
    await adapter.init()
    assert adapter._http_client is not None
    assert adapter._owns_client is True
    await adapter.cleanup()
    assert adapter._http_client is None


@pytest.mark.asyncio
async def test_infisical_health_returns_true() -> None:
    """health() calls get_secret and returns True (lines 69-73)."""
    client = _DummyHTTPClient()
    adapter = InfisicalSecretAdapter(
        InfisicalSecretSettings(
            base_url="https://example.com", token="tok", environment="dev"
        ),
        http_client=client,
    )
    await adapter.init()
    assert await adapter.health() is True


@pytest.mark.asyncio
async def test_infisical_cleanup_closes_owned_client() -> None:
    """cleanup() calls aclose() on owned client (line 80)."""
    client = _DummyHTTPClient()
    adapter = InfisicalSecretAdapter(
        InfisicalSecretSettings(
            base_url="https://example.com", token="tok", environment="dev"
        ),
        http_client=client,
    )
    await adapter.init()
    adapter._owns_client = True
    await adapter.cleanup()
    assert client.closed is True
    assert adapter._http_client is None


@pytest.mark.asyncio
async def test_infisical_invalidate_cache() -> None:
    """invalidate_cache() clears the cache (lines 86-88)."""
    client = _DummyHTTPClient()
    adapter = InfisicalSecretAdapter(
        InfisicalSecretSettings(
            base_url="https://example.com", token="tok", environment="dev"
        ),
        http_client=client,
    )
    await adapter.init()
    await adapter.get_secret("API_KEY")
    assert adapter._cache
    await adapter.invalidate_cache()
    assert adapter._cache == {}


@pytest.mark.asyncio
async def test_infisical_project_id_in_payload() -> None:
    """get_secret includes projectId in payload when project_id is set (line 102)."""
    captured: list[dict] = []

    class CapturingClient(_DummyHTTPClient):
        async def post(self, url: str, json: dict, headers: dict) -> _DummyResponse:
            captured.append(json)
            return _DummyResponse(200, {"secretValue": "v"})

    adapter = InfisicalSecretAdapter(
        InfisicalSecretSettings(
            base_url="https://example.com",
            token="tok",
            environment="dev",
            project_id="proj-123",
        ),
        http_client=CapturingClient(),
    )
    await adapter.init()
    await adapter.get_secret("KEY")
    assert captured[0]["projectId"] == "proj-123"


@pytest.mark.asyncio
async def test_infisical_get_secret_missing_value_raises() -> None:
    """get_secret raises LifecycleError when secretValue is None and not allow_missing (line 111)."""
    from oneiric.core.lifecycle import LifecycleError

    class NullValueClient(_DummyHTTPClient):
        async def post(self, url: str, json: dict, headers: dict) -> _DummyResponse:
            return _DummyResponse(200, {})  # no secretValue key

    adapter = InfisicalSecretAdapter(
        InfisicalSecretSettings(
            base_url="https://example.com", token="tok", environment="dev"
        ),
        http_client=NullValueClient(),
    )
    await adapter.init()
    with pytest.raises(LifecycleError, match="secret-value-missing"):
        await adapter.get_secret("KEY", allow_missing=False)


@pytest.mark.asyncio
async def test_infisical_get_cached_evicts_expired_entry() -> None:
    """_get_cached returns None and evicts entry when TTL has expired (lines 123-124)."""
    import time

    client = _DummyHTTPClient()
    adapter = InfisicalSecretAdapter(
        InfisicalSecretSettings(
            base_url="https://example.com",
            token="tok",
            environment="dev",
            cache_ttl_seconds=5,
        ),
        http_client=client,
    )
    await adapter.init()
    await adapter.get_secret("KEY")
    # Manually expire the entry
    adapter._cache["KEY"] = ("v", time.monotonic() - 1)
    result = await adapter._get_cached("KEY")
    assert result is None
    assert "KEY" not in adapter._cache


def test_infisical_ensure_client_raises_when_not_initialized() -> None:
    """_ensure_client raises LifecycleError when http_client is None (line 134)."""
    from oneiric.core.lifecycle import LifecycleError

    adapter = InfisicalSecretAdapter(
        InfisicalSecretSettings(
            base_url="https://example.com", token="tok", environment="dev"
        )
    )
    with pytest.raises(LifecycleError, match="infisical-http-client-not-initialized"):
        adapter._ensure_client()
