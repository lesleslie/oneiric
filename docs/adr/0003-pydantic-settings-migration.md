---
status: active
role: canonical
kind: decision
date: 2026-10-11
last_reviewed: 2026-10-11
superseded_by: null
blocks_on: []
decision_date: 2026-10-11
topic: oneiric-config
---

# ADR 0003: Adopt pydantic-settings as Oneiric's settings loader (revised)

> **Revision 2** (2026-10-11, late session): five-agent ensemble review
> caught factual errors and missing risks. This revision addresses them.
> See companion decision note recording the review findings (forthcoming
> in `.claude/decisions/2026-10-11-pydantic-settings-plan-review.md`).

## Status

**Active** as of 2026-10-11. Implementation plan in
[`docs/plans/2026-10-11-pydantic-settings-migration.md`](../plans/2026-10-11-pydantic-settings-migration.md);
spec update at
[`docs/specs/2026-10-11-adapter-contract-design.md`](../specs/2026-10-11-adapter-contract-design.md) §4 and §9.

## Class relationship (the question the original ADR glossed over)

```
              ┌─ BaseSettings (pydantic_settings)
              │      ↑
              │      │ extends
              │      │
              │  OneiricSettings ─── owns `settings_customise_sources` chain
              │      │
              │      │ has nested field of type
              │      ↓
              │  OneiricMCPConfig ──── (was BaseModel; will become BaseSettings)
              │      ↑
              │      │ nested in
              │      │
              │  build_oneiric_settings(project_name) ─── returns
              │      │ _Project(OneiricSettings) with
              │      │ model_config.env_prefix = f"{project_name.upper()}_"
              │      │
              │      │ Mahavishnu (consumer) does:
              │      ↓
              │  from oneiric.core.config import load_settings as _oneiric_load
              │  (MahavishnuSettings extends BaseSettings directly;
              │  it does NOT extend OneiricMCPConfig — see correction below)
              │
              │  Akosha / Crackerjack / Session-Buddy (consumers) similar
              │
              └─ mcp_common.OneiricMCPConfig re-export (mcp_common/fastmcp/__init__.py:31)
                 is independent — it references the substrate's
                 OneiricMCPConfig at runtime; not a parent class.
```

**Correction to original ADR (line 182):** the prior claim
*"The cross-repo consumer contract: `MahavishnuSettings extends
`OneiricMCPConfig` (still works)"* was wrong.
`mahavishnu/core/config.py:2689` declares
`class MahavishnuSettings(BaseSettings):` — `BaseSettings` directly,
not `OneiricMCPConfig`. `OneiricMCPConfig` is a *nested field* on
`MahavishnuSettings` (`oneiric_mcp: OneiricMCPConfig = Field(...)` at
line 2984). Mahavishnu consumes Oneiric's settings indirectly via
`from oneiric.core.config import load_settings as _oneiric_load`
(mahavishnu/core/config.py:3153).

Furthermore, Mahavishnu has its **own local re-declaration** of
`OneiricMCPConfig` at `mahavishnu/core/config.py:1817`
(`class OneiricMCPConfig(BaseModel):`). That local class is distinct
from the substrate's `OneiricMCPConfig` and is not affected by this
migration. Post-migration, two `OneiricMCPConfig` classes coexist
with different inheritance (substrate: `BaseSettings`; Mahavishnu
local: `BaseModel`); Phase 3 of the plan addresses whether to migrate
the duplicate, delete it, or keep the deliberate split.

## Context

ACB (Oneiric's architectural ancestor; archived at
`/Users/les/Projects/ARCHIVED/acb`) hand-rolled its settings loader.
The rationale was real at the time: pydantic-settings lacked
**YAML**, **secrets**, and full **env-var** support — ACB needed all
three. So `acb/config.py` implemented its own
`PydanticSettingsProtocol`, `PydanticSettingsSource`,
`InitSettingsSource`, `UnifiedSettingsSource`, and `Settings.create_async()`
chain.

Oneiric inherited the architecture but lost much of the machinery in
the migration. The substrate now ships a ~500-line hand-rolled
`load_settings()` function (`oneiric/core/config.py:372`) that:

1. Parses six YAML layers (defaults → `settings/<project>.yaml` →
   `settings/local.yaml` → `${XDG_CONFIG_HOME}/<project>/config.yaml`
   → `${XDG_CONFIG_HOME}/<project>/local.yaml` → env vars
   `${PROJECT}_*__*`).
2. Layer-merges them in priority order using `_deep_merge`
   (line 905).
3. Resolves `_ALIAS_OVERRIDES` (line 800-805) for backward-compat
   with pre-`__` env-var conventions (`ONEIRIC_ACTIVITY_STORE` →
   `runtime_paths.domain_activity_path`; `ONEIRIC_LOG_LEVEL` →
   `logging.level`).
4. Returns a `OneiricSettings(**merged_dict)` populated from the
   merged dict.

Crucially, **`OneiricSettings` and `OneiricMCPConfig` extend
`BaseModel`, not `BaseSettings`** — but their `model_config`
already declares pydantic-settings' `env_prefix`,
`env_nested_delimiter`, `env_file`, and `populate_by_name`
(`oneiric/core/config.py:296-317`). The convention is declared;
the loader is not wired up. The hand-rolled `load_settings()` then
re-implements the loading that pydantic-settings' `BaseSettings`
machinery would do for free.

### What's changed since ACB

Verified via current pydantic-settings docs (2026-10-11 via
context7):

| Feature ACB needed | pydantic-settings status today |
|---|---|
| YAML loader | Built-in `YamlConfigSettingsSource` |
| TOML loader | Built-in `TomlConfigSettingsSource` |
| JSON loader | Built-in `JsonConfigSettingsSource` |
| `.env` loader | Built-in `DotEnvSettingsSource` |
| File-based secrets (Docker/K8s) | Built-in `SecretsSettingsSource` + `NestedSecretsSettingsSource` |
| AWS Secrets Manager | Extension `AWSSecretsManagerSettingsSource` |
| GCP Secret Manager | Extension `GoogleSecretManagerSettingsSource` |
| Azure Key Vault | Extension `AzureKeyVaultSettingsSource` |
| SOPS-encrypted secrets | Extension `pydantic-settings-sops` |
| HashiCorp Vault | Extension `pydantic-settings-vault` |
| Env vars with prefix | `SettingsConfigDict(env_prefix=...)` |
| Env vars with nested delimiter | `SettingsConfigDict(env_nested_delimiter=...)` |
| Case-sensitive env | `SettingsConfigDict(case_sensitive=True)` |
| Custom sources | Subclass `PydanticBaseSettingsSource` |
| Source precedence customization | Override `settings_customise_sources` (first returned = highest priority) |
| Per-instance env_prefix override | `BaseSettings(__init__, _env_prefix=...)` constructor arg |

**Every feature ACB hand-rolled is now built-in.** The original
rationale for the custom loader no longer exists.

### Evidence of borrowing without using

`oneiric/core/config.py:337-346` contains an explicit comment
documenting that the env-var naming convention
`ONEIRIC_OBSERVABILITY__CONNECTION_STRING` was specifically designed
to mirror pydantic-settings' nested-delimiter feature. This is
**convention-borrowing without loader-borrowing**.

### ACB precedence characterization (the riskiest unstated assumption)

The plan must pin ACB's actual precedence before migration. From
`acb/config.py` (specifically: `PydanticSettingsProtocol`,
`InitSettingsSource`, `UnifiedSettingsSource` lines 140-260):

ACB's source order was (lowest → highest priority):

1. Library defaults
2. Config file (YAML)
3. **Env vars** (read at `_env_overrides`)
4. `_ALIAS_OVERRIDES` (line 800-805) — applied AFTER env vars

Pydantic-settings' `settings_customise_sources` returns sources where
**first returned = highest priority**. To match ACB's precedence the
chain must be:

```python
return (
    _alias_overrides_source,    # aliases last
    env_settings,                # env overrides YAML
    yaml_layer_5_xdg_local,      # 5 YAML layers, lowest first
    yaml_layer_4_xdg_config,
    yaml_layer_3_local,
    yaml_layer_2_project,
    yaml_layer_1_project,
    init_settings,               # constructor kwargs win if explicit
)
```

The plan's Phase 1 Task 1.3 implements this corrected chain order.
The Phase 0 task pins the precedence in tests before migration.

## Decision

Oneiric's settings loader migrates to pydantic-settings natively.

Concretely:

1. **`OneiricSettings` and `OneiricMCPConfig` extend `BaseSettings`**
   instead of `BaseModel`. Same `model_config = SettingsConfigDict(...)`
   blocks already in the code — the inheritance change activates them.

2. **`load_settings()` is replaced** by a `settings_customise_sources`
   method on `OneiricSettings` that returns a 7-source chain (see ACB
   precedence above, reversed to pydantic-settings' "first wins"
   convention).

3. **`OneiricMCPConfig.env_file=".env"` is dropped** (currently dead
   config on `BaseModel`, becomes active on `BaseSettings`, silently
   reads `.env` files from CWD on every instantiation). Migration
   without this drop is a regression.

4. **`OneiricSettings.model_config` gets `arbitrary_types_allowed=True`**
   so the nested `auth: OneiricMCPAuthConfig` dataclass field
   doesn't break construction. The `auth:` field's env-var source
   is **excluded** from the chain (we keep the existing
   `OneiricMCPAuthConfig.from_env()` call site at the CLI as the
   single point of env-var overlay on auth).

5. **Hand-rolled YAML parsing helpers (`_read_file`, `_load_layer_file`,
   `_deep_merge`, `_coerce_env_value`) are deleted.** Replaced by
   `YamlConfigSettingsSource(settings_cls, yaml_file=..., deep_merge=True)`
   for each layer.

6. **`_ALIAS_OVERRIDES` re-implemented as `AliasChoices`** on the
   target fields: `RuntimePathsConfig.domain_activity_path` gets
   `validation_alias=AliasChoices("domain_activity_path", "ONEIRIC_ACTIVITY_STORE")`
   (already done at line 270); `LoggingConfig.level` gets
   `validation_alias=AliasChoices("level", "ONEIRIC_LOG_LEVEL")`
   (NEW — to add). Full audit of `_ALIAS_OVERRIDES` is Phase 0.

7. **Per-project `env_prefix`** is handled by a memoized factory:
   ```python
   _PROJECT_SETTINGS: dict[str, type[OneiricSettings]] = {}

   def build_oneiric_settings(project_name: str) -> type[OneiricSettings]:
       if project_name not in _PROJECT_SETTINGS:
           class _Project(OneiricSettings):
               model_config = SettingsConfigDict(
                   env_prefix=f"{project_name.upper()}_",
                   env_nested_delimiter="__",
                   extra="allow",
                   populate_by_name=True,
                   arbitrary_types_allowed=True,
               )
           _PROJECT_SETTINGS[project_name] = _Project
       return _PROJECT_SETTINGS[project_name]
   ```
   `load_settings(project_name="X")` then returns
   `build_oneiric_settings(project_name)().model_validate(...)` after
   applying the explicit `path=` override (see §8 below).

8. **Explicit `path=` override and `{PROJECT}_CONFIG` env var** are
   preserved by post-construction `model_validate(merged_dict)` —
   pydantic-settings' `init_settings` source covers constructor kwargs
   but cannot easily model "explicit_config_data applies last as a
   final override". Phase 1 Task 1.5 implements the merge + apply.

9. **`BodaiManifestSource` is defined** as a thin
   `PydanticBaseSettingsSource` subclass reading from the
   `oneiric remote-sync` cache, between YAML and env in the chain.
   Skipped (no-op) when no manifest URL is configured. Cache +
   signature semantics deferred to a follow-on spec.

10. **Adapter settings** follow the same pattern: `BaseModel` for
    adapters that don't need env-var loading (most adapters);
    `BaseSettings` for adapters that do (LLM, embedding, vector,
    observability). Phase 2 of the plan.

## Consequences

**Code removed (estimate ~400 lines, revised down from initial ~500
based on actual line counts):**

- `oneiric/core/config.py::load_settings` body (~200 lines)
- `_env_overrides()` (~68 lines)
- `_coerce_env_value()` (~12 lines)
- `_read_file()` (~43 lines)
- `_deep_merge()` (~12 lines)
- `_ALIAS_OVERRIDES` dict + consumer code (~30 lines)
- Total removed: **~365 lines** (initial ADR claimed -500; revised
  estimate is -365 after independent verification by 5-agent review).

**Code added (estimate ~250 lines, revised up from initial ~150
based on independent verification):**

- `settings_customise_sources` chain (~50 lines, was ~30)
- `BodaiManifestSource` (~50 lines, was ~30; underestimated)
- `build_oneiric_settings` factory + memoization (~20 lines)
- Phase 0 audit + precedence tests (~50 lines)
- Per-adapter `AliasChoices` rewiring (~30 lines)
- `arbitrary_types_allowed=True` + `auth:` exclusion logic (~10 lines)
- Test rewrite for the 7 broken test files (~80 lines, was 0 — added)
- Total added: **~290 lines**

**Net delta: ~-75 lines** (revised from initial ~-350 estimate;
initial estimate was optimistic because it didn't account for
BodaiManifestSource's true size or the test rewrite scope).

**Cross-repo impact (corrected):**

- `MahavishnuSettings` extends `BaseSettings` directly (not
  `OneiricMCPConfig`). Its `oneiric_mcp: OneiricMCPConfig` nested
  field is the substrate's class post-migration (becomes
  `BaseSettings`). No source change required in Mahavishnu —
  **but** Mahavishnu's local shadow `OneiricMCPConfig(BaseModel)` at
  `mahavishnu/core/config.py:1817` is divergent; Phase 3 task 3.7
  decides whether to migrate or delete it.
- Akosha's runtime fallback `OneiricMCPConfig(BaseModel)` at
  `akosha/config.py:38-43` diverges if oneiric is not installed.
  Phase 3 task 3.8 verifies no Akosha test relies on BaseModel-
  specific behavior.
- `mcp-common`'s `MCPBaseSettings(BaseModel)` at
  `mcp-common/config/base.py:34-45` emits a deprecation message
  pointing at `OneiricMCPConfig` (the substrate's class). After
  migration, that deprecation message refers to a class whose
  semantics change. Phase 3 task 3.9 decides whether to migrate
  `MCPBaseSettings` too or document the divergence.
- The `PrompAdapterSettings(BaseSettings)` at
  `mcp-common/prompting/models.py:49` is independent — it's the
  prompt-engineering layer, not the MCP-config layer. Unaffected.

**Compatibility:**

- The `${PROJECT}_*__*` env-var convention is preserved.
- The XDG-compliant layered config is preserved via per-layer
  `YamlConfigSettingsSource` paths.
- The `_ALIAS_OVERRIDES` semantics are preserved via
  `validation_alias=AliasChoices(...)`.
- Pre-1.0: per project policy, no deprecation window.

## Validation

This ADR is correctly applied when:

- [ ] `OneiricSettings` and `OneiricMCPConfig` extend `BaseSettings`.
- [ ] `model_config` blocks retain the same `env_prefix` /
      `env_nested_delimiter` declarations.
- [ ] `OneiricSettings.model_config` declares
      `arbitrary_types_allowed=True` (so the `auth: OneiricMCPAuthConfig`
      dataclass field doesn't break construction).
- [ ] `OneiricMCPConfig.model_config` does NOT declare `env_file`
      (the `.env` activation regression is avoided).
- [ ] `LoggingConfig.level` declares
      `validation_alias=AliasChoices("level", "ONEIRIC_LOG_LEVEL")`.
- [ ] `settings_customise_sources` returns sources in ACB's precedence
      order, **reversed** for pydantic-settings' "first wins" convention.
- [ ] `_alias_overrides_source` is the first-returned source
      (highest priority).
- [ ] `env_settings` comes before any `YamlConfigSettingsSource`
      so env vars override YAML.
- [ ] `_load_layer_file`, `_read_file`, `_deep_merge`,
      `_coerce_env_value`, `_env_overrides`, `_ALIAS_OVERRIDES` are
      all deleted from `oneiric/core/config.py`.
- [ ] Each `YamlConfigSettingsSource` is constructed with
      `deep_merge=True` so nested dicts across layers merge properly.
- [ ] `load_settings(project_name="X")` returns an instance whose
      env prefix is `X_` (uppercased) AND whose `auth:` field is
      the result of `OneiricMCPAuthConfig.from_env()` post-construction.
- [ ] `mcp__oneiric__*` MCP tools still work without changes.
- [ ] Mahavishnu's local `OneiricMCPConfig(BaseModel)` decision is
      documented (Phase 3 task 3.7 result).

## References

- ACB inheritance: `acb/config.py:140-260` (hand-rolled source chain)
  and `acb/config.py:401` (`Settings(BaseModel)`).
- ACB per-category: `acb/adapters/vector/_base.py` (`VectorBaseSettings(Settings, SSLConfigMixin)`).
- Oneiric substrate today: `oneiric/core/config.py:296` (`OneiricMCPConfig(BaseModel)`),
  `oneiric/core/config.py:311` (`OneiricSettings(BaseModel)`), and `oneiric/core/config.py:372` (`load_settings`).
- Cross-repo consumer facts (corrected): `mahavishnu/core/config.py:2689`,
  `mahavishnu/core/config.py:1817`, `mahavishnu/core/config.py:2984`.
- Akosha fallback: `akosha/akosha/config.py:38-43`.
- mcp-common deprecated seam: `mcp-common/mcp_common/config/base.py:34-45`.
- Migration plan: [`docs/plans/2026-10-11-pydantic-settings-migration.md`](../plans/2026-10-11-pydantic-settings-migration.md).
- Spec: [`docs/specs/2026-10-11-adapter-contract-design.md`](../specs/2026-10-11-adapter-contract-design.md) §4 (settings) and §9 (reference implementation).
- Companion ADRs:
  [0001-deployability-discipline.md](0001-deployability-discipline.md),
  [0002-oneiric-adapter-contract.md](0002-oneiric-adapter-contract.md).
- Cleanup scope: [`.claude/decisions/2026-10-11-dhara-substrate-refs-cleanup.md`](../../.claude/decisions/2026-10-11-dhara-substrate-refs-cleanup.md).