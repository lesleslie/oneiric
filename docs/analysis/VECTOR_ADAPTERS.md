# Vector Database Adapters

**Status:** Initial Implementation
**Date:** 2025-11-27
**Adapters:** Pinecone, Qdrant, PGVector

______________________________________________________________________

## Overview

Oneiric now supports vector database adapters for AI/LLM workloads. Vector databases enable semantic search, similarity matching, and embeddings storage for AI applications.

## Installation

Vector SDKs are guarded behind optional extras so the core package stays lightweight. Install the ones you need:

```bash
pip install 'oneiric[vector-pinecone]'   # Pinecone client
pip install 'oneiric[vector-qdrant]'     # Qdrant client
pip install 'oneiric[vector]'            # Installs both extras above
```

These extras map directly to `pyproject.toml`’s `[project.optional-dependencies]` entries, so upgrading the repo automatically surfaces new versions. The CLI/demo docs cross-link these extras whenever a sample flow uses Pinecone or Qdrant.

**Implemented Adapters:**

- ✅ **Pinecone** - Managed serverless vector database
- ✅ **Qdrant** - High-performance open-source vector search engine
- ✅ **PGVector** - Postgres extension with asyncpg pool + pgvector type registration

**Planned Adapters (per ADAPTER_STRATEGY.md):**

- 📝 Weaviate
- ✅ DuckDB PGQ (now implemented under `graph/duckdb_pgq.py`)

______________________________________________________________________

## Architecture

### Base Classes

All vector adapters inherit from `VectorBase` and implement standard lifecycle hooks:

```python
from oneiric.adapters.vector import VectorBase


class MyVectorAdapter(VectorBase):
    async def init(self) -> None:
        """Initialize connection"""

    async def health(self) -> bool:
        """Health check"""

    async def cleanup(self) -> None:
        """Cleanup resources"""
```

### Common Models

**`VectorDocument`** - Document with vector embedding:

```python
from oneiric.adapters.vector import VectorDocument

doc = VectorDocument(
    id="doc-123",
    vector=[0.1, 0.2, 0.3, ...],  # Embedding vector
    metadata={"title": "Example", "author": "Alice"},
)
```

**`VectorSearchResult`** - Search result with similarity score:

```python
from oneiric.adapters.vector import VectorSearchResult

result = VectorSearchResult(
    id="doc-123",
    score=0.95,  # Similarity score (higher = more similar)
    metadata={"title": "Example"},
    vector=[0.1, 0.2, ...],  # Optional
)
```

______________________________________________________________________

## Pinecone Adapter

### Configuration

```yaml
# settings/adapters.yml
vector: pinecone
from oneiric.adapters.vector import PineconeSettings

settings = PineconeSettings(
    api_key="your-api-key",
    environment="us-west1-gcp-free",
    index_name="my-index",
    serverless=True,
    cloud="aws",
    region="us-east-1",
    metric="cosine",  # cosine, euclidean, dotproduct
    default_dimension=1536,  # OpenAI ada-002 default
)
```

### Usage

```python
from oneiric.adapters import get_adapter
from oneiric.adapters.vector import VectorDocument

# Get adapter via lifecycle manager
adapter = await lifecycle.activate("adapter", "vector")

# Upsert documents
docs = [
    VectorDocument(
        id="doc-1", vector=[0.1, 0.2, 0.3, ...], metadata={"title": "Document 1"}
    ),
    VectorDocument(
        id="doc-2", vector=[0.4, 0.5, 0.6, ...], metadata={"title": "Document 2"}
    ),
]

doc_ids = await adapter.upsert(
    collection="documents",  # Namespace in Pinecone
    documents=docs,
)

# Search
query_vector = [0.15, 0.25, 0.35, ...]
results = await adapter.search(
    collection="documents",
    query_vector=query_vector,
    limit=10,
    filter_expr={"title": "Document 1"},  # Metadata filter
    include_vectors=False,
)

for result in results:
    print(f"ID: {result.id}, Score: {result.score}")
    print(f"Metadata: {result.metadata}")
```

### Features

- ✅ **Serverless & Pod-based indexes**
- ✅ **Namespaces** (collections)
- ✅ **Metadata filtering**
- ✅ **Batch operations** (configurable batch size)
- ✅ **Multiple distance metrics** (cosine, euclidean, dotproduct)
- ✅ **Auto-index creation**

### Capabilities

```python
adapter.has_capability("vector_search")  # True
adapter.has_capability("batch_operations")  # True
adapter.has_capability("metadata_filtering")  # True
adapter.has_capability("namespaces")  # True
adapter.has_capability("serverless")  # True
```

______________________________________________________________________

## Qdrant Adapter

### Configuration

```yaml
# settings/adapters.yml
vector: qdrant
from oneiric.adapters.vector import QdrantSettings

settings = QdrantSettings(
    url="http://localhost:6333",
    api_key="your-api-key",  # Optional
    grpc_port=6334,
    prefer_grpc=True,
    timeout=30.0,
    default_collection="documents",
    default_dimension=1536,
    on_disk_vectors=False,  # Store vectors in RAM for speed
    enable_quantization=True,  # Compress vectors
)
```

### Usage

```python
from oneiric.adapters.vector import VectorDocument

# Get adapter
adapter = await lifecycle.activate("adapter", "vector")

# Create collection
await adapter.create_collection(
    name="documents", dimension=1536, distance_metric="cosine"
)

# Upsert documents
docs = [
    VectorDocument(
        vector=[0.1, 0.2, 0.3, ...], metadata={"category": "tech", "year": 2024}
    )
]
doc_ids = await adapter.upsert("documents", docs)

# Search with filters
results = await adapter.search(
    collection="documents",
    query_vector=[0.15, 0.25, 0.35, ...],
    limit=10,
    filter_expr={"category": "tech", "year": 2024},
    score_threshold=0.7,  # Min similarity threshold
)

# Scroll through large result sets
documents, next_offset = await adapter.scroll(
    collection="documents", limit=100, filter_expr={"category": "tech"}
)

# Continue scrolling
more_docs, next_offset = await adapter.scroll(
    collection="documents", limit=100, offset=next_offset
)
```

### Features

- ✅ **HTTP & gRPC protocols**
- ✅ **Collections** (separate vector spaces)
- ✅ **Advanced metadata filtering**
- ✅ **Scroll API** (pagination for large datasets)
- ✅ **Quantization** (vector compression)
- ✅ **HNSW indexing** (configurable)
- ✅ **On-disk vectors** (optional)
- ✅ **Streaming operations**

### Capabilities

```python
adapter.has_capability("vector_search")  # True
adapter.has_capability("batch_operations")  # True
adapter.has_capability("metadata_filtering")  # True
adapter.has_capability("scroll")  # True
adapter.has_capability("quantization")  # True
adapter.has_capability("streaming")  # True
```

______________________________________________________________________

## Common Operations

### 1. Basic CRUD

```python
# Insert
doc_ids = await adapter.insert(collection, documents)

# Upsert (insert or update)
doc_ids = await adapter.upsert(collection, documents)

# Get by IDs
docs = await adapter.get(collection, ["doc-1", "doc-2"], include_vectors=True)

# Delete by IDs
success = await adapter.delete(collection, ["doc-1", "doc-2"])

# Count
total = await adapter.count(collection)
filtered_count = await adapter.count(collection, filter_expr={"year": 2024})
```

### 2. Collection Management

```python
# Create collection
await adapter.create_collection(
    name="documents", dimension=1536, distance_metric="cosine"
)

# List collections
collections = await adapter.list_collections()

# Delete collection
await adapter.delete_collection("documents")
```

### 3. Dynamic Collection Access

```python
# Access collections as attributes
results = await adapter.documents.search(query_vector=[0.1, 0.2, ...], limit=10)

# Same as
results = await adapter.search(
    collection="documents", query_vector=[0.1, 0.2, ...], limit=10
)
```

______________________________________________________________________

## Metadata Filtering

### Pinecone

```python
# Exact match
filter_expr = {"category": "tech"}

# Multiple conditions (implicit AND)
filter_expr = {"category": "tech", "year": 2024}

# Pinecone filter syntax (advanced)
filter_expr = {"$and": [{"category": {"$eq": "tech"}}, {"year": {"$gte": 2020}}]}
```

### Qdrant

```python
# Simple filters (string, int, float, bool)
filter_expr = {"category": "tech", "year": 2024}

# List matching (any of)
filter_expr = {"category": ["tech", "science"]}

# Qdrant automatically converts to Filter(must=[...])
```

______________________________________________________________________

## Distance Metrics

All adapters support standard distance metrics:

| Metric | Description | Use Case |
|-------------|--------------------------------------|-----------------------------|
| `cosine` | Cosine similarity (angle-based) | Text embeddings (default) |
| `euclidean` | L2 distance (geometric distance) | Spatial data |
| `dot_product` | Dot product (magnitude-aware) | Normalized embeddings |
| `manhattan` | L1 distance (Qdrant only) | High-dimensional data |

______________________________________________________________________

## Performance Tuning

### Pinecone

```python
settings = PineconeSettings(
    # Batch size for upserts
    upsert_batch_size=100,
    upsert_max_retries=3,
    upsert_timeout=30.0,

    # Index type
    serverless=True,  # Auto-scaling
    # OR
    serverless=False,
    pod_type="p1.x1",  # Fixed pods
    replicas=2,        # High availability
    shards=2,          # Horizontal scaling
)
```

### Qdrant

```python
settings = QdrantSettings(
    # HNSW index tuning
    hnsw_config={
        "m": 16,  # Links per node (higher = better recall)
        "ef_construct": 100,  # Build-time accuracy (higher = slower build)
        "full_scan_threshold": 10000,  # Switch to brute force below this
    },
    # Quantization (compression)
    enable_quantization=True,
    quantization_config={
        "scalar": {
            "type": "int8",  # 8-bit quantization
            "quantile": 0.99,  # Preserve 99% of values
            "always_ram": True,  # Keep compressed vectors in RAM
        }
    },
    # Storage
    on_disk_vectors=False,  # RAM = fast, disk = large datasets
    # Protocol
    prefer_grpc=True,  # gRPC is faster than HTTP
)
```

______________________________________________________________________

## Integration with Lifecycle Manager

Vector adapters follow the same lifecycle pattern as other Oneiric adapters:

```python
from oneiric.core.lifecycle import LifecycleManager
from oneiric.core.resolution import Resolver

resolver = Resolver()
lifecycle = LifecycleManager(resolver)

# Activate adapter
adapter = await lifecycle.activate("adapter", "vector")

# Health check
is_healthy = await lifecycle.probe_instance_health("adapter", "vector")

# Hot-swap to different provider
adapter = await lifecycle.swap("adapter", "vector", provider="qdrant")

# Get status
status = lifecycle.get_status("adapter", "vector")
print(status.state)  # "ready", "failed", "activating"
```

______________________________________________________________________

## Testing

Vector adapters can be tested with mock embeddings:

```python
import pytest
from oneiric.adapters.vector import VectorDocument


@pytest.mark.asyncio
async def test_vector_search(lifecycle):
    adapter = await lifecycle.activate("adapter", "vector")

    # Create test documents
    docs = [
        VectorDocument(id=f"test-{i}", vector=[float(i)] * 1536, metadata={"index": i})
        for i in range(10)
    ]

    # Upsert
    doc_ids = await adapter.upsert("test-collection", docs)
    assert len(doc_ids) == 10

    # Search
    results = await adapter.search(
        collection="test-collection", query_vector=[5.0] * 1536, limit=3
    )

    assert len(results) == 3
    assert results[0].id == "test-5"  # Closest match

    # Cleanup
    await adapter.delete_collection("test-collection")
```

______________________________________________________________________

## Next Steps

### High Priority (Next Sprint)

1. **Embedding Adapters** (per ADAPTER_STRATEGY.md)

   - OpenAI embeddings
   - Sentence Transformers
   - ONNX embeddings

1. **PGVector Adapter**

   - Reuse existing database/postgres adapter
   - Add vector extension support

1. **AI/LLM Adapters**

   - OpenAI (GPT-4, embeddings)
   - Anthropic (Claude)
   - Google Gemini

### Future Enhancements

- **Hybrid search** (vector + full-text)
- **Multi-vector support** (multiple embeddings per document)
- **Batch streaming** (large dataset ingestion)
- **Vector caching** (frequently-accessed vectors)
- **Automatic reranking** (improve search quality)

______________________________________________________________________

## References

- **Pinecone Docs:** https://docs.pinecone.io/
- **Qdrant Docs:** https://qdrant.tech/documentation/
- **ADAPTER_STRATEGY.md** - Overall adapter porting roadmap
- **ACB Comparison:** `docs/ONEIRIC_VS_ACB.md`

______________________________________________________________________

## Migration from ACB

If migrating from ACB's vector adapters:

### Key Differences

1. **Settings Model** - Pydantic V2 instead of V1
1. **Lifecycle Hooks** - `init()`, `health()`, `cleanup()` instead of ACB's lifecycle
1. **No Dependency Injection** - Settings passed directly to constructor
1. **Simplified Interface** - No advanced features (caching, hybrid search) yet

### Migration Example

**ACB:**

```python
from acb.depends import depends


@depends.inject
def __init__(self, config: Inject[Config]):
    super().__init__(**kwargs)
```

**Oneiric:**

```python
def __init__(self, settings: PineconeSettings):
    super().__init__(settings)
    self._settings = settings
```

______________________________________________________________________

## PGVector Adapter

### Configuration

```yaml
# settings/adapters.yml
vector: pgvector
from oneiric.adapters.vector.pgvector import PgvectorSettings

settings = PgvectorSettings(
    host="127.0.0.1",
    port=5432,
    user="postgres",
    password="postgres",
    database="vectors",
    db_schema="public",
    collection_prefix="vectors_",
    default_dimension=1536,
    default_distance_metric="cosine",
)
```

### Usage

```python
adapter = await lifecycle.activate("adapter", "vector")

# Ensure collection/table exists
await adapter.create_collection(name="documents", dimension=1536)

# Upsert documents
await adapter.upsert(
    "documents",
    [
        VectorDocument(
            id="doc-1",
            vector=[0.1, 0.2, 0.3],
            metadata={"title": "Doc 1", "topic": "demo"},
        ),
    ],
)

# Search with metadata filter
results = await adapter.search(
    "documents",
    query_vector=[0.1, 0.2, 0.3],
    limit=5,
    filter_expr={"topic": "demo"},
    include_vectors=True,
)
```

### Features

- ✅ Asyncpg pool with pgvector type registration
- ✅ Collection/table helpers (create/list/drop)
- ✅ Metadata filtering via JSONB (`metadata @> {...}`)
- ✅ Distance metrics: cosine, L2, dot/inner product
- ✅ IVF index creation with configurable `lists`
- ✅ Optional inline manifest support (pure SQL, no HTTP SDK)
- 📦 Install via `uv sync --group vector-pgvector` (pulls `pgvector>=0.2.4` alongside `asyncpg`)

### Capabilities

```python
adapter.has_capability("vector_search")  # True
adapter.has_capability("batch_operations")  # True
adapter.has_capability("metadata_filtering")  # True
adapter.has_capability("collections")  # True
adapter.has_capability("sql")  # True
```

______________________________________________________________________

## Summary

- ✅ **3 vector database adapters** implemented (Pinecone, Qdrant, PGVector)
- ✅ **Standardized interface** via `VectorBase`
- ✅ **Lifecycle integration** (health checks, hot-swapping)
- ✅ **Production-ready** for AI/LLM workloads
- 📝 **Next:** Weaviate integration; DuckDB PGQ shipped via `graph/duckdb_pgq.py`

______________________________________________________________________

## Related Documentation

- **DuckDB Adapter:** `docs/DUCKDB_ADAPTER.md` - Analytical SQL database
- **ADAPTER_STRATEGY.md** - Overall adapter porting roadmap
