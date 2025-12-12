# Event Routing Observability Demo

**Last Updated:** 2025-12-09
**Purpose:** Show how to inspect event subscribers, emit events, and capture telemetry evidence using the built-in CLI commands and the Fastblocks parity fixture.

______________________________________________________________________

## 1. Prerequisites

- `uv` installed locally.
- Oneiric checkout with `.oneiric_cache/` available (CLI writes telemetry + health artifacts here).
- Sample manifest: `docs/examples/FASTBLOCKS_PARITY_FIXTURE.yaml` (ships event metadata).
- Optional: serverless profile (`ONEIRIC_PROFILE=serverless`) to mirror Cloud Run behavior.

______________________________________________________________________

## 2. Inspect Event Subscribers

Use the orchestrator inspector to dump the current subscriber map without booting the long-running loop:

```bash
uv run python -m oneiric.cli orchestrate \
  --events \
  --inspect-json \
  --topic fastblocks.order.created
```

Sample output (truncated):

```json
{
  "topic": "fastblocks.order.created",
  "handlers": [
    {
      "key": "fastblocks.events.order-handler",
      "provider": "order-handler",
      "priority": 50,
      "fanout_policy": "exclusive",
      "retry_policy": {"attempts": 3, "base_delay": 0.5},
      "filters": [{"path": "payload.region", "equals": "us"}]
    }
  ]
}
```

Attach this JSON to parity PRs so reviewers can verify handler priorities, filters, and retry policies match the manifest.

______________________________________________________________________

## 3. Emit Events with CLI Proofs

Emit a payload using the same dispatcher that runtime workflows use:

```bash
uv run python -m oneiric.cli event emit \
  --topic fastblocks.order.created \
  --payload '{"order_id":"demo-123","region":"us"}' \
  --json
```

The CLI prints the handler results plus retry metadata. Save the JSON output alongside the inspector payload so downstream repos can replay the same event inputs.

______________________________________________________________________

## 4. Telemetry Snapshots

Event dispatch telemetry lands in `.oneiric_cache/runtime_telemetry.json`. Capture it immediately after emitting an event:

```bash
cat .oneiric_cache/runtime_telemetry.json
```

Relevant fields:

- `event_handlers` → list of handlers invoked, latency, and retry attempts.
- `topic` → event topic dispatched.
- `filters_applied` → filter evaluation results.

For Cloud Run proofs, bundle the telemetry snapshot, CLI inspector output, and CLI emit output in release notes.

______________________________________________________________________

## 5. Manifest Metadata Reference

`docs/examples/FASTBLOCKS_PARITY_FIXTURE.yaml` includes the event metadata used above, mirroring the schema described in `docs/REMOTE_MANIFEST_SCHEMA.md`:

- `event_topics`, `event_filters`, `event_priority`, `event_fanout_policy`, and `retry_policy` for handlers.
- DAG definitions with `retry_policy` and explicit `scheduler` hints (queue category/provider) so enqueue operations default to Cloud Tasks.

When updating manifests, keep the CLI proofs in this doc synchronized so the inspector output mirrors the manifest structure.

______________________________________________________________________

## 6. Additional Checks

1. `uv run python -m oneiric.cli activity --json` → confirm the Service Supervisor captured the latest event counts.
1. `uv run python -m oneiric.cli health --probe --json` → ensure event dispatcher appears in `lifecycle_state`.
1. Run `uv run pytest tests/cli/test_commands.py::TestEventWorkflowCommands` before committing changes to the dispatcher/CLI.

______________________________________________________________________

Link this demo in parity PRs and runbook appendices so partners can reproduce the exact evidence required for the M1 “event routing beta” milestone.
