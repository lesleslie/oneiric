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

# ADR 0003: Adopt pydantic-settings as Oneiric's settings loader

## Status

**Active** as of 2026-10-11. Implementation plan in
[`docs/plans/2026-10-11-pydantic-settings-migration.md`](../plans/2026-10-11-pydantic-settings-migration.md);
spec update at
[`docs/specs/2026-10-11-adapter-contract-design.md`](../specs/2026-10-11-adapter-contract-design.md) §4 and §9.

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
2. Layer-merges them in priority order.
3. Returns a `OneiricSettings(**merged_dict)` populated from the
   merged dict.

Crucially, **`OneiricSettings` and `OneiricMCPConfig` extend
`BaseModel`, not `BaseSettings`** — but their `model_config`
already declares pydantic-settings' `env_prefix`,
`env_nested_delimiter`, `env_file`, and `populate_by_name`
(`oneiric/core/config.py:304-317`). The convention is declared;
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
| Source precedence customization | Override `settings_customise_sources` |

**Every feature ACB hand-rolled is now built-in.** The original
rationale for the custom loader no longer exists.

### Evidence of borrowing without using

`oneiric/core/config.py:337-346` contains an explicit comment
documenting that the env-var naming convention
`ONEIRIC_OBSERVABILITY__CONNECTION_STRING` was specifically designed
to mirror pydantic-settings' nested-delimiter feature:

> The sub-model already declares
> ``env_prefix="ONEIRIC_OTEL_STORAGE_"`` on its own model_config, but
> those env vars only fire when ``OTelStorageSettings`` is constructed
> standalone; nesting it here lets
> ``ONEIRIC_OBSERVABILITY__CONNECTION_STRING=...`` work via
> pydantic-settings' nested-delimiter.

This is **convention-borrowing without loader-borrowing**: the
naming pattern follows pydantic-settings' idiom, but the actual
loading is still Oneiric's custom code.

## Decision

Oneiric's settings loader migrates to pydantic-settings natively.

Concretely:

1. **`OneiricSettings` and `OneiricMCPConfig` extend `BaseSettings`**
   instead of `BaseModel`. Same `model_config = SettingsConfigDict(...)`
   blocks already in the code — the inheritance change activates them.

2. **`load_settings()` is replaced** by a `settings_customise_sources`
   method on `OneiricSettings` (or, more precisely, on the dynamically
   built per-project subclass) that returns the same six-layer chain
   as `YamlConfigSettingsSource` instances, in priority order. Later
   sources override earlier ones, matching ACB's hand-rolled merge
   semantics.

3. **Hand-rolled YAML parsing helpers (`load_yaml_*`) are deleted.**
   pydantic-settings ships `YamlConfigSettingsSource` that reads,
   parses, and feeds the YAML file as init kwargs.

4. **Per-project `env_prefix`** is handled by a small factory:
   ```python
   def build_oneiric_settings(project_name: str) -> type[OneiricSettings]:
       class _Project(OneiricSettings):
           model_config = SettingsConfigDict(env_prefix=f"{project_name.upper()}_", ...)
       return _Project
   ```
   `load_settings(project_name="session_buddy")` then returns
   `build_oneiric_settings("session_buddy")()` — an instance whose env
   prefix is `SESSION_BUDDY_`.

5. **Oneiric-specific custom sources are kept thin.**
   - `BodaiManifestSource` — loads from a signed YAML via
     `oneiric remote-sync` (the existing CLI; this just plugs it into
     the settings source chain). Defined as a subclass of
     `PydanticBaseSettingsSource`.
   - XDG-compliant path discovery (`${XDG_CONFIG_HOME}/<project>/...`)
     remains — but it's now path-finding, not loader code. It builds
     the list of paths the YAML sources read.

6. **Adapter settings** (`*BaseSettings` in each category) follow the
   same pattern: `BaseModel` for adapters that don't need env-var
   loading (most adapters); `BaseSettings` for adapters that do (LLM,
   embedding, vector, observability). The substrate-side
   `OneiricAdapterSettings` base recommended in earlier discussion
   becomes a `BaseModel` mixin; adapters needing env vars extend it
   then add `BaseSettings` themselves, or skip the substrate base and
   extend `BaseSettings` directly. Spec §4 spells this out.

## Consequences

**Code removed (estimate ~500 lines):**

- `oneiric/core/config.py::load_settings` body (replaced with
  `settings_customise_sources`)
- `load_yaml_*` helpers (any)
- Manual env-var interpolation logic
- Manual layer-priority merge logic

**Code added (estimate ~150 lines):**

- `BodaiManifestSource` (one small class)
- Per-project factory `build_oneiric_settings(project_name)`
- Test coverage for the new chain

**Compatibility:**

- The `${PROJECT}_*__*` env-var convention is preserved (the factory
  applies the same prefix).
- The XDG-compliant layered config (location: `~/.config/<project>/{config,local}.yaml`)
  is preserved (now via `YamlConfigSettingsSource` paths).
- `settings/<project>.yaml` and `settings/local.yaml` defaults are
  preserved.
- Pre-1.0: per project policy, no deprecation window. The custom
  loader is removed in the same release the BaseSettings inheritance
  lands. If a downstream consumer was reaching into `load_settings`
  internals, that's a behavioral break — acceptable pre-1.0.

**What stays unchanged:**

- `OneiricSettings` field shape (all existing fields preserved).
- `OneiricMCPConfig` field shape.
- The cross-repo consumer contract: `MahavishnuSettings` extends
  `OneiricMCPConfig` (still works).
- The `mcp__oneiric__*` MCP tools (registry is unaffected).

## Alternatives considered

- **Keep the hand-rolled loader.** Rejected: the maintenance cost
  (~500 lines of duplicate machinery) is real, and pydantic-settings
  now provides every feature ACB needed to roll its own. There is
  no remaining benefit to hand-rolling.
- **Partial adoption** (e.g., use pydantic-settings for env vars but
  keep hand-rolled YAML layers). Rejected: the YAML layer chain is
  the most code we have (~200 lines). Hand-rolling it while adopting
  env vars from pydantic-settings is the worst of both worlds.
- **Adopt `BaseSettings` but keep `load_settings` as a wrapper.**
  Considered for backwards compatibility. Rejected: pre-1.0 policy
  (per `feedback-no-backwards-compat-pre-1.0.md`); the wrapper
  preserves no semantic that's actually load-bearing.

## Validation

This ADR is correctly applied when:

- [ ] `OneiricSettings` and `OneiricMCPConfig` extend `BaseSettings`.
- [ ] `model_config` blocks retain the same `env_prefix` /
      `env_nested_delimiter` / `env_file` declarations.
- [ ] `OneiricSettings().observability.connection_string` is settable
      via `ONEIRIC_OBSERVABILITY__CONNECTION_STRING=...` (the
      pre-migration behavior).
- [ ] `${XDG_CONFIG_HOME}/<project>/{config,local}.yaml` overrides
      still work and beat `settings/<project>.yaml`.
- [ ] `settings/<project>.yaml` overrides still beat hardcoded
      defaults.
- [ ] `load_settings(project_name="X")` returns an instance whose
      env prefix is `X_` (uppercased).
- [ ] `mcp__oneiric__*` MCP tools still work without changes.
- [ ] `MahavishnuSettings` (extends `OneiricMCPConfig`) still loads
      correctly via `mahavishnu settings load`.

## References

- ACB inheritance: `acb/config.py:140-260` (hand-rolled source chain)
  and `acb/config.py:401` (`Settings(BaseModel)` — note the ACB
  pattern is the same as Oneiric's today).
- ACB per-category: `acb/adapters/vector/_base.py` (`VectorBaseSettings(Settings, SSLConfigMixin)`).
- Oneiric substrate today: `oneiric/core/config.py:296` (`OneiricMCPConfig(BaseModel)`),
  `oneiric/core/config.py:311` (`OneiricSettings(BaseModel)`), and `oneiric/core/config.py:372` (`load_settings`).
- Migration plan: [`docs/plans/2026-10-11-pydantic-settings-migration.md`](../plans/2026-10-11-pydantic-settings-migration.md).
- Spec: [`docs/specs/2026-10-11-adapter-contract-design.md`](../specs/2026-10-11-adapter-contract-design.md) §4 (settings) and §9 (reference implementation).
- Companion ADRs:
  [0001-deployability-discipline.md](0001-deployability-discipline.md),
  [0002-oneiric-adapter-contract.md](0002-oneiric-adapter-contract.md).
- Cleanup scope: [`.claude/decisions/2026-10-11-dhara-substrate-refs-cleanup.md`](../../.claude/decisions/2026-10-11-dhara-substrate-refs-cleanup.md).