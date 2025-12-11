# Adapter Remediation & Execution Plan

**Date:** 2025-12-03
**Owner:** Platform Core (Oneiric)
**Scope:** Close the gaps identified in the adapter review (registration, dependencies, regression fixes, and roadmap accuracy) and prepare pending ports.
**Execution Tracker:** `docs/implementation/ADAPTER_REMEDIATION_EXECUTION.md`
**Strategy Snapshot:** `docs/STRATEGIC_ROADMAP.md`

______________________________________________________________________

## 1. Objectives

1. **Restore adapter availability** – ensure every newly added adapter (DuckDB, vector, embedding, LLM) can be resolved and exercised through `AdapterBridge`.
1. **Fix regressions** – revert the HTTP adapter to an async client and repair broken remote watcher tests.
1. **Unblock dependencies/tests** – declare required extras (pinecone-client, qdrant-client, duckdb, openai, sentence-transformers, onnxruntime, transformers, anthropic, numpy) and add smoke coverage.
1. **Align roadmap** – update docs to distinguish completed adapters vs remaining ACB backlog (pgvector, MongoDB, DynamoDB, Firestore, Gemini, DNS, FTP, messaging).

______________________________________________________________________

## 1.1 Direction Updates (Dec 2025)

- **Target runtime:** Google Cloud Run / serverless-first. Optimize builds for Cloud Run buildpacks, ship a Procfile, and keep Docker optional.
- **Platform goal:** Oneiric will ultimately replace ACB end-to-end (adapters + services/tasks/events). There will be no hybrid deployment in production; plan for a single cut-over when parity lands.
- **Deployment posture:** Hot-swapping/config watchers remain valuable for long-lived Crackerjack-like services; serverless profiles should default to stateless resolver loads and lazy imports to keep cold starts low.

______________________________________________________________________

## 2. Work Breakdown

| Track | Tasks | Owners | Notes |
|-------|-------|--------|-------|
| **Registration** | - Extend `builtin_adapter_metadata()` with DuckDB, Pinecone, Qdrant, OpenAI/SentenceTransformers/ONNX embeddings, OpenAI/Anthropic LLMs.<br>- Ensure `AdapterBridge` smoke test exercises at least one of each new category. | Platform Core | File: `oneiric/adapters/bootstrap.py` |
| **Dependencies** | - Add runtime extras in `pyproject.toml` under `adapters` group or new `[dependency-groups.ai]`.<br>- Document installation instructions in `docs/EMBEDDING_ADAPTERS.md`, `docs/VECTOR_ADAPTERS.md`, etc.<br>- Verify `uv lock` captures new packages. | Platform Core | Keep numpy import localized if possible. |
| **HTTP Adapter Regression** | - Reintroduce `httpx.AsyncClient` usage plus per-request options.<br>- Update tests to cover async flow without bypassing the client via mocks.<br>- Add regression test that ensures `await adapter.get(...)` performs an awaited call. | Runtime Team | Files: `oneiric/adapters/http/httpx.py`, `tests/adapters/test_http_adapter.py`, `tests/actions/test_http_action.py`. |
| **Remote Watcher Tests** | - Restore correct `RemoteSourceConfig` usage when calling `sync_remote_manifest`.<br>- Add fixture helpers for file-based manifests.<br>- Ensure tests use the watcher entrypoints (async loop). | Runtime Team | File: `tests/integration/test_remote_watchers.py`. |
| **Base Module Strategy** | - Retire legacy `_base.py` modules in favor of `common.py` helpers per adapter category.<br>- Guard heavy imports (`numpy`) behind optional extras and add tests covering shared helpers. | Platform Core + AI Team | Files: `oneiric/adapters/embedding/common.py`, `vector/common.py`, `llm/common.py`, `nosql/common.py`. |
| **Resiliency & Runtime** | - Replace remote artifact fetching with `httpx.AsyncClient` streaming.<br>- Swap retries/circuit breakers to `tenacity` + `aiobreaker` wrappers.<br>- Rebuild selection watchers on filesystem events (`watchfiles`) with serverless-friendly fallbacks.<br>- Move domain activity persistence to a sqlite-backed store. | Platform Core + Runtime Team | Files: `oneiric/remote/loader.py`, `oneiric/core/resiliency.py`, `oneiric/runtime/watchers.py`, `oneiric/runtime/activity.py`. |
| **Roadmap Update** | - Amend `docs/analysis/ADAPTER_STRATEGY.md` & `docs/implementation/ADAPTER_PORT_SUMMARY.md` to reflect shipped adapters and outstanding backlog.<br>- Add section enumerating missing ACB adapters (pgvector, MongoDB, DynamoDB, Firestore, Gemini, DNS, FTP, messaging) with target releases.<br>- Reference `docs/implementation/MESSAGING_AND_SCHEDULER_ADAPTER_PLAN.md` for Wave 2 delivery. | Docs Team | Provide matrix mapping ACB → Oneiric status. |

### 2.1 Gap Snapshot (Dec 2025)

The current backlog extracted from `docs/analysis/ADAPTER_GAP_AUDIT.md` focuses on two tracks that must be resolved before the single-swoop cut-over:

1. **Graph/Feature stores** – ✅ Completed (Neo4j + ArangoDB + DuckDB PGQ shipped Dec 2025). Keep Neptune as optional follow-up if requirements land.
1. **DNS/File transfer** (Cloudflare/Route53 + FTP/SFTP) – Security/Infra backlog for Wave C unless FastBlocks/Crackerjack request earlier delivery.

Keep this section synchronized with the audit table to avoid duplicating stale TODOs across plans.

______________________________________________________________________

## 3. Execution Timeline

1. **Day 0-1:** Registration + dependency updates + HTTP adapter fix.
1. **Day 1-2:** Remote watcher tests + base module decision + smoke coverage.
1. **Day 2:** Documentation refresh + backlog matrix + sign-off.

______________________________________________________________________

## 4. Acceptance Criteria

- `uv run pytest -k "adapter or remote_watchers"` passes locally.
- `oneiric.adapters.bootstrap.builtin_adapter_metadata()` exposes metadata for every shipped adapter (verified via unit test / CLI `--demo list --domain adapter`).
- Docs plainly separate “shipped” vs “pending” adapters, and list missing ACB ports with owner + ETA.
- No async/sync regressions in HTTP adapter; actions relying on HTTP clients run without blocking.
- Remote watcher integration tests use `RemoteSourceConfig` and `sync_remote_manifest` correctly.

______________________________________________________________________

## 5. Open Questions / Follow-Ups

1. Do we further split the new `common.py` helper modules into lighter mixins before more adapters land?
1. Should AI/LLM adapters ship as optional extras (e.g., `pip install oneiric[ai]`)? Need packaging strategy.
1. Confirm whether future pgvector adapter should live under `database/` or `vector/` per roadmap.

______________________________________________________________________

**Next Review:** sync with stakeholders after completing Track 1 (registration + deps + HTTP fix) to confirm scope remains correct.
**Sign-off:** merge fixes + updated docs + test evidence into main branch before next Crackerjack run.

> **Compatibility note:** Some upstream SDKs (Anthropic, onnxruntime) currently ship wheels that conflict with Python 3.14 or `httpx>=1.0`. Document manual installation guidance instead of pinning them into `pyproject.toml` until upstream support lands.
