---
title: Oneiric Adapter Contract — Authoring and Discovery Specification
status: active
role: canonical
date: 2026-10-11
last_reviewed: 2026-10-11
superseded_by: null
blocks_on: []
topic: adapter-registry
related:
  - ../adr/0002-oneiric-adapter-contract.md
  - ../REMOTE_MANIFEST_SCHEMA.md
---

# Oneiric Adapter Contract — Authoring and Discovery Specification

## Summary

This is the canonical contract for **what makes a Python class an
Oneiric adapter**. An adapter satisfies five sub-contracts and is
then registered into Oneiric's resolver. Consumers discover adapters
through `AdapterBridge.use(...)` (in-process) or through the
`mcp__oneiric__*` MCP tools (cross-component).

The contract is authoritative for all current and future Oneiric
adapters. New adapter authors should read this spec top to bottom
before writing their first class.

## 1. The static declaration: `AdapterMetadata`

Every adapter is declared by a **class-level** `AdapterMetadata`
instance on the adapter class itself:

```python
from oneiric.adapters.metadata import AdapterMetadata

class MyAdapter:
    metadata = AdapterMetadata(
        category="cache",           # The slot it fills
        provider="my-impl",           # Identity within the slot
        factory="mypkg.adapters.my:MyAdapter",  # Or a callable
        capabilities=["cache", "ttl"],          # Tags for capability-aware resolution
        settings_model=MyAdapterSettings,       # Pydantic settings class
        stack_level=20,
        priority=300,
        owner="My Team",                         # Ops/introspection
        requires_secrets=True,                   # Indicates secret-keyed config
        version="1.0.0",
        description="Short prose for catalog UI",
    )
```

The `AdapterMetadata` model is defined at
[`oneiric/adapters/metadata.py:21`](../adapters/metadata.py). The full
field set:

| Field | Type | Required | Purpose |
|---|---|---|---|
| `category` | `str` | yes | Slot the adapter fills. Resolver keys by `(domain="adapter", key=category)`. |
| `provider` | `str` | yes | Identity within the slot. Multiple providers may coexist for one category. |
| `factory` | `str` or `Callable` | yes | How to build it. Prefer the `"module:Class"` string — survives pickling, lazily resolved, introspectable. |
| `version` | `str` | no | Semver or project-internal version. Surfaced in catalog + `validate_adapter`. |
| `description` | `str` | no | Short prose for catalog UI. |
| `capabilities` | `list[str]` | no | Tags for capability-aware resolution. `AdapterBridge.use(category, capabilities=[...])` filters by these. |
| `stack_level` | `int` | no | Resolution axis (path-style ranking; default 0). Higher wins ties. |
| `priority` | `int` | no | Resolution axis. Higher wins ties. |
| `source` | `CandidateSource` | no | How the candidate was registered. See §6. |
| `health` | `Callable[[], bool]` | no | Optional health-probe. Defaults to instance method. |
| `owner` | `str` | no | Ops/introspection: which team owns this adapter. |
| `requires_secrets` | `bool` | no | Indicates whether config needs a secret-manager adapter to load. |
| `settings_model` | `Pydantic class` or string path | no | Typed config schema. See §4. |
| `extras` | `dict` | no | Escape hatch for adapter-specific metadata. Stripped of empty values before persistence. |

`AdapterMetadata.to_candidate()` converts to a `Candidate` for the
resolver — see
[`oneiric/core/resolution.py:41`](../core/resolution.py) for the full
scoring algorithm (override × capability_match × priority × stack_level
× registration_order).

## 2. The lifecycle contract: three async methods

Every adapter class implements:

```python
class MyAdapter:
    metadata = AdapterMetadata(...)  # see §1

    async def init(self) -> None:
        """Warm up clients, open pools. Called once per resolution."""

    async def health(self) -> bool:
        """Return True/False. NEVER raise — raise = 5xx, not degraded."""

    async def cleanup(self) -> None:
        """Close pools, drop clients. Called on bridge.shutdown()."""
```

Driven by `LifecycleManager` and invoked by
[`AdapterBridge.use()`](../adapters/bridge.py:44). The bridge's
`_after_handle` hook captures adapter-state metrics + emits
`adapter-ready` log line after every successful resolution.

**Health contract** (critical):

- `health() -> bool` — return `True`/`False`, **never raise**.
- Catch transport errors inside, log a warning, return `False`.
- The monitoring layer relies on `bool`; raising would surface as a
  5xx instead of a degraded state.

Reference: [`oneiric/adapters/queue/redis_streams.py:174-188`](../adapters/queue/redis_streams.py).

## 3. The factory contract

The `factory` field is the resolver's only way to construct the
adapter. Prefer the **string form**:

```python
factory="mypkg.adapters.my:MyAdapter"
```

The string form:

- Survives pickling (settings, manifests, remote manifests).
- Resolves lazily (no import at metadata-declaration time).
- Makes the catalog introspectable from metadata alone.

A callable works too:

```python
factory=MyAdapter  # The class itself
```

…but ties registration to import-time and prevents some
pickle/serialize paths.

## 4. The settings contract: a Pydantic model

Every adapter that takes config exposes a Pydantic settings model.
The choice between `pydantic.BaseModel` and `pydantic_settings.BaseSettings`
depends on whether the adapter needs env-var loading:

### Default: `pydantic.BaseModel`

For adapters whose config is constructed explicitly (passed in via
`__init__` from a parent config, set by the resolver from a remote
manifest, etc.):

```python
from pydantic import BaseModel, Field

class MyAdapterSettings(BaseModel):
    url: str = Field(default="http://localhost:8080")
    timeout_ms: int = Field(default=1000, ge=0)
    require_secrets: bool = Field(default=False)
```

### When you need env vars: `pydantic_settings.BaseSettings`

For adapters that need to load config from environment variables
(API keys, endpoints, model names), use `pydantic_settings.BaseSettings`:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class LLMAdapterSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LLM_")
    api_key: str
    model: str = "claude-sonnet-4-20250514"
    base_url: str = "https://api.example.com"
```

This gives you free env-var loading (`LLM_API_KEY=...`,
`LLM_MODEL=...`), plus access to all of pydantic-settings' source
machinery (YAML files via `YamlConfigSettingsSource`, secrets via
`SecretsSettingsSource`, etc.) when needed. The precedent in
Oneiric is `oneiric/adapters/observability/settings.py::OTelStorageSettings`.

### Wire in `AdapterMetadata`

```python
metadata = AdapterMetadata(
    ...
    settings_model=MyAdapterSettings,
)
```

The resolver stores the module-qualified path. `AdapterBridge`
materializes settings when instantiating — for `BaseSettings`
subclasses, the env-var loading happens automatically at that point.

### Note: no `OneiricAdapterSettings` substrate base

Oneiric does **not** ship a substrate-level `OneiricAdapterSettings`
class. ACB had this pattern (per `acb/config.py::Settings` +
`acb/adapters/vector/_base.py::VectorBaseSettings(Settings, SSLConfigMixin)`),
but the Oneiric migration dropped it. Each adapter category rolls
its own `*BaseSettings` class (`LLMBaseSettings`, `VectorBaseSettings`,
`NoSQLBaseSettings`, `EmbeddingBaseSettings`); each extends
`pydantic.BaseModel` (or `BaseSettings` if env vars are needed)
directly. This is a deliberate decision — there's no implicit
substrate base to extend.

### Substrate-side settings loading (for context)

The substrate's own config (`OneiricSettings`, `OneiricMCPConfig`)
**extends `pydantic_settings.BaseSettings`** per
[ADR 0003](../adr/0003-pydantic-settings-migration.md). It does not
extend `pydantic.BaseModel`. The substrate loads its config via
pydantic-settings' native `settings_customise_sources` chain (a
sequence of `YamlConfigSettingsSource` + `EnvSettingsSource` +
optional `SecretsSettingsSource`), not via a hand-rolled loader.

Adapter authors should NOT replicate a hand-rolled loader — if your
adapter needs YAML/secrets/env-var loading, use pydantic-settings
directly. The substrate chose pydantic-settings; the substrate's
adapters should follow.

## 5. The capability contract: string tags

`capabilities: list[str]` substitutes for inheritance hierarchies:

```python
metadata = AdapterMetadata(
    ...
    capabilities=["cache", "ttl", "lru"],
)
```

The resolver filters and scores candidates by capability match. This
is how `AdapterBridge.use("cache", capabilities=["ttl"])` finds the
right one when several cache adapters are registered.

## 6. The discovery contract: registered, not imported

An adapter that exists as a class file but isn't registered is
**invisible**. Registration happens through one of four
`CandidateSource` paths (defined in
[`oneiric/core/resolution.py:34`](../core/resolution.py)):

| `CandidateSource` | Path | Use for |
|---|---|---|
| `LOCAL_PKG` | `register_builtin_adapters()` in `oneiric/adapters/bootstrap.py:143` | Built-in adapters shipped with Oneiric. |
| `ENTRY_POINT` | Third-party packages via Python entry points | Out-of-tree adapters published on PyPI. |
| `REMOTE_MANIFEST` | YAML manifests (schema at `docs/REMOTE_MANIFEST_SCHEMA.md`) loaded via `oneiric remote-sync` | Cross-environment manifest delivery with ED25519 signature verification. |
| `MANUAL` | `resolver.register(candidate)` at runtime | Tests, dynamic registration. |

**`REMOTE_MANIFEST` clarification (post-Dhara-decomposition):** the
enum name is historical. It does **not** mean "load from a separate
substrate service." It means "load from a signed YAML manifest via
the `oneiric remote-sync` CLI, persisting records into Oneiric's local
JSON registry at `~/.oneiric/adapter_registry.json`." The Dhara MCP
service that previously held the cross-ecosystem catalog has been
decomposed and is no longer in the resolution path. See
[`.claude/decisions/2026-10-11-dhara-substrate-refs-cleanup.md`](../../.claude/decisions/2026-10-11-dhara-substrate-refs-cleanup.md).

## 7. The runtime access contract: `AdapterBridge.use()`

Consumers never instantiate adapters directly. The pattern:

```python
bridge = AdapterBridge(resolver, lifecycle, settings)

# Pick by category only — resolver scores by priority/capability
handle = await bridge.use("cache")

# Pick a specific provider
handle = await bridge.use("cache", provider="redis")

# Capability-gate
handle = await bridge.use("cache", capabilities=["ttl"])

# Use the resolved instance
await handle.instance.set("user:42", value, ttl=60)
```

`bridge.use()` returns an `AdapterHandle`:

```python
@dataclass
class AdapterHandle:
    category: str
    provider: str
    instance: Any      # The live, init()'d adapter instance
    settings: Any     # The materialized Pydantic settings
    metadata: dict     # The adapter's metadata dict
```

If no candidate matches, raises
`LifecycleError("No adapter candidate found for {key}")`.

## 8. Cross-component discovery: `mcp__oneiric__*` tools

Other Bodai components (Mahavishnu, Akosha, Crackerjack, Session-Buddy)
discover adapters through Oneiric's MCP server. The relevant tools:

| Tool | Purpose |
|---|---|
| `oneiric_list_adapters` | List all registered adapters (filterable by domain/category). |
| `oneiric_get_adapter` | Retrieve a specific adapter by `(domain, key, provider)`. |
| `oneiric_get_adapter_health` | Probe an adapter's health. |
| `oneiric_validate_adapter` | Verify an adapter's factory import + deps + capabilities. |
| `oneiric_list_adapter_versions` | Version history per adapter. |
| `oneiric_store_adapter` | Register/update a custom adapter. |
| `oneiric_report_runtime` | Push runtime facts (sanitized server-side). |

These wrap `OneiricAdapterRegistry`
([`oneiric/mcp/adapter_registry.py`](../mcp/adapter_registry.py)) which
persists to `~/.oneiric/adapter_registry.json`.

**Cross-component consumers do not import Oneiric directly.** They call
the MCP tools. This is the rule that survived the Dhara decomposition.

## 9. Reference implementation

The cleanest existing example is
[`oneiric/adapters/queue/redis_streams.py`](../adapters/queue/redis_streams.py).
It shows all five sub-contracts in one place: `AdapterMetadata` at the
class level (line 75-86), `init/health/cleanup` lifecycle methods
(line 105-197), factory as `"oneiric.adapters.queue.redis_streams:RedisStreamsQueueAdapter"`
string, `RedisStreamsQueueSettings` Pydantic model (line 38-71 —
currently `BaseModel`; would migrate to `BaseSettings` if env-var
loading became a requirement, per §4), capability tags
`["queue", "pubsub", "fanout"]` (line 79).

For an adapter that uses `BaseSettings` for env-var loading, see
`oneiric/adapters/observability/settings.py::OTelStorageSettings` —
it declares `env_prefix="ONEIRIC_OTEL_STORAGE_"` and inherits
from `pydantic_settings.BaseSettings`.

Use these as templates when writing a new adapter.

## 10. Anti-patterns

- **Inheriting from an abstract base class.** There is no `BaseAdapter`.
  Inheriting creates a misleading type hint and prevents the resolver
  from treating adapters uniformly.
- **Raising from `health()`.** Raises = 5xx in monitoring; `False` is the
  correct degraded state.
- **Hardcoding `factory` as a callable when shipping in a
  manifest.** String form is required for `REMOTE_MANIFEST` to
  reconstruct the class on the receiving end.
- **Constructing the adapter directly with `MyAdapter()`.** Always go
  through `AdapterBridge.use()`. Direct construction skips lifecycle,
  metrics, and resolver scoring.
- **Skipping `AdapterMetadata` and importing the class elsewhere.**
  Unregistered classes are invisible to the resolver.
- **Hand-rolling a settings loader.** The substrate uses
  `pydantic_settings.BaseSettings` natively per
  [ADR 0003](../adr/0003-pydantic-settings-migration.md). Adapter
  authors who need YAML/secrets/env-var loading should extend
  `pydantic_settings.BaseSettings` — don't reimplement
  pydantic-settings.
- **POSTing to a non-existent HTTP service in `init()`.** See the
  deleted `mcp_pusher.py` — that was Dhara-MCP-decomposition rot.
  Anything you `import` in `init()` must be a real, current dependency.

## 11. Adding a new adapter — checklist

1. Define the Pydantic `Settings` model.
2. Define the adapter class with class-level `AdapterMetadata`.
3. Implement `init`, `health`, `cleanup`.
4. Add the class to
   [`oneiric/adapters/bootstrap.py::builtin_adapter_metadata()`](../adapters/bootstrap.py).
   The list order does not matter — resolver scores by priority, not
   registration order.
5. (Optional) write a test that exercises the lifecycle methods
   directly + a test that calls `AdapterBridge.use(category="...")`
   and asserts the resolved instance is the expected class.
6. Run `oneiric mcp health` after the change to confirm the new
   adapter is in the catalog.

For non-built-in adapters, substitute step 4 with an entry point in
`pyproject.toml` (see `oneiric/adapters/README.md` for the discovery
pattern).

## 12. Status

- **Active** as of 2026-10-11.
- This spec is enforced by code review, not by a runtime validator. A
  future validator (analogous to `crackerjack`'s hook system) may be
  proposed if drift recurs.
- See [`docs/adr/0002-oneiric-adapter-contract.md`](../adr/0002-oneiric-adapter-contract.md)
  for the decision rationale.