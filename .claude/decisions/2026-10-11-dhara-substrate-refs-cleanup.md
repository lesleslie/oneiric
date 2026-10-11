---
status: partial
role: historical
date: 2026-10-11
last_reviewed: 2026-10-11
superseded_by: null
topic: storage-consolidation
---

______________________________________________________________________

## status: partial role: historical date: 2026-10-11 last_reviewed: 2026-10-11 superseded_by: null topic: storage-consolidation

# Dhara substrate references — documentation cleanup (2026-10-11)

Historical record of a single-session cleanup pass. The Dhara MCP service
was retired during the broader substrate consolidation; this note
records which Oneiric references were stale after that consolidation
and which were fixed in this session.

## Context

The Dhara MCP service (port 8683, package `dhara`) was decomposed into
Oneiric's MCP server over multiple phases (Phase 1 = adapter-registry
tools, Phase 8 = substrate feeds + scheduler). Per
`docs/specs/2026-09-16-oneiric-fastmcp-pivot-design.md`, the runtime
target today is: Oneiric's MCP server owns the adapter catalog and
substrate feeds; no separate Dhara MCP service runs in the path.

Active code in Oneiric accumulated Dhara-shaped references that no
longer match the runtime (POSTs to port 8683, "Druva (Curator)"
sections, `DHruVA_MCP_URL` env-var setup commands, "Phase 1 of Dhara
MCP decomposition" framing in docstrings, etc.). Operators following
docs encountered dead URLs and references to services that no longer
exist.

## Decision rule

When documenting Oneiric's adapter registry or substrate behaviour:

1. Do not reference `Dhara`, `Druva`, or `DHruVA_MCP_URL` as a runtime
   dependency. Oneiric's MCP server is the registry backend.
2. The `REMOTE_MANIFEST` `CandidateSource` enum value refers to
   oneiric remote-sync loading YAML manifests into Oneiric's local
   registry — not to a separate substrate service.
3. If a doc describes runtime that no longer exists, prefer deleting
   the section over framing it as historical. Operator-facing docs
   (README, QUICKSTART, service-dependencies, operational-modes)
   describe the current contract.
4. Historical specs/plans (docs/specs/, docs/plans/, CHANGELOG) may
   retain Dhara references — they are the record of the decomposition
   that already happened.

## Cleanup completed this session

**Deleted (dead runtime — no production callers):**

- `oneiric/adapters/mcp_pusher.py` — POSTed to `localhost:8683/tools/store_adapter`; service not running.
- `tests/adapters/test_mcp_pusher.py`, `tests/test_mcp_pusher_coverage.py` — tests for the dead pusher.

**Updated (active code — replaced Dhara framing):**

- `oneiric/mcp/adapter_registry.py` — module docstring + `AdapterRecord` docstring + class docstring + `to_dict` docstring + `# ----- async public API -----` section header. Reframed from "Phase 1 of Dhara MCP decomposition" to "Oneiric's adapter registry."
- `oneiric/mcp/server.py` — comment block on the 8 adapter tools. Removed "Ported from dhara.mcp.tools..." framing.
- `oneiric/adapters/cache/persistent_kv.py` — module + class docstrings. Removed "Ported from dhara.mcp.kv_timeseries" framing.
- `oneiric/adapters/cache/persistent_kv.py:103` — class docstring drop.
- `oneiric/adapters/bootstrap.py` — `queued_publisher` docstring dropped Dhara spec reference.
- `oneiric/adapters/vector/hot_store.py` — refactor-context note dropped "Phase 5 task 8 of dhara-mcp-decomposition-design.md" reference.
- `oneiric/adapters/vector/duckdb_hot_store.py` — refs block dropped Dhara spec reference.
- `oneiric/core/ulid.py` — dropped the `dhara` → `druva` → built-in import fallback chain (Dhara package is not installed in Oneiric's venv; the chain was already dead).
- `tests/integration/test_persistent_kv_adapter_e2e.py` — Dhara framing dropped.
- `tests/integration/test_oneiric_mcp_e2e.py` — "Phase 1 of Dhara MCP decomposition" docstring dropped.
- `tests/unit/test_redis_cache_settings.py` — Dhara-specific reference dropped.
- `README.md:79` — adapter-registry row dropped "(ported from `dhara.mcp.tools.group_registers.register_adapter_registry_group` during the Phase 1 Dhara decomposition)".
- `QUICKSTART.md` — removed `oneiric start --manifest http://dhara:8683/mcp` and `oneiric health --probe`; rewrote Standard Mode block to reference the local manifest path.
- `docs/reference/service-dependencies.md` — replaced entire "Druva (Curator)" section with "Remote Manifest Source" pointing at `docs/REMOTE_MANIFEST_SCHEMA.md`; removed `DHruVA_MCP_URL` env vars and Druva blocks from the dependency-tree, status JSON, monitoring list, dashboard list, and auth list.
- `docs/guides/operational-modes.md` — removed all `DHruVA_MCP_URL` env vars; rewrote Standard Mode overview, table rows, troubleshooting commands to reference manifest URL / `oneiric manifest verify`.

## NOT done this session (tracked follow-ups)

- `oneiric/adapters/tracked_settings.py` — initially deleted as part of this pass but restored at operator request. Module pushes snapshots to a non-existent Dhara HTTP service. No production callers, but `MEMORY_ARCHITECTURE.md` and the architecture doc line treat it as live runtime. **Tracked follow-up: either delete or rewrite to use Oneiric's own substrate in a separate, explicit PR.**
- `docs/architecture/MEMORY_ARCHITECTURE.md` — 36 remaining Dhara references including the "Audience" list, the "Dhara distribution bridge" line, table rows describing `TrackedSettings` push, the `TrackedSettings → DharaHTTP` Mermaid diagram, Q6/Q7 examples, and the footer list of dead-code files. **Tracked follow-up: rewrite this large internal architecture doc.**

## Status

- `partial` — surgical cleanup is done in the operator-facing surface and the active code; the two tracked follow-ups above are still open.
- Subsequent cleanup PRs should reference this note when addressing the remaining items.