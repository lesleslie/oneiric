# Serverless & Parity Execution Plan

**Last Updated:** 2025-12-07
**Owners:** Platform Core (runtime + adapters), Docs Team, Deployment Experience
**Purpose:** Capture the post–Track G decisions, codify the “Oneiric replaces ACB” mandate, and lay out the concrete work we must finish so Cloud Run/serverless deployments, orchestration parity, and documentation cleanup converge on the same timeline. Strategic context sits in \[\[STRATEGIC_ROADMAP|`docs/STRATEGIC_ROADMAP.md`\]\]; milestone status for every item below is tracked in \[\[IMPLEMENTATION_PHASE_TRACKER|`docs/IMPLEMENTATION_PHASE_TRACKER.md`\]\]. For navigation help (and links to related architecture/runbook docs) see \[\[README|`docs/README.md`\]\].

______________________________________________________________________

## 1. Decisions & Guardrails (Recap)

1. **ACB sunset:** Oneiric will replace ACB end-to-end across Crackerjack, FastBlocks, and session-mgmt-mcp. No hybrid “mix adapters/actions” mode will ship because no production workloads force backwards compatibility.
1. **Serverless-first:** Google Cloud Run (and other buildpack-based runtimes) are the primary deployment targets. The Docker/Kubernetes docs were removed; Procfile/buildpack is the only supported deployment path alongside systemd for local agents.
1. **Lean adapters/actions:** `_base.py` scaffolding is retired; shared helpers live in `common.py` modules with lazy imports. New adapters/actions must follow that pattern and expose optional extras for heavyweight dependencies.
1. **Secrets precedence:** Secret Manager adapters (GCP/AWS) and other providers take precedence over plain env vars in serverless profiles; env adapters remain as fallbacks for local dev/testing.
1. **Observability posture:** Structlog JSON stays on `stdout`; `stderr` is reserved for crashes. Rich/loguru pretty output is allowed only for dev runs. Remote loader remains on `httpx` + `tenacity/aiobreaker`; adapters may wrap other HTTP libs when needed.
1. **Package scope:** Oneiric ships as a single distribution until orchestration parity is complete; afterwards we can evaluate splitting adapters/actions into extras if it reduces install surface.
1. **MCP scope:** Oneiric does not host its own MCP server. Crackerjack/FastBlocks can expose MCP endpoints that wrap Oneiric orchestrations if needed; Oneiric focuses on orchestration/core runtime.

______________________________________________________________________

## 2. Workstreams

| Workstream | Goal | Key Tasks | Owner(s) | Target |
|------------|------|-----------|----------|--------|
| **WS-A: Serverless Profile** | Deliver a Cloud Run–ready profile with Procfile/buildpack docs, lazy imports, and manifest packaging. | ✅ CLI/main automatically honor `ONEIRIC_PROFILE`, profile toggles disable watchers/remote polling, Procfile/Cloud Run docs live in `docs/deployment/CLOUD_RUN_BUILD.md`; remaining polish is telemetry screenshots + optional manifest pack helper refinements. | Runtime + Deployment | Q1 2026 |
| **WS-B: Orchestration Parity** | Implement events, task DAGs, and service supervisors using best-in-class Python libs so Oneiric replaces ACB orchestration. | Adopt `anyio` TaskGroups + `networkx` DAG modeling + sqlite checkpoints, add service supervisor, wire event routing with `msgspec` envelopes, document migration steps. | Platform Core | Q2 2026 |
| **WS-C: Adapter/Action Completeness** | Close the adapter/action gaps between ACB and Oneiric (pgvector, secrets variants, HTTP choices, notification/email, scheduler bridges). | Port remaining ACB adapters/actions, add optional extras, guard imports, add CLI/tests, update manifests. | Adapter Team | Rolling |
| **WS-D: Documentation & Roadmap Hygiene** | Consolidate redundant docs, surface current plans, and keep Track G follow-ups visible. | Archive week-by-week completion reports into `/docs/archive`, refresh `docs/README.md`, keep roadmap + plan cross-links healthy, capture newly approved decisions. | Docs Team | Dec 2025 |

______________________________________________________________________

## 3. Serverless Profile Blueprint (WS-A)

1. **Procfile & buildpacks**
   - ✅ Provide `Procfile.cloudrun` with `web: uv run python -m oneiric.cli orchestrate --profile serverless --no-remote` so buildpack-based flows have an explicit manifest to reference (kept in sync with the root Procfile).
   - Author `docs/deployment/CLOUD_RUN_BUILD.md` covering `pack build`, `gcloud run deploy --source`, and the `--env-file` workflow.
   - ✅ Add CLI helper: `uv run python -m oneiric.cli manifest pack --output build/manifest.json`.
   - ✅ Ship the global `--profile` flag (default/serverless) so `uv run python -m oneiric.cli orchestrate --profile serverless` is the canonical Cloud Run entrypoint.
   - ✅ CLI + `main.py` now read `ONEIRIC_PROFILE` (and config defaults) so Cloud Run deploys only need an env var instead of duplicating the profile stanza inside the settings file.
1. **Runtime toggles**
   - Serverless profile disables file watchers, remote polling, and hot reload (`RuntimeProfileConfig.watchers_enabled=False`, `remote_enabled=False`, `inline_manifest_only=True`). Hot swap stays available for long-lived Crackerjack installs only.
   - Ensure resolver defaults to inline manifests packaged within the container; remote refresh runs only when explicitly enabled.
   - Surface the toggle status through `oneiric cli supervisor-info`, which echoes the profile default, `RuntimeSupervisorConfig.enabled`, and any `ONEIRIC_RUNTIME_SUPERVISOR__ENABLED` override so Cloud Run runbooks can capture the exact posture before deploys.
1. **Secrets + config**
   - Prioritize `oneiric.adapters.secrets.gcp.SecretManagerSecretsAdapter` (default) → `aws` → `env` fallback.
   - Document the precedence order (Secret Manager → environment variables → manifest overrides) and reference the `Profile`, `Secrets`, and `lifecycle_state` sections emitted by `oneiric cli health --probe --json` so ops teams can verify serverless posture before deploys (capture the output in release notes alongside `supervisor-info` so the enabling proof is self-contained).
   - Document secret rotation + caching expectations for Cloud Run revisions.
1. **Cold start + size**
   - Guard heavy optional dependencies via extras (e.g., `pip install oneiric[vector,pg]`).
   - Document recommended buildpack `BP_KEEP_FILES=/oneiric/` layout and caching strategies.
1. **Testing**
   - ✅ Add CI job: `uv run pytest -k serverless_profile` covering toggles/manifests (see `.github/workflows/release.yml`).
   - Capture CLI transcript demonstrating a local buildpack deploy.

______________________________________________________________________

## 4. Orchestration Parity Blueprint (WS-B)

### Libraries & Adapters to Leverage

| Capability | Library / Adapter | Notes |
|------------|-------------------|-------|
| Concurrent event routing | `anyio` TaskGroups | Cancel scopes + nursery semantics for deterministic cleanups. |
| Event serialization | `msgspec` | Fast structured envelopes, lowers cold-start CPU. |
| DAG modeling | `networkx` (primary) + stdlib `graphlib` fallback | Provide “lite” mode for minimal deps. |
| Scheduling | `apscheduler` (Cloud Run friendly) and Cloud Tasks adapter | Wrap as adapters so repos can choose. |
| Persistence | `sqlite` (default), optional `pgvector` for embeddings, `cloud-sql-proxy` aware. |
| Secrets | GCP Secret Manager adapter (default). |

### No-Hybrid Mandate

All orchestration capabilities ship in Oneiric core. Crackerjack/FastBlocks consume them via Oneiric APIs; we will not share orchestration responsibilities with ACB. Any interim work happens in feature branches guarded by flags, not by deploying dual runtimes.

### Milestone Highlights

1. **Events (Jan 2026)**
   - finalize manifest schema additions.
   - Provide CLI `orchestrate --events --print-subscribers`.
   - Document ops playbook for event routing.
1. **Task DAGs (Feb 2026)**
   - `networkx` DAG engine, `sqlite` checkpoint store, CLI `--plan`.
   - Provide Cloud Tasks / Pub/Sub adapters to trigger DAG starts.
1. **Service supervision (Mar 2026)**
   - Supervisor loops integrated with resolver, watchers optional per profile.
   - Write doc: `docs/runbooks/SERVICE_SUPERVISOR.md`.
1. **Migration rehearsals (Apr 2026)**
   - Crackerjack + FastBlocks runbooks + manifest diffs.

______________________________________________________________________

## 5. Adapter & Action Completeness Checklist (WS-C)

### Highest Priority (Q4 2025 → Q1 2026)

1. **Vector & data science**
   - Port `pgvector` adapter with async pool + metadata (owner: Data Platform).
   - Provide `duckdb` parity tests referencing new `activity.sqlite`.
1. **Messaging**
   - ✅ SendGrid/Mailgun/Twilio plus Slack/Teams/webhook adapters shipped with unit tests, CLI demos, and sample manifests. Workflow notify → ChatOps bridging is documented in `docs/examples/LOCAL_CLI_DEMO.md` and referenced in the orchestration parity plan.
   - Next: evaluate `webpush`/mobile push adapters + SecretsHook ergonomics for Teams Graph once requirements land.
1. **Scheduler/queue**
   - ✅ Cloud Tasks + Pub/Sub adapters landed (unit tests + docs). Ensure Redis/NATS integration tests cover parity fixtures under `tests/adapters/`.
1. **Security**
   - Ensure `security.signature`, `security.secure`, `validation.schema` kits all expose CLI and docs.
1. **HTTP adapters**
   - Keep `httpx` in runtime critical path; http adapters remain for consumer choice but remote loader will not depend on them (less indirection, faster cold start).

See `docs/analysis/ADAPTER_GAP_AUDIT.md` for the living adapter backlog.

### Optional / Wave C

1. **Observability exporters** (Logfire, OTLP, Sentry) already ported – add docs referencing serverless profile.
1. **Feature flag adapters** – only if new projects request them.

______________________________________________________________________

## 6. Documentation & Cleanup (WS-D)

1. ✅ **Archive historical completion reports** – `docs/implementation/BUILD_PROGRESS.md`, `UNIFIED_IMPLEMENTATION_PLAN.md`, and every `WEEK*`/`*_COMPLETION` file now live under `docs/archive/implementation/` with an updated index.
1. **Refresh `docs/README.md`** to link to `STRATEGIC_ROADMAP.md`, this plan, and `ORCHESTRATION_PARITY_PLAN.md`.
1. **Update sample manifests** with serverless toggles + Procfile references.
1. **Remove redundant Docker/K8s docs** or mark them as “legacy”; highlight Cloud Run/buildpack flow instead. ✅ Done – only Cloud Run + systemd guides remain under `docs/deployment/`.
1. **Add decision log** in `docs/STRATEGIC_ROADMAP.md §6` summarizing the bullets from §1 here so newcomers understand the December decisions.

______________________________________________________________________

## 7. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Adapter extras bloat cold starts | Slower Cloud Run revisions | Guard heavy deps w/ extras, document `pip install oneiric[vector,pg]`. |
| Untested queue/storage adapters block parity | Cut-over slips | Establish weekly adapter parity review vs `docs/analysis/ACB_ADAPTER_ACTION_IMPLEMENTATION.md`. |
| Doc sprawl reappears | Teams lose signal | Calendar reminder for Docs team to snapshot this plan + roadmap whenever major milestones finish. |
| Buildpack path drift | Deploys break | Add CI smoke test `pack build oneiric:ci` weekly. |

______________________________________________________________________

## 8. Next Actions (Next 2 Weeks)

1. **Serverless profile skeleton (Runtime)**
   - ✅ Implemented profile toggles, env-var fallback, Procfile/guide updates. Next: capture screenshots/logs of a `pack build` + `gcloud run deploy` run to include in the deployment appendix.
1. **Adapter gap audit (Adapter Team)**
   - Diff `docs/analysis/ACB_ADAPTER_ACTION_IMPLEMENTATION.md` vs current adapters; capture the remaining NoSQL/feature-flag backlog now that Mailgun/Twilio/Slack/Teams/webhook + Cloud Tasks/Pub/Sub shipped.
   - Update `ADAPTER_REMEDIATION_EXECUTION.md` with refreshed evidence + owners.
1. **Docs hygiene (Docs Team)**
   - Move week-by-week completion docs into `/docs/archive`, update links.
   - Cross-link roadmap ↔ parity plan ↔ this document.
1. **Parity spike (Platform Core)**
   - ✅ `oneiric.runtime.events` + `oneiric.runtime.dag` landed as prototypes with tests (see `tests/runtime/test_parity_prototypes.py`). Update the orchestration parity plan when wiring them into domains.
   - ✅ Scheduler decision: Cloud Tasks is the default for serverless DAG triggers; `apscheduler` remains optional for Crackerjack cron-like flows.
1. **Roadmap socialization**
   - Update `docs/STRATEGIC_ROADMAP.md` and `docs/implementation/ORCHESTRATION_PARITY_PLAN.md` with the new serverless defaults so partner teams know the cut-over path (no hybrid deployment).
   - Share the updated plan + test evidence (pytest `tests/core/test_profiles.py tests/core/test_serverless_profile.py`) in the next stand-up/Crackerjack sync so downstream repos adopt the same defaults.

Keep this document updated alongside `docs/STRATEGIC_ROADMAP.md` whenever scope or timelines shift. It should act as the day-to-day execution reference for the Cloud Run/serverless push and the “replace ACB in one swoop” initiative.
