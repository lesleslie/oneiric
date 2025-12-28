# Observability Guide

This guide explains how to configure Oneiric's structured logging, context helpers,
the resiliency controls for remote manifest fetches, and the runtime telemetry + ChatOps notification helpers introduced in 0.2.0.

## Structured Logging Setup

- `OneiricSettings.logging` now exposes `LoggingConfig`, which accepts multiple
  sinks via `logging.sinks`. Supported targets are `stdout`, `stderr`, `file`, and
  `http` (POST/HTTPS supported).
- Use `bind_log_context(domain="adapter", key="demo", provider="builtin")` before
  emitting logs from adapters/services/tasks to automatically enrich every record
  with resolver metadata; call `clear_log_context()` when the scope ends.
- Enable OpenTelemetry correlation by default (`include_trace_context = true`) so
  trace/span IDs show up without extra plumbing.

### Example (`settings.toml`)

```toml
[logging]
level = "INFO"
emit_json = true
timestamper_format = "iso"

[[logging.sinks]]
target = "stdout"

[[logging.sinks]]
target = "file"
path = "./logs/oneiric.log"
max_bytes = 1048576
backup_count = 3
```

## Remote Resiliency Controls

- `remote.max_retries`, `remote.retry_base_delay`, `remote.retry_max_delay`, and
  `remote.retry_jitter` govern exponential backoff when fetching manifests or
  artifacts; defaults (3 attempts, 1s base, 30s cap, 0.25 jitter) balance speed
  and caution.
- `remote.circuit_breaker_threshold` and `remote.circuit_breaker_reset` guard
  against thrashing an unhealthy upstream. After N consecutive failures, the
  loader pauses attempts for the configured cool-down window and emits concise
  telemetry (`remote-sync-circuit-open`).
- `remote.latency_budget_ms` defines your acceptable sync latency; `oneiric.cli health`
  now displays the last duration vs this budget and emits a warning when the
  threshold is exceeded.

### Example

```toml
[remote]
enabled = true
manifest_url = "https://demo.example.com/manifest.yaml"
cache_dir = ".oneiric_cache"
max_retries = 5
retry_base_delay = 0.5
retry_max_delay = 10.0
circuit_breaker_threshold = 4
circuit_breaker_reset = 45.0
```

Set `ONEIRIC_CONFIG=/path/to/settings.toml` (or pass `--config` to the CLI) to
activate these knobs. Pair them with the CLI's `remote-status` command to watch
retry outcomes and circuit-breaker events in real time.

## Monitoring Adapters

- **Sentry**: select `monitoring = "sentry"` and provide a DSN via config or
  `SENTRY_DSN`. Configure sampling via `traces_sample_rate` /
  `profiles_sample_rate` and set `environment`/`release` tags so incidents can be
  filtered in the SaaS UI. The adapter initializes `sentry-sdk`, enables
  optional tracing/profiling, and flushes buffered events when the resolver
  swaps providers.
- **OTLP (OpenTelemetry)**: select `monitoring = "otel-otlp"` to stream metrics
  and traces into any collector (Honeycomb, Grafana Cloud, OTLP gateway). Choose
  `protocol = "grpc"` or `"http/protobuf"`, set headers for vendor API keys,
  and tune `export_interval_seconds`/`export_timeout_seconds` to match your SLOs.
  The adapter configures both the tracing and metrics pipelines—disable either
  by setting `enable_traces` or `enable_metrics` to `false`.
- **Logfire**: remains available when you want Logfire’s combined logging +
  metrics stack with auto-instrumentation toggles for HTTPX/pydantic/system
  metrics.

## Metrics At A Glance

- `oneiric_remote_*` counters/histograms cover remote sync successes, failures,
  durations, and digest checks (emitted from the loader).
- `oneiric_lifecycle_swap_duration_ms` captures activation/swap timings with a
  `success/failed` attribute for dashboards.
- `oneiric_activity_pause_events_total` and
  `oneiric_activity_drain_events_total` count operator actions triggered via the
  CLI or automation. Use these metrics to correlate incidents with runtime
  controls such as pause/drain.

## Runtime Telemetry + Inspectors

- `oneiric.cli orchestrate --print-dag [--workflow KEY ...]` prints the active DAG graph (nodes, dependencies, retry policy, queue metadata) without starting the orchestrator loop. Pass `--inspect-json` to capture the payload for dashboards.
- `oneiric.cli orchestrate --events` performs the same inspection for event handlers (topics, fanout policy, concurrency, filters).
- Both commands exit immediately, making them safe to run in CI to snapshot runtime wiring before deploying.
- Every dispatch/run updates `.oneiric_cache/runtime_telemetry.json` with the last event dispatch + workflow execution (handler attempts/failures, per-node durations). CLI inspectors trigger the same writes so you can capture artifacts without letting the orchestrator loop run indefinitely.
- Forward the telemetry JSON to Logfire/OTLP collectors if you want historical graphs without scraping CLI commands; the runtime recorder also emits structured `runtime-event-telemetry` and `runtime-workflow-telemetry` logs for Logfire dashboards.
- For migration evidence, copy `.oneiric_cache/runtime_telemetry.json` into the repo-specific folders under `docs/examples/` (see the Crackerjack/Fastblocks/Session‑Mgmt guides). `tests/integration/test_migration_parity.py` consumes the same fixture to ensure telemetry + manifests stay aligned.

### CLI Notification Replay

- `uv run python -m oneiric.cli action-invoke workflow.notify --workflow fastblocks.workflows.fulfillment --payload '{"message":"Deploy ready","channel":"deploys"}' --send-notification --json`
  replays the ChatOps path using the `NotificationRouter`; the CLI routes through the same adapters (`--notify-adapter` / `--notify-target` override defaults) used by orchestrator workflows.
- Add `--workflow KEY` so the router pulls metadata (`adapter_provider`, `channel`, templates) from the DAG spec; runtimes and CLI demos stay in sync.
- Include the transcript (JSON or text) alongside telemetry and DAG/event payloads so reviewers can confirm Slack/Teams/Webhook output matches expectations.

## CLI Diagnostics & Dashboards

- `oneiric.cli status` now prints swap latency percentiles (p50/p95/p99) and
  success rates for whichever domain you inspect. Feed the `--json` output into
  your observability stack to derive the same summaries inside dashboards.
- `oneiric.cli health` enriches the runtime snapshot with pause/drain counters
  plus explicit remote latency budget status, making it easy to alert when the
  orchestrator regularly exceeds `remote.latency_budget_ms`.
- Combine `status --json` with `jq` or `uv run python -m json.tool` to export
  the summary block into Prometheus textfiles or push-gateway jobs; the summary
  payload already includes the percentile data points.
- Keep the new `oneiric.cli plugins` command handy during incidents: it confirms
  which entry-point groups registered candidates, so you can tell if a missing
  provider stems from plugin discovery or manifest selection.
- `oneiric.cli remote-status` reports the manifest URL, cached sync metrics, and
  latency-budget status for the most recent refresh so you can correlate remote
  failures with orchestrator health snapshots.
- `oneiric.cli activity --json` outputs per-domain pause/drain counts along with
  the individual entries, making it trivial to chart how many services are in a
  maintenance state at any given time.
- Pair those commands with the repo-specific parity guides under `docs/examples/*_OBSERVABILITY.md`; they spell out which artifacts (DAG JSON, event JSON, telemetry, ChatOps transcript) must accompany Crackerjack/Fastblocks/Session‑Mgmt rehearsals.

### Tracking Adapter/Action Migration

- Use `oneiric.cli list --domain adapter --shadowed --json` while migrating ACB adapters to confirm candidates registered from packages vs. remote manifests; the output includes provider metadata (capabilities, stack level, source) so you can verify Wave A/B/C assignments without digging through manifests.
- `oneiric.cli explain --domain adapter cache` surfaces the resolver decision (config override, priority, stack level) which helps validate that the newly ported adapter is actually selected after you update settings or manifests.
- `oneiric.cli list --domain task --shadowed` and `oneiric.cli list --domain workflow` expose the same metadata for action kits once they’re registered through the new action runner contract—use this to double-check that resolver domains match the Stage 3 checklist before deprecating the ACB counterparts.
- Record CLI snapshots (command + JSON output) alongside Crackerjack reports in PRs so reviewers can see the migration state; this mirrors the expectations documented in the related projects: `acb`, `crackerjack`, and `fastblocks`.
