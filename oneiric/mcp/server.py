"""Oneiric FastMCP server — substrate state + workflow task scheduling.

REQ-001 / REQ-002: single FastMCP server replaces the legacy aiohttp
SubstrateHTTPServer and SchedulerHTTPServer. Auth is delegated to
mcp-common's BearerTokenMiddleware; this module only declares the
tool surface and per-tool permissions.

Public entrypoint: build_mcp_server(config, *, auth_config, providers,
store=None, processor=None) -> fastmcp.FastMCP.

The CLI (``oneiric mcp``) wires the auth config + store + processor
into this entrypoint at startup.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from fastmcp import FastMCP
from mcp_common.auth.config import AuthConfig
from mcp_common.auth.decorator import require_auth
from mcp_common.auth.middleware import BearerTokenMiddleware
from mcp_common.auth.permissions import Permission
from mcp_common.auth.provider import IdentityProvider

if TYPE_CHECKING:  # pragma: no cover - guarded import
    from oneiric.core.config import OneiricMCPConfig
    from oneiric.mcp.health import HealthFeedState
    from oneiric.mcp.store import SubstrateStore
    from oneiric.runtime.scheduler import WorkflowTaskProcessor


class _ConfigLike(Protocol):
    name: str


def build_mcp_server(
    config: _ConfigLike,
    *,
    auth_config: AuthConfig,
    providers: dict[str, IdentityProvider],
    store: SubstrateStore | None = None,
    processor: WorkflowTaskProcessor | None = None,
    health_feeds: dict[str, HealthFeedState] | None = None,
) -> FastMCP:
    """Construct the FastMCP server with the substrate + scheduler tool surface.

    Args:
        config: OneiricMCPConfig (or any object with a .name attribute).
        auth_config: mcp-common AuthConfig. When auth_config.enabled is
            False, no BearerTokenMiddleware is installed; tools with
            @require_auth still raise AuthenticationRequiredError at
            call time (safe default — substrate tools refuse anonymous
            calls).
        providers: provider name -> IdentityProvider map. Empty when
            auth_config.enabled is False.
        store: SubstrateStore instance. Created lazily here if not
            supplied.
        processor: WorkflowTaskProcessor instance. Created lazily here
            if not supplied.
        health_feeds: injectable per-route HealthFeedState map for
            the /health route. Created lazily here if not supplied.
    """
    mcp = FastMCP(name=config.name)

    if auth_config.enabled and providers:
        mcp.add_middleware(
            BearerTokenMiddleware(
                auth_config=auth_config,
                providers=providers,
            )
        )

    # Minimal tool surface so the auth wiring is verifiable end-to-end.
    # T7+ expands with full read/write substrate + scheduler tools. The
    # closure captures ``store`` so the tool reads from the configured
    # substrate; if no store is supplied, fall back to the default root.
    if store is None:
        from oneiric.mcp.store import SubstrateStore
        store = SubstrateStore()

    @require_auth(Permission.READ, service_name=auth_config.service_name)
    async def read_settings() -> dict[str, Any]:
        """Return the current settings bucket from the substrate."""
        return store.read_settings()

    mcp.tool()(read_settings)

    return mcp


__all__ = ["build_mcp_server"]