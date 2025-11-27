# Stage 3 – Action Migration Plan

Purpose: port ACB’s action kits (tasks/events/workflows/helpers) into Oneiric’s
resolver so every action enjoys the same lifecycle, metadata, and hot-swap
guarantees as adapters.

## Waves & Scope

| Wave | Focus | Representative Kits | Exit Criteria |
| --- | --- | --- | --- |
| Wave A | Stateless + utility actions | compression/encoding, workflow automation helpers, validation shims | Action metadata/schema registered for each kit, CLI `list/explain` shows the kits, resolver swaps validated via unit tests. |
| Wave B | External-service actions | HTTP convenience wrappers, security/signature helpers, data processing/enrichment | Service actions honor SecretsHook/config bridging, tests cover retry/backoff + resolver precedence. |
| Wave C | Observability/debug + optional kits | console/debug helpers, metrics emitters, feature-flag or payments if retained | Hooks emit structured logs/OTel spans, optional kits documented & feature-flagged. |

## Deliverables Per Kit

1. **Metadata & Settings** – each action kit exposes `ActionMetadata` (domain,
   key, provider, capabilities, owner, requires_secrets) plus an optional
   `Settings` model for typed configuration.
2. **Lifecycle Hooks** – kits implement `prepare/execute/cleanup`, expose a
   health probe, and surface pause/drain semantics via the domain bridge.
3. **Resolver Registration** – register kits through `domains.*` bridges so CLI
   `list/explain` shows precedence/selection reasoning.
4. **Tests** – unit tests for lifecycle + resolver behavior plus integration
   coverage where external services are mocked.
5. **Docs** – README snippets + manifest/config samples mirroring the adapter
   documentation style.
6. **Naming** – action keys follow `<capability>.<verb>` (`compression.encode`, `data.sanitize`, `validation.schema`) so verbs stay visible while related helpers share a namespace.

## Kickoff Tasks

- [x] Document the plan (this file) and link it from the Stage 3 section in
  `docs/ACB_ADAPTER_ACTION_IMPLEMENTATION.md`.
- [x] Define `ActionMetadata` + bridge helpers mirroring adapter bridges so
  action kits can self-register (see `oneiric/actions/metadata.py` + CLI `action` domain).
- [x] Port the compression/encoding kit (Wave A) to validate the pipeline.
- [x] Update CLI docs/examples and provide `action-invoke` so kits can be executed directly from the CLI.
- [x] Expand test scaffolding (`tests/actions/…`) mirroring the adapter suite.

## Wave A Progress

- [x] `compression.encode` – validates metadata + lifecycle wiring for stateless helpers.
- [x] `compression.hash` – hashing helper supporting SHA-256/512 and Blake2b with hex/base64 output for quick checksum workflows.
- [x] `serialization.encode` – JSON/YAML/pickle serialization helper covering encode/decode plus optional file writes.
- [x] `workflow.audit` – structured audit/notification helper with payload redaction, CLI coverage, docs, and resolver registration.
- [x] `workflow.notify` – notification helper with channels/recipients/context returned via resolver + CLI tests.
- [x] `workflow.retry` – deterministic retry/backoff helper with metadata, resolver + CLI coverage.

## Wave B Progress

- [x] `http.fetch` – async HTTP convenience wrapper powered by `httpx.AsyncClient`, handles query/header merges, JSON parsing, timeout/redirect controls, plus CLI/manifest/provider settings coverage.
- [x] `security.signature` – HMAC helper that signs strings/JSON payloads (SHA-256/512/Blake2b) with configurable encoding/timestamp fields and SecretsHook alignment.
- [x] `security.secure` – secure token/password helper covering token generation, PBKDF2 password hashing, and timing-safe comparisons.
- [x] `data.transform` – declarative selector/rename/default action for shaping dict payloads pre-enrichment; exposes metadata/settings/tests mirroring adapters.
- [x] `data.sanitize` – allowlist/mask/drop helper for scrubbing sensitive fields prior to downstream routing.
- [x] `validation.schema` – lightweight schema guard enforcing required fields and type hints within payloads.

## Wave C Progress

- [x] `debug.console` – structured console/debug helper that logs via structlog, echoes to stdout, scrubs sensitive fields, and ships with settings/tests/docs so operators can trace workflows directly from the resolver.

## Workflow Orchestrator Progress

- [x] `workflow.orchestrate` – orchestration planner that ingests versioned workflow definitions, validates dependency graphs, enforces parallelism limits, and emits deterministic batches/graphs so long-running orchestrators can resume, pause, or replay runs while honoring the Stage 3 action metadata + CLI tooling.

## Task Runner Progress

- [x] `task.schedule` – cron/interval planner that validates windows, max-runs, tags, and queue metadata, emits deterministic future runs, and exposes resolver metadata/tests so schedulers can drive queue adapters without referencing the legacy ACB task scheduler.

## Event Dispatch Progress

- [x] `event.dispatch` – webhook/event dispatcher that emits structured envelopes and concurrent HTTP hooks (with dry-run/timeout controls) while logging hook outcomes for observability.

## Automation Utility Progress

- [x] `automation.trigger` – declarative rule engine that inspects runtime context, evaluates boolean/threshold/containment conditions, and returns the matching action payloads so automation flows retain the original “verb-first” naming pattern.

## Open Questions

- Which ACB kits deliver the most value early (compression vs. HTTP helpers vs.
  workflow automation)?
- Do we keep console/debug helpers separate or expose them as structured log
  processors + CLI conveniences?
- How should remote manifests express action selections (same schema as
  adapters or action-specific overrides)?

Track updates by editing this file alongside
`docs/ACB_ADAPTER_ACTION_IMPLEMENTATION.md` so Stage 3 progress stays visible.
