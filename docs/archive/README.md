# Oneiric Documentation Archive

Use this folder to stage legacy completion reports, phased implementation summaries, and other high-noise artifacts that we still want to keep for historical context. Moving these files out of the primary `docs/` index keeps the live plans (roadmap + execution plan) concise for new contributors.

## Legacy Implementation Reports

| Status | Document | Notes |
|--------|----------|-------|
| ✅ Archived | `docs/archive/implementation/BUILD_PROGRESS.md` | Phase-by-phase log superseded by `STRATEGIC_ROADMAP.md`. |
| ✅ Archived | `docs/archive/implementation/UNIFIED_IMPLEMENTATION_PLAN.md` | Replaced by `SERVERLESS_AND_PARITY_EXECUTION_PLAN.md`. |
| ✅ Archived | `docs/archive/implementation/WEEK1_SECURITY_COMPLETION.md` | Historical audit output (Week 1). |
| ✅ Archived | `docs/archive/implementation/WEEK_3_4_SUMMARY.md` | Week 3-4 recap. |
| ✅ Archived | `docs/archive/implementation/CLI_TESTS_COMPLETION.md` | Detailed CLI coverage report. |
| ✅ Archived | `docs/archive/implementation/DOMAIN_BRIDGE_TESTS_COMPLETION.md` | Domain tests summary. |
| ✅ Archived | `docs/archive/implementation/INTEGRATION_TESTS_COMPLETION.md` | Integration/E2E completion log. |
| ✅ Archived | `docs/archive/implementation/LIFECYCLE_TESTS_COMPLETION.md` | Lifecycle completion log. |
| ✅ Archived | `docs/archive/implementation/REMOTE_TESTS_COMPLETION.md` | Remote loader completion report. |
| ✅ Archived | `docs/archive/implementation/RUNTIME_TESTS_COMPLETION.md` | Runtime completion report. |
| ✅ Archived | `docs/archive/implementation/SIGNATURE_VERIFICATION_COMPLETION.md` | Security runbook snapshot. |
| ✅ Archived | `docs/archive/implementation/THREAD_SAFETY_COMPLETION.md` | Concurrency completion log. |
| ✅ Archived | `docs/archive/ACB_COMPARISON.md` | Historical Oneiric vs ACB comparison (superseded by `docs/ONEIRIC_VS_ACB.md`). |
| ✅ Archived | `docs/archive/BUILD_PROMPTS.md` | Legacy execution checklist for early build phases. |
| ✅ Archived | `docs/archive/DOCUMENTATION_AUDIT_SUMMARY.md` | Documentation audit summary (v0.2.0-era). |
| ✅ Archived | `docs/archive/analysis/DNS_FILE_TRANSFER_ADAPTER_PLAN.md` | Wave C adapter plan (DNS + file transfer) now complete. |
| ✅ Archived | `docs/archive/implementation/LOGGING_OBSERVABILITY_PLAN.md` | Superseded observability plan (replaced by `docs/OBSERVABILITY_GUIDE.md`). |
| ✅ Archived | `docs/archive/implementation/NOSQL_ADAPTER_SPRINT.md` | NoSQL adapter sprint plan (shipped). |
| ✅ Archived | `docs/archive/implementation/GRAPH_ADAPTER_PLAN.md` | Graph adapter delivery plan (shipped). |
| ✅ Archived | `docs/archive/implementation/MESSAGING_AND_SCHEDULER_ADAPTER_PLAN.md` | Messaging + scheduler adapter plan (shipped). |
| ✅ Archived | `docs/archive/implementation/PLUGIN_ENTRYPOINT_PLAN.md` | Superseded plugin entry-point plan (implemented; see `docs/ONEIRIC_VS_ACB.md`). |
| ✅ Archived | `docs/archive/implementation/RESOLUTION_LAYER_PLAN.md` | Superseded resolution plan (see `docs/RESOLUTION_LAYER_SPEC.md`). |

## Historical Plans

The following plans were superseded by the streamlined execution plan:

- `docs/archive/implementation/LOGGING_OBSERVABILITY_PLAN.md` - Superseded by `docs/OBSERVABILITY_GUIDE.md`
- `docs/archive/implementation/RESOLUTION_LAYER_PLAN.md` - Superseded by `docs/RESOLUTION_LAYER_SPEC.md`
- `docs/archive/implementation/PLUGIN_ENTRYPOINT_PLAN.md` - Superseded by `docs/ONEIRIC_VS_ACB.md`
- `docs/implementation/ADAPTER_MIGRATION_PLAN.md` - Removed; superseded by `docs/implementation/ADAPTER_REMEDIATION_PLAN.md`
- `docs/implementation/ADAPTER_DISCOVERY_AND_HOT_SWAP_PLAN.md` - Removed; superseded by core resolution layer docs

Historical content available in git history if needed.

## How to Archive

1. Move the file into this folder (mirror the original subdirectory if needed, e.g., `archive/implementation/`).
1. Update `docs/README.md` to remove the file from active navigation and add an “Archive” reference pointing here.
1. Keep a short note in the archived file’s front-matter explaining why it was moved (e.g., “Superseded by STRATEGIC_ROADMAP.md on 2025-12-07.”).

This workflow keeps Oneiric’s documentation approachable without losing the detailed history that auditors and future maintainers may need.
