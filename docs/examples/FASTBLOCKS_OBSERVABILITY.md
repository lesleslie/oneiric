# Fastblocks Observability Checklist

Use this checklist whenever we validate Fastblocks workflows on Oneiric. The inspectors + telemetry snapshot replace the old MCP dashboard screenshots.

## 0. Parity Fixture & Tests

- Load `docs/examples/FASTBLOCKS_PARITY_FIXTURE.yaml` into both Oneiric and ACB runs so DAG snapshots stay identical.
- `uv run pytest tests/integration/test_migration_parity.py` exercises the manifest through `RuntimeOrchestrator.sync_remote`; re-run it whenever the manifest changes so CI enforces the same evidence captured here.
- Record any updates in `docs/implementation/CUTOVER_VALIDATION_CHECKLIST.md` so the cut-over table reflects the latest rehearsal.
- Capture the ChatOps transcript with `uv run python -m oneiric.cli action-invoke workflow.notify --workflow fastblocks.workflows.fulfillment --payload '{"message":"Deploy complete","channel":"deploys"}' --send-notification --json` so reviewers can see the exact Slack/Teams/Webhook output produced by the new router. The CLI uses the shared `NotificationRouter`, so orchestrator runs and rehearsals emit identical payloads.

## 1. Print the DAGs You Care About

```bash
uv run python -m oneiric.cli \
  --profile serverless \
  orchestrate \
  --print-dag \
  --workflow fastblocks.session-sync \
  --workflow fastblocks.webhook-fanout
```

- Add `--inspect-json` to capture a machine-readable payload for the docs repo.
- The output includes entry nodes, queue metadata, and retry policy – mirror this in the parity issue.

Use the `--print-dag --inspect-json` output to capture topology/metadata without executing nodes, and attach that JSON to parity issues.

```bash
# Inspect the DAG plan without executing it (topology + metadata)
uv run python -m oneiric.cli workflow plan \
  --profile serverless \
  --workflow fastblocks.workflows.fulfillment \
  --json
```

Attach the `workflow plan` JSON alongside the `--print-dag` output so reviewers see the same topology the executor will run (nodes, dependencies, queue hints, retry policies).

## 2. Inspect Event Handlers

```bash
uv run python -m oneiric.cli \
  --profile serverless \
  orchestrate \
  --events \
  --inspect-json > artifacts/fastblocks_events.json
```

Store the JSON alongside the DAG snapshot so reviewers can verify the dispatcher wiring (topics, filters, concurrency).

## 3. Archive `runtime_telemetry.json`

Every orchestrator run (and CLI inspector) updates `.oneiric_cache/runtime_telemetry.json`. Copy it into the Fastblocks parity folder so CI/dashboards can ingest:

- Event handler attempts/durations/failures.
- Workflow node runtimes + retry counts.

## 4. Workflow Runs & Checkpoints

Demonstrate both inline DAG execution and queue-backed enqueue flows:

```bash
# Run the workflow inline (no enqueue, useful for quick parity proofs)
uv run python -m oneiric.cli workflow run \
  --profile serverless \
  --workflow fastblocks.workflows.fulfillment \
  --context '{"order_id":"demo-123"}' \
  --workflow-checkpoints \
  --resume-checkpoint \
  --json

# Enqueue the workflow via the configured queue adapter (Cloud Tasks)
uv run python -m oneiric.cli workflow enqueue \
  --profile serverless \
  --workflow fastblocks.workflows.fulfillment \
  --context '{"order_id":"demo-123"}' \
  --json
```

Artifacts to capture:

- `workflow run` JSON output (node-by-node duration + retry status).
- Updated `.oneiric_cache/workflow_checkpoints.sqlite` (or configured store). Dump via `sqlite3 .oneiric_cache/workflow_checkpoints.sqlite '.schema; select * from checkpoints;'`.
- `runtime_telemetry.json` after the run to show DAG node telemetry.
- Optional: Cloud Tasks delivery logs hitting `/tasks/workflow` when using the enqueue command.

If a node fails, rerun `workflow run --resume-checkpoint` (or re-run with `--workflow-checkpoints`) and attach both transcripts to the parity issue.

## 5. ChatOps Output

Fastblocks already uses `workflow.notify` → Slack. Use the CLI bridge (`action-invoke workflow.notify --workflow fastblocks.workflows.fulfillment --send-notification`) to replay the manifest metadata and capture the exact message forwarded through the configured adapter. Include that JSON transcript with the parity artifacts so reviewers and ChatOps owners can compare against the legacy MCP output.

> Tip: when you need to override the adapter/target during rehearsals, pass `--notify-adapter notifications.slack --notify-target '#deploys'` so the CLI still runs through the same NotificationRouter path.
