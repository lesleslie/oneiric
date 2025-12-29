# Oneiric Orchestration Parity Plan

**Last Updated:** 2025-12-06
**Owner:** Platform Core & Runtime Team
**Purpose:** Outline the remaining work to bring Oneiric's events, tasks, and service orchestration capabilities to full parity with ACB so Crackerjack, Fastblocks, and session-mgmt-mcp can run solely on Oneiric. Strategic priorities are summarized in \[\[STRATEGIC_ROADMAP|`docs/STRATEGIC_ROADMAP.md`\]\] and every milestone in this plan rolls up to \[\[IMPLEMENTATION_PHASE_TRACKER|`docs/IMPLEMENTATION_PHASE_TRACKER.md`\]\]. For the broader documentation index (architecture specs, runbooks, observability guides) see \[\[README|`docs/README.md`\]\].

______________________________________________________________________

## Recent Progress (December 2025)

1. **Serverless entrypoints aligned** – `Procfile` + `Procfile.cloudrun` now share the canonical `uv run python -m oneiric.cli orchestrate --profile serverless --no-remote` command, and the Cloud Run buildpack guide contains the end-to-end transcript for CI/reference. Cold-start toggles live in `RuntimeProfileConfig`.
1. **Messaging + scheduler bridges shipped** – Mailgun/SendGrid/Twilio plus Slack/Teams/Webhook adapters and the Cloud Tasks/Pub/Sub queue adapters are in-tree with CLI/tests (WS-C dependencies ready for DAG/event routing). Cloud Tasks is the default DAG scheduler; APScheduler remains optional for long-lived Crackerjack cron flows.
1. **Remote/resiliency modernized** – httpx + tenacity/aiobreaker loader, sqlite activity store, and watchfiles-based watchers are complete (Track G follow-up), so event/task orchestration can lean on the updated runtime primitives without bespoke patches.
1. **Parity prototypes landed** – `oneiric.runtime.events.EventDispatcher` and `oneiric.runtime.dag` implement the reference event fan-out and DAG execution loops with accompanying tests (`tests/runtime/test_parity_prototypes.py`). These spikes validate the anyio + msgspec + networkx approach ahead of production integration.
1. **Dispatcher/DAG wired into runtime + CLI** – `EventBridge` and `WorkflowBridge` now rebuild handler sets/DAG specs after every manifest or watcher refresh, the orchestrator triggers those refreshes, and the CLI exposes `event emit` + `workflow run` commands (with JSON output) so manifests can exercise fan-out/DAGs without bespoke scripts. Docs (`README.md`, `docs/examples/LOCAL_CLI_DEMO.md`) and tests (`tests/cli/test_commands.py::TestEventWorkflowCommands`) cover the new flows.
   - README `Quick Start` now includes `event emit` and `workflow run` commands so parity rehearsals can reuse a common set of snippets alongside the serverless quickstart.
   - Use `orchestrate --print-dag --inspect-json` or `workflow plan --json` to capture DAG topology/metadata without executing nodes; attach the JSON output to parity issues before running workflows.
1. **Handler resiliency + telemetry** – Event handlers can define `retry_policy` metadata (attempts/base/max delay/jitter). The dispatcher runs them through `run_with_retry`, logs structured `event-handler-*` telemetry, and surfaces attempt counts in CLI JSON so manifest operators can see when retries kick in (`tests/runtime/test_parity_prototypes.py` cover success/failure paths). Telemetry also ships via OTLP/Logfire spans (`get_tracer("runtime.events")`).
1. **DAG retries + checkpoints** – Workflow DAG nodes now accept the same `retry_policy` metadata as actions/events plus an optional checkpoint mapping so partially-complete runs can resume without re-running succeeded nodes. `oneiric.runtime.dag.execute_dag` persists per-node durations/attempts and raises `DAGExecutionError` when retries exhaust; `WorkflowBridge.execute_dag` exposes the checkpoint hook. Docs + sample manifests include retry examples; tests cover success, resume, and failure exhaust paths.

Use this section to keep parity stakeholders aware of the latest landings before the milestones below are updated.

______________________________________________________________________

## 1. Goals & Success Criteria

1. **Event routing parity** – dynamic subscription, filtering, and fan-out match ACB's event bus semantics while honoring Oneiric's resolver priorities.
1. **Task DAG orchestration** – DAG definitions, dependency management, retries, and checkpointing meet or exceed ACB's task runner so workflows can be ported without hybrid stacks.
1. **Service supervision** – lifecycle hooks, draining/pausing, and hot-reload policies keep long-lived adapters/services stable on Cloud Run + Crackerjack environments.
1. **Single cut-over** – Oneiric assumes all orchestration responsibilities; ACB orchestration code is retired once these milestones land (no hybrid deployments).
1. **Migration clarity** – docs, manifests, and CLI tooling let sibling repos cut over once parity tasks are complete.

______________________________________________________________________

## 2. Workstreams

### P1 – Event Routing & Dispatch

- **Resolver integration:** extend `oneiric.domains.events` to register listener metadata (filters, priority, fan-out policy) and expose it through remote manifests. ✅ Remote manifest schema now includes `event_filters`, `event_priority`, and `event_fanout_policy`, and `EventBridge` converts them into dispatcher metadata so handlers can be filtered and ranked without bespoke code.
- **Routing engine:** adopt `anyio` TaskGroups + `structlog` span IDs (with `msgspec` envelopes) for concurrent dispatch, allowing structured replay of log lines while keeping payload encoding fast. ✅ The spike in `oneiric.runtime.events` is now wired through `EventBridge` + `RuntimeOrchestrator`, and CLI/App docs describe how to emit events via `oneiric.cli event emit ...`.
- **Metadata schema:** ✅ `RemoteManifestEntry.capabilities` now accepts rich capability descriptors (event types, schema references, security posture) while keeping legacy string lists backwards compatible. Loader propagates both the capability names and full descriptors to candidate metadata so resolver explain output and CLI manifests can audit P1 adapters before routing changes.
- **Safety:** integrate `tenacity` retry profiles (already available in `oneiric.core.resiliency`) for transient failures, and wire response codes into runtime telemetry. ✅ Local config watchers now force `EventBridge`/`WorkflowBridge` to rebuild dispatcher/DAG metadata even when selections remain unchanged; remote loader already refreshes bridges after sync. Handler retries emit structured logs + CLI telemetry, and the dispatcher now records OTLP-friendly duration/attempt metrics for Logfire/OTLP adapters.

### P2 – Task Graph Execution

- **Graph modeling:** use `networkx` (or `graphlib` for stdlib-only mode) to describe DAGs so tasks inherit battle-tested topological sorting and cycle detection. ✅ Prototype lives in `oneiric.runtime.dag` and is now consumed by `WorkflowBridge`.
- **Execution runtime:** build an async task runner on top of `anyio.TaskGroup`, with pluggable persistence for checkpoints (sqlite initially, optional Cloud SQL later). ✅ Runtime now exposes node-level retry policies + an optional checkpoint mapping so partially completed DAGs can resume without re-running succeeded nodes; CLI `workflow run` inherits the behavior. Checkpoints now persist to configurable SQLite stores (defaults under `.oneiric_cache`) and the executor emits per-node metrics so dashboards can inspect retries/durations.
- **Scheduling adapters:** ✅ Cloud Tasks + Pub/Sub queue adapters now live under `oneiric.adapters.queue.*` with docs/tests. `WorkflowBridge.enqueue_workflow` and the orchestrator now use the adapter bridge directly, honoring workflow metadata and `[workflows.options.queue_category]` so Cloud Tasks becomes the default scheduler without CLI overrides (`apscheduler` remains optional for Crackerjack cron flows).
- **Manifest support:** ✅ Remote manifest schema, samples, and Cloud Run docs now describe DAG metadata (`metadata.scheduler`, retry policies, queue selection) end-to-end. `tests/integration/test_e2e_workflows.py::test_remote_manifest_workflow_scheduler_metadata` covers manifest-driven scheduler routing, and `docs/deployment/CLOUD_RUN_BUILD.md` details how Cloud Tasks callbacks hit the builtin HTTP server exposed by `oneiric.cli orchestrate`.

### P3 – Service Supervisors & Health

- **Supervisor loop:** promote the orchestrator into a first-class service supervisor that watches `DomainActivityStore`, respects draining windows, and coordinates health probes across adapters/services/tasks.
- **Serverless profile:** codify Cloud Run toggles (disable long-running watchers, rely on manifest snapshots, load secrets via Secret Manager) and document Procfile/buildpack commands (see `SERVERLESS_AND_PARITY_EXECUTION_PLAN.md` §3).
- **Secrets + config:** prefer Secret Manager + env overrides; keep remote watchers optional for serverless workloads per Track G design.

#### Status Snapshot (Dec 2025)

- ✅ `DomainActivityStore` + CLI pause/drain commands already persist flags per domain key (`oneiric.runtime.activity`, `oneiric.cli activity/pause/drain`) and `RuntimeOrchestrator` exports the current snapshot to `runtime_health.json`.
- ✅ `LifecycleManager` exports uniform status payloads + health probes, so the supervisor layer can reuse those results when gating restarts/draining.
- ✅ `SecretsHook.prefetch()` now warms the configured secrets adapter during orchestrator start, and the CLI `health` command emits `profile` + `secrets` metadata (including provider readiness) so operators can confirm serverless toggles and Secret Manager status without digging into logs.
- ✅ `RuntimeHealthSnapshot` now merges supervisor pause/drain state with lifecycle statuses; `oneiric cli health` prints the new `lifecycle_state` block so Cloud Run probes and Crackerjack dashboards can reason about draining windows without scraping multiple files.
- ✅ The orchestrator now registers each bridge with the shared `ServiceSupervisor`, which polls the activity store, blocks dispatch via `should_accept_work()`, and broadcasts pause/drain deltas to domain bridges so adapters/tasks/services consume the same throttling decisions without bespoke refresh logic.
- ✅ Serverless profile toggles remain the default and the Procfile/buildpack docs (`docs/deployment/CLOUD_RUN_BUILD.md`) plus the CLI demo now call out the supervisor loop, `--health-path`, and cache requirements so Cloud Run teams know when to rely on manifest snapshots vs. remote refresh.
- ✅ README + `docs/examples/LOCAL_CLI_DEMO.md` now surface `supervisor-info`, `activity`, and `health --probe --json` transcripts required for GA proofs, and `docs/deployment/CLOUD_RUN_BUILD.md` embeds the same CLI evidence in the sample buildpack transcript.
- ✅ `docs/runbooks/SERVICE_SUPERVISOR.md` documents the pause/drain workflow, CLI proofs, and Cloud Run expectations so operators have a single reference during cut-over rehearsals.

#### Implementation Plan

1. **Supervisor loop + activity enforcement**

   - Introduce `oneiric.runtime.supervisor.ServiceSupervisor` that is instantiated by `RuntimeOrchestrator.start()` and runs a lightweight polling loop to:
     - watch the shared `DomainActivityStore` for pause/drain deltas and update per-domain throttles for adapters/services/tasks/workflows (the supervisor now exposes listener hooks so bridges consume activity deltas immediately).
     - coordinate draining: once a domain is marked draining, stop accepting new work (event/task dispatch), await `LifecycleManager` instance drains, and surface the progress through the CLI (`oneiric cli activity --json` + `health --probe`).
     - ✅ consolidate lifecycle status + runtime health JSON into one snapshot (PID, watchers, remote sync telemetry, activity counts, lifecycle statuses) so Cloud Run health probes and Crackerjack dashboards can read a single file.
   - Extend bridges with a `should_accept_work()` helper that consults supervisor state; dispatcher/DAG executors must exit early when paused/draining (now wired via supervisor listeners so adapters/tasks/services share throttling state).
   - Document the operator touchpoints for the new flag: `oneiric cli supervisor-info` reports whether the supervisor loop is enabled (from profile, config, or `ONEIRIC_RUNTIME_SUPERVISOR__ENABLED`), so parity runbooks reference a single command when validating Cloud Run toggles.
   - Tests: ✅ `tests/runtime/test_supervisor.py` covers pause/drain enforcement + listener deltas, and `tests/runtime/test_orchestrator.py::test_supervisor_disabled_*` plus `test_health_snapshot_includes_activity_state` assert the orchestrator obeys the `runtime.supervisor.enabled` flag and persists supervisor activity into `runtime_health.json`. CLI demos are updated to guide operators through the same verification flow.

1. **Serverless profile hardening**

   - Move the orchestration profile knobs from ad-hoc `settings.profile` checks into a typed `RuntimeProfileConfig` consumed by supervisor/orchestrator so Cloud Run deploys only start watchers that are explicitly enabled.
   - Update `Procfile*`, `README.md`, and `docs/deployment/CLOUD_RUN_BUILD.md` with a supervisor-focused runbook: how to ship pre-packed manifests, which env vars (`ONEIRIC_PROFILE=serverless`, `ONEIRIC_ACTIVITY_STORE`) control watcher behavior, and where `runtime_health.json`/activity sqlite live inside the container for `gcloud run services describe`.
   - Add CLI usage (`oneiric cli orchestrate --profile serverless --no-remote --health-path /var/tmp/runtime_health.json`) to the docs so platform teams can verify supervisor telemetry locally before deploying.

1. **Secrets + config + remote optionality**

   - Wire supervisor startup to the secrets hook so it can prefetch Secret Manager values needed for health probes (e.g., adapters that require credentials to run `ping()` methods) without blocking first request.
   - Document the precedence order (Secret Manager → env vars → manifest overrides) inside this plan and `SERVERLESS_AND_PARITY_EXECUTION_PLAN.md`, highlighting how serverless runs default to manifest snapshots with remote refresh opt-in. Operators should run `oneiric cli health --probe --json` (or the `uv run ... --demo` equivalent) before deploys to capture the `secrets` block showing provider + status.
   - Extend `oneiric.cli health --probe` to optionally emit secret/provider metadata (sanitized) so ops can confirm which secret providers are active in serverless vs. long-running profiles.
   - ✅ The CLI now prints `profile` + `secrets` blocks (JSON and human output) and the serverless docs instruct operators to verify the `status=ready` Secret Manager indicator before deploys.

1. **Rollout + validation**

   - Feature-flag the supervisor loop behind `runtime.supervisor.enabled` for one release; enable it by default once tests and docs land. Capture the expected CLI proof (sample `supervisor-info`, `activity --json`, `health --probe --json` output) in `docs/examples/LOCAL_CLI_DEMO.md` so downstream repos can paste the same transcript into their Cloud Run smoke tests.
   - ✅ Capture CLI transcripts (`activity`, `health --probe`, orchestrator logs) and include them in `docs/examples/LOCAL_CLI_DEMO.md` so teams can attach the same JSON artifacts to their Cloud Run rehearsals.
   - ✅ Integration coverage (`tests/integration/test_supervisor_orchestrate.py`) now boots the supervisor-enabled orchestrator, enforces pause/drain via the `service` bridge, and verifies `runtime_health.json` mirrors the activity store. The default `uv run pytest` CI job exercises this suite, so downstream repos can rely on the bundled transcripts + tests instead of wiring bespoke supervisor smoke loops.
   - ✅ README serverless quickstart + `docs/deployment/CLOUD_RUN_BUILD.md` transcripts show the GA workflow: run `supervisor-info`, `health --probe --json`, and include the outputs with deploy tickets so supervisors are validated alongside serverless toggles/secrets.
   - ✅ `docs/examples/LOCAL_CLI_DEMO.md` now instructs operators to dump `.oneiric_cache/runtime_health.json` after running the CLI probes so GA evidence contains both the structured CLI output and the persisted health snapshot used by Cloud Run.

#### P3 Deliverables & Owners

| Track | Deliverable | Artifacts | Owner(s) | Exit Criteria |
|-------|-------------|-----------|----------|---------------|
| Supervisor runtime | `oneiric.runtime.supervisor.ServiceSupervisor`, bridge gating, lifecycle drain orchestration | New runtime module + tests (`tests/runtime/test_supervisor.py`), bridge helper APIs, orchestrator wiring | Platform Core (Runtime) | Pause/drain state blocks dispatch; runtime health JSON mirrors supervisor state; tests cover drain + resume |
| Serverless ergonomics | Profile wiring + docs updates | `RuntimeProfileConfig` refactor, `README.md`, `docs/deployment/CLOUD_RUN_BUILD.md`, Procfile samples, CLI help | Platform Core + Docs | Serverless profile instructions mention supervisor; Procfile/CLI examples run supervisor loop; buildpack guide references activity/health paths |
| Secrets/config posture | Secrets preload + probe metadata | `oneiric.core.config` profile precedence docs, CLI `health --probe` metadata enhancements, plan cross-links | Platform Core (Config) | Health probe output shows secrets provider info; docs explain Secret Manager precedence |
| Validation | CI smoke + demo evidence | ✅ `tests/integration/test_supervisor_orchestrate.py`, default `uv run pytest` pipeline, updated `docs/examples/LOCAL_CLI_DEMO.md` transcript | Platform Core + QA | Supervisor-enabled orchestrator passes CI and documented demo |

**Phase status:** ✅ All exit criteria for P3 are satisfied (supervisor enforcement, serverless ergonomics, secrets precedence, and validation evidence), so this workstream is considered complete.

### P4 – Observability & Tooling

- ✅ **CLI enhancements:** `oneiric.cli orchestrate --print-dag` and `--events` now stream inspector payloads (human or `--inspect-json`) without booting the runtime loop. Inspectors surface DAG topology, queue metadata, handler concurrency, filters, and the supervisor’s pause/drain snapshot so MCP dashboards can render parity views.
- ✅ **Telemetry:** a new `runtime_telemetry.json` sink (mirroring the remote telemetry writer) records event handler attempts + workflow node durations. The dispatcher + DAG engine feed the recorder, and Logfire/OTLP exporters pick up the structured logs for Crackerjack dashboards.
- ✅ **Docs:** `docs/ONEIRIC_VS_ACB.md`, the parity plan, and repo-specific guides (Crackerjack, Fastblocks, session-mgmt-mcp) document how to capture DAG/Event inspectors, where telemetry lives, and how to replay the flows with `uv run python -m oneiric.cli`.
- ✅ **Event routing runbook:** `docs/examples/EVENT_ROUTING_OBSERVABILITY.md` now walks through the subscriber inspector, CLI `event emit`, and telemetry capture required for M1 proofs.
- ✅ **Workflow/DAG observability:** `docs/examples/FASTBLOCKS_OBSERVABILITY.md` includes `workflow run` + `workflow enqueue` commands, checkpoint capture instructions, and telemetry artifacts so the M2 DAG runtime deliverables have concrete evidence.
- ✅ **ChatOps:** the existing Slack/Teams/Webhook adapters stay wired to `workflow.notify`, and the new documentation walks platform teams through forwarding inspector + telemetry output into their ChatOps rooms alongside the notification payloads.

### P6 – ChatOps Integration

- ✅ **Action → Adapter bridge:** a new `NotificationRouter` (see `oneiric/runtime/notifications.py`) converts `workflow.notify` payloads into `NotificationMessage` objects and forwards them via `AdapterBridge`. The CLI’s `action-invoke workflow.notify` command now emits to ChatOps when `--workflow`/`--send-notification` flags are provided, and tests cover the router + route derivation.
- ✅ **Manifest hints:** workflow candidates can set `metadata.notifications` (adapter key/provider overrides, default channel/target, title templates, context flags, extra payload) and the CLI resolves those hints automatically. The parity fixture (`docs/examples/FASTBLOCKS_PARITY_FIXTURE.yaml`) and observability guides document the schema so manifests stay self-describing.
- ✅ **Serverless posture:** observability guides + LOCAL_CLI_DEMO now describe how to configure Slack/Teams/Webhook adapters in serverless profiles, reuse Secret Manager, and capture CLI transcripts that include the ChatOps dispatch so Cloud Run rehearsals prove parity without ACB.

### P5 – Migration & Validation

- ✅ **Parity fixture:** `docs/examples/FASTBLOCKS_PARITY_FIXTURE.yaml` now mirrors the Fastblocks DAG (event trigger, tasks, notify action, queue adapter). `tests/integration/test_migration_parity.py` exercises the manifest through `RuntimeOrchestrator.sync_remote`, ensuring each domain registers and the DAG cache refreshes.
- ✅ **Cut-over checklist:** `docs/implementation/CUTOVER_VALIDATION_CHECKLIST.md` lists the adapter coverage, manifest snapshot, CLI transcript, and telemetry artifacts each repo must attach before switching from ACB. The table at the end tracks Crackerjack, Fastblocks, and session-mgmt readiness.

______________________________________________________________________

## 3. Milestones

| Milestone | Target | Deliverables |
|-----------|--------|--------------|
| **M1 – Event routing beta** | Jan 2026 | Updated `oneiric.domains.events`, manifest schema, CLI inspect command, unit tests. |
| **M2 – DAG runtime alpha** | Feb 2026 | `networkx`-backed DAG engine, sqlite checkpoint store, CLI `workflow plan` + `orchestrate --print-dag --inspect-json` output, integration tests. |
| **M3 – Service supervisor GA** | Mar 2026 | Orchestrator refactor, serverless profile docs, health/watchers telemetry, Procfile examples. |
| **M4 – Repo cut-over rehearsals** | Apr 2026 | Fastblocks + Crackerjack runbooks updated, parity test suites running in CI, MCP references swapped to Oneiric. |

______________________________________________________________________

## 4. Dependencies & Open Questions

- **Existing libs:** `anyio`, `networkx`, `msgspec`, `tenacity`, `sqlite3` already approved; Cloud Tasks is the default scheduler for serverless triggers, while `apscheduler` remains under evaluation for long-lived cron workloads (Crackerjack/local dev).
- **Secrets strategy:** ✅ Crackerjack and Fastblocks both run on Secret Manager, so migration docs can describe the Secret Manager → env → manifest precedence without calling out `.env` stopgaps beyond local dev.
- **Testing infra:** coordinate with Crackerjack QA for shared parity fixtures.

______________________________________________________________________

## 5. Status Tracking

- Progress is tracked in this document and summarized in `docs/STRATEGIC_ROADMAP.md` (§3).
- Execution details live beside other remediation work in `docs/implementation/ADAPTER_REMEDIATION_EXECUTION.md` (§7).
- Update this plan whenever milestones shift or new dependencies surface so sibling repos know exactly what is left before the single-swoop cut-over.
