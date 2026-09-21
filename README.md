# Oneiric

[![Code style: crackerjack](https://img.shields.io/badge/code%20style-crackerjack-000042)](https://github.com/lesleslie/crackerjack)
[![Runtime: oneiric](https://img.shields.io/badge/runtime-oneiric-6e5494)](https://github.com/lesleslie/oneiric)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Python: 3.14+](https://img.shields.io/badge/python-3.14%2B-green)](https://www.python.org/downloads/)

**Explainable component resolution, lifecycle management, and remote delivery for Python 3.14+ runtimes**

**current v0.21.8**

Oneiric is a standalone resolver and runtime foundation. Register adapters,
services, tasks, events, workflows, and actions; explain selection decisions;
manage lifecycle transitions; and hydrate capabilities from remote manifests.

## Quick Links

- [Capabilities](#capabilities)
- [Domains and built-ins](#domains-and-built-ins)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [CLI map](#cli-map)
- [MCP server](#mcp-server)
- [Documentation](#documentation)

## Quality checks

Use Crackerjack for the repository quality gate; the commands are documented
below in [Development](#development).

______________________________________________________________________

## Capabilities

- **Resolution:** deterministic selection by explicit configuration, stack,
  priority, and registration order, with explainable and shadowed candidates.
- **Lifecycle:** activation, health checks, binding, cleanup, rollback, and
  safe provider swaps through `LifecycleManager`.
- **Runtime orchestration:** watchers, remote refresh, workflow checkpoints,
  event dispatch, pause/drain supervision, and optional scheduler callbacks.
- **Remote delivery:** YAML/JSON manifests with optional digest and signature
  verification, canonical packaging, and per-domain registration.
- **Operations:** structured logging, runtime health and telemetry snapshots,
  notification routing, plugin discovery, and secrets-cache management.

______________________________________________________________________

## Domains and built-ins

The resolver exposes six registered domains. Each domain uses the same
selection and lifecycle model, while domain-specific bridges provide the
execution behavior.

| Domain | Role |
| --- | --- |
| **Adapters** | Providers for cache, storage, queues, HTTP, databases, NoSQL, graph, vector, embeddings, LLMs, secrets, messaging, DNS, file transfer, and monitoring. |
| **Services** | Lifecycle-managed application services registered by the host application or a manifest. |
| **Tasks** | Async task providers and queue metadata used by runtime workflows. |
| **Events** | Topic dispatch with filtering, fan-out, retries, and handler inspection. |
| **Workflows** | DAG planning, execution, enqueueing, checkpoints, and telemetry. |
| **Actions** | Built-in kits for compression, HTTP, workflow, security, serialization, data, validation, task, event, automation, and debugging operations. |

Built-in action keys include `compression.encode`, `compression.hash`,
`compression.stream`, `workflow.audit`, `workflow.orchestrate`,
`workflow.notify`, `workflow.retry`, `http.fetch`, `event.dispatch`, and
`debug.console`. Use `oneiric --demo list --domain action` to inspect the
complete registry.

______________________________________________________________________

## MCP server

Oneiric exposes a FastMCP server (substrate state + workflow task scheduling) that replaces the legacy aiohttp SubstrateHTTPServer and SchedulerHTTPServer. The server speaks JSON-RPC over HTTP on **port 8681** (configurable via `$ONEIRIC_MCP_PORT`) and binds to `127.0.0.1` by default — non-loopback binds require auth to be enabled. Auth itself is delegated to mcp-common's `BearerTokenMiddleware`; configure providers via the `auth:` section in `~/.oneiric/settings.yaml` (or the path passed via `$ONEIRIC_SETTINGS_PATH`).

### Tool surface (14 tools across 3 groups)

| Group | Count | Purpose |
|-------|-------|---------|
| Substrate | 6 | 3 reads + 3 writes against the substrate (settings, context, progress records) |
| Scheduler | 1 | `schedule_task` — dispatch a workflow task via the scheduler processor |
| Adapter registry | 7 | OneiricAdapterRegistry read/list/state/refresh/clear/diagnose/health (ported from `dhara.mcp.tools.group_registers.register_adapter_registry_group` during the Phase 1 Dhara decomposition) |

Plus the 4 mcp-common baseline tools (`discover_tools`, `get_liveness`, `get_readiness`, `health_check_all`) for a 18-tool total MCP surface.

### CLI lifecycle

```bash
# Start (detached by default; --foreground for blocking)
oneiric mcp start --port 8681

# Probe
oneiric mcp status
oneiric mcp health

# Stop
oneiric mcp stop
```

______________________________________________________________________

## Runtime and operations

- Watchers reload selections using watchfiles or polling; serverless profiles
  can disable remote refresh and watchers.
- `RuntimeOrchestrator` coordinates remote sync, event dispatch, workflow
  execution, checkpoints, notifications, and the optional scheduler HTTP
  server for Cloud Tasks callbacks.
- `DomainActivityStore` records pause/drain state, while the supervisor keeps
  inactive components from accepting work.
- Runtime health, telemetry, lifecycle, activity, and workflow checkpoint
  artifacts are written beneath the configured cache directory.
- `oneiric health`, `status`, `activity`, `remote-status`, and
  `supervisor-info` expose operator-facing state.

______________________________________________________________________

## Configuration

`load_settings()` layers project and user configuration for the selected
`project_name`. From lowest to highest precedence, it checks:

1. Code defaults
1. `settings/<project_name>.yaml` or `.yml` at the project root
1. `settings/local.yaml` at the project root
1. `${XDG_CONFIG_HOME:-~/.config}/<project_name>/config.yaml`
1. `${XDG_CONFIG_HOME:-~/.config}/<project_name>/local.yaml`
1. Environment overrides in the form `<PROJECT_NAME>_<SETTING>__<FIELD>`

For example, a project using `project_name="oneiric"` checks
`~/.config/oneiric/config.yaml` and `~/.config/oneiric/local.yaml` when
`XDG_CONFIG_HOME` is not set. Set `XDG_CONFIG_HOME` to relocate the user
configuration root. Missing layered files are ignored. Project paths are
normally anchored at the installed package/project root; an explicit
`project_root=` can be supplied when embedding Oneiric elsewhere.

An explicit `path=` argument to `load_settings()` or the corresponding
`<PROJECT_NAME>_CONFIG` environment variable is applied last and takes
precedence over all layered files. The CLI exposes the same override through
`--config`.

______________________________________________________________________

## Quick start

For repository development:

```bash
uv sync --group dev
uv run oneiric --demo list --domain adapter
uv run oneiric --demo list --domain action
uv run oneiric --demo explain demo --domain adapter
uv run oneiric --demo health --probe --json
```

Inspect runtime plans without starting the long-running loop:

```bash
uv run oneiric --demo orchestrate --print-dag --inspect-json
uv run oneiric --demo orchestrate --events --inspect-json
uv run oneiric workflow plan --workflow <workflow-key> --json
```

Run a manifest sync, event, workflow, or action explicitly:

```bash
uv run oneiric remote-sync --manifest docs/sample_remote_manifest.yaml
uv run oneiric event emit demo.event --payload '{"source":"cli"}' --json
uv run oneiric workflow run <workflow-key> --context '{"request_id":"demo"}' --json
uv run oneiric action-invoke compression.encode --payload '{"text":"hello"}' --json
```

Start the orchestrator when a long-running process is required:

```bash
uv run oneiric start \
  --manifest docs/sample_remote_manifest.yaml \
  --refresh-interval 120 \
  --no-http
uv run oneiric process-status
uv run oneiric health --probe --json
uv run oneiric stop
```

### Serverless profile

The `serverless` profile is intended for deployments such as Cloud Run. It
can be selected through the environment or CLI and combined with explicit
remote/HTTP settings:

```bash
uv run oneiric manifest pack \
  --input docs/sample_remote_manifest.yaml \
  --output build/serverless_manifest.json

ONEIRIC_PROFILE=serverless uv run oneiric supervisor-info
ONEIRIC_PROFILE=serverless uv run oneiric health --probe --json
ONEIRIC_PROFILE=serverless uv run oneiric start --no-remote --no-http
```

Deployment details are in [docs/deployment/CLOUD_RUN_BUILD.md](docs/deployment/CLOUD_RUN_BUILD.md).

______________________________________________________________________

## CLI map

The installed console script is `oneiric`. Use `oneiric --help` for the
complete command surface; `uv run oneiric` is the repository-local form.

- **Inspect:** `list`, `status`, `explain`, `health`, `plugins`, and
  `supervisor-info` expose registrations, resolution decisions, lifecycle
  state, and runtime health.
- **Manage lifecycle:** `swap`, `pause`, `drain`, `start`, `stop`, and
  `process-status` control providers and the background orchestrator.
- **Run work:** `event emit`, `workflow plan`, `workflow run`,
  `workflow enqueue`, and `action-invoke` exercise runtime capabilities.
- **Deliver manifests:** `remote-sync`, `remote-status`, and `manifest pack`
  handle remote inputs and cached synchronization state.
- **Operate integrations:** `plugins`, `secrets`, `shell`, and `load-test`
  provide discovery, secret-cache operations, interactive administration, and
  runtime load testing.

______________________________________________________________________

## Bodai Integration

When installed alongside the [Bodai ecosystem](https://github.com/lesleslie/bodai),
Oneiric supplies the shared resolver, lifecycle manager, and adapter catalog
used by the other Bodai components. The standalone install is identical —
Bodai does not impose special-case overrides on Oneiric's domain model;
consumers wire the same `load_settings()` and adapter registries they would in
any other Python application.

______________________________________________________________________

## Observability and state

Oneiric uses structured logging and writes runtime artifacts below the
configured `cache_dir` (the default setting is `.oneiric_cache`). The runtime
surface includes:

- `runtime_health.json` for watcher, remote, supervisor, and orchestrator state
- `runtime_telemetry.json` for event and workflow execution summaries
- `lifecycle_status.json` for provider lifecycle snapshots
- `domain_activity.sqlite` for pause/drain state
- `workflow_checkpoints.sqlite` for resumable workflow execution when enabled

See [docs/OBSERVABILITY_GUIDE.md](docs/OBSERVABILITY_GUIDE.md) for logging,
telemetry, and artifact-handling details. `workflow.notify` routes messages
through the configured messaging adapter when notification delivery is enabled.

______________________________________________________________________

## Remote manifests

Remote manifests can describe adapters, services, tasks, events, workflows, and
actions. Oneiric can load them from local paths or supported URIs, validate
optional signatures and digests, register their domains, and refresh them on a
schedule.

```bash
uv run oneiric manifest pack \
  --input docs/sample_remote_manifest.yaml \
  --output build/manifest.json
uv run oneiric remote-sync --manifest docs/sample_remote_manifest.yaml
uv run oneiric remote-status
```

See [docs/REMOTE_MANIFEST_SCHEMA.md](docs/REMOTE_MANIFEST_SCHEMA.md) and
[docs/SIGNATURE_VERIFICATION.md](docs/SIGNATURE_VERIFICATION.md) for the
manifest and verification contracts.

______________________________________________________________________

## Documentation

- [Documentation index](docs/README.md) — navigation through architecture,
  operations, examples, and reference material.
- [CLI reference](docs/CLI_REFERENCE.md) — command options and operator flows.
- [Package map](oneiric/README.md) — module layout and extension points.
- [Custom adapters](docs/guides/custom-adapter.md) — registration and resolver
  extension patterns.
- [XDG configuration](docs/ONEIRIC_SHELL_QUICKREF.md) — configuration layers
  and interactive settings inspection.
- [Observability guide](docs/OBSERVABILITY_GUIDE.md) — logging and runtime
  artifacts.
- [Deployment guides](docs/deployment/) and [runbooks](docs/runbooks/) —
  Cloud Run, systemd, maintenance, and troubleshooting.

______________________________________________________________________

## Development

```bash
# Fast repository checks
python -m crackerjack run --fast

# Comprehensive checks
python -m crackerjack run --comp

# Full quality run, including tests
python -m crackerjack run --run-tests
```

Run the repository-local gate after changing runtime, adapter, action, or CLI
behavior. Add or update tests and documentation with the same change.

______________________________________________________________________

## Contributing

1. Review the relevant architecture and operator documentation.
1. Run `python -m crackerjack run --run-tests` before opening a PR.
1. Add or update tests for runtime features, adapters, actions, or CLI flows.
1. Update the README or linked documentation when the operator surface changes.

______________________________________________________________________

## License and support

- **License:** BSD-3-Clause (see `LICENSE`).
- **Issues:** https://github.com/lesleslie/oneiric/issues
- **Docs:** Start with [docs/README.md](docs/README.md).
