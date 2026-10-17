---
title: Oneiric Substrate — Shared Persistence and Embedding Layer
status: active
role: canonical
date: 2026-10-17
last_reviewed: 2026-10-17
superseded_by: null
blocks_on: []
topic: persistence
related:
  - ../architecture/MEMORY_ARCHITECTURE.md
  - ../specs/2026-10-11-adapter-contract-design.md
  - ../adr/0002-oneiric-adapter-contract.md
---

# Oneiric Substrate

> **Audience**: Bodai ecosystem contributors integrating Mahavishnu,
> Akosha, Session-Buddy, Crackerjack, or any external consumer with
> Oneiric's persistence + embedding layer.
> **Source of truth**: `oneiric/adapters/storage/`,
> `oneiric/adapters/database/`, `oneiric/adapters/cache/`,
> `oneiric/adapters/queue/`, `oneiric/adapters/vector/`,
> `oneiric/adapters/embedding/`, `oneiric/adapters/observability/`,
> `oneiric/core/substrate_settings.py`, `oneiric/core/bridge.py`.

The Oneiric **substrate** is the shared persistence and embedding
layer every Bodai component binds against. It subsumed the old
Dhara storage concerns in 2026-09 (per
[ADR 017](https://github.com/lesleslie/mahavishnu/blob/main/docs/adr/017-oneiric-shared-persistence-substrate.md)):
all blob, SQL, KV, queue, vector, and embedding operations are now
fronted by Oneiric adapters rather than cross-component imports.

## 1. What the substrate is

The substrate is not a database. It is a **uniform adapter layer**
across six storage categories, all built on the same metadata +
lifecycle contract:

| Category   | Adapter examples                          | Use it for                                 |
|------------|-------------------------------------------|--------------------------------------------|
| `storage`  | `s3`, `local_disk`, `mirror`, `snapshot`  | Blobs, files, backup snapshots, OTel logs. |
| `database` | `sqlite`, `postgres`, `libsql`, `turso`   | SQL with migrations, ACID transactions.    |
| `cache`    | `memory`, `redis`, `multitier`, `snapshot`| KV reads, hot-tier state, session caches.  |
| `queue`    | `redis_streams`, `kafka`, `pubsub`, `nats`| Durable background work, fanout, WAL.     |
| `vector`   | `pgvector`, `qdrant`, `duckdb_hot_store`  | Embedding storage + similarity search.    |
| `embedding`| `openai`, `local`, `probe_chain`          | Compute embeddings (L2-normalized).       |

Together they replace Dhara's hardcoded `FileStorage`, Akosha's bespoke
`HotStorageConfig`, Mahavishnu's direct `akosha.storage` import, and
Session-Buddy's per-repo SQLite.

**Hot / warm / cold tiers** (per `SubstrateSettings` in
`oneiric/core/substrate_settings.py`):

- **Hot** (`cache`): in-process or Redis, microsecond reads, optional
  TTL. Used for recently-resolved lookups, adapter registry mirrors,
  and lock tokens.
- **Warm** (`vector` + `database`): pgvector and Postgres for
  embeddings + relational queries. Millisecond reads. Serverless-safe
  via Neon read replicas.
- **Cold** (`storage`): S3-compatible object stores for blobs,
  backups, audit logs. Tunable lifecycle policy.

All three tiers bind against a single `SubstrateSettings` container —
the env-var form `ONEIRIC__SUBSTRATE__CACHE__MAX_ENTRIES=5` reaches
the `cache__max_entries` field on that model.

## 2. How to use it

Consumers never import concrete adapters. They go through
`AdapterBridge.use()`:

```python
from oneiric.adapters.bridge import AdapterBridge
from oneiric.core.config import load_settings

settings = load_settings()
bridge = AdapterBridge(resolver, lifecycle, settings)

# Resolve by category only — resolver scores by priority + capability
cache_handle = await bridge.use("cache")
await cache_handle.instance.set("user:42", {"name": "Ada"}, ttl=60)

# Or pin a specific provider
db_handle = await bridge.use("database", provider="postgres")
pool = await db_handle.instance.connect()

# Or capability-gate
vector_handle = await bridge.use("vector", capabilities=["hnsw"])
hits = await vector_handle.instance.search_similar(
    query_embedding=embedding, limit=10, threshold=0.7
)
```

`bridge.use()` returns an `AdapterHandle` carrying the live, init()'d
instance + materialized Pydantic settings + the original metadata dict.
If no candidate matches, it raises
`LifecycleError("No adapter candidate found for {key}")`.

### 2.1 Init / store / query / retrieve

The lifecycle contract is three async methods on every adapter
(`oneiric/core/lifecycle.py`):

```python
class MyAdapter:
    metadata = AdapterMetadata(category="vector", provider="pgvector", ...)

    async def init(self) -> None:
        """Open pool, ping backend, prepare schema. Idempotent."""

    async def health(self) -> bool:
        """Return True/False. NEVER raise — raise = 5xx, not degraded."""

    async def cleanup(self) -> None:
        """Close pool, drop connections. Called on bridge.shutdown()."""
```

Storage adapters add CRUD methods specific to their category. Examples:

```python
# Vector adapter — search + insert
async def insert(self, record: dict) -> None: ...
async def search_similar(self, query: list[float], limit: int = 10,
                         threshold: float = 0.7) -> list[dict]: ...

# Database adapter — connection pool + transactional context
async def connect(self) -> Connection: ...
async def execute(self, sql: str, params: dict | None = None) -> Cursor: ...

# Cache adapter — typed KV
async def get(self, key: str) -> Any | None: ...
async def set(self, key: str, value: Any, ttl: float | None = None) -> None: ...
async def delete(self, key: str) -> bool: ...

# Storage adapter — blob I/O
async def put(self, key: str, data: bytes, metadata: dict | None = None) -> str: ...
async def get(self, key: str) -> bytes: ...
async def list(self, prefix: str = "") -> AsyncIterator[str]: ...
```

### 2.2 Embeddings: L2-normalized at the base

`EmbeddingBase.embed_text()` / `embed_texts()` / `embed_documents()`
**always** return unit-length vectors. Subclasses hand back raw
provider output; the base re-normalizes to L2 norm == 1. Callers do
not need to (and should not) apply their own normalization.

```python
handle = await bridge.use("embedding", provider="openai")
vector = await handle.instance.embed_text("hello world")
assert math.isclose(sum(c * c for c in vector), 1.0, abs_tol=1e-6)
```

This is enforced by `tests/adapters/embedding/test_normalize_layer.py`
and is the substrate-wide contract regardless of provider.

## 3. Adapter lifecycle: register, resolve, dispose

### 3.1 Register

Built-in adapters register through `register_builtin_adapters()` in
`oneiric/adapters/bootstrap.py`. Third-party adapters register via
Python entry points declared in `pyproject.toml`. Runtime
registration (tests, plugins) goes through
`resolver.register(candidate)` directly.

The four `CandidateSource` paths (`oneiric/core/resolution.py`):

- `LOCAL_PKG` — built-ins shipped with Oneiric.
- `ENTRY_POINT` — out-of-tree adapters published on PyPI.
- `REMOTE_MANIFEST` — signed YAML manifests (the Dhara-MCP path that
  previously held the cross-ecosystem catalog has been decomposed;
  `REMOTE_MANIFEST` now means "load from
  `~/.oneiric/adapter_registry.json` after `oneiric remote-sync`").
- `MANUAL` — `resolver.register(...)` at runtime.

### 3.2 Resolve

The `Resolver` scores candidates by `priority × capability_match ×
stack_level × registration_order` and picks the highest-scoring
match. `AdapterBridge.use(category, provider=..., capabilities=...)`
calls the resolver, materializes settings, and runs `init()` before
returning the handle.

### 3.3 Dispose

`bridge.shutdown()` walks every handle that was issued during the
session, calling `cleanup()` in reverse-resolution order. After
shutdown the bridge is dead — subsequent `use()` calls raise
`LifecycleError`. Applications embed the bridge in their main
lifecycle (e.g. `mahavishnu.core.app.MahavishnuApp`).

`health()` is **never** expected to raise. Transport errors are
logged and surfaced as `False`. Monitoring relies on the bool
contract — raising would surface as a 5xx instead of a degraded
state.

## 4. Cross-component access (Bodai consumers)

Mahavishnu, Akosha, Session-Buddy, and Crackerjack **do not import
Oneiric directly** for substrate access. They call the MCP tools:

| Tool                         | Purpose                                       |
|------------------------------|-----------------------------------------------|
| `oneiric_list_adapters`      | List registered adapters (filter by domain).  |
| `oneiric_get_adapter`        | Retrieve adapter record by `(domain, key, provider)`. |
| `oneiric_get_adapter_health` | Probe adapter health.                         |
| `oneiric_validate_adapter`   | Verify factory import + deps + capabilities.   |
| `oneiric_store_adapter`      | Register/update a custom adapter.              |
| `oneiric_report_runtime`     | Push sanitized runtime facts.                  |

This rule survived the Dhara decomposition (2026-09) — direct Python
imports across Bodai components are forbidden.

## 5. Migration from Dhara's old storage API

Dhara's pre-2026-09 storage surface (`dhara/storage/file.py` +
`dhara/mcp/server_core.py` `FileStorage` class) is **gone**. Repos
that referenced it must migrate:

| Old Dhara surface                            | New Oneiric substrate call                          |
|----------------------------------------------|-----------------------------------------------------|
| `from dhara.storage import FileStorage`      | `await bridge.use("storage", provider="local_disk")`  |
| `FileStorage(path)` / `.read()` / `.write()` | `StorageAdapter.put()` / `.get()`                   |
| `from akosha.storage import HotStore` (cross-component import — forbidden) | `await bridge.use("vector", capabilities=["hnsw"])` |
| `HotStore.initialize()` / `.search_similar()`| `VectorAdapter.initialize()` / `.search_similar()`  |
| `mahavishnu.ingesters.otel_ingester` direct dhara imports | `bridge.use("vector")` + `bridge.use("storage")` |
| Hardcoded `fcntl`-based locks in Dhara MCP   | Resolver + lifecycle + adapter-level locking        |
| `dhara/mcp/server_core.py` adapter registry  | `oneiric_list_adapters` MCP tool + local JSON       |

The Dhara repo still exists as a separate component (it handles
federated identity / session restoration and other non-storage
concerns); only its storage surface was lifted into Oneiric.

**Migration steps for a repo that previously depended on Dhara
storage**:

1. Add `oneiric` to the repo's `[project].dependencies`.
2. Replace direct `from dhara.storage import ...` with
   `bridge = AdapterBridge(...); await bridge.use("storage", ...)`.
3. Replace cross-component imports from `akosha.storage` /
   `session_buddy.storage` with the same bridge pattern (the
   corresponding Oneiric adapter category).
4. Verify with `oneiric mcp health` that the new adapter is in the
   catalog and reports `healthy`.
5. Run the repo's test matrix with `ONEIRIC__SUBSTRATE__STORAGE__BACKEND=s3`
   in CI to exercise the cloud path (per ADR 017 serverless-readiness).

## 6. References

- [ADR 017 — Oneiric as the shared persistence substrate for Bodai](https://github.com/lesleslie/mahavishnu/blob/main/docs/adr/017-oneiric-shared-persistence-substrate.md)
- [ADR 013 — Mahavishnu Dhara adapter-tool boundary](https://github.com/lesleslie/mahavishnu/blob/main/docs/adr/013-mahavishnu-dhara-adapter-tool-boundary.md)
- [ADR 0002 — Oneiric adapter contract](adr/0002-oneiric-adapter-contract.md)
- [Oneiric Adapter Contract spec](specs/2026-10-11-adapter-contract-design.md)
- [Oneiric Memory Architecture](architecture/MEMORY_ARCHITECTURE.md)
- [Migration guide for Dhara-using repos](MIGRATION_GUIDE.md)
