# Resolution Layer Specification

This specification defines a shared discovery/registration/resolver layer for all pluggable domains (adapters, services, tasks, events, workflows) with stack-aware precedence, hot swapping, and remote-sourced candidates.

## Scope
- Domains: adapters (by category), services (by service_id), tasks (by task_type), events (by event_name/type), workflows (by workflow_id, optional version).
- Sources: local packages (via register_pkg), remote manifests (HTTP/S3/GCS/OCI), optional entry points in future.
- Features: precedence resolution, activation/hot swap, observability, remote fetch with integrity checks.

## Terminology
- Candidate: A resolvable item for a domain/key with metadata and a factory/init hook.
- Active: The candidate currently bound for a domain/key.
- Shadowed: Candidate that lost resolution but remains registered for introspection.
- Priority: Numeric ordering derived from package inference or explicit config.
- Stack level (z-index): Optional integer on the candidate metadata used as a tie-breaker inside a package.

## Precedence Rules
Applied in order for each domain/key (highest wins):
1) Explicit override (config/manifest selection).
2) Inferred priority from register_pkg (caller path mapped to stack order; fallback heuristics).
3) Candidate metadata stack_level (higher wins).
4) Registration order (last registered wins).

## Data Model (Candidate)
- domain: str (adapter|service|task|event|workflow)
- key: str (category/service_id/task_type/event_name/workflow_id[+version])
- provider: str | None (human-readable provider/implementation id)
- priority: int | None (inferred; higher means higher precedence)
- stack_level: int | None (optional z-index)
- factory: callable or import path (creates/returns the instance or handler)
- metadata: dict (includes version, capabilities, source info)
- source: enum (local_pkg | remote_manifest | entry_point | manual)
- registered_at: timestamp
- health: optional callable for readiness checks

## APIs
- Discovery inputs:
  - `discover_from_pkg(name, path, priority)` -> list[Candidate]
  - `discover_from_manifest(manifest_descriptor)` -> list[Candidate]
  - (Future) `discover_from_entry_points(group)` -> list[Candidate]
- Registration:
  - `register_candidate(candidate: Candidate) -> None`
  - Side effect: update per-domain registry and recompute active/shadowed.
- Resolution:
  - `resolve(domain, key) -> Candidate | None` (applies precedence rules)
  - `list_active(domain) -> list[Candidate]`
  - `list_shadowed(domain) -> list[Candidate]`
- Activation/Hot swap:
  - `activate(domain, key) -> instance` (instantiate active candidate lazily)
  - `swap(domain, key, provider=None, force=False) -> instance`
    - Re-resolve with optional provider filter.
    - Instantiate and health-check new candidate.
    - Call cleanup() on old instance if supported.
    - Commit or rollback (unless force).
- Observability:
  - `explain(domain, key) -> decision trace` (why winner, why losers)
  - Emit events/hooks for pre/post swap and registration.

## Remote Manifest
- Manifest entry fields: domain, key, provider, uri, sha256, optional signature, optional stack_level, optional version, source label.
- Flow:
  1) Fetch manifest (HTTP/S3/GCS/OCI).
  2) Verify signature/digest.
  3) Download artifact to cache; install/import or place on sys.path.
  4) Register candidates with manifest-provided stack_level and source priority.
  5) Fallback: use cached artifact if offline; otherwise fall back to local candidates.

## Domain Integration
- Adapters: tie resolver into import_adapter/_find_adapter; add stack_level to Adapter metadata; use resolver for enablement and swaps.
- Services: resolver selects service class per service_id before registry binding.
- Tasks: resolver selects handler per task_type; queue binds active handler.
- Events: resolver selects handler(s) per event name/type; bind highest winner; optionally allow multiple with priority ordering.
- Workflows: resolver selects workflow definition/engine per workflow_id [+ version]; support activation flag and swap.

## Hot Swap Lifecycle
- Steps: resolve target -> instantiate -> health check -> pre_swap hook -> bind new -> cleanup old -> post_swap hook.
- Rollback if instantiation/health check fails (unless force).
- Config/manifest watcher triggers swap when mappings change.
- Domain-specific hooks: e.g., pause/drain for queues, graceful DB pool replacement.

## Security & Integrity
- Require sha256 (and optional signature) for remote artifacts.
- Enforce allowlist/denylist for sources; configurable cache directory.
- Do not auto-execute arbitrary code without digest verification.

## Observability
- Per-domain tables: active vs shadowed, priorities, stack_level, source, timestamps.
- Decision trace: show which rule decided the winner.
- Metrics: swap attempts, successes/failures, resolution latency.

## Compatibility & Migration
- Defaults maintain current behavior if no stack_level or remote manifests are present.
- Existing register_* calls keep working; they flow through register_candidate internally.
- Adopt incrementally:
  1) Implement resolver/registry in-memory.
  2) Route adapters through it.
  3) Add hot swap for adapters.
  4) Extend to services/tasks/events/workflows.
  5) Add observability and remote manifest support.
