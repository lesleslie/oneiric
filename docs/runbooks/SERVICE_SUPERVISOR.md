# Service Supervisor Runbook

**Last Updated:** 2025-12-09  
**Audience:** Runtime operators, Cloud Run deployers, site reliability owners

The Service Supervisor coordinates pause/drain state, health probes, and dispatch gating across adapters, services, tasks, events, and workflows. This runbook explains how to operate the supervisor in both long-lived (systemd) and serverless (Cloud Run) environments.

______________________________________________________________________

## 1. Supervisor Overview

- The supervisor polls the SQLite-backed `DomainActivityStore` (`.oneiric_cache/domain_activity.sqlite`) and broadcasts pause/drain deltas to every domain bridge.
- Dispatchers consult `should_accept_work()` before running event handlers or workflow nodes; paused/draining domains reject new work until the supervisor signals resume.
- `RuntimeHealthSnapshot` combines supervisor state, lifecycle statuses, watcher/remote telemetry, and manifest counts in `.oneiric_cache/runtime_health.json`. Cloud Run readiness checks read the same file.

______________________________________________________________________

## 2. Enabling & Inspecting the Supervisor

| Toggle | Description |
|--------|-------------|
| `RuntimeProfileConfig.supervisor_enabled` | Profile default (`default` and `serverless` enable it) |
| `runtime.supervisor.enabled` | Settings override inside `settings.toml` |
| `ONEIRIC_RUNTIME_SUPERVISOR__ENABLED` | Env override (`true`/`false`) |

Always confirm the active toggle before deploying:

```bash
uv run python -m oneiric.cli supervisor-info --json
```

Fields to capture:

- `profile_default` / `runtime_config` / `env_override`
- `supervisor_enabled`
- `watchers_enabled`, `remote_enabled`, `inline_manifest_only`

Attach this JSON to release notes so auditors know which toggle path enabled the supervisor.

______________________________________________________________________

## 3. Health & Activity Proof

Before each deploy:

```bash
uv run python -m oneiric.cli activity --json
uv run python -m oneiric.cli health --probe --json
cat .oneiric_cache/runtime_health.json
```

Verify the outputs report:

- `activity_state` per domain (paused/draining/accepting) with notes.
- `lifecycle_state` showing adapter/provider readiness.
- `profile` and `secrets` blocks (serverless toggles + Secret Manager status).
- `supervisor.enabled = true` inside both CLI and JSON snapshot.

Cloud Run: include the CLI JSON + `runtime_health.json` contents in the change ticket so reviewers see the same data that readiness probes consume.

______________________________________________________________________

## 4. Pause, Drain, Resume

Use the CLI to manipulate activity state:

```bash
# Pause a domain (no new work accepted, existing work completes)
uv run python -m oneiric.cli pause --domain adapter --key cache

# Drain (stop accepting work and wait for in-flight operations to finish)
uv run python -m oneiric.cli drain --domain workflow --key fastblocks.workflows.fulfillment

# Resume
uv run python -m oneiric.cli resume --domain workflow --key fastblocks.workflows.fulfillment
```

After each command, run `activity --json` and `health --probe --json` to confirm the supervisor propagated the change.

______________________________________________________________________

## 5. Serverless Deployments (Cloud Run)

1. Set `ONEIRIC_PROFILE=serverless` and, if needed, `ONEIRIC_RUNTIME_SUPERVISOR__ENABLED=true` in the deploy command or Procfile.
1. Persist `.oneiric_cache/` via `BP_KEEP_FILES=/workspace/.oneiric_cache` so `domain_activity.sqlite` and `runtime_health.json` survive container rebuilds.
1. Expose `--health-path /workspace/.oneiric_cache/runtime_health.json` when running the orchestrator so Cloud Run probes can read the snapshot.
1. Follow the serverless quickstart (`README.md`) or Cloud Run build guide to capture `supervisor-info`, `health --probe --json`, and the raw `runtime_health.json` output.

______________________________________________________________________

## 6. Troubleshooting

| Symptom | Likely Cause | Resolution |
|---------|--------------|------------|
| `supervisor-info` shows `supervisor_enabled=false` | Profile or env override disabled it | Re-enable via profile/settings/env var before deploy |
| `activity --json` shows stale pause/drain notes | `.oneiric_cache` not persisted | Ensure cache directory is writable/persisted; rerun CLI after restarting |
| Cloud Run readiness never flips healthy | `runtime_health.json` missing or supervisor disabled | Confirm `--health-path`, cache permissions, and supervisor toggles |
| Dispatch still runs on paused domain | CLI not targeting correct key/domain | Use `activity --json` to confirm key, re-run pause, and check logs for supervisor listener warnings |

______________________________________________________________________

## 7. References

- `docs/implementation/ORCHESTRATION_PARITY_PLAN.md` (P3 – Service Supervisors & Health)
- `docs/deployment/CLOUD_RUN_BUILD.md` (sample transcript + CLI proofs)
- `docs/examples/LOCAL_CLI_DEMO.md` (CLI commands and sample JSON output)
- `README.md` (serverless quickstart + runtime controls)
