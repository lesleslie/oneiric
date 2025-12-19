# Build Prompts (Execution Checklist)

Use these prompts to drive implementation in an AI-assisted or task-tracking context.

## Phase 1: Core Resolution Layer

- "Implement `core/resolution` with Candidate model, registries, precedence rules,
  active/shadowed lists, and explain trace."
- "Add hot-swap primitives (pre/post hooks, health check, rollback, cleanup) in
  `core/lifecycle`."
- "Wire `register_pkg` priority inference (path-based map + env override) to feed
  resolver."
- "Add `core/runtime` TaskGroup/nursery helpers for structured concurrency."

## Phase 2: Adapter Modularization

- "Split adapters bootstrap into metadata, discovery, resolver bridge, lifecycle,
  public API modules."
- "Add stack_level to adapter metadata and move enablement to resolver."
- "Implement config/manifest watcher to trigger adapter swaps on diff."
- "Add CLI/debug commands: list/why/explain/swap for adapters; show active vs shadowed."
- "Add adapter provider settings models (Pydantic) and load via the new config layer."

## Phase 3: Cross-Domain Alignment

- "Migrate services, tasks, events, workflows to resolver-backed registries with the
  same precedence rules and shadow lists."
- "Add domain bridges (services/tasks/events/workflows) to map keys/providers to the
  resolver; include activation flags and swap hooks."
- "Define per-domain settings models and load through the config layer."

## Phase 4: Plugin Protocol & Remote Artifacts

- "Implement entry-point/pluggy-style discovery alongside path-based discovery."
- "Implement remote manifest fetch (HTTPS/S3/GCS/OCI) with sha/signature verification,
  cache, and install to vendor dir/sys.path; normalize candidates."
- "Add remote manifest/config location to settings; allow secret adapters to supply
  credentials/tokens."

## Phase 5: Observability & Resiliency

- "Wire OpenTelemetry tracing/metrics/logging into resolution, lifecycle, and domain
  bridges; add structured fields (domain/key/provider/source/priority/stack_level)."
- "Implement health/readiness hooks and swap-time checks."
- "Add shared backpressure/timeout helpers and retry/backoff + circuit breaker mixins
  for outbound adapters."

## Phase 6: Lifecycle & Safety

- "Finalize lifecycle contract: init/health/cleanup/pause-resume; enforce cleanup on
  swap and shutdown; rollback on failed init."
- "Add cancellation-safe utilities and ensure background work uses TaskGroup helpers."

## Phase 7: Tooling & UX

- "Build CLI commands across domains: list/why/explain/swap/health/show-sources."
- "Add sample manifests, stack-order env template, and remote adapter quickstart."
- "Expand tests: precedence matrix, swap rollback, remote fetch integrity, per-domain
  override behaviors."

## Config & Secrets

- "Implement Pydantic settings layer for selection + provider settings; include secret
  source hook that uses the configured secret adapter when enabled."
- "Define config schema (app/debug/adapters selection/adapter_settings/services/tasks/
  events/workflows/secrets/remote)."
