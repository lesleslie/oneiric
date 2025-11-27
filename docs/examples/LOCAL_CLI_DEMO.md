# Local CLI Demo

This runnable example shows how to combine the CLI, remote manifest loader, and the new logging/resiliency knobs.

## 1. Copy the sample settings

```bash
cp docs/examples/demo_settings.toml ~/.oneiric.toml
```

Update the file if you want to change cache directories or logging sinks. The sample configuration enables structured logs (stdout + rotating file), remote retries, and circuit breaker protection, and it points at `docs/sample_remote_manifest.yaml` so you can run everything offline.
It also enables `[plugins] auto_load = true` so any installed entry-point plugins (`oneiric.adapters`, etc.) are registered before the demo metadata.

## 2. Run the orchestrator with the sample settings

```bash
ONEIRIC_CONFIG=~/.oneiric.toml \
uv run python -m oneiric.cli orchestrate --refresh-interval 60 --demo
```

This command boots the runtime orchestrator, registers demo providers, and refreshes the bundled manifest every minute. Watch the log output for `remote-sync-complete` and `remote-refresh-circuit-open` events to verify retry/circuit-breaker behavior.

## 3. Inspect runtime health and activity

In a second shell, run the CLI against the same config to view health snapshots and activity state:

```bash
ONEIRIC_CONFIG=~/.oneiric.toml uv run python -m oneiric.cli status --domain adapter
ONEIRIC_CONFIG=~/.oneiric.toml uv run python -m oneiric.cli health --probe --json
ONEIRIC_CONFIG=~/.oneiric.toml uv run python -m oneiric.cli activity --json
```

Persisted telemetry lives under the cache directory configured in the sample file; open `.oneiric_cache/demo.log` to review the JSON log stream with trace context.
