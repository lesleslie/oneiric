# Grand Implementation Plan (Oneiric)

This plan assumes no backward-compat constraints. It prioritizes clarity, modularity,
and modern async ergonomics.

## Objectives
- Extract a unified resolution layer (discovery + registration + resolver + swap).
- Modularize adapter bootstrap and align all domains (adapters/services/tasks/events/
  workflows) on the same precedence and lifecycle semantics.
- Add a plugin protocol, remote artifact pipeline, and robust lifecycle hooks.
- Standardize observability (tracing/metrics/logging) and resiliency patterns.
- Prepare for emerging async techniques (structured concurrency, durable execution,
  effect-like cancellation control).
- Keep typed configuration with Pydantic v2, retain secret adapters as config sources,
  and make adapter/provider settings first-class in the new stack.

## Phased Work

### Phase 1: Core Resolution Layer
- Implement resolver module (per SPEC) with in-memory registries, precedence rules,
  active/shadowed views, and explain/trace.
- Add candidate model with priority + stack_level.
- Wire `register_pkg` priority inference (path-based map, env override, fallback
  heuristics) feeding resolver.
- Add hot-swap primitives (pre/post hooks, health check, rollback, cleanup).
_- Add config bridge skeleton for selection (domain/key → provider) to feed resolver._

- ### Phase 2: Adapter Modularization
- Modularize adapter bootstrap into: metadata, discovery, resolver bridge,
  lifecycle, public import API.
- Add stack_level to adapter metadata; move enablement to resolver.
- Implement config/manifest watcher → swap adapters on diff.
- Add CLI/debug views for active vs shadowed adapters.
_- Introduce adapter provider settings models and load them via the new config layer
  (Pydantic settings); selection still goes through resolver._

### Phase 3: Cross-Domain Alignment
- Migrate services, tasks, events, workflows to resolver-backed registries:
  - Keys: service_id, task_type, event_name/type, workflow_id(+version).
  - Override semantics identical to adapters.
  - Shadow lists for observability.
- Add activation flags and swap hooks per domain (pause/drain for queues, graceful
  workflow transitions).
_- Add per-domain settings models (services/tasks/events/workflows) under the same
  Pydantic config layer; ensure secret sources can hydrate missing secrets where
  enabled._

### Phase 4: Plugin Protocol & Remote Artifacts
- Add entry-point style discovery (or pluggy-like) alongside path-based discovery.
- Implement remote manifest fetch (HTTPS/S3/GCS/OCI) with sha/signature, cache,
  and install (wheel/zip) into a vendor dir or sys.path prepend.
- Normalize remote candidates into resolver with source metadata.
- Optional: MCP/registry service for centralized descriptor delivery.
_- Add remote-config/manifest location to settings; allow secret adapters to supply
  credentials/tokens for remote fetch._

### Phase 5: Observability & Resiliency
- Standardize OpenTelemetry tracing/metrics across adapters/services/events/tasks/
  workflows; provide context propagation helpers.
- Add structured logging fields (domain, key, provider, source, priority).
- Health + readiness interfaces; swap-time and startup health checks.
- Backpressure/timeouts: shared helpers for per-domain defaults.

### Phase 6: Lifecycle & Safety
- Define lifecycle interface: init, health, cleanup, pause/resume (for stateful).
- Enforce cleanup on swap and shutdown; add rollback on failed init.
- Add cancellation-safe utilities (asyncio shields, timeouts) and make adapters
 /workers use them.

### Phase 7: Tooling & UX
- CLI commands: list/why/explain/swap for each domain; show shadowed candidates.
- Dev ergonomics: sample manifests, stack-order env template, remote adapter
  quickstart.
- Tests: matrix for precedence, swap rollback, remote fetch integrity, per-domain
  override behaviors.

## Future/Optional Enhancements
- Structured concurrency helpers (nursery-like patterns) to scope tasks and ensure
  clean cancellation.
- Durable execution hooks: pluggable backend (e.g., temporal-like or lightweight
  saga runner) for workflows/tasks that need retries and state.
- Policy-driven retries/backoff standardized across adapters/services.
- Middleware/pipeline support for adapters (compose adapters as chains/middleware).
- Capability negotiation: select candidates by capabilities/tags when multiple
  providers exist.
- Rate limiting and circuit breakers as first-class mixins for outbound adapters.
- State machine DSL for workflows with versioned definitions and migrations.
- Entry-point ecosystem starter kits (templates for adapters/services/plugins).

## Execution Notes
- Drop legacy compatibility; refactor aggressively for clarity.
- Keep modules small and single-purpose; enforce typed public APIs.
- Land in phases with green tests at each phase; add observability early to aid
  debugging.
