# Runtime orchestration

Runtime components coordinate watchers, remote sync, telemetry, notifications, and
long-running orchestration loops. These are used by the CLI and `main.py`.

## Key modules

- `orchestrator.py` - `RuntimeOrchestrator` lifecycle + remote sync wiring.
- `watchers.py` - selection/config watchers (polling or watchfiles).
- `telemetry.py` - runtime telemetry snapshots.
- `health.py` - runtime health snapshot helpers.
- `scheduler.py` - scheduler HTTP server for workflow task callbacks.
- `notifications.py` - `workflow.notify` routing helpers.
- `activity.py` / `supervisor.py` - pause/drain state + supervisor loop.

Docs: `docs/OBSERVABILITY_GUIDE.md`, `docs/deployment/CLOUD_RUN_BUILD.md`.
