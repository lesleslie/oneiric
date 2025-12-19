"""Tests for SecretsHook caching + invalidation."""

from __future__ import annotations

import asyncio

import pytest

from oneiric.core.config import SecretsConfig, SecretsHook


class DummySecretsProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_secret(self, secret_id: str) -> str:
        self.calls.append(secret_id)
        return f"value-{secret_id}-{len(self.calls)}"


class DummyCachingProvider(DummySecretsProvider):
    def __init__(self) -> None:
        super().__init__()
        self.invalidated = False

    async def invalidate_cache(self) -> None:
        self.invalidated = True


class DummyLifecycle:
    def __init__(self, provider) -> None:
        self.provider = provider
        self.instance = None

    def get_instance(self, domain: str, key: str):
        return self.instance

    async def activate(self, domain: str, key: str, provider: str):
        self.instance = self.provider
        return self.instance


@pytest.mark.asyncio
async def test_secrets_cache_hits() -> None:
    provider = DummySecretsProvider()
    lifecycle = DummyLifecycle(provider)
    hook = SecretsHook(
        lifecycle,
        SecretsConfig(
            domain="adapter", key="secrets", provider="env", cache_ttl_seconds=1.0
        ),
    )

    assert await hook.get("api-key") == "value-api-key-1"
    assert await hook.get("api-key") == "value-api-key-1"
    assert provider.calls == ["api-key"]


@pytest.mark.asyncio
async def test_secrets_cache_invalidate_specific_keys() -> None:
    provider = DummySecretsProvider()
    lifecycle = DummyLifecycle(provider)
    hook = SecretsHook(
        lifecycle,
        SecretsConfig(
            domain="adapter", key="secrets", provider="env", cache_ttl_seconds=1.0
        ),
    )

    await hook.get("token")
    assert hook.invalidate(keys=["token"]) == 1
    await hook.get("token")
    assert provider.calls == ["token", "token"]


@pytest.mark.asyncio
async def test_secrets_cache_expires() -> None:
    provider = DummySecretsProvider()
    lifecycle = DummyLifecycle(provider)
    hook = SecretsHook(
        lifecycle,
        SecretsConfig(
            domain="adapter", key="secrets", provider="env", cache_ttl_seconds=0.01
        ),
    )

    await hook.get("short-lived")
    await asyncio.sleep(0.02)
    await hook.get("short-lived")
    assert provider.calls == ["short-lived", "short-lived"]


@pytest.mark.asyncio
async def test_secrets_cache_disabled_when_ttl_zero() -> None:
    provider = DummySecretsProvider()
    lifecycle = DummyLifecycle(provider)
    hook = SecretsHook(
        lifecycle,
        SecretsConfig(
            domain="adapter", key="secrets", provider="env", cache_ttl_seconds=0
        ),
    )

    await hook.get("no-cache")
    await hook.get("no-cache")
    assert provider.calls == ["no-cache", "no-cache"]
    assert hook.invalidate(keys=["no-cache"]) == 0


@pytest.mark.asyncio
async def test_secrets_prefetch_sets_flag() -> None:
    provider = DummySecretsProvider()
    lifecycle = DummyLifecycle(provider)
    hook = SecretsHook(
        lifecycle,
        SecretsConfig(
            domain="adapter", key="secrets", provider="env", cache_ttl_seconds=1.0
        ),
    )

    assert hook.prefetched is False
    ready = await hook.prefetch()
    assert ready is True
    assert hook.prefetched is True


@pytest.mark.asyncio
async def test_secrets_prefetch_handles_missing_provider() -> None:
    lifecycle = DummyLifecycle(None)
    hook = SecretsHook(
        lifecycle,
        SecretsConfig(
            domain="adapter",
            key="secrets",
            provider=None,
            inline={"token": "inline"},
        ),
    )

    ready = await hook.prefetch()
    assert ready is False
    assert hook.prefetched is False


@pytest.mark.asyncio
async def test_secrets_rotate_invalidates_provider_cache() -> None:
    provider = DummyCachingProvider()
    lifecycle = DummyLifecycle(provider)
    hook = SecretsHook(
        lifecycle,
        SecretsConfig(
            domain="adapter", key="secrets", provider="env", cache_ttl_seconds=1.0
        ),
    )

    await hook.get("token")
    removed = await hook.rotate(keys=["token"])

    assert removed == 1
    assert provider.invalidated is True
