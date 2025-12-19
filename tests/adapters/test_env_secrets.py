from __future__ import annotations

import pytest

from oneiric.adapters import register_builtin_adapters
from oneiric.adapters.bridge import AdapterBridge
from oneiric.adapters.secrets.env import EnvSecretAdapter, EnvSecretSettings
from oneiric.core.config import LayerSettings
from oneiric.core.lifecycle import LifecycleManager
from oneiric.core.resolution import Resolver


@pytest.mark.asyncio
async def test_env_secret_adapter_reads_values(monkeypatch) -> None:
    monkeypatch.setenv("ONEIRIC_SECRET_API_KEY", "secret-123")
    adapter = EnvSecretAdapter(EnvSecretSettings())
    await adapter.init()
    assert await adapter.get_secret("api_key") == "secret-123"
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_env_secret_adapter_health_checks_required(monkeypatch) -> None:
    monkeypatch.delenv("ONEIRIC_SECRET_MISSING", raising=False)
    adapter = EnvSecretAdapter(EnvSecretSettings(required_keys=["missing"]))
    await adapter.init()
    assert await adapter.health() is False
    monkeypatch.setenv("ONEIRIC_SECRET_MISSING", "value")
    assert await adapter.health() is True
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_env_secret_adapter_via_bridge(monkeypatch) -> None:
    monkeypatch.setenv("ONEIRIC_SECRET_API_TOKEN", "super-secret")
    resolver = Resolver()
    register_builtin_adapters(resolver)
    lifecycle = LifecycleManager(resolver)
    bridge = AdapterBridge(
        resolver,
        lifecycle,
        LayerSettings(selections={"secrets": "env"}),
    )
    handle = await bridge.use("secrets")
    assert handle.provider == "env"
    assert await handle.instance.get_secret("api_token") == "super-secret"
