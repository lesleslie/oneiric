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


# ---------------------------------------------------------------------------
# Tests — coverage gaps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gcp_init_via_secretmanager_v1(monkeypatch) -> None:
    """init() creates SecretManagerServiceAsyncClient when client is None (lines 66-76)."""
    import sys
    import types
    from types import SimpleNamespace

    client = _FakeSecretClient({})
    instances: list[Any] = []

    class FakeAsyncClient:
        def __init__(self) -> None:
            instances.append(self)
            self._secrets: dict[str, str] = {}
            self.closed = False

        async def access_secret_version(self, request: dict[str, Any]) -> Any:
            raise _NotFoundError()

        async def close(self) -> None:
            self.closed = True

    fake_sm = types.ModuleType("google.cloud.secretmanager_v1")
    fake_sm.SecretManagerServiceAsyncClient = FakeAsyncClient  # type: ignore[attr-defined]
    fake_google = types.ModuleType("google")
    fake_cloud = types.ModuleType("google.cloud")
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.cloud", fake_cloud)
    monkeypatch.setitem(sys.modules, "google.cloud.secretmanager_v1", fake_sm)

    adapter = GCPSecretManagerAdapter(GCPSecretManagerSettings(project_id="demo"))
    await adapter.init()
    assert isinstance(adapter._client, FakeAsyncClient)


@pytest.mark.asyncio
async def test_gcp_init_with_credentials_file(monkeypatch, tmp_path) -> None:
    """init() uses from_service_account_file when credentials_file is set (line 71)."""
    import sys
    import types
    from pathlib import Path

    creds_file = tmp_path / "sa.json"
    creds_file.write_text("{}")
    loaded_paths: list[str] = []

    class FakeAsyncClientFromFile:
        @classmethod
        def from_service_account_file(cls, path: str) -> "FakeAsyncClientFromFile":
            loaded_paths.append(path)
            return cls()

        async def access_secret_version(self, request: dict[str, Any]) -> Any:
            raise _NotFoundError()

        async def close(self) -> None:
            pass

    class FakeAsyncClient:
        def __init__(self) -> None:
            pass

    class FakeSM:
        SecretManagerServiceAsyncClient = FakeAsyncClientFromFile

    fake_sm = types.ModuleType("google.cloud.secretmanager_v1")
    fake_sm.SecretManagerServiceAsyncClient = FakeAsyncClientFromFile  # type: ignore[attr-defined]
    fake_google = types.ModuleType("google")
    fake_cloud = types.ModuleType("google.cloud")
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.cloud", fake_cloud)
    monkeypatch.setitem(sys.modules, "google.cloud.secretmanager_v1", fake_sm)

    adapter = GCPSecretManagerAdapter(
        GCPSecretManagerSettings(project_id="demo", credentials_file=creds_file)
    )
    await adapter.init()
    assert isinstance(adapter._client, FakeAsyncClientFromFile)
    assert loaded_paths == [str(creds_file)]


@pytest.mark.asyncio
async def test_gcp_invalidate_cache() -> None:
    """invalidate_cache() clears the cache (lines 98-100)."""
    client = _FakeSecretClient({"KEY": "val"})
    adapter = GCPSecretManagerAdapter(
        GCPSecretManagerSettings(project_id="demo"), client=client
    )
    await adapter.init()
    await adapter.get_secret("KEY")
    assert adapter._cache
    await adapter.invalidate_cache()
    assert adapter._cache == {}


@pytest.mark.asyncio
async def test_gcp_get_secret_reraises_when_not_allow_missing() -> None:
    """get_secret re-raises when allow_missing=False and exception occurs (line 119)."""
    client = _FakeSecretClient({})
    adapter = GCPSecretManagerAdapter(
        GCPSecretManagerSettings(project_id="demo"), client=client
    )
    await adapter.init()
    with pytest.raises(_NotFoundError):
        await adapter.get_secret("MISSING", allow_missing=False)


def test_gcp_ensure_client_raises_when_not_initialized() -> None:
    """_ensure_client raises LifecycleError when client is None (line 130)."""
    from oneiric.core.lifecycle import LifecycleError

    adapter = GCPSecretManagerAdapter(GCPSecretManagerSettings(project_id="demo"))
    with pytest.raises(LifecycleError, match="gcp-secret-client-not-initialized"):
        adapter._ensure_client()


def test_gcp_is_not_found_via_message_string() -> None:
    """_is_not_found returns True when exc.args[0] contains NOT_FOUND (lines 137-140)."""
    adapter = GCPSecretManagerAdapter(GCPSecretManagerSettings(project_id="demo"))
    assert adapter._is_not_found(Exception("NOT_FOUND: secret does not exist")) is True
    assert adapter._is_not_found(Exception("404 secret not found")) is True
    assert adapter._is_not_found(Exception(404)) is False  # non-string → line 140


@pytest.mark.asyncio
async def test_gcp_get_cached_evicts_expired_entry() -> None:
    """_get_cached returns None and evicts entry when TTL has expired (lines 150-151)."""
    import time

    client = _FakeSecretClient({"KEY": "v"})
    adapter = GCPSecretManagerAdapter(
        GCPSecretManagerSettings(project_id="demo", cache_ttl_seconds=1),
        client=client,
    )
    await adapter.init()
    await adapter.get_secret("KEY")
    key = adapter._cache_key("KEY", None)
    # Manually expire the cache entry
    adapter._cache[key] = ("v", time.monotonic() - 1)
    result = await adapter._get_cached("KEY", None)
    assert result is None
    assert key not in adapter._cache
