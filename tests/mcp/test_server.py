"""Tests for oneiric.mcp.server — build_mcp_server() + substrate tools.

Asserts behavior the user observes:
- when auth is enabled, tools gate
- when disabled, tools raise AuthenticationRequiredError (safe default)
- T7-T12: read/write substrate tools register, render payloads, write records,
  enforce input validation
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from fastmcp import FastMCP
from mcp_common.auth.context import _principal_var
from mcp_common.auth.permissions import Permission
from mcp_common.auth.principal import Principal
from mcp_common.auth.provider import IdentityProvider
from pydantic import ValidationError

from oneiric.mcp.config import OneiricMCPAuthConfig, load_auth_config
from oneiric.mcp.health import HealthFeedState
from oneiric.mcp.server import build_mcp_server
from oneiric.mcp.store import SubstrateStore


class _StubConfig:
    """Minimal config that satisfies OneiricMCPConfig shape for tests."""

    def __init__(self, name: str = "oneiric"):
        self.name = name


class _FakeProvider(IdentityProvider):
    """IdentityProvider stub that always fails to verify (good enough for shape tests)."""

    async def verify_token(self, token: str, *, expected_audience: str | None = None) -> Any:
        raise NotImplementedError("stub")


class _FakeProcessor:
    """Scheduler processor stub — records each ``process(payload)`` call."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(payload)
        return {
            "workflow": payload["workflow"],
            "run_id": "run-xyz",
            "workflow_provider": payload.get("workflow_provider"),
            "metadata": payload.get("metadata") or {},
            "results": {"ok": True},
            "processed_at": "2026-09-16T22:00:00+00:00",
        }


def _seed_readwrite_principal() -> Any:
    """Seed a Principal with both READ+WRITE permissions for the duration of a test.

    Returns the contextvars Token so callers can ``_principal_var.reset(token)``
    after the test body to avoid leaking state across the event loop.
    """
    principal = Principal(
        issuer="test",
        subject="test-user",
        permissions=frozenset({Permission.READ, Permission.WRITE}),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        raw_claims={},
    )
    return _principal_var.set(principal)


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
        mcp = build_mcp_server(
            _StubConfig(),
            auth_config=auth_config,
            providers=providers,
            processor=_FakeProcessor(),
        )
        # fastmcp.FastMCP exposes a `.name` attribute.
        assert mcp.name == "oneiric"

    async def test_auth_enabled_gates_tools(
        self, auth_enabled: OneiricMCPAuthConfig, tmp_path
    ) -> None:
        from mcp_common.auth.exceptions import AuthenticationRequiredError

        auth_config, providers = load_auth_config(
            auth_enabled,
            provider_factories={"stub": lambda _: _FakeProvider()},
        )
        store = SubstrateStore(root=tmp_path)
        feeds = {"settings": HealthFeedState(name="settings")}
        mcp = build_mcp_server(
            _StubConfig(), auth_config=auth_config, providers=providers,
            store=store, processor=_FakeProcessor(), health_feeds=feeds,
        )
        tool = next(
            t for t in await mcp.list_tools() if t.name == "read_settings"
        )
        with pytest.raises(AuthenticationRequiredError):
            await tool.fn()

    async def test_auth_disabled_still_raises_on_unauthenticated_tool_call(
        self, auth_disabled: OneiricMCPAuthConfig, tmp_path
    ) -> None:
        """Spec §6.2 safe default: even with auth disabled, substrate
        tools refuse anonymous calls (cannot read a Principal from a
        middleware that doesn't exist)."""
        from mcp_common.auth.exceptions import AuthenticationRequiredError

        auth_config, providers = load_auth_config(auth_disabled)
        store = SubstrateStore(root=tmp_path)
        feeds = {"settings": HealthFeedState(name="settings")}
        mcp = build_mcp_server(
            _StubConfig(), auth_config=auth_config, providers=providers,
            store=store, processor=_FakeProcessor(), health_feeds=feeds,
        )
        tool = next(
            t for t in await mcp.list_tools() if t.name == "read_settings"
        )
        with pytest.raises(AuthenticationRequiredError):
            await tool.fn()


class TestSubstrateTools:
    """Tests for the 6 substrate MCP tools (T7-T12).

    The test builds a server with all 3 feeds (settings/context/progress)
    and exercises the read + write paths through the registered tools.
    Auth is disabled because we don't actually verify a token — we only
    test the safe-default ``AuthenticationRequiredError`` for read_settings
    once in TestBuildMcpServer above.
    """

    def _build(
        self, tmp_path, *, processor: _FakeProcessor | None = None
    ) -> tuple[FastMCP, SubstrateStore, dict[str, HealthFeedState]]:
        auth_config, providers = load_auth_config(OneiricMCPAuthConfig(enabled=False))
        store = SubstrateStore(root=tmp_path)
        feeds = {
            name: HealthFeedState(name=name)
            for name in ("settings", "context", "progress")
        }
        mcp = build_mcp_server(
            _StubConfig(),
            auth_config=auth_config,
            providers=providers,
            store=store,
            processor=processor or _FakeProcessor(),
            health_feeds=feeds,
        )
        return mcp, store, feeds

    async def _tool(self, mcp: FastMCP, name: str) -> Any:
        tools = await mcp.list_tools()
        matches = [t for t in tools if t.name == name]
        if not matches:
            raise AssertionError(f"tool {name!r} not registered")
        return matches[0].fn

    async def _with_principal(self, coro):
        """Run ``coro`` with a seeded READ+WRITE principal; reset after."""
        token = _seed_readwrite_principal()
        try:
            return await coro
        finally:
            _principal_var.reset(token)

    # ----- T7: read_settings -----

    async def test_all_six_tools_registered(self, tmp_path) -> None:
        mcp, _, _ = self._build(tmp_path)
        names = {t.name for t in await mcp.list_tools()}
        assert {
            "read_settings",
            "write_settings",
            "read_context",
            "write_context",
            "read_progress",
            "write_progress",
        } <= names

    async def test_read_settings_empty(self, tmp_path) -> None:
        mcp, _, _ = self._build(tmp_path)
        fn = await self._tool(mcp, "read_settings")
        result = await self._with_principal(fn())
        assert result["current"] is None
        assert result["history"] == []
        assert result["history_total"] == 0
        assert result["version"] is None

    async def test_read_settings_returns_current_and_history(self, tmp_path) -> None:
        mcp, store, _ = self._build(tmp_path)
        store.write_settings(
            SimpleNamespace(model_dump=lambda: {"version": "v1", "source": None})
        )
        fn = await self._tool(mcp, "read_settings")
        result = await self._with_principal(fn())
        assert result["current"]["payload"]["version"] == "v1"
        assert len(result["history"]) == 1

    # ----- T8: write_settings -----

    async def test_write_settings_appends_and_records(self, tmp_path) -> None:
        mcp, store, feeds = self._build(tmp_path)
        fn = await self._tool(mcp, "write_settings")
        result = await self._with_principal(
            fn(version="v1", source="test")
        )
        assert isinstance(result["record_id"], str) and result["record_id"]
        assert result["version"] == "v1"
        bucket = store.read_settings()
        assert len(bucket["history"]) == 1
        assert bucket["current"]["payload"]["version"] == "v1"
        assert feeds["settings"].cycles_total == 1
        assert feeds["settings"].entities_count == 1

    async def test_write_settings_rejects_oversize_metadata(self, tmp_path) -> None:
        mcp, _, _ = self._build(tmp_path)
        fn = await self._tool(mcp, "write_settings")
        with pytest.raises(ValidationError):
            await self._with_principal(
                fn(version="v1", metadata={"k": "x" * 1025})
            )

    # ----- T9: read_context -----

    async def test_read_context_lists_tenants(self, tmp_path) -> None:
        mcp, store, _ = self._build(tmp_path)
        store.write_context(
            "acme",
            SimpleNamespace(
                model_dump=lambda: {
                    "tenant_id": "acme",
                    "version": "v1",
                    "kind": None,
                }
            ),
        )
        store.write_context(
            "contoso",
            SimpleNamespace(
                model_dump=lambda: {
                    "tenant_id": "contoso",
                    "version": "v1",
                    "kind": None,
                }
            ),
        )
        fn = await self._tool(mcp, "read_context")
        result = await self._with_principal(fn())
        assert result["tenant_total"] == 2
        tenant_ids = {t["tenant_id"] for t in result["tenants"]}
        assert tenant_ids == {"acme", "contoso"}

    async def test_read_context_empty(self, tmp_path) -> None:
        mcp, _, _ = self._build(tmp_path)
        fn = await self._tool(mcp, "read_context")
        result = await self._with_principal(fn())
        assert result["tenant_total"] == 0
        assert result["tenants"] == []

    # ----- T10: write_context -----

    async def test_write_context_appends_to_tenant(self, tmp_path) -> None:
        mcp, store, feeds = self._build(tmp_path)
        fn = await self._tool(mcp, "write_context")
        await self._with_principal(
            fn(tenant_id="acme", version="v1")
        )
        await self._with_principal(
            fn(tenant_id="acme", version="v2", kind="blueprint")
        )
        bucket = store.read_context()
        tenant = bucket["tenants"]["acme"]
        assert len(tenant["history"]) == 2
        assert tenant["current"]["payload"]["version"] == "v2"
        assert feeds["context"].cycles_total == 2

    # ----- T11: read_progress -----

    async def test_read_progress_lists_workflows(self, tmp_path) -> None:
        mcp, store, _ = self._build(tmp_path)
        store.write_progress(
            SimpleNamespace(
                model_dump=lambda: {
                    "workflow_id": "wf-1",
                    "stage": "start",
                    "percent": 0,
                }
            )
        )
        store.write_progress(
            SimpleNamespace(
                model_dump=lambda: {
                    "workflow_id": "wf-2",
                    "stage": "start",
                    "percent": 0,
                }
            )
        )
        store.write_progress(
            SimpleNamespace(
                model_dump=lambda: {
                    "workflow_id": "wf-1",
                    "stage": "middle",
                    "percent": 50,
                }
            )
        )
        fn = await self._tool(mcp, "read_progress")
        result = await self._with_principal(fn())
        assert result["workflow_total"] == 2
        wf_ids = {wf["workflow_id"] for wf in result["workflows"]}
        assert wf_ids == {"wf-1", "wf-2"}

    # ----- T12: write_progress -----

    async def test_write_progress_appends_snapshots(self, tmp_path) -> None:
        mcp, store, feeds = self._build(tmp_path)
        fn = await self._tool(mcp, "write_progress")
        r1 = await self._with_principal(
            fn(workflow_id="wf-1", stage="start", percent=10)
        )
        r2 = await self._with_principal(
            fn(workflow_id="wf-1", stage="middle", percent=50, note="halfway")
        )
        assert isinstance(r1["record_id"], str) and r1["record_id"]
        assert r2["percent"] == 50
        bucket = store.read_progress()
        wf = bucket["workflows"]["wf-1"]
        assert len(wf["snapshots"]) == 2
        assert feeds["progress"].cycles_total == 2

    async def test_write_progress_rejects_out_of_range_percent(self, tmp_path) -> None:
        mcp, _, _ = self._build(tmp_path)
        fn = await self._tool(mcp, "write_progress")
        with pytest.raises(ValidationError):
            await self._with_principal(
                fn(workflow_id="wf-1", stage="start", percent=150)
            )


class TestSchedulerTool:
    """Tests for the ``schedule_task`` MCP tool (T13).

    Auth is disabled in the build but ``@require_auth`` still demands a
    Principal on the call (safe default — see TestBuildMcpServer). Use
    ``_seed_readwrite_principal`` via ``_with_principal`` to seed the
    WRITE permission required by the schedule_task decorator.
    """

    def _build_with_processor(
        self, tmp_path, *, processor: _FakeProcessor | None
    ) -> FastMCP:
        auth_config, providers = load_auth_config(OneiricMCPAuthConfig(enabled=False))
        store = SubstrateStore(root=tmp_path)
        feeds = {
            name: HealthFeedState(name=name)
            for name in ("settings", "context", "progress")
        }
        return build_mcp_server(
            _StubConfig(),
            auth_config=auth_config,
            providers=providers,
            store=store,
            processor=processor,
            health_feeds=feeds,
        )

    async def _tool(self, mcp: FastMCP, name: str) -> Any:
        tools = await mcp.list_tools()
        matches = [t for t in tools if t.name == name]
        if not matches:
            raise AssertionError(f"tool {name!r} not registered")
        return matches[0].fn

    async def _with_principal(self, coro):
        token = _seed_readwrite_principal()
        try:
            return await coro
        finally:
            _principal_var.reset(token)

    async def test_schedule_task_invokes_processor(self, tmp_path) -> None:
        """schedule_task should hand the assembled payload to processor.process."""
        processor = _FakeProcessor()
        mcp = self._build_with_processor(tmp_path, processor=processor)
        fn = await self._tool(mcp, "schedule_task")
        result = await self._with_principal(
            fn(workflow="my-workflow", context={"k": "v"})
        )
        assert result["run_id"] == "run-xyz"
        assert processor.calls[0]["workflow"] == "my-workflow"
        assert processor.calls[0]["context"] == {"k": "v"}

    def test_build_mcp_server_raises_when_processor_missing(self, tmp_path) -> None:
        """silent-failure-hunter #1: explicit None processor must raise at
        startup rather than silently registering a tool that would 404
        at first call."""
        auth_config, providers = load_auth_config(OneiricMCPAuthConfig(enabled=False))
        store = SubstrateStore(root=tmp_path)
        feeds = {"settings": HealthFeedState(name="settings")}
        with pytest.raises(RuntimeError, match="schedule_task requires a processor"):
            build_mcp_server(
                _StubConfig(),
                auth_config=auth_config,
                providers=providers,
                store=store,
                processor=None,
                health_feeds=feeds,
            )


class TestHealthRoute:
    """Tests for the public ``GET /health`` route (T14).

    The route is registered via ``@mcp.custom_route`` so it bypasses the
    MCP tool layer and is exempt from ``@require_auth`` — k8s/LB health
    probes can hit it without a bearer token.

    A ``_FakeProcessor`` is supplied because ``build_mcp_server`` raises
    when ``processor is None`` (T13 silent-failure-hunter guard); passing
    a processor lets the test isolate the missing-route failure mode.
    """

    async def test_health_returns_200_when_all_feeds_healthy(
        self, tmp_path
    ) -> None:
        from starlette.testclient import TestClient

        auth_config, providers = load_auth_config(OneiricMCPAuthConfig(enabled=False))
        store = SubstrateStore(root=tmp_path)
        feeds = {"settings": HealthFeedState(name="settings")}
        # A feed with cycles_total == 0 reports unhealthy (uninitialized).
        # Record one successful cycle so the feed is "healthy" by T4's
        # semantics: cycles > 0 AND errors == 0.
        feeds["settings"].record_success(entities_count=0)
        mcp = build_mcp_server(
            _StubConfig(),
            auth_config=auth_config,
            providers=providers,
            store=store,
            processor=_FakeProcessor(),
            health_feeds=feeds,
        )
        # FastMCP exposes the underlying Starlette ASGI app via .http_app().
        # custom_route() decorators add routes to that app, bypassing the
        # MCP tool layer, so the /health route is reachable via plain HTTP.
        app = mcp.http_app()
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        assert "settings" in body["routes"]
