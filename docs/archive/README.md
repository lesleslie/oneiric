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

## Historical Plans

The following plans have been deleted as they were superseded by the streamlined execution plan:

- ~~`docs/implementation/ADAPTER_MIGRATION_PLAN.md`~~ - Deleted (superseded by ADAPTER_REMEDIATION_PLAN.md)
- ~~`docs/implementation/ADAPTER_DISCOVERY_AND_HOT_SWAP_PLAN.md`~~ - Deleted (functionality now in core resolution layer)
- ~~`docs/implementation/LOGGING_OBSERVABILITY_PLAN.md`~~ - Deleted (superseded by OBSERVABILITY_GUIDE.md)
- ~~`docs/implementation/RESOLUTION_LAYER_PLAN.md`~~ - Deleted (superseded by RESOLUTION_LAYER_SPEC.md)
- ~~`docs/implementation/PLUGIN_ENTRYPOINT_PLAN.md`~~ - Deleted (functionality deferred to future enhancement)

Historical content available in git history if needed.

## How to Archive

1. Move the file into this folder (mirror the original subdirectory if needed, e.g., `archive/implementation/`).
1. Update `docs/README.md` to remove the file from active navigation and add an “Archive” reference pointing here.
1. Keep a short note in the archived file’s front-matter explaining why it was moved (e.g., “Superseded by STRATEGIC_ROADMAP.md on 2025-12-07.”).

This workflow keeps Oneiric’s documentation approachable without losing the detailed history that auditors and future maintainers may need.
