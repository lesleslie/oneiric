# Graph Adapter Plan (ArangoDB & DuckDB PGQ)

> **Archive Notice (2025-12-19):** Adapters shipped; retained for historical traceability. See `docs/analysis/GRAPH_ADAPTERS.md` for current usage/configuration.

**Last Updated:** 2025-12-10
**Owner:** Data Platform (Ravi)
**Scope:** Deliver the remaining graph adapters outlined in `docs/analysis/ADAPTER_STRATEGY.md`, starting with ArangoDB (Graph/Cypher/Gremlin) followed by DuckDB PGQ. *(Both adapters shipped Dec 2025; this document remains for historical traceability.)*

______________________________________________________________________

## 1. Objectives

1. **ArangoDB Adapter (Wave 1)** *(✅ Shipped Dec 2025)*

   - Ship `oneiric.adapters.graph.arangodb.ArangoDBGraphAdapter` with CRUD/query helpers.
   - Provide Pydantic settings, metadata (category `graph`, provider `arangodb`), and manifest entries.
   - Support both HTTP and native protocol via `python-arango` with optional extra (`oneiric[graph-arangodb]`).
   - Add fake driver + unit tests mirroring the Neo4j coverage.

1. **DuckDB PGQ Adapter (Wave 2)** *(✅ Shipped Dec 2025)*

   - `oneiric.adapters.graph.duckdb_pgq.DuckDBPGQAdapter` exposes ingest/query helpers on top of DuckDB + PGQ.
   - Optional extra `oneiric[graph-duckdb-pgq]` installs DuckDB 1.0+.
   - Tests use fake connections so the optional dependency stays optional in CI.

1. **Documentation & Samples**

   - Expand `docs/analysis/GRAPH_ADAPTERS.md` with new sections per adapter (install instructions, demo config, manifest snippets).
   - Update `docs/sample_remote_manifest*.yaml` and `docs/examples/demo_settings.toml` once adapters are live.
   - Record roadmap progress in `ADAPTER_STRATEGY.md`, `ADAPTER_PORT_SUMMARY.md`, and `ADAPTER_GAP_AUDIT.md`.

______________________________________________________________________

## 2. Work Breakdown

| Track | Tasks | Owner | Notes |
|-------|-------|-------|-------|
| **Dependency & Packaging** | - Add `graph-arangodb` extra (`python-arango>=x.y`).<br>- Research DuckDB PGQ packaging (likely `duckdb>=1.1.0` + `duckdb_graph`).<br>- Update `pyproject.toml`, regenerate `uv.lock`, and document installs. | Platform Core | Keep optional extras isolated to avoid bloating default installs. |
| **Adapter Implementation (ArangoDB)** | - Define `ArangoDBGraphSettings` (endpoint, database, auth, TLS, graph name).<br>- Implement lifecycle hooks (`init`, `health`, `cleanup`).<br>- Add helpers: `create_vertex`, `create_edge`, `query_aql`, `query_gremlin` (if required).<br>- Include driver factory injection for tests. | Data Platform | Reference ACB adapter for API parity. |
| **Adapter Implementation (DuckDB PGQ)** | - Model settings (database path, extension path, read-only toggle).<br>- Implement helper methods for building PGQ queries and returning Pydantic models.<br>- Ensure `health()` validates `INSTALL/LOAD pgq`. | Data Platform | Coordinate with analytics team on default schema. |
| **Testing** | - Unit tests for ArangoDB driver interactions (fake client, verifying queries).<br>- Unit tests for DuckDB PGQ (temporary file DB + sample graph).<br>- Update `tests/adapters/test_bootstrap_metadata.py` to assert new metadata entries. | QA + Platform | Mirror Neo4j test structure for consistency. |
| **Documentation & Examples** | - Extend `GRAPH_ADAPTERS.md` with sections for ArangoDB and DuckDB PGQ.<br>- Update `docs/examples/LOCAL_CLI_DEMO.md` with smoke snippets once adapters land.<br>- Refresh manifest snippets + README navigation as needed. | Docs Team | Keep instructions aligned with extras and sample settings. |

______________________________________________________________________

## 3. Timeline & Milestones

| Week | Deliverable | Evidence |
|------|-------------|----------|
| Week 1 | ArangoDB adapter implementation + tests + extras | ✅ Landed (adapter, docs, manifests, optional extra). |
| Week 2 | DuckDB PGQ adapter skeleton + packaging notes | ✅ Completed (adapter + tests + docs merged). |
| Week 3 | DuckDB PGQ completion + documentation sweep | ✅ Completed (GRAPH_ADAPTERS.md + manifests + status docs updated). |

Stretch goal: evaluate Neptune adapter requirements and note blockers (SDK availability, auth posture) for Q1 ’26 planning.

______________________________________________________________________

## 4. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| ArangoDB driver compatibility with Python 3.14 | Pin to latest `python-arango` release; add compatibility note if wheels lag behind. |
| DuckDB PGQ extension availability | Document manual `INSTALL pgq; LOAD pgq;` steps; optionally embed SQL bootstrap in adapter `init()`. |
| Optional extras explosion | Keep new extras scoped per adapter (`graph-arangodb`, `graph-duckdb-pgq`) and add a meta extra later if needed. |

______________________________________________________________________

## 5. Next Actions

1. Monitor demand for `graph/neptune.py` and document requirements if stakeholders request it.
1. Keep `GRAPH_ADAPTERS.md` updated if new PGQ features or manifest tweaks land.
