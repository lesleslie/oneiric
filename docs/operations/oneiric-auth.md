# Oneiric Auth — Operator Guide

## What changed

`oneiric http` is replaced by `oneiric mcp` (REQ-007). The underlying
HTTP server is now FastMCP-based and inherits auth from
`mcp-common.auth.middleware.BearerTokenMiddleware` (REQ-002).

The CLI subcommand `oneiric http` is gone — use `oneiric mcp`.

## Deployment posture

Trusted-network default (firewall is the primary gate). Auth is **opt-in**.

## Enabling auth

### Settings file (`settings/oneiric.yaml`)

```yaml
auth:
  enabled: true
  default_provider: jwt
  trusted_issuers:
    - mahavishnu-prod
```

### Env vars (override)

```bash
ONEIRIC_AUTH_ENABLED=true
ONEIRIC_AUTH_DEFAULT_PROVIDER=jwt
ONEIRIC_AUTH_TRUSTED_ISSUERS=mahavishnu-prod
```

## What's gated

| Endpoint | Permission | Token required |
|---|---|---|
| `GET /health` | — | No (always public) |
| `read_settings`, `read_context`, `read_progress` | `READ` | Yes |
| `write_settings`, `write_context`, `write_progress`, `schedule_task` | `WRITE` | Yes |

A token without the required permission returns `403 InsufficientPermissionError`.

## Roles

Use mcp-common's standard role mapping:

- `reader` → `{READ}`
- `operator` → `{READ, WRITE}`
- `admin` → all four

For trusted-network deployments, `reader` for diagnostic tools, `operator`
for routine writes, `admin` reserved for break-glass.

## Token format

`Authorization: Bearer <token>` where `<token>` is whatever the configured
`IdentityProvider` accepts (e.g. JWT for the mahavishnu provider).

## Disabling auth

Set `auth.enabled = false` (default). The server still refuses anonymous
calls to substrate tools (raises `AuthenticationRequiredError`) — substrate
data is always attributed. To intentionally allow anonymous access, remove
the `@require_auth` decorator from the relevant tool (not done in this
design).

## Troubleshooting

- **`401` from a tool you have a valid token for**: check `trusted_issuers`
  in `settings/oneiric.yaml` includes the token's issuer.
- **`403` from a write**: your token has `READ` but not `WRITE`. Request
  operator-role credentials.
- **Server refuses to start with `auth.enabled=true`**: check the provider
  factory is wired in the settings loader; `validate_auth_config()` runs at
  startup and aborts on misconfiguration.

## Known limitations

The auth posture documented above depends on the mcp-common middleware and
its surrounding primitives. Two bugs are known upstream and tracked against
`mcp-common`. They are NOT oneiric code defects; oneiric just inherits them
through the inherited middleware. Operators enabling `auth.enabled=true`
should understand the blast radius before exposing the server.

### BearerTokenMiddleware contextvar-propagation bug

**Upstream component:** `mcp-common.auth.middleware.BearerTokenMiddleware`.

**Symptom:** Under specific async-boundary conditions, `Principal.current()`
returns `None` inside tool handlers even when the inbound `Authorization: Bearer <token>` header was successfully verified. Practical effect: a caller
holding a valid token sees `tools/list` return 200 (no `@require_auth` on
that framework-level path), but `tools/call` on a gated tool raises
`AuthenticationRequiredError` from the `@require_auth` decorator because the
principal contextvar reads empty.

**Tracked under:** mcp-common issue tracker — search `BearerTokenMiddleware contextvar propagation`. Until a fix lands, operators running oneiric with
`auth.enabled=true` should expect intermittent 401s on `tools/call` even
with a known-good token; the workaround is to retry the call once (the
middleware re-seeds on each request).

### Tool inventory leak on absent Authorization header

**Upstream component:** `mcp-common.auth.middleware.BearerTokenMiddleware`.

**Symptom:** `tools/list` returns the full tool inventory to any anonymous
caller — the middleware only runs token verification when an `Authorization`
header is PRESENT. An absent header short-circuits via
`return await call_next(context)` and bypasses per-tool gating, because
`tools/list` is a framework-level method (not an individual tool) and so is
not decorated with `@require_auth`.

**Tracked under:** mcp-common issue tracker — search
`BearerTokenMiddleware tools/list bypass`. Operationally this means the
*names and schemas* of every registered tool are enumerable by an
unauthenticated network-adjacent caller. This is acceptable on a
trusted-network deployment (the same firewall that motivated the opt-in
default) but must not be combined with a public-network deployment of
`oneiric mcp` until the upstream fix lands.

## CLI surface

The `oneiric mcp` lifecycle CLI mirrors the legacy `oneiric http start|stop| status|health` shape so operators already familiar with the HTTP server can
operate the FastMCP server the same way. All four subcommands live under
`oneiric.cli.mcp.mcp_app` and are registered on the top-level `oneiric` CLI
via `mcp_app` in `oneiric/cli/__init__.py`.

| Command | One-line description |
|---|---|
| `oneiric mcp start` | Start the FastMCP server in the foreground. Reads settings via `_load_auth_from_settings()`, binds the configured host/port (defaults `127.0.0.1:8765`), and refuses to start when `auth.enabled=true` and no providers are wired. |
| `oneiric mcp stop` | Stop a running FastMCP server. Reads the PID file, sends SIGTERM, waits up to `--timeout` seconds (default 5), then escalates to SIGKILL. |
| `oneiric mcp status` | Show whether the server is running. Probes both the PID file and the configured host:port; emits a human-readable summary or `--json` for scripting. |
| `oneiric mcp health` | Probe the server's `/health` endpoint. Returns `ok` only when the auth provider set is non-empty and `validate_auth_config()` passed at startup. |

Example:

```bash
# Start on the default port with auth opt-in
oneiric mcp start --host 127.0.0.1 --port 8765

# Check status from another shell
oneiric mcp status --json

# Graceful stop, escalate after 10s if still alive
oneiric mcp stop --timeout 10
```

## Adding a custom identity provider

The default `_build_provider_factories()` stub in
`/Users/les/Projects/oneiric/oneiric/cli/mcp.py` returns `{}` so the CLI can
be exercised standalone in dev/CI. Production deployments wire their JWT,
OIDC, or other token-verifying constructors there (or hand a pre-populated
dict to `start` via the settings loader).

### Extension point

Edit `_build_provider_factories` in
`/Users/les/Projects/oneiric/oneiric/cli/mcp.py`. The function returns a
`dict[str, Callable[[dict[str, Any]], IdentityProvider]]` mapping
`IdentityProviderSpec.name` → constructor. Each constructor accepts a
dict of provider-specific config keys and returns an `IdentityProvider`
instance.

### Protocol

Implement the `IdentityProvider` Protocol from
`mcp-common.auth.provider`:

```python
from mcp_common.auth.provider import IdentityProvider, ProviderHealth
from mcp_common.auth.principal import Principal

class MyCustomProvider:
    name: str = "my-custom"

    async def verify_token(self, token: str, *, expected_audience: str | None = None) -> Principal:
        # Raise an AuthError subclass on failure.
        ...

    async def health(self) -> ProviderHealth:
        return ProviderHealth(name=self.name, state="healthy")
```

### Wiring example

```python
# In _build_provider_factories()
def _build_provider_factories() -> dict[str, Callable[[dict[str, Any]], IdentityProvider]]:
    return {
        "jwt": lambda cfg: JWTIdentityProvider(secret=cfg["secret"], issuer=cfg["issuer"]),
        "my-custom": lambda cfg: MyCustomProvider(config=cfg),
    }
```

The settings loader resolves `auth.default_provider` against this dict at
startup. `validate_auth_config()` raises when `auth.enabled=true` but
`_build_provider_factories()` returns `{}` — by design: opt-in auth must
never silently start without providers. Reference implementations of
`JWTIdentityProvider` and `AnthropicIdentityProvider` live in
`/Users/les/Projects/mcp-common/mcp_common/auth/providers/`.
