# Migration Validation & Cut-over Checklist

This checklist captures the artifacts every repo must produce before we switch its MCP workloads from ACB to Oneiric. It pairs with the Fastblocks parity fixture so teams can rehearse the cut-over repeatably in CI and through the CLI.

## 1. Shared Fixtures

- **Remote manifest:** `docs/examples/FASTBLOCKS_PARITY_FIXTURE.yaml` mirrors the Fastblocks workflows (event trigger, two task nodes, notification action, and queue adapter). The same manifest can be consumed by ACB and Oneiric so dashboards show identical DAGs. `tests/integration/test_migration_parity.py` consumes the fixture so CI confirms the same registration counts documented here.
- **Test harness:** `uv run pytest tests/integration/test_migration_parity.py` loads the manifest via `RuntimeOrchestrator.sync_remote` and asserts each domain is registered plus the DAG metadata is refreshed. Re-run this test after modifying the fixture or parity plan.
- **Runtime telemetry:** The orchestrator writes `.oneiric_cache/runtime_telemetry.json`. Copy this file into the repo-specific observability folders (Crackerjack/Fastblocks/Session-Mgmt) to attach telemetry snapshots to PRs.

## 2. Validation Steps

Perform the following before declaring a repo ready for cut-over:

1. **Adapter coverage:** Confirm every adapter referenced by the manifest exists in Oneiric (or has a stub equivalent) and that `oneiric.core.lifecycle` can activate the providers without manual environment tweaks.
2. **Manifest snapshot:** Store the exact manifest (or canonical YAML diff) in the repo’s observability folder so reviewers know which keys/providers were used during the rehearsal.
3. **CLI transcript:** Run `uv run python -m oneiric.cli orchestrate --print-dag --workflow fastblocks.workflows.fulfillment --inspect-json --manifest docs/examples/FASTBLOCKS_PARITY_FIXTURE.yaml` and attach the output (plain text or JSON) to the change request.
4. **Event inspector:** Capture `uv run python -m oneiric.cli orchestrate --events --inspect-json --manifest docs/examples/FASTBLOCKS_PARITY_FIXTURE.yaml` so parity reviews include queue/topic fan-out details.
5. **ChatOps replay:** `uv run python -m oneiric.cli action-invoke workflow.notify --workflow fastblocks.workflows.fulfillment --payload '{"message":"Deploy ready","channel":"deploys"}' --send-notification --json` produces the Slack/Teams/Webhook transcript via `NotificationRouter`; include it with the parity artifacts (override adapters/targets via CLI flags if needed, the router path stays identical).
6. **Telemetry archive:** After a local orchestrator loop (or CI dry run), copy `.oneiric_cache/runtime_telemetry.json` into the runbook folder and reference it in the PR description.

## 3. Repo Sign-off Table

| Repo | Fixture Snapshot | CLI Transcript | Telemetry Archive | Status |
|------|------------------|----------------|-------------------|--------|
| Crackerjack | Pending | Pending | Pending | 🟡 Needs validation |
| Fastblocks | Pending | Pending | Pending | 🟡 Needs validation |
| session-mgmt-mcp | Pending | Pending | Pending | 🟡 Needs validation |

Update the table (✅ / 🟢 Ready) once the artifacts above are attached to the repo’s migration PR.

## 4. Cut-over Prerequisites

- **Adapter readiness:** All Stage 3 adapters required by the repo appear in `oneiric/adapters` or the remote manifest fixture.
- **Secrets strategy:** Secrets are pulled via `SecretsHook` (GCP Secret Manager preferred) with no lingering `.env` requirements.
- **Telemetry + ChatOps:** Dashboards (or Slack/Teams rooms) receive both inspector output and `workflow.notify` payloads to mirror the legacy MCP view.
- **Rollback notes:** Each repo documents the CLI flags required to revert to ACB in case the new manifest fails (typically re-pointing manifests in the platform deployment config).

## 5. Ongoing Maintenance

- Re-run the migration parity test whenever adapters, workflows, or event schemas change.
- Keep the manifest + CLI transcripts in sync with the repo-specific observability guides.
- Append dated notes to the table above when a repo completes its rehearsal so the parity plan can point to the exact checklist entry.
