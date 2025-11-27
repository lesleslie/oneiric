## Dev Quickstart

```
uv run python main.py
```

### Dependency Groups

The base install ships only the resolver/runtime dependencies. Install extras when you want the bundled adapters/action kits to pull in their vendor SDKs:

- `uv pip install -e '.[adapters]'` adds the async clients used by the builtin adapters (aiohttp, aioboto3/botocore, asyncpg/aiomysql/aiosqlite, coredis, PyJWT, Logfire, nats-py, OTLP exporters, Sentry, Azure Blob, etc.). Combine with `dev` (`uv pip install -e '.[dev,adapters]'`) when you need both tooling and adapter stacks locally.
- `actions` is defined for parity even though the current action kits rely entirely on the core dependencies; no extra install step is required today, but `uv pip install -e '.[actions]'` is reserved for future kits that add optional requirements.

## ONNXRuntime Compatibility

This project uses Python 3.14, but ONNXRuntime does not yet have compatible wheels for this Python version.
The `crackerjack` dev dependency has been temporarily removed due to its ONNXRuntime requirement.
For ONNXRuntime-dependent tasks, use the following approach:

```bash
# Run ONNXRuntime-dependent Python scripts using Python 3.13 via uvx
uvx --python 3.13 --with onnxruntime python your_script.py

# Or use the convenience script:
./scripts/onnx_runner.sh examples/onnx_example.py
```

For quality checks that require crackerjack, you can install it separately using uvx:
```bash
uvx --with crackerjack python -m crackerjack -a patch
```

For more details, see [ONNX_GUIDE.md](ONNX_GUIDE.md).

### Quality Control & Best Practices

- Run Crackerjack for end-to-end quality gates before opening a PR: `python -m crackerjack -a patch` (adjust bump as needed) or `python -m crackerjack -x -t -p patch -c` to execute the same stages piecemeal.
- Follow the adjusted ACB + Crackerjack guidelines from the sibling repos (`../acb`, `../crackerjack`, `../fastblocks`) for coding standards, review expectations, and release hygiene; Oneiric inherits those norms while tailoring them to the resolver/lifecycle architecture here.
- Keep documentation and manifests aligned with those best practices—lint manifests, update changelogs, and capture CLI/log screenshots for behavior changes the same way ACB and FastBlocks do.

## CLI

- `uv run python -m oneiric.cli --demo list --domain adapter`
- `uv run python -m oneiric.cli --demo explain status --domain service`
- `uv run python -m oneiric.cli --demo status --domain service --key status`
- `uv run python -m oneiric.cli --demo list --domain action`
- `uv run python -m oneiric.cli --demo action-invoke compression.encode --payload '{"text":"hello"}' --json`
- `uv run python -m oneiric.cli remote-sync --manifest docs/sample_remote_manifest.yaml`
- `uv run python -m oneiric.cli remote-sync --manifest docs/sample_remote_manifest.yaml --watch --refresh-interval 60`
- `uv run python -m oneiric.cli remote-status`
- `uv run python -m oneiric.cli orchestrate --manifest docs/sample_remote_manifest.yaml --refresh-interval 120`
- `uv run python -m oneiric.cli pause --domain service status --note "maintenance window"`
- `uv run python -m oneiric.cli drain --domain service status --note "draining queue"`
- `uv run python -m oneiric.cli health`
- `uv run python -m oneiric.cli --demo list --domain task`
- Tip: the CLI uses [Typer](https://typer.tiangolo.com/); run `python -m oneiric.cli --install-completion` to enable shell completions.

### Action Kits

- Builtin kits currently include:
  - `compression.encode` – stateless compression/decompression helper.
  - `workflow.audit` – structured audit logging with redaction controls.
  - `workflow.notify` – workflow notification helper for broadcasts.
  - `workflow.retry` – deterministic retry/backoff guidance.
  - `http.fetch` – HTTP convenience wrapper around `httpx.AsyncClient` with JSON parsing, query/header merging, and timeout/redirect controls.
  - `security.signature` – HMAC helper that signs payloads (SHA-256/512/Blake2b) and emits header/timestamp fields for downstream validation.
  - `data.transform` – declarative field selector/renamer/default injector for shaping dictionaries ahead of downstream enrichment steps.
  - `debug.console` – console/debug helper that emits structured records via structlog and echoes messages to stdout for rapid troubleshooting.
- Select kits the same way as adapters via `[actions.selections]` and `[actions.provider_settings]`:
  ```toml
  [actions.selections]
  "workflow.audit" = "builtin-workflow-audit"
  "workflow.notify" = "builtin-workflow-notify"
  "workflow.retry" = "builtin-workflow-retry"
  "http.fetch" = "builtin-http-fetch"
  "security.signature" = "builtin-security-signature"
  "data.transform" = "builtin-data-transform"
  "debug.console" = "builtin-debug-console"

  [actions.provider_settings."workflow.audit"]
  channel = "deploys"
  include_timestamp = true
  redact_fields = ["secret", "token"]

  [actions.provider_settings."workflow.notify"]
  default_channel = "deploys"
  default_level = "info"
  default_recipients = ["ops@example.com"]

  [actions.provider_settings."workflow.retry"]
  max_attempts = 5
  base_delay_seconds = 2
  multiplier = 2
  jitter = 0.2

  [actions.provider_settings."http.fetch"]
  base_url = "https://status.example.com/api"
  timeout_seconds = 5
  default_headers = { "User-Agent" = "oneiric-http-action" }

  [actions.provider_settings."security.signature"]
  secret = "demo-secret"
  algorithm = "sha256"
  encoding = "hex"

  [actions.provider_settings."data.transform"]
  include_fields = ["id", "status", "payload"]
  rename_fields = { "payload" = "body" }

  [actions.provider_settings."debug.console"]
  prefix = "[workflow]"
  echo = true
  scrub_fields = ["secret", "token", "password"]
  ```
- Invoke kits directly with `uv run python -m oneiric.cli --demo action-invoke workflow.audit --payload '{"event":"deploy","details":{"service":"api"}}' --json`, `... workflow.notify --payload '{"message":"deploy","recipients":["ops"],"channel":"deploys"}'`, `... workflow.retry --payload '{"attempt":1,"max_attempts":3}'`, plus the Wave B/C helpers: `... http.fetch --payload '{"path":"/v1/health","params":{"env":"dev"}}' --json`, `... security.signature --payload '{"message":"demo","secret":"abc"}' --json`, `... data.transform --payload '{"data":{"id":1,"extra":"x"},"defaults":{"status":"active"}}' --json`, or `... debug.console --payload '{"message":"checkpoint","details":{"secret":"hide"}}' --json` to confirm scrubbing/prefix handling.

### Remote manifest refresh

- Use `remote-sync` for one-off fetches; add `--watch` to keep refreshing using the configured `settings.remote.refresh_interval`.
- Provide `--refresh-interval <seconds>` when running with `--watch` to force-enable the refresh loop even if the config disables it (e.g., `--refresh-interval 120`).
- Run `remote-status` at any time to inspect the cached telemetry (`last_success_at`, failures, per-domain registration counts, skipped entries, duration/digest checks). Data is written to the remote cache dir (default `.oneiric_cache/remote_status.json`) and mirrored via OpenTelemetry counters/histograms.
- Remote refresh telemetry is also emitted via structured logs (`remote.telemetry` logger) and OpenTelemetry counters (`oneiric_remote_*`), so tie your logging + metrics backends into those names for production dashboards.
- Recommended production posture: keep `remote.enabled = true`, set an explicit `refresh_interval` (300s+), and let long-running runtimes/orchestrators manage refreshes.
- Use shorter intervals or manual CLI overrides only in development or during incident response to avoid thrashing remote providers.
- The bundled sample manifest (`docs/sample_remote_manifest.yaml`) registers demo adapter/service/task/event/workflow providers backed by `oneiric.remote.samples` so every domain can be tested end-to-end; invalid entries are skipped with validation warnings.

### Domain status snapshots

- `oneiric.cli status` reports the resolver + lifecycle state for each domain key (active provider, source, priority, stack level, instance type, and shadowed count).
- Add `--key` to inspect a single key, `--json` for machine-readable output, `--shadowed` to include shadowed candidate details, and `--domain` to switch between adapters/services/tasks/events/workflows.
- Adapter status output automatically includes the cached remote telemetry summary for easier troubleshooting and now surfaces swap-latency percentiles plus pause/drain counts for the selected domain.
- Lifecycle-aware fields (current/pending provider, last health, last error) appear after a key has been activated by the lifecycle manager (orchestration, watcher-triggered swap, manual use).
- Lifecycle snapshots are persisted to `<settings.remote.cache_dir>/lifecycle_status.json` so `status` can inspect live services even when another process owns the orchestrator.
- Runtime orchestrator health (watchers remote loop, last sync/error, orchestrator PID) is persisted to `<settings.remote.cache_dir>/runtime_health.json`; `oneiric.cli health` prints the runtime + lifecycle snapshots so you can inspect long-running services from another shell.
- Runtime health output also includes last remote sync summary (per-domain registrations, skipped entries, total registered) sourced from the orchestrator snapshot along with latency-budget status so you know if the most recent refresh exceeded your SLO.
- `status` also reports the most recent remote sync count for the selected domain, pulled from the cached telemetry.
- `oneiric.cli remote-status` surfaces the current manifest URL, cached metrics, and latency-budget status so you can confirm remote refresh health even when the orchestrator runs elsewhere.

### Logging & Resiliency

- Configure structured logging via `[logging]` in your settings file. Multiple sinks are supported (stdout, stderr, file with rotation, HTTP) using `[[logging.sinks]]` blocks; run the CLI with `--config` or set `ONEIRIC_CONFIG` so `configure_logging(settings.logging)` loads your preferences.
- Call `bind_log_context(domain="adapter", key="demo", provider="builtin")` inside adapters/services to enrich log lines with resolver metadata; pair with OpenTelemetry tracing to get `trace_id`/`span_id` on every record.
- Tune remote reliability using the new fields under `[remote]`: `max_retries`, `retry_base_delay`, `retry_max_delay`, `retry_jitter`, `circuit_breaker_threshold`, `circuit_breaker_reset`, and `latency_budget_ms`. These settings power the shared circuit breaker + exponential backoff used by `remote-sync`, the orchestrator refresh loop, and the CLI; the health command surfaces warnings when the last sync exceeds your `latency_budget_ms`.
- Lifecycle swaps, pause/resume operations, and drain/clear events now emit OpenTelemetry metrics (`oneiric_lifecycle_swap_duration_ms`, `oneiric_activity_pause_events_total`, `oneiric_activity_drain_events_total`) so dashboards can track operator actions alongside remote sync counters.
- See `docs/OBSERVABILITY_GUIDE.md` for ready-to-run snippets that combine logging sinks and remote resiliency.

### Monitoring Adapters

- Use the Logfire monitoring adapter (`monitoring = "logfire"`) to forward structured logs/metrics to Logfire. Minimal config:
  ```toml
  [adapters.selections]
  monitoring = "logfire"

  [adapters.provider_settings.logfire]
  service_name = "oneiric-dev"
  ```
- Set `LOGFIRE_TOKEN` or `adapters.provider_settings.logfire.token` so the adapter can authenticate; optional toggles exist for HTTPX/system-metrics instrumentation.
- Set `LOGFIRE_TOKEN` or `adapters.provider_settings.logfire.token` so the adapter can authenticate; optional toggles exist for HTTPX/system-metrics instrumentation.
- Prefer Sentry when you need SaaS crash/error aggregation bundled with lightweight tracing:
  ```toml
  [adapters.selections]
  monitoring = "sentry"

  [adapters.provider_settings.sentry]
  environment = "prod-us"
  traces_sample_rate = 0.25
  profiles_sample_rate = 0.05
  ```
  Provide a DSN via `adapters.provider_settings.sentry.dsn` or `SENTRY_DSN`. The adapter initializes `sentry-sdk` with the supplied sampling knobs, supports optional tracing/profiling, and flushes spans/errors on cleanup so runtime swaps don’t drop buffered events.
- Use the OTLP adapter (`monitoring = "otel-otlp"`) to wire both metrics and traces to any OpenTelemetry collector:
  ```toml
  [adapters.selections]
  monitoring = "otel-otlp"

  [adapters.provider_settings."otel-otlp"]
  endpoint = "http://otel-collector:4318"
  protocol = "http/protobuf"  # or "grpc"
  headers = { "x-honeycomb-team" = "abc123" }
  enable_traces = true
  enable_metrics = true
  export_interval_seconds = 5
  ```
  The adapter configures OTLP span/metric exporters (HTTP or gRPC) using the OpenTelemetry SDK, binds `service.name`/`deployment.environment`, and registers shutdown hooks so lifecycle swaps flush exporters cleanly. Disable traces or metrics independently if you only need one signal.

### Cache Adapters

- Use the in-memory cache adapter (`cache = "memory"`) for demos and tests when you need deterministic, process-local storage with optional TTL + capacity bounds.
- Switch to Redis for distributed caches by selecting the `redis` provider (backed by `coredis` + TrackingCache client-side caching) and configuring `[adapters.provider_settings.redis]`:
  ```toml
  [adapters.selections]
  cache = "redis"

  [adapters.provider_settings.redis]
  url = "redis://localhost:6379/0"
  key_prefix = "oneiric:"
  ```
- Omit `url` to fall back to host/port/db fields, set `ssl = true` or `username`/`password` for managed Redis, and let TTL arguments (seconds as floats) roll into millisecond-level expirations. Health checks rely on async `PING`, so configure security groups/firewalls accordingly.
- Client-side caching is enabled by default via `enable_client_cache = true`; tune `client_cache_max_keys`, `client_cache_max_size_bytes`, or `client_cache_max_idle_seconds` to match your workload if you want to reduce (or disable) the TrackingCache footprint.

### HTTP Adapters

- httpx remains the async default (`http = "httpx"`), ideal for streaming responses or when you need tight integration with async orchestrators.
- Aiohttp is now available (`http = "aiohttp"`) when you prefer its client/session features (e.g., websocket support, per-request SSL knobs) while staying purely async:
  ```toml
  [adapters.selections]
  http = "aiohttp"

  [adapters.provider_settings.aiohttp]
  base_url = "https://api.example.com"
  timeout = 5
  headers = { "User-Agent" = "oneiric-aiohttp" }
  ```
- Pick aiohttp when you need compatibility with aiohttp’s middleware/websocket ecosystem, keep httpx for its modern transport stack—both adapters share the same `HTTPClientSettings` knobs (base URL, headers, verify flag, healthcheck path).

### Queue Adapters

- Redis Streams is the first queue provider (`queue = "redis-streams"`); selections live under `[adapters.selections]` just like other domains:
  ```toml
  [adapters.selections]
  queue = "redis-streams"

  [adapters.provider_settings."redis-streams"]
  stream = "jobs"
  group = "workers"
  consumer = "worker-1"
  url = "redis://localhost:6379/0"
  block_ms = 1000
  ```
- The adapter auto-creates the consumer group (toggle via `auto_create_group`) and exposes async helpers for `enqueue`, `read`, `ack`, and `pending`. Use `maxlen` to enforce approximate retention and `consumer_buffer_size` to batch reads.
- Like the cache adapter, Redis Streams relies on `coredis`, so TLS credentials (`rediss://` URLs, ACL usernames/passwords) and connection pooling options from your redis deployment continue to work.
- Need NATS instead? Select `queue = "nats"` for lightweight pub/sub backed by `nats-py`:
  ```toml
  [adapters.selections]
  queue = "nats"

  [adapters.provider_settings.nats]
  servers = ["nats://127.0.0.1:4222"]
  name = "oneiric-worker"
  queue = "jobs"
  ```
- The NATS adapter connects asynchronously, exposes `publish`, `subscribe`, and `request` helpers, and respects TLS/reconnect tuning from `NATSQueueSettings` so you can match production topologies.

### Storage Adapters

- Google Cloud Storage (preferred) keeps adapter configs consistent with ACB’s default deployment target:

  ```toml
  [adapters.selections]
  storage = "gcs"

  [adapters.provider_settings.gcs]
  bucket = "oneiric-demo"
  project = "my-gcp-project"
  credentials_file = "./service-account.json"  # optional when running on GCE/GKE
  ```

  The adapter wraps the official `google-cloud-storage` client with async-friendly helpers (`upload`, `download`, `list`, `delete`). Provide a service account JSON when running outside Google Cloud, or rely on workload identity. Client creation happens during lifecycle `init`, so hot swaps reuse the same credentials wiring.

- Local filesystem storage keeps blobs close to the runtime and is useful for dev/test manifests:

  ```toml
  [adapters.selections]
  storage = "local"

  [adapters.provider_settings.local]
  base_path = "./.oneiric_blobs"
  ```

  Files are written relative to `base_path`; keys map directly to nested paths (`reports/2024-01.json` → `./.oneiric_blobs/reports/2024-01.json`). The adapter guards against path traversal and supports async-friendly save/read/delete/list helpers.

- S3 remains available when teams still need AWS compatibility:

  ```toml
  [adapters.selections]
  storage = "s3"

  [adapters.provider_settings.s3]
  bucket = "oneiric-demo"
  region = "us-east-1"
  access_key_id = "AKIA..."
  secret_access_key = "super-secret"
  ```

  All operations run through `aioboto3` so uploads/downloads remain async-first. Optional fields include `endpoint_url` (for MinIO-compatible targets), `use_accelerate_endpoint`, and `healthcheck_key` if you want deeper probes than `HEAD Bucket`.

- Azure Blob Storage joins the storage lineup for teams anchored in Azure but still following Oneiric’s GCP-first defaults:

  ```toml
  [adapters.selections]
  storage = "azure-blob"

  [adapters.provider_settings."azure-blob"]
  container = "oneiric-artifacts"
  connection_string = "DefaultEndpointsProtocol=https;AccountName=...;AccountKey=..."
  ```

  Provide either a full `connection_string` or an `account_url` plus `credential` (account key or SAS token). The adapter uses the async `azure-storage-blob` client so uploads/downloads remain non-blocking, and lifecycle health checks probe the container via the Azure SDK. All metadata/registration behaves like other adapters, meaning resolver swaps and SecretsHook injection work identically across GCS, Azure, and S3.

### Database Adapters

- The Postgres adapter uses `asyncpg` pools and exposes `execute`, `fetch_one`, and `fetch_all` helpers:
  ```toml
  [adapters.selections]
  database = "postgres"

  [adapters.provider_settings.postgres]
  host = "127.0.0.1"
  port = 5432
  user = "oneiric"
  password = "secret"
  database = "oneiric"
  max_size = 10
  ```
- MySQL adapters rely on `aiomysql` for pooling; configuration mirrors Postgres (host, port, db, credentials, pool sizes). Use `autocommit = false` when you need explicit transaction control.
- SQLite support is bundled for local demos and integration tests. Selecting `database = "sqlite"` (with an optional `path`) gives you an `aiosqlite` connection that still honors lifecycle hooks so swapping to Postgres/MySQL later is seamless.

### Identity Adapters

- Auth0 JWT validation is available via the `identity = "auth0"` selection:
  ```toml
  [adapters.selections]
  identity = "auth0"

  [adapters.provider_settings.auth0]
  domain = "tenant.us.auth0.com"
  audience = "api://default"
  ```
  The adapter caches JWKS responses, validates issuer/audience claims, and exposes `verify_token(token)` to downstream services. Override `jwks_url` or `cache_ttl_seconds` if you run through a proxy or need tighter refresh windows.

### Action Kits (Stage 3)

- Stage 3 focuses on migrating ACB’s action kits (tasks/events/workflows helpers) into Oneiric’s resolver. The scaffolding now exists via `oneiric.actions.ActionMetadata` + `register_action_metadata`, so action kits can self-register exactly like adapters.
- Inspect registered kits with `uv run python -m oneiric.cli --demo list --domain action` (or `explain`/`status` with `--domain action`). Remote manifests and local settings can start targeting the `action` domain using the familiar `[actions]` selections/provider settings blocks.
- Action keys follow a `<capability>.<verb>` pattern (`compression.encode`, `data.sanitize`, `security.secure`) so the resolver registry stays descriptive without sacrificing the verb-based naming ACB teams preferred.
- See `docs/STAGE3_ACTION_MIGRATION.md` for wave breakdowns, kit expectations, and contribution guidance while the Stage 3 migration proceeds.
- Available builtin kits now cover Stage 3 Waves A + B + the opening Wave C helper: compression helpers (`compression.encode`, `compression.hash`), serialization helpers (`serialization.encode`), workflow utilities (`workflow.audit`, `workflow.notify`, `workflow.retry`), the workflow orchestrator planner (`workflow.orchestrate`), HTTP fetch (`http.fetch`), signature + token helpers (`security.signature`, `security.secure`), data processing (`data.transform`, `data.sanitize`), validation (`validation.schema`), the console/debug utility (`debug.console`), cron/interval planners (`task.schedule`), webhook dispatch hooks (`event.dispatch`), and declarative automation rules (`automation.trigger`). Each exposes metadata, typed settings, and CLI coverage for inspection/testing.
- Trigger kits directly from the CLI using
  `uv run python -m oneiric.cli --demo action-invoke compression.encode --payload '{"text":"cli"}' --json`,
  `... action-invoke http.fetch --payload '{"path":"/v1/ping"}' --json`,
  or any of the workflow/security/data helpers from the earlier sections.

### Examples

- `docs/examples/LOCAL_CLI_DEMO.md` walks through a runnable CLI/orchestrator scenario using the bundled `docs/examples/demo_settings.toml`. Copy the sample config (or set `ONEIRIC_CONFIG` to it) and follow the steps to exercise remote syncs, health snapshots, and the new logging output locally.
- `docs/examples/plugins/hello_oneiric_plugin/` contains a sample plugin package (pyproject + entry points) that you can install via `uv pip install -e` to verify entry-point discovery end-to-end.

### Plugins & Entry Points

- Enable plugin auto-loading by setting `[plugins] auto_load = true` in your settings file; Oneiric will scan the built-in entry-point groups (`oneiric.adapters`, `oneiric.services`, etc.) and register any `AdapterMetadata` or `Candidate` objects the plugins return.
- Add custom entry-point groups via `plugins.entry_points = ["acme.oneiric.adapters"]` to load your organization-specific integrations. Plugin factories should return `AdapterMetadata`, `Candidate`, or iterables thereof—see `docs/PLUGIN_ENTRYPOINT_PLAN.md` for guidance.
- Entry-point bootstrapping runs before local config/remote manifests, so you can layer environment-specific selections on top of plugin-provided defaults.
- Run `oneiric.cli plugins` (and `--json` if you need machine output) to inspect the groups that loaded, the number of registered candidates, and any plugin failures before relying on them in config/remote manifests.
- See `docs/examples/plugins/hello_oneiric_plugin/` for a ready-to-install adapter/service plugin that demonstrates entry-point wiring and CLI diagnostics.

### AI & Design Service Integration

- `docs/AI_AGENT_COMPATIBILITY.md` outlines how to expose adapter/action metadata to AI agents, MCP servers, and design tools (CLI `describe --json`, HTTP/gRPC hooks, schema exports, and observability expectations) so automation layers can introspect and orchestrate Oneiric safely.

### Lifecycle health snapshots

- Run `oneiric.cli health` to dump persisted lifecycle states (ready/failed, current vs pending provider, last health/error timestamps) across all domains.
- Use `--domain`, `--key`, `--probe`, and `--json` to filter, run live probes, or emit machine-readable payloads; data is read from the same snapshot file written by orchestrators/services.
- Runtime orchestrator health (watchers remote loop, last sync/error, orchestrator PID) is persisted to `<settings.remote.cache_dir>/runtime_health.json`; `oneiric.cli health` prints the runtime + lifecycle snapshots so you can inspect long-running services from another shell.

### Domain activity controls

- Use `oneiric.cli pause` (with `--resume` to unpause) to mark a domain key paused while you perform maintenance; pair with `--note` for operator context. Config watchers respect the paused flag and skip swap attempts until resumed.
- Use `oneiric.cli drain` (with `--clear` to stop draining) to signal that a key is draining outstanding work before a swap; notes surface in `status`.
- `oneiric.cli activity --json` emits per-domain counts (paused, draining, note-only) alongside the detailed entries so you can wire pause/drain telemetry into dashboards.

### Secrets Providers

- The built-in env secrets adapter (`provider = "env"`) reads values from environment variables prefixed with `ONEIRIC_SECRET_…` (configurable via `EnvSecretSettings`). Declare the selection in your config:
  ```toml
  [adapters.selections]
  secrets = "env"

  [adapters.provider_settings.env]
  prefix = "ONEIRIC_SECRET_"
  required_keys = ["api_token"]
  ```
- SecretsHook automatically picks up the active secrets adapter; pair it with `required_keys` to ensure missing secrets fail early via adapter health checks.
- For local development, use the file secrets adapter (`provider = "file"`) that loads a JSON map of key/value pairs:
  ```toml
  [adapters.selections]
  secrets = "file"

  [adapters.provider_settings.file]
  path = "./secrets.dev.json"
  ```
  Keep the file out of VCS and rely on `reload_on_access = true` if you want edits to apply without restarts.
- Infisical support brings remote secret retrieval with caching:
  ```toml
  [adapters.selections]
  secrets = "infisical"

  [adapters.provider_settings.infisical]
  base_url = "https://app.infisical.com"
  token = "machine-token"
  environment = "dev"
  secret_path = "/"
  ```
  Values are fetched via the Infisical API and memoized for `cache_ttl_seconds`. Missing keys return `None` when `allow_missing` is set, making it easy to probe optional secrets without surfacing errors.
- Google Secret Manager (GCP Secret Manager) is now the default remote secret provider to pair with GCS-backed deployments:
  ```toml
  [adapters.selections]
  secrets = "gcp-secret-manager"

  [adapters.provider_settings."gcp-secret-manager"]
  project_id = "my-gcp-project"
  credentials_file = "./service-account.json"  # optional
  default_version = "latest"
  cache_ttl_seconds = 120
  ```
  The adapter uses the async Secret Manager client, caches payloads in-memory, and respects lifecycle swaps so rolling credentials (new versions) only requires updating the configured version or rotating the remote secret.
- AWS Secrets Manager covers teams anchored in AWS regions:
  ```toml
  [adapters.selections]
  secrets = "aws-secret-manager"

  [adapters.provider_settings."aws-secret-manager"]
  region = "us-east-1"
  cache_ttl_seconds = 300
  version_stage = "AWSCURRENT"
  ```
  Provide credentials using standard AWS env vars/profiles or inline `access_key_id`/`secret_access_key`. The adapter relies on `aioboto3` for async calls, caches decrypted payloads for the configured TTL, and exposes `allow_missing` semantics so health probes and optional lookups behave like the other providers.

### Runtime orchestrator

- `oneiric.cli orchestrate` starts the runtime orchestrator, domain watchers, and (optionally) the remote refresh loop until interrupted.
- Pass `--manifest` to override the remote manifest URL/path and `--refresh-interval` to set a loop interval even if the config disables it; `--no-remote` skips remote sync entirely.
- Use `--demo` for a self-contained playground (demo adapters/services/etc.) and edit selections in your config file to observe watcher-driven swaps in real time.
