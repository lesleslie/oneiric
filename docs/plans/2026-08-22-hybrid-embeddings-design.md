## status: active role: implementation date: 2026-08-22 last_reviewed: 2026-08-22 superseded_by: null blocks_on: [] topic: embeddings

# Hybrid EmbeddingService Design

**Date:** 2026-08-22
**Status:** Approved Design
**Implementing:** Real embeddings across the Bodai ecosystem via a 5-backend
probe chain in oneiric.

______________________________________________________________________

## Executive Summary

The Bodai ecosystem currently has **three separate EmbeddingService
implementations**, all in degraded states:

- `akosha/processing/embeddings.py` — mock-only, `is_available()` always `False`
- `oneiric/adapters/observability/embeddings.py` — optional sentence-transformers,
  mock fallback
- `mahavishnu/ingesters/otel_ingester.py` — lazy optional sentence-transformers
  - fastembed, redundant paths

This plan **consolidates all embedding concerns into oneiric** with a
5-backend probe chain that finally delivers real semantic embeddings to
all Bodai consumers.

______________________________________________________________________

## Goals

1. **Real embeddings everywhere** — `is_available()` finally returns `True`
1. **Single source of truth** — one EmbeddingService, one config schema
1. **Graceful degradation** — chain probes each backend; first responder wins
1. **No ONNX dependency** — matches project policy set in crackerjack / session-buddy
1. **Zero hard deps** — all backends are HTTP or pure-numpy (model2vec)

______________________________________________________________________

## Non-Goals

- Distillation / training of new models (use existing pre-trained models)
- Multi-locale support beyond what `potion-multilingual-128M` provides
- Real-time embedding streaming (batch API is sufficient)

______________________________________________________________________

## Backend Chain (probe order)

```
1. llama.cpp server     preferred local    http://localhost:8080/v1/embeddings
2. Ollama               fallback local     http://localhost:11434/v1/embeddings
3. MiniMax (ZhipuAI)    cloud              https://api.minimax.chat/v1/embeddings
4. Model2Vec            pure-numpy offline minishlab/potion-base-32M
5. Mock                 last resort        deterministic Gaussian
```

Each leg is probed **once at `initialize()` time** with a fast GET to
`/v1/models` (or equivalent). First responder wins. The selected backend
is cached for the lifetime of the service.

**Why this order:**

- **llama.cpp first** (user preference): preferred local runtime
- **Ollama second** (already running in user's ecosystem at :11434)
- **MiniMax third** (when `MINIMAX_API_KEY` + `MINIMAX_GROUP_ID` are set)
- **Model2Vec fourth** (pure-numpy fallback; works offline without Ollama)
- **Mock fifth** (deterministic; never blocked)

______________________________________________________________________

## Settings Schema (oneiric)

```yaml
oneiric:
  embeddings:
    llama_cpp:
      enabled: true
      base_url: "http://localhost:8080"
      model: "nomic-embed-text"
      timeout_seconds: 5
    ollama:
      enabled: true
      base_url: "http://localhost:11434"
      model: "nomic-embed-text"
      timeout_seconds: 10
    minimax:
      enabled: true
      api_key: "${MINIMAX_API_KEY}"
      group_id: "${MINIMAX_GROUP_ID}"
      base_url: "https://api.minimax.chat/v1"
      model: "embo-01"
      timeout_seconds: 30
    model2vec:
      enabled: true
      model_name: "minishlab/potion-base-32M"
      cache_dir: "${ONEIRIC_CACHE_DIR}/models"
    mock:
      fallback: true
      dimension: 384
```

All backends are opt-in via `enabled: true/false`. Missing env vars
auto-skip a backend (it just doesn't probe successfully).

______________________________________________________________________

## Architecture

```
EmbeddingService.initialize()
    ↓
For each backend in chain (5 iterations):
    if not enabled: skip
    try: probe(backend)            # fast GET /v1/models
    except: log + continue
    if probe succeeded: set self._backend; break
    ↓
If no backend succeeded: self._backend = "mock"
    ↓
Return service ready

EmbeddingService.encode(text)
    ↓
if self._backend == "llama_cpp": return httpx POST /v1/embeddings
if self._backend == "ollama":    return httpx POST /v1/embeddings
if self._backend == "minimax":   return httpx POST /v1/embeddings
if self._backend == "model2vec": return StaticModel.encode(text)
if self._backend == "mock":      return _generate_fallback_embedding(text)
```

______________________________________________________________________

## Components

### 1. `EmbeddingService` (rewritten)

**File:** `oneiric/adapters/observability/embeddings.py`

**Public API (unchanged where possible):**

```python
class EmbeddingService:
    def __init__(self, settings: EmbeddingSettings | None = None) -> None: ...
    async def initialize(self) -> None: ...  # probes chain
    def is_available(self) -> bool: ...      # True if any real backend
    async def encode(self, text: str) -> np.ndarray: ...        # async API
    async def encode_batch(self, texts: list[str]) -> list[np.ndarray]: ...
    def dimension(self) -> int: ...          # reports active backend's dim
    def backend_name(self) -> str: ...       # for observability
```

**Backward compatibility:** Existing call sites use
`SentenceTransformer(model_name=...)`. The new service accepts the
same constructor pattern via `EmbeddingSettings.model_name` default,
BUT also accepts `settings: EmbeddingSettings` for the full chain.

### 2. `EmbeddingSettings` (new)

**File:** `oneiric/adapters/observability/embedding_settings.py`

Pydantic model matching the YAML schema above. Loaded via oneiric's
standard layered config (defaults → yaml → env).

### 3. `BackendProbe` (new)

**File:** `oneiric/adapters/observability/embedding_probe.py`

Per-backend probe + encode implementation. Each backend is a class
implementing a `BackendProbe` protocol:

```python
class BackendProbe(Protocol):
    name: str
    async def probe(self) -> bool: ...
    async def encode(self, text: str) -> np.ndarray: ...
    async def encode_batch(self, texts: list[str]) -> list[np.ndarray]: ...
    def dimension(self) -> int: ...
```

______________________________________________________________________

## Integration Contract

### Triggered from

- `akosha.mcp.server` lifespan (replaces existing `get_embedding_service()` singleton init)
- `mahavishnu.ingesters.otel_ingester` (replaces lazy optional-import branches)
- `mahavishnu.core.embeddings_oneiric` (delegates to oneiric)

### Returns to / updates

- All MCP embedding tools in akosha: `generate_embedding`, `generate_batch_embeddings`, `search_all_systems`
- Mahavishnu OTel semantic trace search
- Future Bodai components needing embeddings

### Demonstrable by

1. `pytest oneiric/tests/unit/test_embedding_chain.py` — all 5 backends tested in isolation
1. `pytest oneiric/tests/unit/test_embedding_probe.py` — probe order verified
1. Runtime: `curl http://localhost:8682/health` → akosha reports backend name
1. Runtime: `mcp__akosha__generate_embedding("hello")` → returns REAL 384-dim embedding (via Ollama today)

### Rollback signal

- If `is_available()` returns `False` after rollout → probe order needs adjustment
- If encode latency > 200ms for Ollama path → check `OLLAMA_NUM_PARALLEL` config
- If `MINIMAX_GROUP_ID` missing causes auth error → check probe timeout

### Observability added

- New Prometheus counter: `oneiric_embedding_backend_selections_total{backend}`
- New Prometheus histogram: `oneiric_embedding_encode_duration_seconds{backend}`
- Span attribute on each encode call: `embedding.backend`, `embedding.dimension`
- Log line at `initialize()`: `"Embedding backend selected: {name} (dim={n})"`

______________________________________________________________________

## Migration Impact

| Component | Before | After |
|---|---|---|
| **akosha** | `processing/embeddings.py` (mock, broken wiring) | `from oneiric.adapters.observability.embeddings import EmbeddingService` |
| **mahavishnu** | Lazy optional imports in 2 files | Use oneiric directly |
| **oneiric** | Sentence-transformers + mock | Hybrid chain |
| **session-buddy** | "HTTP embedding providers" (separate) | Out of scope; tracked separately |
| **crackerjack** | No embeddings | Unchanged |
| **dhara** | No embeddings | Unchanged |
| **mcp-common** | No embeddings | Unchanged |

**Dimension migration:** Current 384-dim → Model2Vec's `potion-base-32M`
is **768-dim**. Ollama's `nomic-embed-text` is **768-dim**. MiniMax's
`embo-01` is **1024-dim**. All callers must accept variable dim — the
service now reports `dimension()` instead of hardcoding.

**No persisted embeddings exist** (mock was fresh at last deploy), so
migration is safe.

______________________________________________________________________

## Phase Plan

| Phase | Description | Files |
|---|---|---|
| **1** | Failing tests in oneiric | `tests/unit/test_embedding_chain.py`, `test_embedding_probe.py` |
| **2** | Implement hybrid `EmbeddingService` | `embeddings.py`, `embedding_settings.py`, `embedding_probe.py` |
| **3** | Migrate akosha | `akosha/processing/embeddings.py` → shim re-exporting from oneiric |
| **4** | Simplify mahavishnu | `ingesters/otel_ingester.py`, `core/embeddings_oneiric.py` |
| **5** | Runtime verification | All components restart, all tools work end-to-end |

______________________________________________________________________

## Risks & Mitigations

| Risk | Probability | Mitigation |
|---|---|---|
| `MINIMAX_GROUP_ID` not in user's env | 90% | Probe fails gracefully; chain skips to Ollama |
| User's `MINIMAX_API_KEY` lacks embeddings scope | 30% | Probe returns 403; chain skips to Ollama |
| `model2vec` model download blocked by firewall | 20% | Falls back to Ollama (which is running) |
| Ollama restarts during runtime | 40% | `is_available()` returns False mid-session; next encode uses Model2Vec |
| Dimension change breaks a hidden caller | 15% | Public `dimension()` method + audit of `akosha_tools.py` callers |
| `akosha` tests assume 384-dim mock output | 60% | Update test fixtures; use `MagicMock` with `.tolist()` |

______________________________________________________________________

## Out of Scope

- **session-buddy** unification — separate "HTTP providers" abstraction; tracked in a follow-up plan
- **crackerjack** integration — doesn't currently use embeddings
- **Embedding fine-tuning** — using pre-trained models only
- **GPU acceleration** — all backends are CPU-friendly; llama.cpp can use Metal on Apple silicon
- **Quantized model management** — relies on each backend's native model management
