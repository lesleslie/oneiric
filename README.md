## Dev Quickstart

```
uv run python main.py
```

## CLI

- `uv run python -m oneiric.cli --demo list --domain adapter`
- `uv run python -m oneiric.cli --demo explain status --domain service`
- `uv run python -m oneiric.cli --demo status --domain service --key status`
- `uv run python -m oneiric.cli remote-sync --manifest docs/sample_remote_manifest.yaml`
- `uv run python -m oneiric.cli remote-sync --manifest docs/sample_remote_manifest.yaml --watch --refresh-interval 60`
- `uv run python -m oneiric.cli remote-status`
- `uv run python -m oneiric.cli orchestrate --manifest docs/sample_remote_manifest.yaml --refresh-interval 120`
- `uv run python -m oneiric.cli pause --domain service status --note "maintenance window"`
- `uv run python -m oneiric.cli drain --domain service status --note "draining queue"`
- `uv run python -m oneiric.cli health`
- `uv run python -m oneiric.cli --demo list --domain task`
- Tip: the CLI uses [Typer](https://typer.tiangolo.com/); run `python -m oneiric.cli --install-completion` to enable shell completions.

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
- Adapter status output automatically includes the cached remote telemetry summary for easier troubleshooting.
- Lifecycle-aware fields (current/pending provider, last health, last error) appear after a key has been activated by the lifecycle manager (orchestration, watcher-triggered swap, manual use).
- Lifecycle snapshots are persisted to `<settings.remote.cache_dir>/lifecycle_status.json` so `status` can inspect live services even when another process owns the orchestrator.
- Runtime orchestrator health (watchers remote loop, last sync/error, orchestrator PID) is persisted to `<settings.remote.cache_dir>/runtime_health.json`; `oneiric.cli health` prints the runtime + lifecycle snapshots so you can inspect long-running services from another shell.
- Runtime health output also includes last remote sync summary (per-domain registrations, skipped entries, total registered) sourced from the orchestrator snapshot.
- `status` also reports the most recent remote sync count for the selected domain, pulled from the cached telemetry.

### Lifecycle health snapshots

- Run `oneiric.cli health` to dump persisted lifecycle states (ready/failed, current vs pending provider, last health/error timestamps) across all domains.
- Use `--domain`, `--key`, `--probe`, and `--json` to filter, run live probes, or emit machine-readable payloads; data is read from the same snapshot file written by orchestrators/services.
- Runtime orchestrator health (watchers remote loop, last sync/error, orchestrator PID) is persisted to `<settings.remote.cache_dir>/runtime_health.json`; `oneiric.cli health` prints the runtime + lifecycle snapshots so you can inspect long-running services from another shell.

### Domain activity controls

- Use `oneiric.cli pause` (with `--resume` to unpause) to mark a domain key paused while you perform maintenance; pair with `--note` for operator context. Config watchers respect the paused flag and skip swap attempts until resumed.
- Use `oneiric.cli drain` (with `--clear` to stop draining) to signal that a key is draining outstanding work before a swap; notes surface in `status`.

### Runtime orchestrator

- `oneiric.cli orchestrate` starts the runtime orchestrator, domain watchers, and (optionally) the remote refresh loop until interrupted.
- Pass `--manifest` to override the remote manifest URL/path and `--refresh-interval` to set a loop interval even if the config disables it; `--no-remote` skips remote sync entirely.
- Use `--demo` for a self-contained playground (demo adapters/services/etc.) and edit selections in your config file to observe watcher-driven swaps in real time.
