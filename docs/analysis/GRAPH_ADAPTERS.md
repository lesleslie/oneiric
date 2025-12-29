# Graph Adapters (Neo4j & ArangoDB)

**Last Updated:** 2025-12-10
**Scope:** Installation, configuration, and manifest guidance for the Oneiric graph adapters (`Neo4jGraphAdapter`, `ArangoDBGraphAdapter`, `DuckDBPGQAdapter`). This document will expand again if additional adapters (e.g., Neptune) are requested.

______________________________________________________________________

## 1. Extras & Installation

Neo4j ships as an optional extra so default installs remain light. Install the extra before wiring the adapter:

```bash
pip install 'oneiric[graph-neo4j]'
```

Install the ArangoDB extra when targeting that provider:

```bash
pip install 'oneiric[graph-arangodb]'
```

DuckDB PGQ relies on DuckDB 1.0+ with the PGQ extension:

```bash
pip install 'oneiric[graph-duckdb-pgq]'
```

Each adapter guards its import and raises a descriptive `LifecycleError` when the driver is missing.

> **Local DuckDB PGQ:** DuckDB runs in-process; create a writable directory and the adapter will bootstrap the PGQ extension automatically.

______________________________________________________________________

## 2. Adapter Overviews

### Neo4j

- **Module:** `oneiric.adapters.graph.neo4j.Neo4jGraphAdapter`
- **Settings model:** `Neo4jGraphSettings`
- **Factory metadata:** category `graph`, provider `neo4j`, capabilities `nodes`, `relationships`, `cypher`
- **Core helpers:** `create_node(labels, properties)`, `create_relationship(from_id, to_id, rel_type, properties)`, `query(cypher, **params)`

### Configuration snippet (`~/.oneiric.toml`)

```toml
[adapters.selections]
graph = "neo4j"

[adapters.provider_settings.neo4j]
uri = "bolt://localhost:7687"
database = "neo4j"          # optional, Enterprise only
username = "neo4j"
password = "test"
encrypted = false
max_connection_pool_size = 10
```

### Manifest entry (`docs/sample_remote_manifest.yaml`)

```yaml
- domain: adapter
  key: graph.neo4j
  provider: neo4j
  factory: oneiric.adapters.graph.neo4j:Neo4jGraphAdapter
  metadata:
    description: Neo4j graph adapter for knowledge-graph workflows
    stack_level: 30
    priority: 400
    serverless:
      profile: serverless
      remote_refresh_enabled: true
      watchers_enabled: true
```

### CLI smoke test

```bash
ONEIRIC_CONFIG=~/.oneiric.toml uv run python - <<'PY'
import asyncio
from oneiric.adapters import AdapterBridge, register_builtin_adapters
from oneiric.core.config import load_settings
from oneiric.core.lifecycle import LifecycleManager
from oneiric.core.resolution import Resolver

async def main() -> None:
    settings = load_settings()
    resolver = Resolver()
    register_builtin_adapters(resolver)
    lifecycle = LifecycleManager(resolver)
    bridge = AdapterBridge(resolver, lifecycle, settings.adapters)
    handle = await bridge.use("graph")

    node = await handle.instance.create_node(["Demo"], {"name": "neo4j"})
    print("node:", node)

    rows = await handle.instance.query("MATCH (n:Demo) RETURN n LIMIT 1;")
    print("rows:", rows)

asyncio.run(main())
PY
```

The adapter performs a health check (`RETURN 1`) during initialization, so the CLI run will surface connectivity issues before any mutations occur.

______________________________________________________________________

### ArangoDB

- **Module:** `oneiric.adapters.graph.arangodb.ArangoDBGraphAdapter`
- **Settings model:** `ArangoDBGraphSettings`
- **Factory metadata:** category `graph`, provider `arangodb`, capabilities `vertices`, `edges`, `aql`
- **Core helpers:** `create_vertex(collection, document)`, `create_edge(collection, from_id, to_id, document)`, `query_aql(query, bind_vars)`

### Configuration snippet (`~/.oneiric.toml`)

```toml
[adapters.selections]
graph = "arangodb"

[adapters.provider_settings.arangodb]
hosts = "http://localhost:8529"
database = "_system"
graph = "demo_graph"
username = "root"
password = "test"
verify = false
request_timeout = 30.0
```

### Manifest entry (`docs/sample_remote_manifest.yaml`)

```yaml
- domain: adapter
  key: graph.arangodb
  provider: arangodb
  factory: oneiric.adapters.graph.arangodb:ArangoDBGraphAdapter
  metadata:
    description: ArangoDB graph adapter for multi-model workloads
    stack_level: 30
    priority: 390
    serverless:
      profile: serverless
      remote_refresh_enabled: true
      watchers_enabled: true
```

### CLI smoke test

```bash
ONEIRIC_CONFIG=~/.oneiric.toml uv run python - <<'PY'
import asyncio

from oneiric.adapters import AdapterBridge, register_builtin_adapters
from oneiric.core.config import load_settings
from oneiric.core.lifecycle import LifecycleManager
from oneiric.core.resolution import Resolver


async def main():
    settings = load_settings()
    resolver = Resolver()
    register_builtin_adapters(resolver)
    lifecycle = LifecycleManager(resolver)
    bridge = AdapterBridge(resolver, lifecycle, settings.adapters)
    handle = await bridge.use("graph")

    vertex = await handle.instance.create_vertex("people", {"name": "Arango"})
    print("vertex:", vertex)

    rows = await handle.instance.query_aql("FOR v IN people RETURN v", bind_vars=None)
    print("rows:", rows)


asyncio.run(main())
PY
```

The adapter uses `asyncio.to_thread()` to keep the synchronous python-arango client off the event loop. Health checks run `RETURN 1` by default, so connectivity issues surface immediately.

______________________________________________________________________

### DuckDB PGQ

- **Module:** `oneiric.adapters.graph.duckdb_pgq.DuckDBPGQAdapter`
- **Settings model:** `DuckDBPGQSettings`
- **Factory metadata:** category `graph`, provider `duckdb_pgq`, capabilities `pgq`, `table_edges`, `analytics`
- **Core helpers:** `ingest_edges(edges)`, `neighbors(node_id)`, `query(sql, parameters)`

The adapter opens a local DuckDB database (in-memory or file), installs/loads the PGQ extension (unless `read_only = true`), and ensures an edge table exists for storing traversals. Bring your own PGQ queries (e.g., `SELECT * FROM PGQ_DFS(...)`) and pass them through `query()`.

### Configuration snippet (`~/.oneiric.toml`)

```toml
[adapters.selections]
graph = "duckdb_pgq"

[adapters.provider_settings.duckdb_pgq]
database = ".oneiric_cache/graphs.duckdb"
edge_table = "pgq_edges"
source_column = "source_id"
target_column = "target_id"
install_pgq = true
```

### Manifest entry (`docs/sample_remote_manifest.yaml`)

```yaml
- domain: adapter
  key: graph.duckdb_pgq
  provider: duckdb_pgq
  factory: oneiric.adapters.graph.duckdb_pgq:DuckDBPGQAdapter
  metadata:
    description: DuckDB PGQ adapter for in-process graph analytics
    serverless:
      profile: serverless
      remote_refresh_enabled: true
      watchers_enabled: true
```

### CLI smoke test

```bash
ONEIRIC_CONFIG=~/.oneiric.toml uv run python - <<'PY'
import asyncio

from oneiric.adapters import AdapterBridge, register_builtin_adapters
from oneiric.core.config import load_settings
from oneiric.core.lifecycle import LifecycleManager
from oneiric.core.resolution import Resolver


async def main():
    settings = load_settings()
    resolver = Resolver()
    register_builtin_adapters(resolver)
    lifecycle = LifecycleManager(resolver)
    bridge = AdapterBridge(resolver, lifecycle, settings.adapters)
    handle = await bridge.use("graph")

    await handle.instance.ingest_edges([("root", "child-a"), ("root", "child-b")])
    print("neighbors:", await handle.instance.neighbors("root"))
    rows = await handle.instance.query(
        "SELECT COUNT(*) AS edge_count FROM pgq_edges"
    )
    print("edge-count:", rows)


asyncio.run(main())
PY
```

The adapter keeps the synchronous DuckDB client off the event loop with `asyncio.to_thread`. For production runs, mount the DuckDB database on persistent storage so PGQ traversals have state between restarts.

______________________________________________________________________

## 3. Feature Notes

- **Pydantic settings:** `Neo4jGraphSettings` binds Bolt URI, credentials, TLS, and pool sizing with full type hints.
- **Arango settings:** `ArangoDBGraphSettings` exposes hosts/database/graph/auth/tls plus request timeouts and graph name selection.
- **DuckDB PGQ settings:** `DuckDBPGQSettings` configure database storage, edge table identifiers, and extension bootstrapping.
- **Native driver exposure:** the adapter lazily constructs `neo4j.AsyncGraphDatabase.driver`. Advanced consumers can accept the adapter instance and call `instance._ensure_driver()` if they need raw sessions.
- **Multi-model support:** the Arango adapter targets named graphs when configured but falls back to document collections so workflows can operate without predefined graphs. DuckDB PGQ stores edges in a local table and exposes helper methods for ingestion and traversal.
- **Structured logging:** all lifecycle events log under `adapter.graph.neo4j` / `adapter.graph.arangodb` / `adapter.graph.duckdb_pgq`.
- **Serverless posture:** metadata defaults to stack level `30` with priorities `400` (Neo4j), `390` (ArangoDB), and `360` (DuckDB PGQ) so manifests can prioritize them as needed.

______________________________________________________________________

## 4. Verification & Follow-Ups

- Integration coverage lives under `tests/adapters/graph/test_neo4j_adapter.py`. Add new fixtures here when ArangoDB/DuckDB PGQ ship so graph adapters share fakes.
- ArangoDB unit tests live in `tests/adapters/graph/test_arangodb_adapter.py`; reuse the fake graph/database helpers when expanding coverage.
- DuckDB PGQ tests (`tests/adapters/graph/test_duckdb_pgq_adapter.py`) keep fakes for duckdb connections so optional extras stay optional in CI.
- Keep this guide synchronized with `docs/analysis/ADAPTER_GAP_AUDIT.md` and `docs/implementation/ADAPTER_PORT_SUMMARY.md` as additional graph adapters land.
- Remote manifest examples (`docs/sample_remote_manifest*.yaml`) already reference the adapter; update them if provider keys or stack levels change.

Graph backlog is now clear—additional adapters (e.g., Neptune) can follow the same template if requirements materialize.
