from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from oneiric.adapters.secrets.gcp import (
    GCPSecretManagerAdapter,
    GCPSecretManagerSettings,
)


class _NotFoundError(Exception):
    def __init__(self) -> None:
        self.code = SimpleNamespace(name="NOT_FOUND")


class _FakeSecretClient:
    def __init__(self, secrets: dict[str, str]) -> None:
        self._secrets = secrets
        self.closed = False

    async def access_secret_version(self, request: dict[str, Any]) -> Any:
        name = request["name"]
        secret_name = name.split("/secrets/")[1].split("/")[0]
        if secret_name not in self._secrets:
            raise _NotFoundError()
        payload = SimpleNamespace(data=self._secrets[secret_name].encode("utf-8"))
        return SimpleNamespace(payload=payload)

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_gcp_secret_manager_adapter_fetches_and_caches() -> None:
    client = _FakeSecretClient({"API_KEY": "super-secret"})
    settings = GCPSecretManagerSettings(project_id="demo")
    adapter = GCPSecretManagerAdapter(settings, client=client)
    await adapter.init()
    value = await adapter.get_secret("API_KEY")
    assert value == "super-secret"
    value2 = await adapter.get_secret("API_KEY")
    assert value2 == value  # cached
    missing = await adapter.get_secret("MISSING", allow_missing=True)
    assert missing is None
    assert await adapter.health()
    await adapter.cleanup()
    assert client.closed
