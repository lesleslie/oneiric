# AI Agent & Design Service Compatibility

Goal: make Oneiric easy for AI agents, MCP servers, and design tools to inspect, orchestrate, and monitor.

## Declarative Metadata Surfaces

- Expose adapter/action descriptors via `oneiric.cli describe --json` (or REST) so agents can query capabilities (`domains`, `inputs`, `outputs`, health semantics) without importing Python.
- Publish signed JSON manifests describing available providers (capabilities, owner, secrets requirements) so design services can render controls or validate configs offline.
- Align metadata schema with JSON Schema/OpenAPI snippets for each action kit so tools know parameter names, types, and enums.

## Agent-Friendly Entry Points

- Document resolver APIs for agents (resolve/list/explain/pause/drain) in a dedicated “AI Agent Integration” guide plus code samples.
- Provide a lightweight HTTP/gRPC endpoint for list/explain/status so IDE plugins or MCP servers can query the runtime remotely instead of shelling into `oneiric.cli`.
- Offer a Python client + TypeScript SDK that wraps those endpoints for quick integration.

## Observability & Logging

- Default to structured logs with trace/span IDs plus adapter/action context; publish sample Logly/Loki dashboards that highlight swaps, health probes, and remote syncs.
- Emit OpenTelemetry spans for resolver operations and CLI commands so AI agents can correlate their requests with runtime events.
- Provide prebuilt dashboard JSON (Grafana, Honeycomb) so design systems can embed Oneiric metrics as widgets.

## Configuration & Hot Swap Hooks

- Keep configuration reload endpoints accessible (file watcher, remote manifest, CLI) and document how agents can trigger or observe swaps.
- Add webhooks or SSE streams that broadcast resolver/lifecycle events (activated provider, swap failure, remote sync) so UI tools can react instantly.

## Samples & Templates

- Maintain reference manifests/snippets demonstrating best practices for adapters/actions used in AI workflows (LLM, embedding, vector DBs).
- Package adapter/action templates (like `docs/ADAPTER_LIFECYCLE_TEMPLATE.md`) and include JSON examples to teach agents what inputs they can expect.
- Encourage PRs to include CLI JSON output screenshots/logs so future agents have real-world samples to learn from.
