# New Architecture Specification (Oneiric, Python 3.13 Baseline)

Goal: build Oneiric with unified resolution, lifecycle, observability, and plugin
support, reusing existing ACB adapters and actions where useful. Domains (adapters,
services, tasks, events, workflows) plug into the same resolver and lifecycle.

## Top-Level Packages

- `core/runtime`: Context, DI bindings, TaskGroup/nursery helpers, cancellation-safe
  utilities.
- `core/resolution`: Candidate model, resolver, registries (active/shadowed), explain
  API, hot-swap entry points.
- `core/lifecycle`: init/health/cleanup/pause-resume contracts, rollback helpers,
  swap orchestration.
- `core/observability`: OpenTelemetry tracer/metrics/logging helpers; structured
  fields (domain, key, provider, source, priority, stack_level).
- `core/plugins`: discovery sources (local package, entry points, remote manifest),
  plugin loader utilities.
- Domain bridges: `adapters/bridge.py`, `services/bridge.py`, `tasks/bridge.py`,
  `events/bridge.py`, `workflows/bridge.py` — each maps domain concepts to resolver
  keys and lifecycle hooks.

## Candidate Model (shared)

- Fields: domain, key, provider, priority, stack_level (z-index), factory/import,
  metadata (capabilities, version, source), health hook, lifecycle hooks.
- Precedence: explicit config override > pkg-inferred priority > stack_level >
  registration order.

## Domain Mapping

- Adapters: key = category; provider = adapter name; metadata includes capabilities
  and version; lifecycle for outbound resources (connections, clients).
- Services: key = service_id; provider = implementation; lifecycle + health.
- Tasks: key = task_type; provider = handler; pause/resume/drain hooks; resolver
  selects active handler.
- Events: key = event name/type; provider = handler; allow highest-wins by default;
  optional multi-handler pipeline ordered by priority/stack_level.
- Workflows: key = workflow_id (+ optional version); provider = definition/engine;
  activation flag; graceful swap (migrate/drain in-flight where possible).

## Lifecycle & Swap

- Standard contract: init() → health() → (run) → cleanup(); optional pause/resume.
- Swap flow: resolve target → instantiate → health check → pre_swap hook → bind →
  cleanup old → post_swap hook; rollback on failure unless force.
- Config/manifest watcher triggers swap when mappings change.

## Discovery Sources

- Local package: `register_pkg` captures caller path, maps to priority, emits candidates.
- Entry points (or pluggy-style): enumerate entry points for each domain group.
- Remote manifest: signed manifest with uri + sha/signature; download wheel/zip to
  cache; install or sys.path prepend; register candidates with source metadata.

## Observability

- Trace spans for discovery/registration/resolve/swap; metrics for swap attempts/
  successes/failures; structured logs include domain/key/provider/source/priority.
- Health/readiness endpoints/polls backed by lifecycle health hooks.

## Configuration

- Typed settings; `settings/*.yaml` (or TOML) for explicit overrides (domain/key →
  provider). Remote manifest location configurable. Stack order configurable via env
  (e.g., `STACK_ORDER=sites,splashstand,fastblocks,oneiric`).

## CLI/Diagnostics

- Commands: list (active/shadowed), why/explain, swap, health, show sources.
- Per-domain tables include priority, stack_level, source, timestamp, decision reason.

## Compatibility Note

- No legacy constraints. Keep existing adapter behavior by wrapping implementations
  with lifecycle/resolver shims; actions utilities remain, with DI/context bindings.

## Integration Guidance (fastblocks, crackerjack, splashstand, session-mgmt-mcp)

- Feasibility: high. Existing adapter modules can be registered as candidates; their
  categories map directly. Services/tasks/events/workflows integrate by defining
  keys and registering providers; override semantics are handled by resolver.
- Migration steps:
  1. Add stack priority map per app (`STACK_ORDER` env or config; e.g., sites →
     splashstand → fastblocks → oneiric).
  1. Register packages via new `register_pkg` (no old globals).
  1. Wrap adapters with lifecycle shims; declare stack_level/provider metadata.
  1. Bind services/tasks/events/workflows through their bridges; remove legacy
     registration paths.
  1. Enable OTel/logging helpers; add minimal health hooks.
  1. Optionally set up remote manifest for shared/ad-hoc components.
- Strengthening apps:
  - Deterministic overrides across the stack (sites → splashstand → fastblocks → oneiric).
  - Hot swap for safer rollout and config-driven changes.
  - Unified observability and health/reporting.
  - Plugin/remote delivery to share components across repos without copy/paste.

## Optional Early Adds

- Capability tags and negotiation in resolver (select by capability + priority).
- Middleware/pipeline adapters to compose behavior.
- Retry/backoff + circuit breaker mixins for outbound adapters.
- Workflow versioning + migration helpers; durable execution hook for long-running
  workflows/tasks.
- Rate limiting/backpressure utilities shared across domains.
