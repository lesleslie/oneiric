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
from starlette.requests import Request
from starlette.responses import JSONResponse

if TYPE_CHECKING:  # pragma: no cover - guarded import
    from oneiric.core.config import OneiricMCPConfig
    from oneiric.mcp.health import HealthFeedState
    from oneiric.mcp.store import SubstrateStore


class _ConfigLike(Protocol):
    name: str


class _ProcessorLike(Protocol):
    """Structural type for any scheduler-side task processor.

    Production uses ``oneiric.mcp.scheduler.WorkflowTaskProcessor`` (T19
    migrated it from ``oneiric.runtime.scheduler``). The protocol lets
    tests inject a lightweight fake without inheriting from the
    production class.
    """

    async def process(self, payload: dict[str, Any]) -> dict[str, Any]: ...


def _resolve_store(store: SubstrateStore | None) -> SubstrateStore:
    """Return a usable SubstrateStore, defaulting to ~/.oneiric/substrate."""
    if store is None:
        from pathlib import Path

        from oneiric.mcp.store import SubstrateStore as _SubstrateStore

        return _SubstrateStore(root=Path.home() / ".oneiric" / "substrate")
    return store


def _resolve_processor(processor: _ProcessorLike | None) -> _ProcessorLike | None:
    """Return the scheduler processor, preserving explicit None for the
    misconfiguration guard in :func:`_register_scheduler_tools`.

    The current resolver is a pass-through; future production loaders will
    build a processor from a :class:`WorkflowBridge` when ``processor`` is
    not supplied.
    """
    return processor


def _resolve_feeds(
    feeds: dict[str, HealthFeedState] | None,
) -> dict[str, HealthFeedState]:
    """Return per-route HealthFeedState map (settings/context/progress)."""
    if feeds is None:
        from oneiric.mcp.health import HealthFeedState as _HealthFeedState

        feeds = {
            name: _HealthFeedState(name=name)
            for name in ("settings", "context", "progress")
        }
    return feeds


def _register_substrate_tools(
    mcp: FastMCP,
    *,
    store: SubstrateStore,
    feeds: dict[str, HealthFeedState],
    service_name: str,
) -> None:
    """Register the 6 substrate tools (3 reads + 3 writes).

    T7-T12 batch: read_settings / write_settings / read_context /
    write_context / read_progress / write_progress. Each tool records
    success/error on its feed and returns a dict-shaped payload.
    """
    # ----- T7: read_settings -----

    @mcp.tool()
    @require_auth(permission=Permission.READ, service_name=service_name)
    async def read_settings() -> dict[str, Any]:
        """Return the current settings record + history."""
        feed = feeds["settings"]
        try:
            raw = store.read_settings()
            current = raw.get("current")
            history = list(raw.get("history", []))
            payload_version = current["payload"]["version"] if current else None
            rendered = {
                "version": payload_version,
                "settings_version": payload_version,
                "current": current,
                "history": history,
                "history_total": len(history),
            }
        except (OSError, ValueError, TypeError):
            feed.record_error()
            raise
        feed.record_success(entities_count=1 if current else 0)
        return rendered

    # ----- T8: write_settings -----

    @mcp.tool()
    @require_auth(permission=Permission.WRITE, service_name=service_name)
    async def write_settings(
        version: str,
        source: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append a new ActiveSettings version record."""
        from oneiric.mcp.models import ActiveSettingsVersionIn

        feed = feeds["settings"]
        try:
            parsed = ActiveSettingsVersionIn(
                version=version, source=source, metadata=metadata
            )
            record = store.write_settings(parsed)
        except (OSError, ValueError, TypeError):
            feed.record_error()
            raise
        feed.record_success(entities_count=1)
        return {"record_id": record["id"], "version": parsed.version}

    # ----- T9: read_context -----

    @mcp.tool()
    @require_auth(permission=Permission.READ, service_name=service_name)
    async def read_context() -> dict[str, Any]:
        """Return the current ContextVersion per tenant + history."""
        feed = feeds["context"]
        try:
            raw = store.read_context()
            tenants_raw = raw.get("tenants", {}) or {}
            tenants: list[dict[str, Any]] = []
            for tenant_id, entry in tenants_raw.items():
                current = entry.get("current")
                history = list(entry.get("history", []))
                tenants.append(
                    {
                        "tenant_id": tenant_id,
                        "current": current,
                        "history": history,
                        "history_total": len(history),
                    }
                )
            rendered = {"tenants": tenants, "tenant_total": len(tenants)}
        except (OSError, ValueError, TypeError):
            feed.record_error()
            raise
        feed.record_success(entities_count=len(tenants))
        return rendered

    # ----- T10: write_context -----

    @mcp.tool()
    @require_auth(permission=Permission.WRITE, service_name=service_name)
    async def write_context(
        tenant_id: str,
        version: str,
        kind: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append a new ContextVersion record for the named tenant."""
        from oneiric.mcp.models import ContextVersionIn

        feed = feeds["context"]
        try:
            parsed = ContextVersionIn(
                tenant_id=tenant_id,
                version=version,
                kind=kind,
                metadata=metadata,
            )
            record = store.write_context(parsed.tenant_id, parsed)
        except (OSError, ValueError, TypeError):
            feed.record_error()
            raise
        feed.record_success(entities_count=1)
        return {
            "record_id": record["id"],
            "tenant_id": parsed.tenant_id,
            "version": parsed.version,
        }

    # ----- T11: read_progress -----

    @mcp.tool()
    @require_auth(permission=Permission.READ, service_name=service_name)
    async def read_progress() -> dict[str, Any]:
        """Return the progress snapshots per workflow."""
        feed = feeds["progress"]
        try:
            raw = store.read_progress()
            workflows_raw = raw.get("workflows", {}) or {}
            workflows: list[dict[str, Any]] = []
            for workflow_id, entry in workflows_raw.items():
                snapshots = list(entry.get("snapshots", []))
                workflows.append(
                    {
                        "workflow_id": workflow_id,
                        "snapshots": snapshots,
                        "snapshot_total": len(snapshots),
                    }
                )
            rendered = {
                "workflows": workflows,
                "workflow_total": len(workflows),
            }
        except (OSError, ValueError, TypeError):
            feed.record_error()
            raise
        feed.record_success(entities_count=len(workflows))
        return rendered

    # ----- T12: write_progress -----

    @mcp.tool()
    @require_auth(permission=Permission.WRITE, service_name=service_name)
    async def write_progress(
        workflow_id: str,
        stage: str,
        percent: int,
        note: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append a new progress snapshot for the named workflow."""
        from oneiric.mcp.models import ProgressSnapshotIn

        feed = feeds["progress"]
        try:
            parsed = ProgressSnapshotIn(
                workflow_id=workflow_id,
                stage=stage,
                percent=percent,
                note=note,
                metadata=metadata,
            )
            record = store.write_progress(parsed)
        except (OSError, ValueError, TypeError):
            feed.record_error()
            raise
        feed.record_success(entities_count=1)
        return {
            "record_id": record["id"],
            "workflow_id": parsed.workflow_id,
            "stage": parsed.stage,
            "percent": parsed.percent,
        }


def _register_scheduler_tools(
    mcp: FastMCP,
    *,
    processor: _ProcessorLike | None,
    service_name: str,
) -> None:
    """Register the ``schedule_task`` MCP tool (T13).

    The scheduler tool dispatches a workflow task by handing the assembled
    payload to ``processor.process(...)``. ``processor`` is mandatory: a
    None value is treated as a wiring error and raised loudly so the
    misconfiguration is observable at startup instead of silently surfacing
    as "tool not found" on the first call.
    """
    if processor is None:
        # silent-failure-hunter finding #1: silent skip → "tool not found"
        # at first call is unobservable at startup. Log loudly and raise
        # so the operator learns about the misconfiguration before the
        # first tool call.
        from oneiric.core.logging import get_logger

        logger = get_logger("oneiric.mcp.server")
        logger.error(
            "scheduler-processor-missing",
            extra={
                "component": "oneiric.mcp",
                "tool": "schedule_task",
                "remediation": (
                    "Wire a WorkflowTaskProcessor in the production loader "
                    "before calling build_mcp_server()."
                ),
            },
        )
        raise RuntimeError(
            "schedule_task requires a processor; none supplied. "
            "Wire a WorkflowTaskProcessor before calling build_mcp_server()."
        )

    @mcp.tool()
    @require_auth(permission=Permission.WRITE, service_name=service_name)
    async def schedule_task(
        workflow: str,
        context: dict[str, Any] | None = None,
        checkpoint: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Dispatch a workflow task to the scheduler."""
        payload: dict[str, Any] = {
            "workflow": workflow,
            "context": context or {},
            "checkpoint": checkpoint or {},
            "metadata": metadata or {},
        }
        return await processor.process(payload)


def _register_health_route(
    mcp: FastMCP, *, feeds: dict[str, HealthFeedState]
) -> None:
    """Register ``GET /health`` as a public HTTP route (REQ-004, T14).

    Uses FastMCP's ``@mcp.custom_route`` decorator which adds a route to
    the underlying Starlette app, bypassing the MCP tool layer. The route
    is therefore exempt from ``@require_auth`` and can be hit by k8s
    probes / load balancers without a bearer token.
    """

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_request: Request) -> JSONResponse:  # type: ignore[no-untyped-def]
        from oneiric.mcp.health import aggregate_health

        status_code, body = aggregate_health(feeds)
        return JSONResponse(content=body, status_code=status_code)


def build_mcp_server(
    config: _ConfigLike,
    *,
    auth_config: AuthConfig,
    providers: dict[str, IdentityProvider],
    store: SubstrateStore | None = None,
    processor: _ProcessorLike | None = None,
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
        processor: scheduler processor. None is a wiring error and
            raises ``RuntimeError`` at startup so the misconfiguration is
            observable before the first ``schedule_task`` call.
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

    resolved_store = _resolve_store(store)
    resolved_feeds = _resolve_feeds(health_feeds)
    resolved_processor = _resolve_processor(processor)
    _register_substrate_tools(
        mcp,
        store=resolved_store,
        feeds=resolved_feeds,
        service_name=auth_config.service_name,
    )
    _register_scheduler_tools(
        mcp,
        processor=resolved_processor,
        service_name=auth_config.service_name,
    )
    _register_health_route(mcp, feeds=resolved_feeds)

    return mcp


__all__ = ["build_mcp_server"]
