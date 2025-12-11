# Adapter Remediation – Execution Plan

**Last updated:** 2025-12-09  
**Owners:** Platform Core (primary), Runtime Team (HTTP + watcher suite), Docs Team (roadmap parity)  
**Strategy Reference:** `docs/STRATEGIC_ROADMAP.md`

This document translates the remediation strategy tracked in `ADAPTER_REMEDIATION_PLAN.md` into concrete execution steps with owners, success checks, and references to the outstanding ACB adapters we still need to port.

---

## 1. Objectives & Essential Features

| Objective | Description | Owner(s) | Success Checks |
|-----------|-------------|----------|----------------|
| Adapter availability | Every newly added adapter (DuckDB, Pinecone, Qdrant, OpenAI/SentenceTransformers/ONNX embeddings, OpenAI/Anthropic LLMs) resolves through `AdapterBridge`. | Platform Core | `oneiric.adapters.bootstrap.builtin_adapter_metadata()` exposes metadata for each adapter; `uv run python -m oneiric.cli --demo list --domain adapter` shows them. |
| Async HTTP parity | HTTP adapter uses an async client and actions don't regress when `httpx.AsyncClient` is absent. | Runtime Team | `tests/adapters/test_http_adapter.py` and `tests/actions/test_http_action.py` pass; manual demo call hits async path. |
| Remote watcher coverage | Remote watcher tests exercise `RemoteSourceConfig` + file-based manifests end-to-end. | Runtime Team | `tests/integration/test_remote_watchers.py` passes with real loader path. |
| Base module health | Finalize the new `common.py` helper modules (ex-`_base.py`) and guard expensive imports (`numpy`, heavy SDKs) so cold start stays light. | Platform Core + AI Team | Decision documented; tests cover base helpers; optional extras documented if needed. |
| Roadmap accuracy | Docs clearly separate shipped vs pending adapters and track every missing ACB adapter. | Docs Team | `docs/analysis/ADAPTER_STRATEGY.md` and `docs/implementation/ADAPTER_PORT_SUMMARY.md` list pending adapters with owners/ETAs. |

---

## 2. Workstreams & Tasks

### Track A – Registration & Metadata
1. ✅ Extend `builtin_adapter_metadata()` with DuckDB + AI/vector entries (done in `oneiric/adapters/bootstrap.py`).
2. ⏳ Add smoke coverage that instantiates each new adapter via `AdapterBridge` (unit test + CLI transcript).

### Track B – Dependencies & Packaging
1. ✅ Add `numpy` baseline + fix setuptools discovery (`pyproject.toml`).
2. ✅ Add optional extras for vector/embedding/LLM adapters (`pyproject.toml`: `vector-*`, `embedding-*`, `llm-*`, `ai`) and document the install flow.
3. ✅ Guard heavy imports in the `common.py` helper modules so they only load when extras installed (embedding/LLM helpers now lazy-load numpy + client SDKs).

### Track C – HTTP Adapter Regression
1. ✅ Reintroduce async-friendly client path with shim fallback (`oneiric/adapters/http/httpx.py`).
2. ✅ Cover regression with adapter/action tests (`tests/adapters/test_http_adapter.py`, `tests/actions/test_http_action.py`).
3. ⏳ Run remote/action suites under `uv run pytest -k "http"` to capture evidence.

### Track D – Remote Watcher Tests
1. ✅ Use real `RemoteSourceConfig` and manifest loader in tests (`tests/integration/test_remote_watchers.py`).
2. ⏳ Add fixture helper for file-backed manifests (under `tests/fixtures/remote/`).
3. ✅ Execute integration suite: `uv run pytest tests/integration/test_remote_watchers.py` (Dec 10 run, all 14 tests passing).

### Track E – Base Module Decision
1. ✅ Audit `_base.py` modules (`embedding`, `vector`, `llm`, `nosql`) for import-time side effects (e.g., `numpy` load) – see “Base Module Audit” below.
2. ✅ Rename `_base.py` modules to `common.py`, capture the decision in plan docs, and note remaining follow-ups.
3. ⏳ Add targeted unit tests ensuring helpers (chunking, scoring, metadata shaping) stay stable.

### Track F – Documentation & Backlog Hygiene
1. ✅ Update `docs/analysis/ADAPTER_STRATEGY.md` and `docs/implementation/ADAPTER_PORT_SUMMARY.md` with shipped adapters.
2. ✅ Capture remediation backlog + owners in `docs/implementation/ADAPTER_REMEDIATION_PLAN.md`.
3. ✅ Publish CLI transcripts / manifest snippets demonstrating the fixed adapters + watchers (`docs/examples/LOCAL_CLI_DEMO.md`, sample manifests for SendGrid/Mailgun/Twilio/Slack/Teams/Webhook + Cloud Tasks/Pub/Sub).
4. 🚧 Document NoSQL sprint execution plan in `docs/implementation/NOSQL_ADAPTER_SPRINT.md` and keep status synced as tasks close.

### Track G – Resiliency & Runtime Modernization
1. ✅ Remote artifact & manifest fetches now use `httpx.AsyncClient` streaming with digest verification and TLS toggles (`oneiric/remote/loader.py`).
2. ✅ Retry and circuit-breaker helpers wrap `tenacity.AsyncRetrying` and `aiobreaker.CircuitBreaker`, preserving `CircuitBreakerOpen` semantics (`oneiric/core/resiliency.py`).
3. ✅ Selection watchers prefer filesystem events via `watchfiles.awatch`, log their strategy, and automatically fall back to polling/serverless mode when watchers are disabled (`oneiric/runtime/watchers.py`).
4. ✅ Domain activity persistence moved from JSON snapshots to sqlite, giving us safe concurrent updates and reuse across bridges/CLI (`oneiric/runtime/activity.py`, `oneiric/core/config.py`).

**Evidence:** `uv run pytest tests/remote/test_loader.py tests/security/test_cache_paths.py tests/security/test_path_traversal.py tests/domains/test_base.py tests/adapters/test_bridge.py::TestAdapterBridgeActivity`.

---

## 3. Pending Adapter Ports (ACB → Oneiric)

| Category | Adapter(s) | Status | Owner | Notes |
|----------|------------|--------|-------|-------|
| Vector | `pgvector` | ✅ Complete | Platform Core | Asyncpg + pgvector adapter landed with tests + docs references. |
| NoSQL | `mongodb` (✅), `dynamodb` (✅), `firestore` (✅) | Complete | Data Platform (Nadia) | All NoSQL adapters shipped Dec 2025 with extras, manifests, CLI/docs coverage. |
| Graph | `neo4j` (✅), `arangodb` (✅), `duckdb_pgq` (✅), `neptune` | Complete / optional follow-up | Platform Core (Ravi) | All planned graph adapters shipped Dec 2025; revisit Neptune only if stakeholders request it. |
| Messaging | `kafka`, `rabbitmq` | Not started | Runtime Team (Eli) | Align with Stage 3 action migrations; target Feb 2026 after NoSQL. |
| DNS | `cloudflare`, `route53`, `gcdns` | Not started | Infra Team (Mara) | Requires separate secrets handling; targeted for Mar 2026. |
| File Transfer | `ftp`, `sftp` | Not started | Platform Core (Jules) | Gate behind optional extra; ensure security guidance; Mar 2026. |
| AI | `gemini` | Blocked | AI Team | Waiting on official Python SDK for 3.14/httpx1; review monthly. |

Backlog items should stay synchronized with `docs/implementation/ADAPTER_PORT_SUMMARY.md` and `docs/analysis/ADAPTER_STRATEGY.md`.

---

## 4. Base Module Audit

| Module | Findings | Recommended Action |
|--------|----------|--------------------|
| `oneiric/adapters/embedding/common.py` | Replaces `_base.py`; lazy `numpy` loader `_require_numpy()` added 2025-12-05. | Add helper tests + consider splitting heavy math helpers into mixins if adapters diverge. |
| `oneiric/adapters/vector/common.py` | Shared models/helpers with only stdlib + Pydantic deps. | Add tests for `VectorCollection` wrappers and guard future heavy deps. |
| `oneiric/adapters/llm/common.py` | Stdlib + Pydantic only; provides completion + streaming helpers. | Add smoke coverage for chat/stream scaffolding. |
| `oneiric/adapters/nosql/common.py` | Thin lifecycle helper shared by upcoming adapters. | Expand once first NoSQL adapter lands; add docs referencing new module. |

Decision/implementation notes should be appended once we either lazily import heavy deps or split the helpers into lighter modules.

---

## 5. Execution Timeline & Evidence

| Day | Focus | Commands / Evidence |
|-----|-------|---------------------|
| Day 0 | Track A + C hardening | `uv run pytest tests/adapters/test_bootstrap_metadata.py tests/adapters/test_http_adapter.py tests/actions/test_http_action.py` |
| Day 1 | Track B + D coverage | `uv run pytest tests/integration/test_remote_watchers.py` plus CLI demo of adapter listing/action invocation |
| Day 2 | Track E decision + Track F docs | PR notes + doc diffs + manifest snippets |
| Day 3-4 | Track G runtime upgrades | Remote sync logs with httpx, resiliency unit tests, watcher/activity regression tests |

Document CLI transcripts (`oneiric.cli --demo list --domain adapter`, `--demo action-invoke compression.encode …`) inside `docs/examples/` once fixes land.

---

## 6. Risks & Mitigations

- **Heavy optional deps** (Anthropic, onnxruntime) may still block installs → keep them as manual installs and note in docs until upstream catches up.
- **Async regressions** from `httpx` 1.x vs 0.27 differences → maintain shim + tests ensuring `AsyncClient` is preferred when present.
- **Base module churn** could cause adapter code duplication → land decision quickly and add mixin helpers as we standardize on `common.py`.
- **ACB parity drift** → backlog table above must be updated whenever a new adapter ships; tie into release checklist.

---

## 7. Next Actions

1. ✅ Finish Track B (extras decision + guarded imports) and Track D test execution.
2. ✅ Run the broader adapter + watcher suites and attach logs to the next PR (`uv run pytest tests/integration/test_remote_watchers.py` on Dec 10).
3. ✅ Completed the first missing adapter port (`pgvector`) using the new `common.py` helpers, asyncpg pool factory, and CLI/tests.
4. ✅ Landed the Mailgun/Twilio messaging adapters plus Cloud Tasks/Pub/Sub queue adapters with docs/tests so orchestration parity work can use them immediately.
5. Stand up the serverless/Cloud Run profile: add Procfile, document buildpack-first deployments, and capture any runtime toggles needed for stateless invocations.
6. Socialize the new orchestration parity roadmap (events, task DAGs, service supervisors) so we can execute a single Oneiric cut-over without maintaining a hybrid deployment.
7. **Upcoming priority:** with NoSQL + streaming queues delivered, focus shifts to graph adapters and the remaining DNS/FileTransfer backlog. Keep `docs/analysis/ADAPTER_GAP_AUDIT.md` synced as those land.
8. Kick off NoSQL sprint per `docs/implementation/NOSQL_ADAPTER_SPRINT.md`: land extras + metadata (Week 1), then MongoDB → DynamoDB → Firestore adapters with tests/docs checkpoints.

Track completion in this document and mirror updates back to `ADAPTER_REMEDIATION_PLAN.md` so both strategy and execution views remain aligned. Track G closed on 2025-12-06 with the upgrades + tests noted above.
