---
status: complete
role: historical
date: 2026-10-11
last_reviewed: 2026-10-30
superseded_by: null
topic: storage-consolidation
---

______________________________________________________________________

## status: complete role: historical date: 2026-10-11 last_reviewed: 2026-10-30 superseded_by: null topic: storage-consolidation

# Substrate references — documentation cleanup (2026-10-11)

Historical record of a single-session cleanup pass. The external MCP
storage service was retired during the broader substrate consolidation;
this note records which Oneiric references were stale after that
consolidation and which were fixed in this session.

## Context

The external MCP storage service (port 8683) was decomposed into
Oneiric's MCP server over multiple phases (Phase 1 = adapter-registry
tools, Phase 8 = substrate feeds + scheduler). Per
`docs/specs/2026-09-16-oneiric-fastmcp-pivot-design.md`, the runtime
target today is: Oneiric's MCP server owns the adapter catalog and
substrate feeds; no separate external storage service runs in the path.

Active code in Oneiric accumulated references to that retired service
that no longer match the runtime (POSTs to port 8683, "Curator"
sections, the retired service's env-var setup commands, "Phase 1 of the
storage decomposition" framing in docstrings, etc.). Operators following
docs encountered dead URLs and references to services that no longer
exist.

## Decision rule

When documenting Oneiric's adapter registry or substrate behaviour:

1. Do not reference the retired external storage service — by any of its
   former names, or by the env vars it used to read — as a runtime
   dependency. Oneiric's MCP server is the registry backend.
2. The `REMOTE_MANIFEST` `CandidateSource` enum value refers to
   oneiric remote-sync loading YAML manifests into Oneiric's local
   registry — not to a separate substrate service.
3. If a doc describes runtime that no longer exists, prefer deleting
   the section over framing it as historical. Operator-facing docs
   (README, QUICKSTART, service-dependencies, operational-modes)
   describe the current contract.
4. Historical specs/plans (docs/specs/, docs/plans/, CHANGELOG) may
   retain references to the retired service — they are the record of the
   decomposition that already happened.

## Cleanup completed this session

**Deleted (dead runtime — no production callers):**

- `oneiric/adapters/mcp_pusher.py` — POSTed to `localhost:8683/tools/store_adapter`; service not running.
- `tests/adapters/test_mcp_pusher.py`, `tests/test_mcp_pusher_coverage.py` — tests for the dead pusher.

**Updated (active code — replaced the retired-service framing):**

- `oneiric/mcp/adapter_registry.py` — module docstring + `AdapterRecord` docstring + class docstring + `to_dict` docstring + `# ----- async public API -----` section header. Reframed from "Phase 1 of the storage decomposition" to "Oneiric's adapter registry."
- `oneiric/mcp/server.py` — comment block on the 8 adapter tools. Removed the "ported from the old service's MCP tools" framing.
- `oneiric/adapters/cache/persistent_kv.py` — module + class docstrings. Removed the "ported from the old service's KV / time-series tools" framing.
- `oneiric/adapters/cache/persistent_kv.py:103` — class docstring drop.
- `oneiric/adapters/bootstrap.py` — `queued_publisher` docstring dropped the old service spec reference.
- `oneiric/adapters/vector/hot_store.py` — refactor-context note dropped the "Phase 5 task 8 of the old service's decomposition design" reference.
- `oneiric/adapters/vector/duckdb_hot_store.py` — refs block dropped the old service spec reference.
- `oneiric/core/ulid.py` — dropped the retired-package → built-in import fallback chain (the retired package is not installed in Oneiric's venv; the chain was already dead).
- `tests/integration/test_persistent_kv_adapter_e2e.py` — retired-service framing dropped.
- `tests/integration/test_oneiric_mcp_e2e.py` — "Phase 1 storage decomposition" docstring dropped.
- `tests/unit/test_redis_cache_settings.py` — retired-service reference dropped.
- `README.md:79` — adapter-registry row dropped the "(ported from the old service's adapter-registry tool during the Phase 1 decomposition)" note.
- `QUICKSTART.md` — removed `oneiric start --manifest http://<old-host>:8683/mcp` and `oneiric health --probe`; rewrote Standard Mode block to reference the local manifest path.
- `docs/reference/service-dependencies.md` — replaced the entire retired-service section with "Remote Manifest Source" pointing at `docs/REMOTE_MANIFEST_SCHEMA.md`; removed the retired service's env vars and its blocks from the dependency-tree, status JSON, monitoring list, dashboard list, and auth list.
- `docs/guides/operational-modes.md` — removed all of the retired service's env vars; rewrote Standard Mode overview, table rows, troubleshooting commands to reference manifest URL / `oneiric manifest verify`.

## NOT done this session (tracked follow-ups)

- `oneiric/adapters/tracked_settings.py` — initially deleted as part of this pass but restored at operator request. Module pushes snapshots to a non-existent external HTTP service. No production callers, but `MEMORY_ARCHITECTURE.md` and the architecture doc line treat it as live runtime. **Tracked follow-up: either delete or rewrite to use Oneiric's own substrate in a separate, explicit PR.**
- `docs/architecture/MEMORY_ARCHITECTURE.md` — 36 remaining references to the retired service including the "Audience" list, the "distribution bridge" line, table rows describing `TrackedSettings` push, the `TrackedSettings → HTTP` Mermaid diagram, Q6/Q7 examples, and the footer list of dead-code files. **Tracked follow-up: rewrite this large internal architecture doc.**

## 2026-10-30 follow-up — repo-wide removal of the retired service's name

Both tracked follow-ups above are now closed:

- `oneiric/adapters/tracked_settings.py` (and its unit test) were deleted,
  and the `TrackedSettings` export was dropped from
  `oneiric/adapters/__init__.py`.
- `docs/architecture/MEMORY_ARCHITECTURE.md` was rewritten so the retired
  service is described generically and no longer presented as a current
  component, dependency, or service.

Rule 4 above was applied on 2026-10-30: dated plans/specs and current
docs now describe the retired service generically ("the external
substrate", "the old cross-component storage surface") instead of naming
it. Only `CHANGELOG.md` and `docs/**/.archive/` keep the original name —
the former is the release record, the latter is frozen history. This
note was renamed accordingly and all inbound links were updated.

## Status

- `complete` — the surgical cleanup was done in the operator-facing
  surface and the active code on 2026-10-11; the two tracked follow-ups
  were closed on 2026-10-30.
