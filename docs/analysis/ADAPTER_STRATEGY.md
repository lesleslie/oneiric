# Adapter Strategy & Roadmap

**Purpose:** Define the adapter porting strategy, naming conventions, and ORM/query interface approach for Oneiric.

**Status:** Planning Document
**Date:** 2025-11-26

---

## Current Adapter Landscape

### Implemented Adapters (15 categories, 37 adapters)

**Data Layer (2 categories, 9 adapters):**
- ✅ `cache/` - memory (2), redis (2)
- ✅ `database/` - postgres, mysql, sqlite, duckdb (SQL only)

**Infrastructure (3 categories, 10 adapters):**
- ✅ `storage/` - local, s3, gcs, azure
- ✅ `queue/` - nats, redis_streams
- ✅ `secrets/` - env, file, aws, gcp, infisical

**Application Layer (4 categories, 7 adapters):**
- ✅ `http/` - aiohttp, httpx
- ✅ `identity/` - auth0
- ✅ `monitoring/` - logfire, otlp, sentry

**AI Layer (3 categories, 6 adapters):**
- ✅ `embedding/` - openai, sentence_transformers, onnx
- ✅ `vector/` - pinecone, qdrant
- ✅ `llm/` - openai, anthropic

**Total:** 12 categories, 34 adapter implementations

---

## ACB Adapter Categories (for comparison)

**From ACB codebase scan:**
- `ai/` - cloud, edge, hybrid (LLM orchestration)
- `cache/` - memory, redis
- `dns/` - cloudflare, route53, gcdns
- `embedding/` - openai, huggingface, onnx, sentence_transformers, lfm
- `ftpd/` - ftp, sftp
- `graph/` - neo4j, arangodb, duckdb_pgq, neptune
- `logger/` - logly, loguru, structlog
- `messaging/` - (likely kafka, rabbitmq, etc.)

**ACB has ~40+ adapter categories with 100+ implementations**

---

## Database Adapter Naming Strategy

### Current State: `database/` (SQL only)

**Problem:** Category name `database` implies all databases, but only SQL is implemented.

### Recommended Solution: Keep `database/` as SQL umbrella

**Rationale:**
1. **Most common use case** - SQL databases are 80% of production workloads
2. **Consistent with industry** - "database adapter" typically means SQL
3. **NoSQL is niche** - NoSQL databases are specialized, domain-specific
4. **Avoid fragmentation** - Single category easier to discover

### Proposed Structure

```
oneiric/adapters/
├── database/           # SQL databases (umbrella category)
│   ├── postgres.py
│   ├── mysql.py
│   ├── sqlite.py
│   ├── mssql.py       # Future: SQL Server
│   ├── oracle.py      # Future: Oracle
│   └── cockroachdb.py # Future: CockroachDB
│
├── nosql/             # NoSQL databases (umbrella category)
│   ├── mongodb.py     # Document store
│   ├── redis.py       # Key-value (note: redis cache vs redis nosql)
│   ├── cassandra.py   # Wide-column
│   ├── dynamodb.py    # Key-value (AWS)
│   └── firestore.py   # Document store (GCP)
│
├── graph/             # Graph databases (specialized)
│   ├── neo4j.py
│   ├── arangodb.py
│   ├── duckdb_pgq.py
│   └── neptune.py
│
├── vector/            # Vector databases (specialized, AI-specific)
│   ├── pinecone.py
│   ├── weaviate.py
│   ├── qdrant.py
│   ├── milvus.py
│   └── pgvector.py    # Postgres extension (shipped Dec 2025)
│
└── search/            # Search engines (specialized)
    ├── elasticsearch.py
    ├── opensearch.py
    ├── typesense.py
    └── meilisearch.py
```

**Key Decisions:**
- ✅ `database/` = SQL databases (existing behavior preserved)
- ✅ `nosql/` = Document/key-value/wide-column databases
- ✅ `graph/`, `vector/`, `search/` = Specialized categories
- ✅ Category reflects **access pattern**, not storage technology

---

## ORM/Query Interface Strategy

### Philosophy: **Pydantic-First, Universal Query, Zero Vendor Lock-In**

**Core Principles:**
1. **Pydantic models everywhere** - Single source of truth
2. **Universal query interface** - Same API across SQL/NoSQL/Graph
3. **Type-safe at compile time** - Full mypy/pyright support
4. **Adapter-specific optimizations** - Leverage native features when available
5. **Zero learning curve** - Familiar patterns from SQLModel/Redis-OM

### Recommended Stack

#### SQL Databases: **SQLModel** (Pydantic + SQLAlchemy)

**Why SQLModel:**
- ✅ Built on Pydantic V2 (same as Oneiric)
- ✅ Full SQLAlchemy 2.0 support (async)
- ✅ Type-safe queries with IDE autocomplete
- ✅ Single model for both validation + ORM
- ✅ Battle-tested (used by FastAPI ecosystem)
- ✅ Zero additional learning (Pydantic syntax)

**Example:**
```python
from sqlmodel import SQLModel, Field, select
from oneiric.adapters import get_adapter

class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    email: str

# Adapter-agnostic usage
db = await get_adapter("database")  # Resolves to postgres/mysql/sqlite
async with db.session() as session:
    user = User(name="Alice", email="alice@example.com")
    session.add(user)
    await session.commit()

    # Type-safe queries
    result = await session.execute(select(User).where(User.email == "alice@example.com"))
    user = result.scalar_one()
```

#### NoSQL: **Redis-OM + ODMantic** (Pydantic-backed)

**Why Redis-OM + ODMantic:**
- ✅ Pydantic V2 models (consistent with SQLModel)
- ✅ Redis-OM for Redis (hash/JSON storage)
- ✅ ODMantic for MongoDB (async motor)
- ✅ Type-safe queries
- ✅ Automatic indexing

**Example (Redis-OM):**
```python
from redis_om import HashModel
from oneiric.adapters import get_adapter

class Session(HashModel):
    user_id: str
    token: str
    expires_at: int

# Adapter-agnostic usage
redis = await get_adapter("nosql", provider="redis")
session = Session(user_id="123", token="abc", expires_at=1234567890)
await session.save()

# Type-safe queries
sessions = await Session.find(Session.user_id == "123").all()
```

**Example (ODMantic for MongoDB):**
```python
from odmantic import Model
from oneiric.adapters import get_adapter

class Document(Model):
    title: str
    content: str
    tags: list[str]

# Adapter-agnostic usage
mongo = await get_adapter("nosql", provider="mongodb")
engine = mongo.engine  # ODMantic engine
doc = Document(title="Test", content="Hello", tags=["demo"])
await engine.save(doc)

# Type-safe queries
docs = await engine.find(Document, Document.tags.in_(["demo"]))
```

#### Graph Databases: **Custom Pydantic Models + Cypher/Gremlin**

**Why Custom:**
- Graph queries are inherently different (traversals, not filters)
- Cypher (Neo4j) and Gremlin (ArangoDB/Neptune) are domain-specific
- Pydantic models for **node/edge schemas**, native DSLs for queries

**Example:**
```python
from pydantic import BaseModel
from oneiric.adapters import get_adapter

class Person(BaseModel):
    name: str
    age: int

class Knows(BaseModel):
    since: int

# Adapter-agnostic node creation
graph = await get_adapter("graph", provider="neo4j")
await graph.create_node("Person", Person(name="Alice", age=30))

# Native Cypher for complex queries
result = await graph.query(
    "MATCH (p:Person)-[k:KNOWS]->(friend) WHERE p.name = $name RETURN friend",
    name="Alice"
)
```

#### Vector Databases: **Pydantic Models + Native Clients**

**Why Native:**
- Vector search is highly optimized (HNSW, IVF indexes)
- Each database has unique features (metadata filters, hybrid search)
- Pydantic models for **schema**, native clients for queries

**Example:**
```python
from pydantic import BaseModel
from oneiric.adapters import get_adapter

class Embedding(BaseModel):
    text: str
    vector: list[float]
    metadata: dict

# Adapter-agnostic upsert
vector_db = await get_adapter("vector", provider="pinecone")
await vector_db.upsert(
    Embedding(text="Hello world", vector=[0.1, 0.2, ...], metadata={"source": "doc1"})
)

# Native search (optimized)
results = await vector_db.query(
    vector=[0.15, 0.25, ...],
    top_k=10,
    filter={"source": "doc1"}
)
```

---

## Universal Query Interface (Proposed)

### Goal: **Same API across SQL/NoSQL/Graph/Vector**

**Inspired by:** Prisma (TypeScript), Beanie (Python), EdgeDB

### Proposed Interface

```python
from oneiric.adapters import get_adapter

# Adapter-agnostic CRUD
db = await get_adapter("database")  # or "nosql" or "graph"

# Create
user = await db.create(User(name="Alice", email="alice@example.com"))

# Read (universal query syntax)
users = await db.find(User).where(User.email.contains("@example.com")).all()
user = await db.get(User, id=123)

# Update
user.name = "Alice Smith"
await db.save(user)

# Delete
await db.delete(user)

# Transactions (SQL/NoSQL with ACID support)
async with db.transaction():
    await db.create(user1)
    await db.create(user2)  # Rollback if this fails
```

### Implementation Strategy

**Phase 1 (Now):** Keep adapter-specific interfaces
- Each adapter exposes native client (asyncpg, motor, neo4j driver)
- No abstraction layer yet
- **Rationale:** Avoid premature abstraction, learn patterns first

**Phase 2 (Future):** Add universal interface
- Implement `.create()`, `.find()`, `.save()`, `.delete()` on all adapters
- Keep native clients available for advanced use cases
- **Rationale:** 80% of operations are CRUD, 20% need native features

**Phase 3 (Future):** Add query builder
- Chainable query syntax (`.where()`, `.order_by()`, `.limit()`)
- Compile to native queries (SQL/Cypher/Vector search)
- **Rationale:** Type-safe queries without SQL injection

---

## Next Adapters to Port (Priority Order)

### High Priority (Next 3-6 months)

**1. Vector Databases** (Critical for AI workloads)
- `vector/pinecone.py` - Most popular, SaaS
- `vector/qdrant.py` - Open source, self-hosted
- `vector/pgvector.py` - Postgres extension (asyncpg + pgvector extension)
- **Rationale:** AI/LLM workloads are Oneiric's sweet spot

**2. Embedding Adapters** (Complements vector DBs)
- `embedding/openai.py` - Most common
- `embedding/sentence_transformers.py` - Open source
- `embedding/onnx.py` - On-device, low latency
- **Rationale:** Embeddings feed vector databases

**3. NoSQL Databases** (High demand)
- `nosql/mongodb.py` - ✅ Shipped Dec 2025 (Motor-based adapter with CRUD + aggregation)
- `nosql/dynamodb.py` - ✅ Shipped Dec 2025 (aioboto3 adapter with CRUD + scans)
- `nosql/firestore.py` - ✅ Shipped Dec 2025 (Firestore async adapter with set/get/query + emulator support)
- **Rationale:** Many teams need document storage

**4. Graph Databases** (Specialized use cases)
- Neo4j + ArangoDB + DuckDB PGQ adapters ✅ (landed Dec 2025); monitor demand for `graph/neptune.py`.
- **Rationale:** Knowledge graphs, recommendation engines

**5. AI/LLM Adapters** (Strategic)
- `ai/openai.py` - GPT-4, embeddings
- `ai/anthropic.py` - Claude
- `ai/gemini.py` - Google
- **Rationale:** First-class LLM support aligns with AI Agent Compatibility doc

### Medium Priority (6-12 months)

**6. Messaging** (Event-driven architectures)
- `messaging/kafka.py` - ✅ Shipped Dec 2025 (aiokafka streaming adapter)
- `messaging/rabbitmq.py` - ✅ Shipped Dec 2025 (aio-pika queue adapter)
- `messaging/pulsar.py` - Pending (evaluate demand before porting)
- **Rationale:** Complements existing queue adapters

**7. DNS** (DevOps use cases)
- Port ACB's `dns/cloudflare.py`, `dns/route53.py`, `dns/gcdns.py`
- **Rationale:** Infrastructure automation

**8. FTP/SFTP** (Legacy integrations)
- Port ACB's `ftpd/ftp.py`, `ftpd/sftp.py`
- **Rationale:** Many enterprises still use FTP

**9. Search Engines** (Full-text search)
- `search/elasticsearch.py` - Most popular
- `search/opensearch.py` - AWS fork
- `search/typesense.py` - Modern alternative
- **Rationale:** Complements databases

### Low Priority (Future)

**10. Additional SQL Databases**
- `database/mssql.py` - SQL Server (enterprise)
- `database/oracle.py` - Oracle (enterprise)
- `database/cockroachdb.py` - Distributed SQL
- **Rationale:** Less common, niche use cases

**11. Specialized NoSQL**
- `nosql/cassandra.py` - Wide-column (scaling)
- `nosql/couchbase.py` - Document + key-value
- **Rationale:** Very specialized

---

## ACB Parity Status (December 2025)

| ACB Adapter | Oneiric Status | Owner | Notes |
|-------------|----------------|-------|-------|
| `vector/pgvector.py` | ✅ Complete | Data Platform | Asyncpg-backed adapter with inline collection helpers + tests. |
| `nosql/mongodb.py` | ✅ Complete | Platform Core | Motor adapter with CRUD helpers, aggregation, tests (Dec 2025). |
| `nosql/dynamodb.py` | ✅ Complete | Platform Core | aioboto3 adapter with CRUD/scan/conditional writes (Dec 2025). |
| `nosql/firestore.py` | ✅ Complete | Platform Core | Async Firestore adapter with set/get/query + emulator/credentials support (Dec 2025). |
| `graph/neo4j.py` | ✅ Complete | Data Platform | Async driver-backed adapter with node/relationship helpers + docs. |
| `graph/arangodb.py` | ✅ Complete | Data Platform | Multi-model adapter with vertex/edge helpers + docs/tests (Dec 2025). |
| `graph/duckdb_pgq.py` | ✅ Complete | Data Platform | DuckDB PGQ adapter with ingest/query helpers + docs/tests (Dec 2025). |
| `llm/gemini.py` | ❌ Pending | AI Platform | Completes Wave C LLM kits |
| `dns/cloudflare.py`, `dns/route53.py`, `dns/gcdns.py` | ❌ Pending | Infra Team | Needed for DevOps parity |
| `ftpd/ftp.py`, `ftpd/sftp.py` | ❌ Pending | Infra Team | Legacy integrations |
| `messaging/kafka.py`, `messaging/rabbitmq.py` | ✅ Complete | Runtime Team | aiokafka + aio-pika adapters with publish/consume helpers (Dec 2025). |
| `messaging/pulsar.py` | ❌ Pending | Runtime Team | Optional follow-up if demand emerges. |

These items remain in backlog and must be tracked in sprint planning to maintain parity with ACB’s adapter surface.

---

## ORM/Query Recommendation Summary

### Immediate Implementation (v0.3.0)

**SQL Databases:**
- ✅ Use **SQLModel** (Pydantic + SQLAlchemy)
- ✅ Expose native asyncpg/aiomysql/aiosqlite clients for advanced use
- ✅ Add `.session()` context manager to all database adapters
- ✅ Document SQLModel patterns in adapter documentation

**NoSQL Databases (when implemented):**
- ✅ Use **Redis-OM** for Redis (hash/JSON storage)
- ✅ Use **ODMantic** for MongoDB (async motor)
- ✅ Expose native clients for advanced use
- ✅ Document Pydantic model patterns

**Graph Databases (when ported):**
- ✅ Use **Pydantic models** for node/edge schemas
- ✅ Expose native drivers (Neo4j, ArangoDB) for Cypher/Gremlin
- ✅ Add helper methods: `.create_node()`, `.create_edge()`, `.query()`

**Vector Databases (when implemented):**
- ✅ Use **Pydantic models** for document schemas
- ✅ Expose native clients (Pinecone, Qdrant) for optimized queries
- ✅ Add helper methods: `.upsert()`, `.query()`, `.delete()`

### Future Enhancement (v0.4.0+)

**Universal Query Interface:**
- 📝 Add `.create()`, `.find()`, `.save()`, `.delete()` to all adapters
- 📝 Implement chainable query builder (`.where()`, `.order_by()`, `.limit()`)
- 📝 Compile queries to native formats (SQL, Cypher, vector search)
- 📝 Keep native clients available for 20% advanced use cases

**Type Safety:**
- 📝 Full mypy/pyright support
- 📝 IDE autocomplete for all queries
- 📝 Compile-time query validation

---

## Migration Path from ACB

### Adapter Porting Checklist

**For each ACB adapter:**

1. **Copy adapter implementation** from ACB to Oneiric
2. **Update imports** to use Oneiric's core modules:
   - `from oneiric.adapters.metadata import AdapterMetadata`
   - `from oneiric.core.lifecycle import LifecycleError`
   - `from oneiric.core.logging import get_logger`
3. **Add lifecycle hooks** (if missing):
   - `async def health(self) -> bool`
   - `async def cleanup(self) -> None`
4. **Add AdapterMetadata** to class:
   ```python
   metadata = AdapterMetadata(
       category="vector",
       provider="pinecone",
       factory="oneiric.adapters.vector.pinecone:PineconeAdapter",
       capabilities=["upsert", "query", "delete", "namespaces"],
       stack_level=30,
       priority=500,
       source=CandidateSource.LOCAL_PKG,
       owner="Data Platform",
       requires_secrets=True,
       settings_model=PineconeSettings,
   )
   ```
5. **Update Pydantic models** to use V2 syntax:
   - `from pydantic import BaseModel, Field, ConfigDict`
   - Add `model_config = ConfigDict(...)` instead of class Config
6. **Add tests** (100 lines minimum):
   - Unit tests for initialization
   - Health check tests
   - Cleanup tests
   - Integration tests (if possible)
7. **Update documentation**:
   - Add adapter to `oneiric/adapters/<category>/__init__.py`
   - Add usage example to `docs/adapters/<category>_USAGE.md`

### Example: Vector Database Adapter (Pinecone)

**File:** `oneiric/adapters/vector/pinecone.py`

```python
"""Pinecone vector database adapter."""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field
from pinecone import Pinecone

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class PineconeSettings(BaseModel):
    """Configuration for the Pinecone adapter."""

    api_key: str = Field(description="Pinecone API key")
    environment: str = Field(default="us-east-1-aws", description="Pinecone environment")
    index_name: str = Field(description="Index name")


class PineconeAdapter:
    """Pinecone vector database adapter with lifecycle hooks."""

    metadata = AdapterMetadata(
        category="vector",
        provider="pinecone",
        factory="oneiric.adapters.vector.pinecone:PineconeAdapter",
        capabilities=["upsert", "query", "delete", "namespaces", "metadata_filter"],
        stack_level=30,
        priority=500,
        source=CandidateSource.LOCAL_PKG,
        owner="Data Platform",
        requires_secrets=True,
        settings_model=PineconeSettings,
    )

    def __init__(self, settings: PineconeSettings):
        self._settings = settings
        self._client: Optional[Pinecone] = None
        self._index = None
        self._logger = get_logger("adapters.vector.pinecone")

    async def initialize(self) -> None:
        """Initialize Pinecone client and index."""
        try:
            self._client = Pinecone(api_key=self._settings.api_key)
            self._index = self._client.Index(self._settings.index_name)
            self._logger.info("pinecone-initialized", index=self._settings.index_name)
        except Exception as exc:
            raise LifecycleError(f"Failed to initialize Pinecone: {exc}") from exc

    async def health(self) -> bool:
        """Check if Pinecone is healthy."""
        if not self._index:
            return False
        try:
            # Pinecone has no health endpoint, just check if we can describe index
            stats = self._index.describe_index_stats()
            return stats is not None
        except Exception:
            return False

    async def cleanup(self) -> None:
        """Cleanup Pinecone resources."""
        self._client = None
        self._index = None
        self._logger.info("pinecone-cleanup")

    async def upsert(self, vectors: list[dict[str, Any]]) -> None:
        """Upsert vectors into index."""
        if not self._index:
            raise LifecycleError("Pinecone not initialized")
        self._index.upsert(vectors=vectors)

    async def query(
        self, vector: list[float], top_k: int = 10, filter: Optional[dict] = None
    ) -> list[dict]:
        """Query vectors from index."""
        if not self._index:
            raise LifecycleError("Pinecone not initialized")
        results = self._index.query(vector=vector, top_k=top_k, filter=filter)
        return results.matches

    async def delete(self, ids: list[str]) -> None:
        """Delete vectors from index."""
        if not self._index:
            raise LifecycleError("Pinecone not initialized")
        self._index.delete(ids=ids)
```

---

## Conclusion

**Recommended Naming:**
- ✅ Keep `database/` for SQL databases
- ✅ Add `nosql/` for document/key-value stores
- ✅ Add specialized categories: `graph/`, `vector/`, `search/`

**Recommended ORM Strategy:**
- ✅ **SQLModel** for SQL (Pydantic + SQLAlchemy)
- ✅ **Redis-OM + ODMantic** for NoSQL (Pydantic-backed)
- ✅ **Custom Pydantic models** for Graph/Vector (native clients for queries)
- 📝 **Universal query interface** as future enhancement (v0.4.0+)

**Next Adapters (Priority):**
1. Vector databases (Pinecone, Qdrant, PGVector)
2. Embedding adapters (OpenAI, Sentence Transformers)
3. NoSQL databases (MongoDB, DynamoDB, Firestore)
4. AI/LLM adapters (OpenAI, Anthropic, Gemini)

**Timeline:**
- **v0.3.0 (Q1 2025):** Vector + Embedding + NoSQL
- **v0.4.0 (Q2 2025):** Graph + AI/LLM + Universal query interface
- **v0.5.0 (Q3 2025):** Messaging + DNS + Search

This strategy balances **pragmatism** (keep SQL as `database/`) with **clarity** (NoSQL/Graph/Vector are separate concerns) while maintaining **consistency** (Pydantic models everywhere).
