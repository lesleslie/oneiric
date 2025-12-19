# Embedding Adapters

**Status:** Production Ready
**Date:** 2025-11-27
**Adapters:** OpenAI (hosted), Sentence Transformers / ONNX (local, manual install while Python 3.14 wheels are pending)

______________________________________________________________________

## Overview

Embedding adapters generate vector representations (embeddings) of text for semantic search, similarity matching, and AI/ML applications. Embeddings power vector databases and enable semantic understanding of text.

## Installation

AI/embedding stacks pull in heavy SDKs, so each adapter is opt-in via dependency groups:

```bash
pip install 'oneiric[embedding-openai]'   # Hosted OpenAI embeddings + client
pip install 'oneiric[embedding]'          # Alias for the hosted embedding stack
pip install 'oneiric[ai]'                 # Embedding + LLM extras together
```

> **Local adapters:** Sentence Transformers + ONNX Runtime do not publish macOS x86_64 wheels for Python 3.14 yet. Until upstream catches up, run them via `uvx --python 3.13 --with onnxruntime ...` as documented in `docs/ai/ONNX_GUIDE.md`, or keep a side virtualenv on Python 3.13 and install `sentence-transformers` manually.

Use the smaller extras during local smoke tests (e.g., `embedding-openai`) and reserve the meta extras (`embedding`, `ai`) for CI or build images where the broader AI surface is required.

**Implemented Adapters:**

- ✅ **OpenAI** - High-quality embeddings via OpenAI API (text-embedding-3-small, text-embedding-3-large, ada-002)
- ⚠️ **Sentence Transformers** - Open-source, on-device embeddings (models ready, but Python 3.14 wheels pending upstream)
- ⚠️ **ONNX Runtime** - Optimized on-device embeddings (requires manual install per `docs/ai/ONNX_GUIDE.md`)

**Planned Adapters (per ADAPTER_STRATEGY.md):**

- 📝 HuggingFace - Wide variety of embedding models once runtime parity lands

______________________________________________________________________

## Architecture

### Base Classes

All embedding adapters inherit from `EmbeddingBase` and implement standard lifecycle hooks:

```python
from oneiric.adapters.embedding import EmbeddingBase


class MyEmbeddingAdapter(EmbeddingBase):
    async def init(self) -> None:
        """Initialize connection"""

    async def health(self) -> bool:
        """Health check"""

    async def cleanup(self) -> None:
        """Cleanup resources"""
```

### Common Models

**`EmbeddingResult`** - Single text embedding result:

```python
from oneiric.adapters.embedding import EmbeddingResult

result = EmbeddingResult(
    text="Hello world",
    embedding=[0.1, 0.2, 0.3, ...],  # 1536-dimensional vector
    model="text-embedding-3-small",
    dimensions=1536,
    tokens=3,  # Optional token count
    metadata={"index": 0},
)
```

**`EmbeddingBatch`** - Batch embedding results:

```python
from oneiric.adapters.embedding import EmbeddingBatch

batch = EmbeddingBatch(
    results=[result1, result2, ...],
    total_tokens=100,
    processing_time=0.5,
    model="text-embedding-3-small",
    batch_size=10,
)
```

______________________________________________________________________

## OpenAI Embedding Adapter

### Configuration

```yaml
# settings/adapters.yml
embedding: openai
```

```python
from oneiric.adapters.embedding import OpenAIEmbeddingSettings

settings = OpenAIEmbeddingSettings(
    api_key="sk-...",
    model="text-embedding-3-small",  # or 3-large, ada-002
    organization="org-...",  # Optional
    batch_size=100,  # Process up to 100 texts at once
    normalize_embeddings=True,  # L2 normalize vectors
    requests_per_minute=3000,  # Rate limiting
)
```

### Usage

```python
from oneiric.core.lifecycle import LifecycleManager

# Activate adapter
adapter = await lifecycle.activate("adapter", "embedding")

# Single text embedding
text = "The quick brown fox jumps over the lazy dog"
embedding = await adapter.embed_text(text)
print(f"Dimensions: {len(embedding)}")  # 1536 for text-embedding-3-small

# Batch embedding (efficient)
texts = [
    "Machine learning is fascinating",
    "Artificial intelligence is the future",
    "Natural language processing",
]
batch = await adapter.embed_texts(texts)

for result in batch.results:
    print(f"Text: {result.text[:50]}...")
    print(f"Embedding dimensions: {result.dimensions}")
    print(f"Model: {result.model}")
```

### Document Chunking

For large documents that exceed token limits:

```python
# Automatically chunk and embed long documents
documents = [
    "This is a very long document that needs to be chunked...",
    "Another long document...",
]

# Chunk size: 512 characters, overlap: 50 characters
batches = await adapter.embed_documents(documents, chunk_size=512, chunk_overlap=50)

for i, batch in enumerate(batches):
    print(f"Document {i}: {len(batch.results)} chunks")
    for result in batch.results:
        print(f"  Chunk: {result.text[:50]}...")
        print(f"  Metadata: {result.metadata}")
```

### Similarity Computation

```python
# Embed two texts
text1 = "Python is a programming language"
text2 = "Java is a programming language"

emb1 = await adapter.embed_text(text1)
emb2 = await adapter.embed_text(text2)

# Compute cosine similarity
similarity = await adapter.compute_similarity(emb1, emb2, method="cosine")
print(f"Similarity: {similarity:.4f}")  # ~0.85 (very similar)

# Other similarity methods
euclidean = await adapter.compute_similarity(emb1, emb2, method="euclidean")
dot_product = await adapter.compute_similarity(emb1, emb2, method="dot")
manhattan = await adapter.compute_similarity(emb1, emb2, method="manhattan")
```

### Model Information

```python
# Get model details
model_info = await adapter.get_model_info("text-embedding-3-small")
print(model_info)
# {
#     "name": "text-embedding-3-small",
#     "provider": "openai",
#     "type": "embedding",
#     "max_dimensions": 1536,
#     "default_dimensions": 1536,
#     "max_tokens": 8191,
#     "price_per_1k_tokens": 0.00002,
#     "description": "Most efficient embedding model with good performance"
# }

# List all available models
models = await adapter.list_models()
for model in models:
    print(f"{model['name']}: ${model['price_per_1k_tokens']:.6f} per 1k tokens")
```

### Features

- ✅ **Batch processing** (up to 100 texts per request)
- ✅ **Rate limiting** (configurable requests per minute)
- ✅ **Vector normalization** (L2, L1, or none)
- ✅ **Document chunking** (automatic text splitting)
- ✅ **Multiple models** (3-small, 3-large, ada-002)
- ✅ **Custom dimensions** (for v3 models)
- ✅ **Similarity computation** (cosine, euclidean, dot, manhattan)

### Capabilities

```python
adapter.metadata.capabilities  # ['batch_embedding', 'vector_normalization', ...]
```

______________________________________________________________________

## Integration with Vector Databases

Embeddings are typically used with vector databases for semantic search:

```python
from oneiric.adapters.vector import VectorDocument

# Generate embedding
embedding_adapter = await lifecycle.activate("adapter", "embedding")
text = "Machine learning tutorial"
embedding = await embedding_adapter.embed_text(text)

# Store in vector database
vector_adapter = await lifecycle.activate("adapter", "vector")
doc = VectorDocument(
    id="doc-1", vector=embedding, metadata={"text": text, "category": "tutorial"}
)
await vector_adapter.upsert("documents", [doc])

# Search with query
query = "AI tutorial"
query_embedding = await embedding_adapter.embed_text(query)
results = await vector_adapter.search(
    collection="documents", query_vector=query_embedding, limit=5
)

for result in results:
    print(f"Score: {result.score:.4f}")
    print(f"Text: {result.metadata['text']}")
```

______________________________________________________________________

## Model Selection Guide

### text-embedding-3-small

**Best for:**

- Most use cases (general purpose)
- Cost-sensitive applications
- High throughput requirements

**Specs:**

- Dimensions: 1536
- Max tokens: 8191
- Cost: $0.00002 per 1k tokens (very cheap)
- Performance: Excellent for most tasks

### text-embedding-3-large

**Best for:**

- Highest accuracy requirements
- Complex semantic matching
- Research and benchmarking

**Specs:**

- Dimensions: 3072 (higher capacity)
- Max tokens: 8191
- Cost: $0.00013 per 1k tokens
- Performance: Best-in-class

### text-embedding-ada-002

**Best for:**

- Legacy compatibility
- Existing vector databases with ada-002 embeddings

**Specs:**

- Dimensions: 1536
- Max tokens: 8191
- Cost: $0.0001 per 1k tokens
- Performance: Good (v2 model, superseded by v3)

**Recommendation:** Use `text-embedding-3-small` for most applications. It offers the best price/performance ratio.

______________________________________________________________________

## Performance Tuning

### Batch Size

```python
settings = OpenAIEmbeddingSettings(
    batch_size=100,  # Process 100 texts per API call (max efficiency)
)

# Large batch = fewer API calls, better throughput
texts = ["text" + str(i) for i in range(1000)]
batch = await adapter.embed_texts(texts)  # ~10 API calls
```

### Rate Limiting

```python
settings = OpenAIEmbeddingSettings(
    requests_per_minute=3000,  # Adjust based on tier
    tokens_per_minute=1000000,  # Tier 1 limit
)

# Adapter automatically applies rate limiting
```

### Vector Normalization

```python
from oneiric.adapters.embedding import VectorNormalization

settings = OpenAIEmbeddingSettings(
    normalize_embeddings=True,  # Enable normalization
    normalization=VectorNormalization.L2,  # L2 norm (unit vectors)
)

# Normalized vectors are better for cosine similarity
```

### Custom Dimensions (v3 models)

```python
# Reduce dimensionality for faster search
settings = OpenAIEmbeddingSettings(
    model="text-embedding-3-large",
    dimensions=1536,  # Down from 3072 (50% reduction)
)

# Trade-off: Slightly lower accuracy for faster search + less storage
```

______________________________________________________________________

## Lifecycle Integration

```python
from oneiric.core.lifecycle import LifecycleManager

lifecycle = LifecycleManager(resolver)

# Activate
adapter = await lifecycle.activate("adapter", "embedding")

# Health check
is_healthy = await lifecycle.probe_instance_health("adapter", "embedding")

# Hot-swap providers
adapter = await lifecycle.swap("adapter", "embedding", provider="sentence_transformers")

# Get status
status = lifecycle.get_status("adapter", "embedding")
print(status.state)  # "ready", "failed", "activating"
```

______________________________________________________________________

## Testing

```python
import pytest
from oneiric.adapters.embedding import OpenAIEmbeddingSettings


@pytest.fixture
async def embedding_adapter(lifecycle):
    """OpenAI embedding adapter for testing."""
    settings = OpenAIEmbeddingSettings(
        api_key="test-key",  # Use test API key
        model="text-embedding-3-small",
    )

    adapter = await lifecycle.activate("adapter", "embedding")
    yield adapter
    await lifecycle.cleanup_instance("adapter", "embedding")


@pytest.mark.asyncio
async def test_embedding(embedding_adapter):
    """Test text embedding."""
    text = "Test embedding"
    embedding = await embedding_adapter.embed_text(text)

    assert len(embedding) == 1536  # text-embedding-3-small dimensions
    assert all(isinstance(x, float) for x in embedding)


@pytest.mark.asyncio
async def test_similarity(embedding_adapter):
    """Test similarity computation."""
    text1 = "Machine learning"
    text2 = "Artificial intelligence"

    emb1 = await embedding_adapter.embed_text(text1)
    emb2 = await embedding_adapter.embed_text(text2)

    similarity = await embedding_adapter.compute_similarity(emb1, emb2)
    assert 0.0 <= similarity <= 1.0  # Cosine similarity range
    assert similarity > 0.7  # Should be similar
```

______________________________________________________________________

## Cost Optimization

### Caching Embeddings

```python
# Cache embeddings to avoid redundant API calls
embedding_cache = {}


async def get_embedding_cached(text: str) -> list[float]:
    if text in embedding_cache:
        return embedding_cache[text]

    embedding = await adapter.embed_text(text)
    embedding_cache[text] = embedding
    return embedding
```

### Batch Processing

```python
# BAD: Individual API calls
for text in texts:
    await adapter.embed_text(text)  # 1000 API calls

# GOOD: Batch processing
batch = await adapter.embed_texts(texts)  # ~10 API calls (100x fewer)
```

### Model Selection

```python
# text-embedding-3-small: $0.00002 per 1k tokens
# 1M tokens = $20

# text-embedding-3-large: $0.00013 per 1k tokens
# 1M tokens = $130

# Savings: Use 3-small for most tasks (6.5x cheaper)
```

______________________________________________________________________

## Error Handling

```python
from oneiric.core.lifecycle import LifecycleError

try:
    embedding = await adapter.embed_text(text)
except LifecycleError as exc:
    if "rate_limit" in str(exc):
        # Handle rate limiting
        await asyncio.sleep(60)
    elif "invalid_api_key" in str(exc):
        # Handle authentication error
        logger.error("Invalid API key")
    else:
        raise
```

______________________________________________________________________

## Next Steps

### High Priority (Next Sprint)

1. **Sentence Transformers Adapter** (per ADAPTER_STRATEGY.md)

   - Open-source alternative
   - On-device embeddings
   - No API costs

1. **ONNX Adapter**

   - Optimized inference
   - Low-latency on-device
   - Mobile/edge deployment

1. **AI/LLM Adapters**

   - OpenAI (GPT-4)
   - Anthropic (Claude)
   - Integration with embedding adapters

______________________________________________________________________

## References

- **OpenAI Embeddings Guide:** https://platform.openai.com/docs/guides/embeddings
- **Vector Database Integration:** `docs/VECTOR_ADAPTERS.md`
- **ADAPTER_STRATEGY.md** - Overall adapter porting roadmap

______________________________________________________________________

## Summary

- ✅ **1 embedding adapter** implemented (OpenAI)
- ✅ **Standardized interface** via `EmbeddingBase`
- ✅ **Lifecycle integration** (health checks, hot-swapping)
- ✅ **Production-ready** for AI/LLM workloads
- ✅ **Vector database integration** ready
- 📝 **Next:** Sentence Transformers + ONNX + AI/LLM adapters
