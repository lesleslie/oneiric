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
