# Session-Mgmt MCP Observability Runbook

Session-Mgmt’s MCP cut-over relies on the same artifacts as Crackerjack/Fastblocks. Follow these steps whenever you stage a release.

## 1. DAG Snapshot

```bash
uv run python -m oneiric.cli \
  orchestrate \
  --print-dag \
  --workflow sessionmgmt.rebuild-index \
  --workflow sessionmgmt.notify-clients \
  --inspect-json > artifacts/sessionmgmt_dag.json
```

Commit/attach the JSON so reviewers can diff node dependencies and retry policy across versions.

## 2. Event Handler Snapshot

```bash
uv run python -m oneiric.cli orchestrate --events --inspect-json \
  > artifacts/sessionmgmt_events.json
```

This shows the MCP bridge topics, filter clauses, and fan-out policy.

## 3. Telemetry Evidence

- Copy `.oneiric_cache/runtime_telemetry.json` after running orchestrate/inspect commands (inspectors trigger telemetry writes, so no extra run is required).
- The snapshot feeds timing/attempt data into shared dashboards and replaces the manual spreadsheet we used for MCP.

## 4. Notifications

Session-Mgmt sends lifecycle pings via `workflow.notify`. Confirm the Slack/Teams/webhook adapter is configured and capture the transcript with:

```bash
uv run python -m oneiric.cli \
  action-invoke workflow.notify \
  --workflow sessionmgmt.notify-clients \
  --payload '{"message":"Session sync ready","channel":"ops"}' \
  --send-notification \
  --json > artifacts/sessionmgmt_chatops.json
```

Attach the JSON output alongside telemetry so Ops can verify the ChatOps payload that will land in prod. Use `--notify-adapter` / `--notify-target` during rehearsals when you need to point at staging webhooks; the CLI still runs through the same NotificationRouter path.
