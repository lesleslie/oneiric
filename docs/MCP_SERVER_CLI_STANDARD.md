## MCP Server CLI Standard (Oneiric)

This document standardizes MCP server lifecycle and health commands across all
projects adopting Oneiric.

### Standard CLI Flags

- Short lifecycle flags: `--start`, `--stop`, `--restart`, `--status`
- Long aliases: `--start-mcp-server`, `--stop-mcp-server`, `--restart-mcp-server`,
  `--server-status`
- Health inspection: `--health` with optional `--probe` modifier

### Status vs Health vs Probe

- `--status`: confirms the server process is running and the runtime snapshot is
  fresh (updated_at within TTL).
- `--health`: reads Oneiric lifecycle state from the runtime snapshot.
- `--health --probe`: runs live health checks through Oneiric lifecycle probes,
  then prints the updated snapshot output.

### Cache and Snapshot Locations

- Cache root: `.oneiric_cache/` within the project workspace.
- PID file: `.oneiric_cache/mcp_server.pid`
- Runtime health snapshot: `.oneiric_cache/runtime_health.json`
- Runtime telemetry snapshot: `.oneiric_cache/runtime_telemetry.json`

### Oneiric Runtime Sources

- Health snapshot schema: `oneiric.runtime.health.RuntimeHealthSnapshot`
- Telemetry snapshot schema: `oneiric.runtime.telemetry.RuntimeObservabilitySnapshot`
- Lifecycle health probes: `oneiric.core.lifecycle.LifecycleManager`

### Operational Guidance

- Always write a runtime health snapshot at server startup and shutdown.
- Prefer snapshot-based status checks over process scanning to keep behavior
  consistent across all MCP servers.
- Use `--health --probe` for interactive verification or CI smoke checks.

### Adoption Order

1. `mcp-common` (Oneiric native CLI factory)
1. `session-buddy`
1. `raindropio-mcp` and `mailgun-mcp`
1. Remaining active MCP servers
