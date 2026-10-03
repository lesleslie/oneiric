---
title: Oneiric FastMCP Pivot + Auth Integration
status: draft
role: canonical
date: 2026-09-16
last_reviewed: 2026-09-18
topic: mcp-design
created: 2026-09-16
owner: les
priority: high
related:
  - docs/plans/2026-09-16-dhara-mcp-retirement-plan.md
  - docs/superpowers/specs/2026-09-14-dhara-mcp-decomposition-design.md
---

# Oneiric FastMCP Pivot + Auth Integration

## 1. Summary

Migrate oneiric's two hand-rolled **aiohttp** HTTP servers (`SubstrateHTTPServer` and `SchedulerHTTPServer`) to a single **FastMCP**-based MCP server. This aligns oneiric with the Bodai convention every other Bodai MCP server follows, and unlocks `mcp-common`'s existing `BearerTokenMiddleware` for auth — eliminating the need for new auth code in oneiric.

The migration is paired with the security-review findings flagged against the current aiohttp servers (default bind `0.0.0.0`, unbounded POST bodies, `asyncio.Lock` inside `asyncio.to_thread`, production-code `assert`). Most of those findings disappear once the aiohttp servers are gone; the surviving binding-default concern is handled by BearerTokenMiddleware refusing to start without a configured `AuthConfig`.

## 2. Context & Motivation

### 2.1 Why this pivot exists

During Phase 8 of the **dhara MCP retirement plan**, oneiric ported three pieces of dhara substrate functionality (`settings.json`, `context.json`, `progress.json`) plus the workflow task scheduler. The port landed as two standalone aiohttp HTTP servers rather than as MCP tools on a FastMCP server. This deviated from the Bodai convention — every other Bodai MCP server (mahavishnu, akosha, session-buddy, crackerjack) is built on FastMCP.

The deviation created three concrete problems:

1. **Auth gap.** FastMCP servers get `BearerTokenMiddleware` from `mcp-common` for free. aiohttp servers would need bespoke auth code, duplicating logic that already exists in `mcp-common.auth.middleware`.
2. **Code duplication.** The substrate routes re-implement request/response shapes that already exist as MCP tool patterns elsewhere in the Bodai ecosystem.
3. **Operator confusion.** `oneiric http start|stop|status|health` is non-standard. The expected CLI surface is `oneiric mcp start|stop|status|health` to match every other server.

### 2.2 Confirmed context (from brainstorming)

| Decision | Choice |
|---|---|
| Deployment posture | Internal / trusted-network only (firewall is the primary gate) |
| Auth posture | Opt-in shared bearer token (off by default; enabled via `AuthConfig`) |
| Auth source | `mcp-common.auth.middleware.BearerTokenMiddleware` (already exists, no changes needed) |
| Auth scope | `/health` always public; `substrate.*` reads + writes both auth-gated |
| Configuration surface | Settings file (`settings/oneiric.yaml`) with env-var override, per oneiric's layered-config convention |
| Auth providers | mcp-common's `IdentityProvider` interface (JWT, etc.); operator picks at startup |
| CLI rename | `oneiric http` → `oneiric mcp` (no deprecation shim; project policy) |

## 3. Goals

- **G1**: A single FastMCP server in `oneiric/mcp/server.py` exposes all substrate + scheduler functionality as MCP tools.
- **G2**: `BearerTokenMiddleware` from `mcp-common` is wired with `AuthConfig` read from oneiric's settings + env-var layer.
- **G3**: `/health` is a public HTTP route exempt from auth (k8s liveness probes, load-balancer health checks).
- **G4**: All substrate reads + writes require a valid Bearer token matching `AuthConfig.trusted_issuers`.
- **G5**: `oneiric mcp start|stop|status|health` CLI surface replaces the current `oneiric http` commands.
- **G6**: The two aiohttp HTTP servers are removed in the same release (no shims).
- **G7**: Per-tool RBAC via `@require_auth(permission=...)` decorator using `mcp-common.auth.permissions.Permission` (the existing 4-value enum: `READ`, `WRITE`, `DELETE`, `ADMIN`). Substrate reads map to `Permission.READ`; substrate writes + `schedule_task` map to `Permission.WRITE`. Coarse granularity is acceptable per trusted-network posture.

## 4. Non-Goals

- **NG1**: mTLS / OAuth flow / JWT refresh tokens. Trusted-network posture + bearer token is sufficient.
- **NG2**: Multi-tenant substrate isolation beyond what `context.json`'s existing `tenant_id` routing provides.
- **NG3**: A backward-compat `oneiric http` CLI shim. Project policy: no deprecation windows.
- **NG4**: `aiohttp` as a runtime dep. The `http-aiohttp` optional dep group is dropped entirely.
- **NG5**: New auth code in `mcp-common`. We reuse the existing `BearerTokenMiddleware` + `AuthConfig` + `IdentityProvider` machinery unchanged.

## 5. Design

### 5.1 Architecture

**Before** (current state, 2 separate aiohttp servers):

```
oneiric/http/server.py       ─┐
                              ├─►  aiohttp.web.Application
oneiric/runtime/scheduler.py ─┘   bearer auth: NEW code needed in oneiric
```

**After** (single FastMCP server):

```
oneiric/mcp/server.py ──►  fastmcp.FastMCP
                          bearer auth: mcp-common.auth.middleware.BearerTokenMiddleware
                          (zero new auth code; battle-tested)
```

### 5.2 New file: `oneiric/mcp/server.py`

```python
"""Oneiric FastMCP server — substrate state + workflow task scheduling.

Replaces the legacy aiohttp SubstrateHTTPServer and SchedulerHTTPServer with
a single FastMCP server, per Bodai convention. Auth is handled by
mcp-common.auth.middleware.BearerTokenMiddleware; this module only declares
the tool surface + per-tool permissions.

Public entrypoint: build_mcp_server() returns a configured fastmcp.FastMCP
instance. The MCPServerCLIFactory (oneiric.core.cli) wires this into the
oneiric mcp start|stop|status|health CLI surface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp import FastMCP
from mcp_common.auth.middleware import BearerTokenMiddleware
from mcp_common.auth.config import AuthConfig
from mcp_common.auth.provider import IdentityProvider
from mcp_common.auth.decorator import require_auth
from mcp_common.auth.permissions import Permission

if TYPE_CHECKING:
    from oneiric.core.config import OneiricMCPConfig


# Permission tiers — reuse the mcp-common Permission enum (READ / WRITE /
# DELETE / ADMIN). Coarse granularity is acceptable per trusted-network
# posture; fine-grained per-tool permissions are not required. Operators
# map roles to these via AuthConfig + Principal.roles.
#
# Existing role mappings in mcp_common.auth.permissions:
#   "reader"   -> {Permission.READ}
#   "operator" -> {Permission.READ, Permission.WRITE}
#   "admin"    -> all four
#
# Substrate reads (read_settings, read_context, read_progress) require READ.
# Substrate writes + schedule_task require WRITE. There is intentionally
# no DELETE / ADMIN-only tool — admin actions go through the system CLI,
# not the MCP surface.


def build_mcp_server(
    config: OneiricMCPConfig,
    *,
    auth_config: AuthConfig,
    providers: dict[str, IdentityProvider],
) -> FastMCP:
    """Construct the FastMCP server with all substrate + scheduler tools."""
    mcp = FastMCP(name="oneiric")

    # Auth: BearerTokenMiddleware expects FastMCP's middleware system.
    # Wrapped in auth_config.enabled check so trusted-network deployments
    # can opt out (default).
    if auth_config.enabled:
        mcp.add_middleware(
            BearerTokenMiddleware(
                auth_config=auth_config,
                providers=providers,
            )
        )

    # Tool registration (see §5.3 for full signatures).
    _register_substrate_tools(mcp)
    _register_scheduler_tools(mcp)
    _register_health_route(mcp)

    return mcp


def _register_substrate_tools(mcp: FastMCP) -> None:
    """Register the 6 substrate tools (3 reads, 3 writes)."""

    @mcp.tool()
    @require_auth(permission=Permission.READ, service_name="oneiric")
    async def read_settings() -> dict[str, Any]: ...

    @mcp.tool()
    @require_auth(permission=Permission.WRITE, service_name="oneiric")
    async def write_settings(version: str, source: str | None = None,
                             metadata: BoundedMetadata | None = None) -> dict[str, Any]: ...

    # read_context, write_context, read_progress, write_progress follow the
    # same READ / WRITE shape; full bodies live in the implementation plan.


def _register_scheduler_tools(mcp: FastMCP) -> None:
    """Register the workflow task scheduler tool."""

    @mcp.tool()
    @require_auth(permission=Permission.WRITE, service_name="oneiric")
    async def schedule_task(workflow: str, context: dict | None = None,
                            checkpoint: dict | None = None,
                            metadata: BoundedMetadata | None = None) -> dict[str, Any]: ...


def _register_health_route(mcp: FastMCP) -> None:
    """Public /health route — no auth (k8s/LB compat)."""
    @mcp.custom_route("/health", methods=["GET"])
    async def health(_request) -> Response:
        # Aggregate per-feed health from the substrate store; 200 healthy / 503 degraded.
        ...
```

### 5.3 Tool surface

| MCP tool | Replaces | Permission | Notes |
|---|---|---|---|
| `read_settings` | `GET /substrate/settings` | `Permission.READ` | Returns current + history |
| `write_settings` | `POST /substrate/settings` | `Permission.WRITE` | Validates payload (Pydantic), appends to history |
| `read_context` | `GET /substrate/context` | `Permission.READ` | Per-tenant aggregation |
| `write_context` | `POST /substrate/context` | `Permission.WRITE` | Validates + scopes by `tenant_id` |
| `read_progress` | `GET /substrate/progress` | `Permission.READ` | Per-workflow aggregation |
| `write_progress` | `POST /substrate/progress` | `Permission.WRITE` | Appends snapshot |
| `schedule_task` | `POST /task` (SchedulerHTTPServer) | `Permission.WRITE` | Delegates to `WorkflowBridge.execute_dag` |
| `GET /health` | `GET /health` (both aiohttp servers) | *public — no auth* | Aggregates per-feed health, 200/503 |

### 5.4 Pydantic input models (carried over from aiohttp substrate.py)

Reuse the existing `ActiveSettingsVersionIn`, `ContextVersionIn`, `ProgressSnapshotIn` from `oneiric/http/routes/substrate.py` (move to `oneiric/mcp/models.py`). Add a bounded metadata type to address the unbounded-input-disk-fill-dos finding. Metadata contract:

- **Primitives only**: `str`, `int`, `float`, `bool`, `None`. No nested dicts or lists. (Removing the unbounded-input vector is the goal; primitive values are sufficient for substrate observability metadata.)
- **String length cap**: each `str` value ≤ 1024 chars.
- **Dict key length cap**: each `str` key ≤ 256 chars.
- **Max entries**: 64 top-level keys.
- **Total payload cap**: 64 KiB enforced by FastMCP's `client_max_size` setting.

Implementation in `oneiric/mcp/models.py` uses Pydantic `Field(..., max_length=...)` constraints + a custom validator for the dict-entry cap. Pseudocode:

```python
class BoundedMetadata(RootModel[dict[str, BoundedPrimitive]]):
    """Bounded metadata dict — primitives only, finite size."""

class BoundedPrimitive(RootModel[Union[str, int, float, bool, None]]):
    """Primitive metadata value — no nested collections."""
```

`BoundedMetadata` replaces every `metadata: dict[str, Any] | None` field in the three input models.

### 5.5 Settings + env-var configuration

Per oneiric's existing layered-config convention (`OneiricSettings` base reads YAML → env vars override), add an `auth:` section:

```yaml
# settings/oneiric.yaml (new section)
auth:
  enabled: false                # off by default (trusted-network posture)
  default_provider: null        # provider key, e.g. "mahavishnu-jwt"
  trusted_issuers: []           # service-level issuer allowlist
  public_paths:                 # routes that bypass auth
    - /health
```

```bash
# Env-var overrides (oneiric's standard pattern)
ONEIRIC_AUTH_ENABLED=true
ONEIRIC_AUTH_DEFAULT_PROVIDER=mahavishnu-jwt
ONEIRIC_AUTH_TRUSTED_ISSUERS=mahavishnu-prod
ONEIRIC_AUTH_<PROVIDER>_TOKEN=...   # provider-specific signing secrets
```

The loader passes the resolved `AuthConfig` + `dict[str, IdentityProvider]` to `build_mcp_server()`. No new auth-code surface; `mcp_common.auth.identity.validate_auth_config()` runs at startup and the server refuses to start if `enabled=True` with an unconfigured provider.

### 5.6 CLI integration

The existing `MCPServerCLIFactory` (in `oneiric/core/cli.py`) is configured to point at the new FastMCP server class:

```python
# oneiric/cli/mcp.py (new file)
from oneiric.mcp.server import build_mcp_server
from oneiric.mcp.config import OneiricMCPAuthConfig
from oneiric.core.cli import MCPServerCLIFactory

mcp_cli = MCPServerCLIFactory(
    server_class=OneiricMCPServer,
    config_class=OneiricMCPConfig,
    name="mcp",                  # was "http"
    use_subcommands=True,
    description="Oneiric MCP server (FastMCP-based; replaces oneiric http).",
)
```

The old `oneiric/cli/http_cli.py` is **deleted** in the same release. No `oneiric http` alias.

### 5.7 Auth-error → HTTP-status mapping

`mcp-common`'s `AuthError` subclasses already map correctly via the existing `AuthErrorTranslationMiddleware` (Task 6b). No new translation code needed. For documentation:

| `AuthError` | HTTP | JSON-RPC |
|---|---|---|
| `AuthenticationRequiredError` | 401 | -32001 |
| `TokenInvalidError` | 401 | -32001 |
| `TokenExpiredError` | 401 | -32001 |
| `UnknownIssuerError` | 403 | -32001 |
| `InsufficientPermissionError` | 403 | -32001 |
| `SecretNotConfiguredError` | server-refuses-to-start (fail-loud at startup) |

### 5.8 Audit

`mcp-common.auth.audit.AuditLogger` is wired automatically by `BearerTokenMiddleware` when an audit sink is configured (same pattern Mahavishnu uses). No new audit code in oneiric. Audit events surface in the same Grafana/Loki pipeline as the other Bodai MCP servers.

## 6. Migration / Rollout

### 6.1 Phasing

Single release (no deprecation shim, per project policy):

1. Land FastMCP server (`oneiric/mcp/server.py`) + CLI integration (`oneiric/cli/mcp.py`) alongside the existing aiohttp servers.
2. Update `oneiric mcp` to point at the new server.
3. Delete `oneiric/http/server.py`, `oneiric/http/routes/substrate.py` (move models to `oneiric/mcp/models.py`), `oneiric/runtime/scheduler.py`, `oneiric/cli/http_cli.py`.
4. Drop the `http-aiohttp` optional dep group from `oneiric/pyproject.toml`.
5. Remove `aiohttp` from `oneiric` deps entirely.
6. Document in release notes: "CLI subcommand `oneiric http` is replaced by `oneiric mcp`. Auth now uses mcp-common's BearerTokenMiddleware; configure via settings/oneiric.yaml `auth:` section or `ONEIRIC_AUTH_*` env vars."

### 6.2 Operability

- **Trusted-network deployments**: zero config change required. `auth.enabled=false` is the default. When auth is disabled, `BearerTokenMiddleware` is not installed; `@require_auth` cannot read a Principal and raises `AuthenticationRequiredError` at tool-call time. This is the safe default — substrate tools refuse anonymous calls rather than silently returning data. Operators who intentionally want anonymous substrate access must remove the `@require_auth` decorator from those tools (intentionally not done in this design; substrate data is operational config that should always be attributed).

- **Authenticated deployments**: set `ONEIRIC_AUTH_ENABLED=true` + provider config. Tools gate on `@require_auth`; principal carries `roles` mapped to mcp-common's `Permission` enum (`READ`, `WRITE`). The standard role mapping (`reader` → READ, `operator` → READ+WRITE, `admin` → all) covers the substrate surface — `reader` for diagnostic reads, `operator` for routine writes, `admin` for break-glass.

## 7. Test plan

### 7.1 Unit tests

- `oneiric/tests/mcp/test_server.py`:
  - `build_mcp_server` with `auth_config.enabled=False`: middleware not installed; tools raise `AuthenticationRequiredError` for gated calls.
  - `build_mcp_server` with `auth_config.enabled=True` + fake JWT provider: tools accept a valid Bearer token, reject missing/invalid/expired/wrong-issuer.
  - Per-tool RBAC: a `READ`-decorated tool accepts a token with `reader` role (or `Permission.READ` in the principal's permissions); rejects when the principal lacks `READ`.
  - `/health` route returns 200 without auth (both `enabled=true` and `enabled=false`).
- `oneiric/tests/mcp/test_models.py`:
  - `BoundedMetadata` rejects payloads with nested dicts/lists, values > 1024 chars, keys > 256 chars, or > 64 top-level entries.
  - Total payload > 64 KiB is rejected at FastMCP's `client_max_size` layer (test with synthetic 100 KiB body).
- `oneiric/tests/cli/test_mcp_cli.py`:
  - `oneiric mcp start|stop|status|health` work end-to-end with the FastMCP server.
  - Old `oneiric http` command is gone (raises `typer.BadParameter`).

### 7.2 Integration tests

- `tests/integration/test_oneiric_mcp_e2e.py`:
  - Spin up `oneiric mcp` against a fake JWT issuer (test fixture).
  - Call `read_settings` over MCP protocol with a valid token → 200.
  - Call `write_settings` with an oversize metadata payload → 4xx (validation rejected).
  - Call `schedule_task` with a token that has `Permission.WRITE` → 200; without → 403 `InsufficientPermissionError`.
  - `/health` returns 200 regardless of auth state.

### 7.3 Migration smoke

- Drop-in replacement test: existing `oneiric http start` consumers get a clear `typer.BadParameter: "http" is not a oneiric command` error after upgrade (no silent breakage).

## 8. Open questions (resolved during brainstorm)

- **Q1**: What transport does the FastMCP server speak? **A1**: Both stdio (default) and HTTP/SSE (when `--transport http` is passed to `oneiric mcp start`). FastMCP supports both natively.
- **Q2**: What happens to `substrate` state on disk when the FastMCP server loads? **A2**: Unchanged. The on-disk JSON files (`~/.oneiric/substrate/{settings,context,progress}.json`) are read/written via the same `SubstrateStore` class (relocated to `oneiric/mcp/store.py`).
- **Q3**: Does the FastMCP server bind to `0.0.0.0`? **A3**: FastMCP's HTTP transport defaults to `127.0.0.1`. External bind requires explicit `--host 0.0.0.0`. This eliminates the missing-auth-network-exposure finding by default. **Enforcement**: `oneiric/cli/mcp.py::_enforce_public_network_auth_safety` raises `typer.BadParameter` when the resolved bind host is non-loopback AND `mcp_auth_config.enabled` (post-`load_auth_config`) is False. The check resolves every address for the host via `socket.getaddrinfo` (so dual-stack records and symbolic names are checked against every concrete address) and uses the resolved auth config — not the raw `OneiricMCPAuthConfig` — because the resolved value drives whether `build_mcp_server()` actually wires `BearerTokenMiddleware`. The Starlette-level `/mcp/` middleware that hardens the path even when auth is enabled remains as a follow-up (Option A from the 2026-09-18 trade-off review).

## 9. Out-of-scope follow-ons

- **Audit sink for `oneiric` MCP events**: while `AuditLogger` is wired automatically by `BearerTokenMiddleware`, no oneiric-specific audit sink is defined yet. Follow-on: add a Loki sink in `settings/oneiric.yaml`.
- **Custom JWT signing for service-to-service auth**: operators currently must reuse mahavishnu's JWT or roll their own. Follow-on: a oneiric-native `IdentityProvider` that signs local tokens with a configured secret (avoids the cross-component JWT dependency for trusted-network deployments).
- **CLI rename discoverability**: operators searching for `oneiric http` will get a cryptic `BadParameter`. Follow-on: a one-liner in `oneiric --help` output pointing to `oneiric mcp` (only if the help system supports it without code churn).
