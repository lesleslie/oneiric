"""Tests for oneiric.mcp.server — build_mcp_server() skeleton (REQ-001, REQ-002).

Asserts behavior the user observes:
- when auth is enabled, tools gate
- when disabled, tools raise AuthenticationRequiredError (safe default)
"""
from __future__ import annotations

from typing import Any

import pytest

from mcp_common.auth.provider import IdentityProvider

from oneiric.mcp.config import OneiricMCPAuthConfig, load_auth_config
from oneiric.mcp.server import build_mcp_server


class _StubConfig:
    """Minimal config that satisfies OneiricMCPConfig shape for tests."""

    def __init__(self, name: str = "oneiric"):
        self.name = name


class _FakeProvider(IdentityProvider):
    """IdentityProvider stub that always fails to verify (good enough for shape tests)."""

    async def verify_token(self, token: str, *, expected_audience: str | None = None) -> Any:
        raise NotImplementedError("stub")


@pytest.fixture
def auth_disabled() -> OneiricMCPAuthConfig:
    return OneiricMCPAuthConfig(enabled=False)


@pytest.fixture
def auth_enabled(monkeypatch: pytest.MonkeyPatch) -> OneiricMCPAuthConfig:
    # mcp-common's AuthConfig validates a non-empty secret of >=32 chars
    # when identity_providers are configured. Use the shared dev secret
    # so the validator passes; tests don't actually call verify_token.
    monkeypatch.setenv(
        "BODAI_SHARED_SECRET", "test_secret_at_least_32_characters_long_xx"
    )
    cfg = OneiricMCPAuthConfig(
        enabled=True,
        default_provider="stub",
        trusted_issuers=["acme"],
        provider_configs={"stub": {}},
    )
    return cfg


class TestBuildMcpServer:
    """Tests the contract, not the implementation.

    pr-test-analyzer flagged the original `_middleware` introspection as
    fragile (renames in FastMCP would break the tests for cosmetic reasons).
    These tests assert behavior the user observes: when auth is enabled,
    tools gate; when disabled, tools raise AuthenticationRequiredError.
    """

    def test_returns_fastmcp_instance(self, auth_disabled: OneiricMCPAuthConfig) -> None:
        auth_config, providers = load_auth_config(auth_disabled)
        mcp = build_mcp_server(_StubConfig(), auth_config=auth_config, providers=providers)
        # fastmcp.FastMCP exposes a `.name` attribute.
        assert mcp.name == "oneiric"

    async def test_auth_enabled_gates_tools(
        self, auth_enabled: OneiricMCPAuthConfig, tmp_path
    ) -> None:
        from oneiric.mcp.health import HealthFeedState
        from oneiric.mcp.store import SubstrateStore
        auth_config, providers = load_auth_config(
            auth_enabled,
            provider_factories={"stub": lambda _: _FakeProvider()},
        )
        store = SubstrateStore(root=tmp_path)
        feeds = {"settings": HealthFeedState(name="settings")}
        mcp = build_mcp_server(
            _StubConfig(), auth_config=auth_config, providers=providers,
            store=store, health_feeds=feeds,
        )
        tool = next(
            t for t in await mcp.list_tools() if t.name == "read_settings"
        )
        from mcp_common.auth.exceptions import AuthenticationRequiredError
        with pytest.raises(AuthenticationRequiredError):
            await tool.fn()

    async def test_auth_disabled_still_raises_on_unauthenticated_tool_call(
        self, auth_disabled: OneiricMCPAuthConfig, tmp_path
    ) -> None:
        """Spec §6.2 safe default: even with auth disabled, substrate
        tools refuse anonymous calls (cannot read a Principal from a
        middleware that doesn't exist)."""
        from oneiric.mcp.health import HealthFeedState
        from oneiric.mcp.store import SubstrateStore
        auth_config, providers = load_auth_config(auth_disabled)
        store = SubstrateStore(root=tmp_path)
        feeds = {"settings": HealthFeedState(name="settings")}
        mcp = build_mcp_server(
            _StubConfig(), auth_config=auth_config, providers=providers,
            store=store, health_feeds=feeds,
        )
        tool = next(
            t for t in await mcp.list_tools() if t.name == "read_settings"
        )
        from mcp_common.auth.exceptions import AuthenticationRequiredError
        with pytest.raises(AuthenticationRequiredError):
            await tool.fn()