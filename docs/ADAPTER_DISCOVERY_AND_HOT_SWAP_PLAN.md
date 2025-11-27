# Adapter Discovery & Hot Swap Plan

This document captures the plan for bringing back stack-aware adapter precedence (scenario 2) plus runtime hot swapping and remote/hosted adapter loading.

## Goals

- Preserve “higher-level package wins” behavior without requiring a manifest.
- Add an optional metadata `stack_level` (z-index) to break ties within a package.
- Support hot swapping adapters at runtime, including config-driven swaps.
- Allow adapters to be fetched from remote storage/indexes with integrity checks.

## Resolution & Precedence Rules

Order of evaluation (highest precedence first):

1. Explicit override (if present, e.g., in `settings/adapters.yaml` or a remote manifest).
1. `register_pkg`-inferred priority: derive from caller path (e.g., `sites/*` > `splashstand` > `fastblocks` > `oneiric`) using a configurable precedence map/env var; fallback to path depth if unknown.
1. Adapter metadata `stack_level` (z-index): higher value wins inside the same package.
1. Registration order (last registered wins as final tie-breaker).

## `register_pkg` Priority Inference

- Capture caller file from `register_pkg` when `name`/`path` are omitted (already done), then map to a precedence value.
- Provide a small helper (e.g., `stack_order.py`) to:
  - Load a precedence map from env (`STACK_ORDER=sites,splashstand,fastblocks,oneiric`) or a lightweight cache file.
  - Fallback heuristic: parent-first by path depth; look for sentinel files (`stack.cfg`) in ancestors.
- Store inferred priority alongside the queued package so `_process_registration_queue` can sort before registering adapters.

## Metadata Extension (`stack_level`)

- Add optional `stack_level: int | None` to adapter metadata (default `None`).
- Use it only after register_pkg-derived priority; treat it like a z-index within a package.
- Keep backward compatibility: missing field does not change current behavior.

## Hot Swap API

- Introduce `swap_adapter(category, provider=None, *, force=False)`:
  - Resolve target adapter with the same precedence rules.
  - Instantiate and health-check the new adapter.
  - If healthy, call `cleanup()` on the old instance when available, replace the DI binding/context entry, emit pre/post swap events.
  - Roll back if initialization/health check fails unless `force=True`.
- Config/manifest watcher:
  - Watch `settings/adapters.yaml` (or remote manifest) and diff category→provider mappings.
  - For each change, call `swap_adapter` to apply without restart.
- Optional: lifecycle hooks for stateful adapters (pause/resume, drain queues).

## Remote/Hosted Adapters

- Use a signed manifest (`remote_adapters.yml`) with entries like:
  - `category`, `provider`, `uri`, `sha256`, optional `signature`, optional `stack_level`.
- Flow:
  1. Fetch manifest (HTTP/S3/GCS/OCI).
  1. Verify signature/checksum.
  1. Download artifact to a local cache dir; install as wheel/zip or add to `sys.path`.
  1. Register the package with an inferred priority (from manifest + stack_level) and merge into the resolver.
  1. Offline: use cached copy; fall back to local adapters if fetch/verify fails.
- Supported delivery options (pick one to implement first):
  - Signed zip/wheel over HTTPS/S3/GCS (simplest).
  - Private index/extra-index (publish wheels; use uv/pip sync step).
  - OCI/ORAS artifact with digest pinning (supply-chain friendly).
  - MCP/registry service that returns adapter descriptors and download URLs.

## Open Questions

- Should we persist inferred priorities to a cache file for reproducibility in CI?
- Do we need per-category “lock” to prevent swapping while in-flight operations run (e.g., DB migrations)?
- Which remote delivery option should be the default? Signed wheel over HTTPS/S3 is the lowest-friction starting point.
