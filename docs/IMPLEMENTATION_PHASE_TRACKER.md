# Oneiric Delivery Phase Tracker

**Last Updated:** 2025-12-09
**Source Docs:** `docs/README.md`, `docs/STRATEGIC_ROADMAP.md`, `docs/implementation/SERVERLESS_AND_PARITY_EXECUTION_PLAN.md`, `docs/implementation/ORCHESTRATION_PARITY_PLAN.md`, `docs/UNCOMPLETED_TASKS.md`

This tracker distills the outstanding roadmap work into numbered phases so we can quickly see what remains, who owns it, and how close we are to the cut-over.

______________________________________________________________________

## Phase 1 – Serverless Profile Polish

| Item | Owner(s) | Status | Notes / References |
|------|----------|--------|--------------------|
| Capture Cloud Run buildpack transcript (pack build + gcloud deploy) and embed in `docs/deployment/CLOUD_RUN_BUILD.md` | Deployment Experience | ✅ Complete | Execution plan §3.1 |
| Document `supervisor-info`, `health --probe`, and secrets precedence outputs inside README + deployment doc | Runtime + Docs | ✅ Complete | Execution plan §3.2–§3.3 |
| Inline manifest packaging helper (CLI `manifest pack`) walkthrough in README/docs | Docs | ✅ Complete | README + CLI help |
| Cloud Run/serverless profile quickstart snippet + env var table | Docs | ✅ Complete | Roadmap §6 |

**Kickoff Checklist**

1. Confirm owners for each open row and note blockers in stand-up doc.
1. Schedule Cloud Run transcript capture session; assign reviewer for doc updates.
1. Create README/deployment doc TODO comments referencing this tracker so changes do not get lost.

**Exit Criteria:** Serverless deployers can follow README + Cloud Run guide without referencing historical Docker/K8s docs; proofs (CLI snippets/screenshots) live in docs/examples/runbooks.

______________________________________________________________________

## Phase 2 – Orchestration Parity

| Milestone | Target | Status | Key Tasks |
|-----------|--------|--------|-----------|
| M1: Event routing beta | Jan 2026 | ✅ Complete | Manifest schema + event metadata documented, CLI subscriber inspector/runbook published (`docs/examples/EVENT_ROUTING_OBSERVABILITY.md`, `docs/REMOTE_MANIFEST_SCHEMA.md`, README quick start) |
| M2: DAG runtime alpha | Feb 2026 | ✅ Complete | DAG plan/workflow run/enqueue/telemetry/checkpoint docs live (`README.md`, `docs/examples/FASTBLOCKS_OBSERVABILITY.md`, `docs/examples/FASTBLOCKS_PARITY_FIXTURE.yaml`) |
| M3: Service supervisor GA | Mar 2026 | ✅ Complete | Supervisor runbook + CLI proofs published (`docs/runbooks/SERVICE_SUPERVISOR.md`, `docs/examples/LOCAL_CLI_DEMO.md`, `docs/deployment/CLOUD_RUN_BUILD.md`); README/Procfile reference supervisor toggles |
| M4: Repo cut-over rehearsals | Apr 2026 | ⏳ Not started | Update Crackerjack/FastBlocks runbooks, parity fixture CI, MCP references swapped to Oneiric |

**Kickoff Checklist**

1. Hold parity sync to validate milestone dates and owners.
1. Ensure runtime prototypes have open tracking issues linked here.
1. Verify CLI/tests referenced in each milestone already exist or have tickets.

**Dependencies:** `oneiric.runtime.events`, `oneiric.runtime.dag`, Cloud Tasks/PubSub adapters, `docs/examples/FASTBLOCKS_PARITY_FIXTURE.yaml`, cut-over checklist.

______________________________________________________________________

## Phase 3 – Adapter & Action Completeness

| Task | Priority | Status | Notes |
|------|----------|--------|-------|
| PgVector adapter + duckdb parity tests | High | ✅ Complete | `oneiric.adapters.vector.pgvector`, `tests/adapters/test_pgvector_adapter.py`, `docs/examples/FASTBLOCKS_PARITY_FIXTURE.yaml` |
| Remaining network/file-transfer adapters (DNS, FileTransfer) | Medium | ✅ Complete | Cloudflare + Route53 DNS and FTP/SFTP/SCP/HTTP download/HTTPS upload file transfer adapters all ship in-tree (see `docs/analysis/DNS_FILE_TRANSFER_ADAPTER_PLAN.md`). Wave C items now focus on optional transports (webpush, feature flags). |
| Evaluate Wave C adapters (webpush, feature flags) | Low | 💤 Backlog | Capture requirements from downstream repos before prioritizing. |
| Weekly diff vs `docs/analysis/ACB_ADAPTER_ACTION_IMPLEMENTATION.md` | Medium | ⏳ Ongoing | Keep remediation docs updated after each adapter landing. |

**Kickoff Checklist**

1. Re-run adapter gap audit and paste deltas into `ADAPTER_REMEDIATION_EXECUTION.md`.
1. Assign engineering owners for pgvector/duckdb tasks with ETA.
1. Decide whether Wave C evaluation requires product input; if so schedule review.

**Exit Criteria:** Adapter gap audit shows parity with ACB for required domains; Wave C backlog scoped with owners.

______________________________________________________________________

## Phase 4 – Documentation & Hygiene

| Task | Status | Notes |
|------|--------|-------|
| Refresh `docs/README.md` with roadmap/execution plan links | ✅ Complete | Quick nav now links to roadmap, execution plan, parity plan, and tracker |
| Ensure sample manifests (including serverless toggles + Procfile refs) stay current | ✅ Complete | `sample_remote_manifest*.yaml` referenced in docs index; entries list FTP/SFTP/SCP/HTTPS adapters + serverless toggles |
| Archive older weekly completion reports into `docs/archive/` | ✅ Complete | already moved per WS-D |
| Maintain cross-links between roadmap ↔ parity plan ↔ execution plan | ✅ Complete | Roadmap + plans link to tracker and docs index; docs index links back to roadmap/plan loop |

**Kickoff Checklist**

1. Create doc issue list with owners for README/sample manifest updates.
1. Run link audit (e.g., `mdbook-linkcheck` or custom script) to find stale references.
1. Add reminder in Docs team calendar to revisit this phase monthly.

**Exit Criteria:** Contributors can navigate from docs index → roadmap → execution plans without stale/legacy references.

______________________________________________________________________

## Phase 5 – Quality Follow-Ups

| Task | Priority | Status | Notes |
|------|----------|--------|-------|
| Resolve 15 flaky tests (HTTP adapters, events, remote watchers) | Medium | ⏳ Planned | `docs/UNCOMPLETED_TASKS.md §3` |
| Implement secrets rotation without orchestrator restart | Medium | ⏳ Planned | Target v0.3.0 |
| Load testing at 1000+ concurrent swaps | Low | ⏳ Planned | Target v0.3.0 |
| ACB deprecation notices + comms pack | Low | ⏳ Deferred | Wait until repos run solely on Oneiric |

**Kickoff Checklist**

1. File test-flake issues referencing failing suites; attach current CI logs.
1. Draft design note for secrets rotation + load test approach (owner + target release).
1. Engage comms team to prepare outline for ACB deprecation notices once parity dates firm up.

**Exit Criteria:** Patch release closes flakiness, v0.3.0 delivers rotation + load tests, comms ready for final cut-over.

______________________________________________________________________

_Update this tracker whenever roadmap decisions shift or a phase exits. Use the “Status” column to reflect real progress (✅ Complete, ⏳ In progress, 💤 Not started) so downstream teams always know what’s left before the Oneiric-only deployment._
