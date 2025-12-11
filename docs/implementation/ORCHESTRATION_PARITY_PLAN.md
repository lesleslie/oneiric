# Oneiric Orchestration Parity Plan

**Last Updated:** 2025-12-06
**Owner:** Platform Core & Runtime Team
**Purpose:** Outline the remaining work to bring Oneiric's events, tasks, and service orchestration capabilities to full parity with ACB so Crackerjack, Fastblocks, and session-mgmt-mcp can run solely on Oneiric.

______________________________________________________________________

## Recent Progress (December 2025)

1. **Serverless entrypoints aligned** – `Procfile` + `Procfile.cloudrun` now share the canonical `uv run python -m oneiric.cli orchestrate --profile serverless --no-remote` command, and the Cloud Run buildpack guide contains the end-to-end transcript for CI/reference. Cold-start toggles live in `RuntimeProfileConfig`.
1. **Messaging + scheduler bridges shipped** – Mailgun/SendGrid/Twilio plus Slack/Teams/Webhook adapters and the Cloud Tasks/Pub/Sub queue adapters are in-tree with CLI/tests (WS-C dependencies ready for DAG/event routing). Cloud Tasks is the default DAG scheduler; APScheduler remains optional for long-lived Crackerjack cron flows.
1. **Remote/resiliency modernized** – httpx + tenacity/aiobreaker loader, sqlite activity store, and watchfiles-based watchers are complete (Track G follow-up), so event/task orchestration can lean on the updated runtime primitives without bespoke patches.
1. **Parity prototypes landed** – `oneiric.runtime.events.EventDispatcher` and `oneiric.runtime.dag` implement the reference event fan-out and DAG execution loops with accompanying tests (`tests/runtime/test_parity_prototypes.py`). These spikes validate the anyio + msgspec + networkx approach ahead of production integration.
1. **Dispatcher/DAG wired into runtime + CLI** – `EventBridge` and `WorkflowBridge` now rebuild handler sets/DAG specs after every manifest or watcher refresh, the orchestrator triggers those refreshes, and the CLI exposes `event emit` + `workflow run` commands (with JSON output) so manifests can exercise fan-out/DAGs without bespoke scripts. Docs (`README.md`, `docs/examples/LOCAL_CLI_DEMO.md`) and tests (`tests/cli/test_commands.py::TestEventWorkflowCommands`) cover the new flows.
1. **Handler resiliency + telemetry** – Event handlers can define `retry_policy` metadata (attempts/base/max delay/jitter). The dispatcher runs them through `run_with_retry`, logs structured `event-handler-*` telemetry, and surfaces attempt counts in CLI JSON so manifest operators can see when retries kick in (`tests/runtime/test_parity_prototypes.py` cover success/failure paths). Telemetry also ships via OTLP/Logfire spans (`get_tracer("runtime.events")`).
1. **DAG retries + checkpoints** – Workflow DAG nodes now accept the same `retry_policy` metadata as actions/events plus an optional checkpoint mapping so partially-complete runs can resume without re-running succeeded nodes. `oneiric.runtime.dag.execute_dag` persists per-node durations/attempts and raises `DAGExecutionError` when retries exhaust; `WorkflowBridge.execute_dag` exposes the checkpoint hook. Docs + sample manifests include retry examples; tests cover success, resume, and failure exhaust paths.

Use this section to keep parity stakeholders aware of the latest landings before the milestones below are updated.

______________________________________________________________________

## 1. Goals & Success Criteria

1. **Event routing parity** – dynamic subscription, filtering, and fan-out match ACB's event bus semantics while honoring Oneiric's resolver priorities.
1. **Task DAG orchestration** – DAG definitions, dependency management, retries, and checkpointing meet or exceed ACB's task runner so workflows can be ported without hybrid stacks.
1. **Service supervision** – lifecycle hooks, draining/pausing, and hot-reload policies keep long-lived adapters/services stable on Cloud Run + Crackerjack environments.
1. **Serverless-first ergonomics** – cold start budgets, buildpack-based deployments, manifest packaging, and Procfile launches require no Docker-specific logic.
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
- ⏳ The orchestrator still treats bridges in isolation—there is no shared "ServiceSupervisor" that enforces draining windows, schedules coordinated swaps, or broadcasts activity deltas to adapters/tasks/services.
- ⏳ Serverless profile toggles exist (watchers/remote disabled by default) but the Procfile/buildpack docs and CLI help need supervisor-specific guidance (e.g., when to rely on manifest snapshots vs. remote refresh).

#### Implementation Plan

1. **Supervisor loop + activity enforcement**

   - Introduce `oneiric.runtime.supervisor.ServiceSupervisor` that is instantiated by `RuntimeOrchestrator.start()` and runs a lightweight `anyio` TaskGroup to:
     - watch the shared `DomainActivityStore` for pause/drain deltas (poll + sqlite triggers) and update per-domain throttles for adapters/services/tasks/workflows.
     - coordinate draining: once a domain is marked draining, stop accepting new work (event/task dispatch), await `LifecycleManager` instance drains, and surface the progress through the CLI (`oneiric cli activity --json` + `health --probe`).
     - consolidate lifecycle status + runtime health JSON into one snapshot (PID, watchers, remote sync telemetry, activity counts) so Cloud Run health probes and Crackerjack dashboards can read a single file.
   - Extend bridges with a `should_accept_work()` helper that consults supervisor state; dispatcher/DAG executors must exit early when paused/draining.
   - Tests: new `tests/runtime/test_supervisor.py` covering pause/drain enforcement, draining timeouts, and health snapshot updates; update CLI integration tests to assert supervisor-blocked dispatch.

1. **Serverless profile hardening**

   - Move the orchestration profile knobs from ad-hoc `settings.profile` checks into a typed `RuntimeProfileConfig` consumed by supervisor/orchestrator so Cloud Run deploys only start watchers that are explicitly enabled.
   - Update `Procfile*`, `README.md`, and `docs/deployment/CLOUD_RUN_BUILD.md` with a supervisor-focused runbook: how to ship pre-packed manifests, which env vars (`ONEIRIC_PROFILE=serverless`, `ONEIRIC_ACTIVITY_STORE`) control watcher behavior, and where `runtime_health.json`/activity sqlite live inside the container for `gcloud run services describe`.
   - Add CLI usage (`oneiric cli orchestrate --profile serverless --no-remote --health-path /var/tmp/runtime_health.json`) to the docs so platform teams can verify supervisor telemetry locally before deploying.

1. **Secrets + config + remote optionality**

   - Wire supervisor startup to the secrets hook so it can prefetch Secret Manager values needed for health probes (e.g., adapters that require credentials to run `ping()` methods) without blocking first request.
   - Document the precedence order (Secret Manager → env vars → manifest overrides) inside this plan and `SERVERLESS_AND_PARITY_EXECUTION_PLAN.md`, highlighting how serverless runs default to manifest snapshots with remote refresh opt-in.
   - Extend `oneiric.cli health --probe` to optionally emit secret/provider metadata (sanitized) so ops can confirm which secret providers are active in serverless vs. long-running profiles.
   - ✅ The CLI now prints `profile` + `secrets` blocks (JSON and human output) and the serverless docs instruct operators to verify the `status=ready` Secret Manager indicator before deploys.

1. **Rollout + validation**

   - Feature-flag the supervisor loop behind `runtime.supervisor.enabled` for one release; enable it by default once tests and docs land.
   - Capture CLI transcripts (`activity`, `health --probe`, orchestrator logs) and include them in `docs/examples/LOCAL_CLI_DEMO.md` + this plan to prove parity.
   - Coordinate with Crackerjack/Fastblocks to add regression tests that start the supervisor-enabled orchestrator inside CI (using `uv run python -m oneiric.cli orchestrate --profile serverless --no-remote --workflow-checkpoints disabled`) and assert the runtime health payload includes pause/drain state + remote sync telemetry.

#### P3 Deliverables & Owners

| Track | Deliverable | Artifacts | Owner(s) | Exit Criteria |
|-------|-------------|-----------|----------|---------------|
| Supervisor runtime | `oneiric.runtime.supervisor.ServiceSupervisor`, bridge gating, lifecycle drain orchestration | New runtime module + tests (`tests/runtime/test_supervisor.py`), bridge helper APIs, orchestrator wiring | Platform Core (Runtime) | Pause/drain state blocks dispatch; runtime health JSON mirrors supervisor state; tests cover drain + resume |
| Serverless ergonomics | Profile wiring + docs updates | `RuntimeProfileConfig` refactor, `README.md`, `docs/deployment/CLOUD_RUN_BUILD.md`, Procfile samples, CLI help | Platform Core + Docs | Serverless profile instructions mention supervisor; Procfile/CLI examples run supervisor loop; buildpack guide references activity/health paths |
| Secrets/config posture | Secrets preload + probe metadata | `oneiric.core.config` profile precedence docs, CLI `health --probe` metadata enhancements, plan cross-links | Platform Core (Config) | Health probe output shows secrets provider info; docs explain Secret Manager precedence |
| Validation | CI smoke + demo evidence | `tests/integration/test_supervisor_orchestrate.py`, CI job hooking `uv run python -m oneiric.cli orchestrate --profile serverless --no-remote --health-path ...`, updated `docs/examples/LOCAL_CLI_DEMO.md` transcript | Platform Core + QA | Supervisor-enabled orchestrator passes CI and documented demo |

### P4 – Observability & Tooling

- **CLI enhancements:** add `oneiric.cli orchestrate --print-dag` and `--events` inspectors to mirror ACB's MCP dashboards.
- **Telemetry:** reuse `oneiric.remote.telemetry` sinks + OTLP/Logfire adapters for task timing + event retries, emitting structured logs compatible with Crackerjack dashboards.
- **Docs:** capture parity status plus migration steps in `docs/ONEIRIC_VS_ACB.md` and new how-to guides per repo (Crackerjack, Fastblocks, session-mgmt-mcp).
- **ChatOps:** wire the new Slack/Teams/webhook adapters into workflow notify hooks so orchestration events surface consistently across repos.

### P6 – ChatOps Integration

- **Action → Adapter bridge:** `workflow.notify` produces a structured record; orchestrators should translate that record into `NotificationMessage` instances and invoke the selected messaging adapter (Slack/Teams/Webhook) via `AdapterBridge`. The sample script in `docs/examples/LOCAL_CLI_DEMO.md` demonstrates the hand-off.
- **Manifest hints:** remote manifests may annotate workflows/tasks with `metadata.notifications.provider = "slack"` (or teams/webhook) so the orchestrator knows which adapter to resolve. Document this convention alongside the DAG manifest schema updates.
- **Serverless posture:** notification adapters obey the same serverless constraints (Secret Manager first, watchers disabled). Ensure Cloud Run profiles ship with at least one ChatOps adapter configured so parity tests can assert notifications without hitting ACB.

### P5 – Migration & Validation

- **Test suites:** create cross-repo fixtures (e.g., Fastblocks workflow) that run on both ACB and Oneiric to validate behavior before the cut-over.
- **Cut-over checklist:** document prerequisites (adapter coverage, manifest snapshots, CLI transcripts) and add an appendix to this plan when each sibling repo is ready.

______________________________________________________________________

## 3. Milestones

| Milestone | Target | Deliverables |
|-----------|--------|--------------|
| **M1 – Event routing beta** | Jan 2026 | Updated `oneiric.domains.events`, manifest schema, CLI inspect command, unit tests. |
| **M2 – DAG runtime alpha** | Feb 2026 | `networkx`-backed DAG engine, sqlite checkpoint store, CLI `orchestrate --plan` output, integration tests. |
| **M3 – Service supervisor GA** | Mar 2026 | Orchestrator refactor, serverless profile docs, health/watchers telemetry, Procfile examples. |
| **M4 – Repo cut-over rehearsals** | Apr 2026 | Fastblocks + Crackerjack runbooks updated, parity test suites running in CI, MCP references swapped to Oneiric. |

______________________________________________________________________

## 4. Dependencies & Open Questions

- **Existing libs:** `anyio`, `networkx`, `msgspec`, `tenacity`, `sqlite3` already approved; Cloud Tasks is the default scheduler for serverless triggers, while `apscheduler` remains under evaluation for long-lived cron workloads (Crackerjack/local dev).
- **Secrets strategy:** confirm Secret Manager usage for Crackerjack + Fastblocks so we can drop legacy `.env` readers during migration; env adapters stay for dev/local-only use.
- **Testing infra:** coordinate with Crackerjack QA for shared parity fixtures.

______________________________________________________________________

## 5. Status Tracking

- Progress is tracked in this document and summarized in `docs/STRATEGIC_ROADMAP.md` (§3).
- Execution details live beside other remediation work in `docs/implementation/ADAPTER_REMEDIATION_EXECUTION.md` (§7).
- Update this plan whenever milestones shift or new dependencies surface so sibling repos know exactly what is left before the single-swoop cut-over.
