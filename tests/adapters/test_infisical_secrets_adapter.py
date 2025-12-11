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
