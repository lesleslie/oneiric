# Resolution Layer Plan (Discovery + Registration + Resolver)

This plan describes a shared resolution layer that handles discovery, registration, and precedence for all pluggable domains: adapters, services, tasks, events, and workflows. It builds on the adapter work (scenario 2 + hot swap) and generalizes it.

## Goals

- Single precedence policy across domains (hierarchy-aware, overridable).
- Unified APIs for discovery (finding candidates) and registration (making them available).
- Resolver that picks the active candidate per domain/key, with shadowed entries kept for observability.
- Supports hot swap, activation/deactivation, and remote (manifest-based) sources.

## Precedence Rules (highest wins)

1. Explicit override (e.g., config/manifest says provider X for domain/key).
1. `register_pkg` inferred priority (caller path mapped to stack order, e.g., sites > splashstand > fastblocks > oneiric).
1. Metadata `stack_level` (z-index) on the candidate.
1. Registration order (last write wins as final tie-breaker).

## Key Concepts

- **Candidate**: {domain, key, provider, priority, stack_level, factory/init hook, metadata, source}.
- **Domain**: adapters (category), services (`service_id`), tasks (`task_type`), events (`event_name`/`type`), workflows (`workflow_id` [+ version]).
- **Active vs Shadowed**: resolver keeps the winning candidate active; shadowed candidates remain listed for debugging.

## APIs (proposed shape)

- Discovery inputs:
  - Local package scan via `register_pkg` (captures caller path, infers priority).
  - Remote manifest fetch (HTTP/S3/GCS/OCI) returning candidate descriptors.
  - Optional entry-point scan (future).
- Registration:
  - `register_candidate(domain, key, provider, priority, stack_level, factory, meta, source)`
    - Adds to per-domain registry; re-resolves winner; updates active/shadowed lists.
- Resolution:
  - `resolve(domain, key)` → winning candidate (applies precedence rules).
  - `list_active(domain)`, `list_shadowed(domain)`.
- Activation/Hot swap:
  - `activate(domain, key)` binds the resolved candidate (lazy instantiation).
  - `swap(domain, key, provider=None, force=False)` re-resolves, instantiates, health-checks, and replaces binding; calls `cleanup()` on old instance when available; rollback on failure unless `force`.
- Observability:
  - Dump why a candidate lost/won (priority, stack_level, source, timestamp).

## Discovery & Remote Sources

- Manifest format (for remote adapters/services/workflows/etc.):
  - `domain`, `key`, `provider`, `uri`, `sha256`, optional `signature`, optional `stack_level`, optional `version`, `source`.
- Flow:
  1. Fetch manifest (HTTP/S3/GCS/OCI).
  1. Verify signature/digest.
  1. Download artifact to cache; install/import or add to `sys.path`.
  1. Register as a candidate with manifest-provided `stack_level` and source priority.
  1. Offline fallback: use cached artifact; if missing, fall back to local candidates.
- Supported delivery options (pick one first):
  - Signed wheel/zip over HTTPS/S3/GCS (simple baseline).
  - Private index/extra-index.
  - OCI artifact via `oras` (supply-chain friendly).
  - MCP/registry service returning descriptors + URLs.

## Domain Integration Notes

- Adapters: key=category; already have metadata; add stack_level; plug resolver into `import_adapter` path.
- Services: key=service_id; resolver decides which service class to register/activate.
- Tasks: key=task_type; resolver decides handler binding in the queue.
- Events: key=event_name/type; resolver decides handler binding.
- Workflows: key=workflow_id (optionally versioned); resolver chooses definition/engine; support activation flags.

## Hot Swap & Lifecycle

- Pre/post swap hooks for domains to pause/drain (DB pools, queues, workflows).
- Health check the new candidate before commit; rollback on failure; `force` to bypass.
- Config/manifest watcher triggers `swap` per diff (category/provider changes).

## Observability & Tooling

- CLI/UI table per domain: active vs shadowed, why, source, priority, stack_level, timestamp.
- Debug helpers: “why not X?” to show the decision chain.
- Metrics: swap counts, failures, resolution latency.

## Rollout Steps (phased)

1. Extract resolver module with in-memory registries and precedence logic.
1. Migrate adapters to use resolver (keep existing behavior; add stack_level).
1. Add hot-swap for adapters; integrate config/manifest diff watcher.
1. Generalize to services/tasks/events/workflows behind the same resolver.
1. Add observability surfaces (CLI/table, debug logs).
1. Add remote manifest support (start with signed wheel/zip over HTTPS/S3/GCS).
1. Optional: entry-point discovery, OCI artifacts, MCP registry integration.
