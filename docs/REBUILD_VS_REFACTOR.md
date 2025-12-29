# Rebuild vs. Refactor (Python 3.13 Baseline)

Context: We can drop backward compatibility. We want a modern async architecture with
hierarchical resolution, hot swap, plugins, and remote-delivered components while
keeping existing adapter functionality and actions utilities.

## Python Version

- Target Python 3.13 now; plan the migration to Python 3.14 once the toolchain and dependencies are available in CI/dev. If
  any critical deps lag, fall back to 3.13 and bump when they’re ready. Keep code
  3.13-clean so the switch is trivial.

## Recommendation: Clean-Slate Core, Reuse Adapters

- Build a new core (resolution layer, lifecycle, observability, plugin/remote
  interfaces) from scratch instead of incrementally refactoring the current monolith.
- Reuse existing adapter implementations by wrapping them in the new lifecycle/
  resolver APIs; do shallow shims where needed.
- Actions utilities can stay; expose them via the new DI/context if needed.

## Clean-Slate Core Outline

1. New core packages: `core/resolution`, `core/lifecycle`, `core/observability`,
   `core/plugins`, `core/runtime` (context/taskgroups/supervision).
1. Candidate model + resolver (shared across adapters/services/tasks/events/workflows)
   with precedence: config override > package priority > stack_level > last-write.
1. Lifecycle contract (init/health/cleanup/pause-resume) with rollback on failed init.
1. Structured concurrency helpers (TaskGroup/Nursery abstraction) and cancellation-
   safe utilities; make all background work go through them.
1. Observability: OpenTelemetry tracing/metrics/logging fields standard across domains;
   health/readiness hooks.
1. Plugin protocol: entry points or pluggy-style plus path-based discovery; optional
   remote manifest source (signed wheel/zip) with cache.
1. Hot swap: resolver-driven swap with health check, cleanup, rollback; config/manifest
   watcher triggers swaps.
1. CLI/diagnostics: list/why/explain/swap per domain; active vs. shadowed.

## Migration of Existing Adapters/Actions

- Wrap current adapters with the new lifecycle interface; register them via the
  resolver. Keep module code intact where possible.
- Add `stack_level` metadata and provider IDs; map categories to keys.
- Actions utilities: expose via DI/context; keep APIs stable but relocate imports as
  needed.

## Optional/Forward-Looking Items Worth Doing Now

- Capability tags + negotiation in the candidate model (select by capability + priority).
- Middleware/pipeline adapters (wrappers/combinators) to compose behavior.
- Retry/backoff + circuit breaker mixins as shared policies for outbound adapters.
- Remote manifest pipeline (HTTPS/S3/GCS or OCI via oras) with checksum/signature,
  cache dir, and offline fallback.
- Workflow versioning + migration helpers; optional durable execution hook for
  long-running workflows/tasks.
- Rate limiting and backpressure helpers shared across domains.
- Entry-point templates for third-party adapters/services/plugins to grow the
  ecosystem quickly.

## When to Fully Rebuild vs. Refactor

- Rebuild core if:
  - You want the resolver/lifecycle/observability changes fast without fighting the
    existing large modules.
  - You can spend time shimming adapters once rather than untangling legacy flows.
- Refactor incrementally if:
  - Tooling/tests are brittle and you need small steps (not a concern here per goals).

Given no backward-compat constraints and desire for cleaner ergonomics, rebuild the
core layers now, reuse adapters via thin shims, and integrate the forward-looking
features while the architecture is in motion.
