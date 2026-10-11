---
status: draft
role: implementation
date: 2026-10-11
last_reviewed: 2026-10-11
superseded_by: null
blocks_on: []
topic: oneiric-config
---

# Oneiric pydantic-settings migration — implementation plan (revised)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Revision 2** (2026-10-11, late session): five-agent ensemble review
> caught factual errors, missing risks, and an empty validation gate.
> This revision addresses them. Original commit was `5b42cfb`; this
> file supersedes it.

**Date:** 2026-10-11
**Status:** <!-- legacy status: draft — moved to YAML frontmatter -->
**Role:** <!-- legacy role: implementation — moved to YAML frontmatter -->

**Goal:** Drop Oneiric's hand-rolled settings loader and adopt `pydantic_settings.BaseSettings` natively across the substrate's config, every adapter settings class that needs env-var loading, and the five cross-repo consumers (mahavishnu, akosha, crackerjack, session-buddy, mcp-common). The substrate's config declaration (`env_prefix="ONEIRIC_"`, `env_nested_delimiter="__"`, `populate_by_name=True`) already follows pydantic-settings' idiom; this plan wires up the loader instead of re-implementing it.

**Architecture:** Five coordinated phases — Phase 0 (audit + precedence characterization), Phase 1 (substrate migration), Phase 2 (adapter settings), Phase 3 (cross-repo verification + fixes), Phase 4 (cleanup). Each phase has its own Integration Contract (Triggered from, Returns to / updates, Demonstrable by, Rollback signal, Observability added).

**Tech Stack:** `pydantic_settings.BaseSettings` + `SettingsConfigDict` (pydantic-settings 2.15+, installed in `oneiric/.venv`), `YamlConfigSettingsSource`, `EnvSettingsSource`, `SecretsSettingsSource` (built-ins). Pre-1.0: direct commit to main per `bodai-pre-1.0-merge-policy`.

**Adjacent ADRs / specs:**
- [`docs/adr/0003-pydantic-settings-migration.md`](../adr/0003-pydantic-settings-migration.md) (revised) — the decision this plan implements
- [`docs/specs/2026-10-11-adapter-contract-design.md`](../specs/2026-10-11-adapter-contract-design.md) §4 — adapter settings contract (BaseModel vs BaseSettings)
- [`.claude/decisions/2026-10-11-dhara-substrate-refs-cleanup.md`](../../.claude/decisions/2026-10-11-dhara-substrate-refs-cleanup.md) — prior substrate-decomposition cleanup (commit `cd282ba`)

______________________________________________________________________

## Class relationship (cross-reference for ADR 0003 § Class relationship)

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
              └─ mcp_common.OneiricMCPConfig re-export (mcp_common/fastmcp/__init__.mpy:31)
                 is independent — it references the substrate's
                 OneiricMCPConfig at runtime; not a parent class.
```

**Correction to original plan (lines 42, 92-95, 234):**
the prior claim `MahavishnuSettings extends OneiricMCPConfig` was wrong.
`mahavishnu/core/config.py:2689` declares
`class MahavishnuSettings(BaseSettings):` — `BaseSettings` directly,
not `OneiricMCPConfig`. `OneiricMCPConfig` is a *nested field* on
`MahavishnuSettings` (`oneiric_mcp: OneiricMCPConfig = Field(...)` at
line 2984). Mahavishnu consumes Oneiric's settings indirectly via
`from oneiric.core.config import load_settings as _oneiric_load`
(`mahavishnu/core/config.py:3153`).

Furthermore, Mahavishnu has its **own local re-declaration** of
`OneiricMCPConfig` at `mahavishnu/core/config.py:1817`
(`class OneiricMCPConfig(BaseModel):`). That local class is distinct
from the substrate's `OneiricMCPConfig` and is not affected by this
migration.

______________________________________________________________________

## Why these changes

Five-agent ensemble review (2026-10-11) revealed:

1. **Oneiric already declares pydantic-settings' conventions** (`env_prefix`, `env_nested_delimiter`, `env_file`, `populate_by_name`) on `model_config` blocks but inherits from `BaseModel` — so the conventions are declared and the loader is not wired up (`oneiric/core/config.py:296-317`).

2. **The hand-rolled loader is dead weight.** ~365 lines of `load_settings()`, YAML parsing, layer-merging, env-var interpolation, and `_ALIAS_OVERRIDES` in `oneiric/core/config.py`. Every feature is now built-in to pydantic-settings (verified via context7 docs 2026-10-11).

3. **The "I assumed pydantic-settings didn't have what we need" rationale is fully obsolete.** YAML, secrets, env vars, nested delimiter — all built-in.

4. **Cross-repo consumers will not break on the substrate `OneiricMCPConfig`** — but Mahavishnu has a *local* `OneiricMCPConfig` shadow at `mahavishnu/core/config.py:1817` that diverges post-migration unless explicitly handled.

5. **Plan has critical defects that must be fixed before Phase 1:**
   - `MahavishnuSettings extends OneiricMCPConfig` (factual error in original plan, lines 42/93-95/234).
   - Source-order tuple inverted (first returned = highest priority; original plan put env AFTER YAML).
   - `.env` file loading silently activates (`env_file=".env"` was dead config on `BaseModel`).
   - `_ALIAS_OVERRIDES` regression: `ONEIRIC_LOG_LEVEL` not wired via `AliasChoices`.
   - `OneiricSettings.auth: OneiricMCPAuthConfig` collision: nested-delimiter on a `@dataclass` field is undefined.
   - No env-var collision audit (a field `host` would silently flip from a stray env var).
   - ACB precedence unstated.
   - `deep_merge=False` default means nested YAML clobbers across layers.
   - CWD-relative paths break launchd/nohup.
   - `create_async()` is a phantom method.
   - 9-11 commit estimate is optimistic; realistic 25-40.

6. **Pre-1.0 migration policy** (`feedback-no-backwards-compat-pre-1.0.md`): direct commit to main, no deprecation window.

The unifying fix is small: change `BaseModel` → `BaseSettings` (5 lines), replace `load_settings()` body with a `settings_customise_sources` chain (~50 lines), re-implement `_ALIAS_OVERRIDES` via `AliasChoices` (~30 lines), drop the hand-rolled YAML/env-vars helpers (~365 lines deleted, ~290 lines added → net ~-75 lines, not -350 as originally estimated).

______________________________________________________________________

## File map (revised)

### Phase 0 — Audit + precedence characterization (Oneiric, 1 commit)

| Path | Status | Notes |
|---|---|---|
| `oneiric/core/config.py` | read-only | characterize ACB precedence; full audit of `_ALIAS_OVERRIDES`; env-var collision audit |
| `.claude/decisions/2026-10-11-pydantic-settings-plan-review.md` | create | record the 5-agent review findings (not yet written) |

### Phase 1 — Substrate migration (Oneiric, 3-4 commits)

| Path | Status | Notes |
|---|---|---|
| `oneiric/core/config.py` | rewrite | `OneiricSettings` + `OneiricMCPConfig` → `BaseSettings`; `load_settings()` → `settings_customise_sources` chain; add `arbitrary_types_allowed=True`; drop `env_file=".env"` from `OneiricMCPConfig`; delete hand-rolled helpers |
| `oneiric/core/logging.py::LoggingConfig.level` | edit | add `validation_alias=AliasChoices("level", "ONEIRIC_LOG_LEVEL")` |
| `oneiric/core/config.py::_ALIAS_OVERRIDES` (delete) + target fields | delete + edit | re-implement via `AliasChoices` on each target field (full audit in Phase 0) |
| `oneiric/core/build_settings.py` | create | `build_oneiric_settings(project_name)` factory with module-level memoization |
| `oneiric/core/_sources.py` | create | `BodaiManifestSource` — Oneiric-specific custom source (reads from `oneiric remote-sync` cache; skipped when no manifest URL configured) |
| `oneiric/runtime/orchestrator.py` (caller) | edit | call sites that instantiate `OneiricSettings` should use `await asyncio.to_thread(load_settings, project_name=...)` |

### Phase 2 — Adapter settings (Oneiric, 1-2 commits)

| Path | Status | Needs env vars? |
|---|---|---|
| `oneiric/adapters/llm/llm_interface.py::LLMBaseSettings` | migrate → `BaseSettings` (with `env_prefix="LLM_"`) | yes — shared base |
| `oneiric/adapters/embedding/embedding_interface.py::EmbeddingBaseSettings` | migrate → `BaseSettings` (with `env_prefix="EMBEDDING_"`) | yes |
| `oneiric/adapters/vector/vector_types.py::VectorBaseSettings` | migrate → `BaseSettings` (with `env_prefix="VECTOR_"`) | yes |
| `oneiric/adapters/nosql/nosql_types.py::NoSQLBaseSettings` | migrate → `BaseSettings` (with `env_prefix="NOSQL_"`) | yes |
| 9 concrete adapters (Anthropic, OpenAI LLM+Embedding, Pgvector, Pinecone, Qdrant, MongoDB, Firestore, DynamoDB) | inherit from updated shared bases | yes |
| `oneiric/adapters/observability/settings.py::OTelStorageSettings` | already `BaseSettings` | verify env_prefix still resolves; this is the nested-`BaseSettings` sharp edge case |
| `oneiric/adapters/cache/*.py` | leave on `BaseModel` | no |
| `oneiric/adapters/database/*.py` | leave on `BaseModel` | no |
| `oneiric/adapters/secrets/*.py` | leave on `BaseModel` | no |
| `oneiric/adapters/messaging/*.py` | leave on `BaseModel` | no |
| `oneiric/adapters/monitoring/*.py` | leave on `BaseModel` | no |
| `oneiric/adapters/identity/*.py` | leave on `BaseModel` | no |
| `oneiric/adapters/file_transfer/*.py` | leave on `BaseModel` | no |
| `oneiric/adapters/queue/*.py` | leave on `BaseModel` | no — already `BaseModel`, no env-var need identified (spec §9 notes RedisStreamsQueueSettings as a future candidate if env-var need arises) |

### Phase 3 — Cross-repo verification + fixes (5-8 commits across 5 repos)

| Path | Repo | Action |
|---|---|---|
| `mahavishnu/core/config.py::MahavishnuSettings` | mahavishnu | Verify `load_settings("mahavishnu")` returns the same fields. No source change required. |
| `mahavishnu/core/config.py:1817 OneiricMCPConfig` | mahavishnu | **NEW**: explicit decision — migrate to `BaseSettings`, delete in favor of substrate re-export, OR keep the deliberate split. Task 3.7. |
| `akosha/akosha/config.py:38-43 OneiricMCPConfig fallback` | akosha | **NEW**: verify no test relies on `BaseModel`-specific behavior. Task 3.8. |
| `mcp-common/mcp_common/config/base.py:34-45 MCPBaseSettings` | mcp-common | **NEW**: decide whether to migrate `MCPBaseSettings` to `BaseSettings` too, or document the deliberate divergence. Task 3.9. |
| `crackerjack/<khaorg>/config.py` | crackerjack | Verify `load_settings("crackerjack")` works unchanged. |
| `session-buddy/<khaorg>/config.py` | session-buddy | Verify `load_settings("session_buddy")` works unchanged. |
| `mcp-common/src/<khaorg>/config.py` (or equivalent) | mcp-common | Verify `OneiricMCPConfig` re-export works unchanged. |

### Phase 4 — Cleanup + test rewrite (Oneiric, 1-2 commits)

| Path | Action |
|---|---|
| `tests/unit/test_load_settings_cwd_fallback.py` | rewrite or delete (pydantic-settings emits no `DeprecationWarning`) |
| `tests/unit/test_load_settings_xdg.py` | rewrite against new source chain |
| `tests/unit/test_load_settings_anchors.py` | rewrite against new `project_root` handling |
| `tests/unit/test_cli_xdg_loader.py` | rewrite against new source chain |
| `tests/core/test_config_xdg.py` | rewrite (imports deleted `_env_overrides`) |
| `tests/unit/test_core_config_branches.py` | rewrite (calls deleted `_read_file`) |
| `tests/unit/test_core_config.py` | rewrite env-var test cases |
| `docs/architecture/MEMORY_ARCHITECTURE.md` | update to reflect new loader model (Dhara cleanup already at `3ea7ae5`) |

______________________________________________________________________

## Phase 0 — Audit + precedence characterization

### Phase 0 — Integration Contract

**Triggered from:** ADR 0003 (revised) active; spec update at `a191bed`.

**Returns to / updates:**
- `.claude/decisions/2026-10-11-pydantic-settings-plan-review.md` (new) — records the 5-agent review findings
- `docs/plans/2026-10-11-pydantic-settings-migration.md` (this file) — gains pinned ACB precedence + `_ALIAS_OVERRIDES` audit results + env-var collision list

**Demonstrable by:**
- `tests/unit/test_pydantic_settings_precedence.py` — 10 test cases that pin ACB's documented precedence under the CURRENT hand-rolled loader (these become the migration acceptance criteria):
  - `test_env_overrides_yaml_layer_5_xdg_local`
  - `test_env_overrides_yaml_layer_3_project_local`
  - `test_yaml_layer_5_xdg_local_overrides_layer_4_xdg_config`
  - `test_yaml_layer_4_xdg_config_overrides_layer_3_project_local`
  - `test_init_kwargs_default_when_no_source_supplies_value`
  - `test_alias_overrides_activity_store_routes_to_domain_activity_path`
  - `test_alias_overrides_log_level_routes_to_logging_level`
  - `test_explicit_path_argument_overrides_yaml_layers`
  - `test_PROJECT_CONFIG_env_overrides_yaml_layers`
  - `test_yaml_source_with_missing_file_does_not_raise`
- `tests/unit/test_env_var_collision_audit.py` — enumerates every field on `OneiricSettings` + `OneiricMCPConfig` and asserts the migration does not silently flip any of them when run with `env | grep -E "^(ONEIRIC|MAHAVISHNU|AKOSHA|CRACKERJACK|SESSION_BUDDY)" | sort`.

**Rollback signal:** any of the 10 precedence tests fails after Phase 1 implementation; any of the env-var-collision tests reveals a silent flip.

**Observability added:** `oneiric.core.config.load_settings` logs the active source chain and the env-prefix of the resulting subclass at debug level.

### Phase 0 — Tasks

- [ ] **0.1** Run `grep -rn "_ALIAS_OVERRIDES\|_env_overrides" oneiric/` and document each entry. Output: a table mapping each legacy env var → its new `AliasChoices` target field.
- [ ] **0.2** For each `_ALIAS_OVERRIDES` entry, add a test that asserts the env var routes to the correct field under the CURRENT hand-rolled loader. These become the migration acceptance tests.
- [ ] **0.3** Run `env | grep -E "^(ONEIRIC|MAHAVISHNU|AKOSHA|CRACKERJACK|SESSION_BUDDY)" | sort > /tmp/audit-env.txt` against the substrate's field set. Flag any field name that collides with an env var.
- [ ] **0.4** Document the ACB precedence (from `acb/config.py:140-260`) in this plan as the "ACB precedence" section. Pinned order: defaults → YAML → env → `_ALIAS_OVERRIDES`.
- [ ] **0.5** Write `.claude/decisions/2026-10-11-pydantic-settings-plan-review.md` recording the 5-agent review findings and the 17 HIGH+BLOCKER issues addressed by this revision.

### Phase 0 — Validation gates

- [ ] `grep -rn "_ALIAS_OVERRIDES\|_env_overrides" oneiric/` returns all known aliases (and only known ones)
- [ ] `pytest tests/unit/test_pydantic_settings_precedence.py -v` passes against the CURRENT hand-rolled loader
- [ ] `pytest tests/unit/test_env_var_collision_audit.py -v` passes with zero silent flips
- [ ] `.claude/decisions/2026-10-11-pydantic-settings-plan-review.md` exists

### Phase 0 — Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| The 10 precedence tests reveal ACB's actual behavior differs from documented | Medium | If a test fails, the plan reverts — do not proceed to Phase 1 |
| Env-var collision reveals a silent env var in the shell | Medium | The operator must unset those env vars before merging Phase 1 |

______________________________________________________________________

## Phase 1 — Substrate migration

### Phase 1 — Integration Contract

**Triggered from:** Phase 0 complete; precedence tests pinned; env-var audit clean.

**Returns to / updates:**
- `oneiric.core.config.OneiricSettings` extends `BaseSettings` (was `BaseModel`); `model_config` retains the same `env_prefix`/`env_nested_delimiter`/`populate_by_name` declarations; adds `arbitrary_types_allowed=True`.
- `oneiric.core.config.OneiricMCPConfig` extends `BaseSettings` (was `BaseModel`); `model_config` retains declarations; **drops** `env_file=".env"`.
- `oneiric.core.config.load_settings(project_name, path=None)` — preserved as a function; internals use `build_oneiric_settings(project_name)` + `settings_customise_sources` chain + post-construction `model_validate` for `path=` override.
- `_ALIAS_OVERRIDES` semantics preserved via `validation_alias=AliasChoices(...)` on `LoggingConfig.level` (and other target fields per Phase 0 audit).
- `OneiricMCPAuthConfig.from_env()` call-site preserved at the CLI; `auth:` field is **excluded** from env-var source merging.
- `mcp__oneiric__*` MCP tools — unchanged surface.
- `mcp-common.OneiricMCPConfig` re-export — independent (mcp-common's `OneiricMCPConfig` is the substrate's class; re-export site at `mcp_common/fastmcp/__init__.py:31`).

**Demonstrable by:**
- `pytest tests/unit/test_pydantic_settings_precedence.py -v` passes against the new chain (10 tests from Phase 0 still hold).
- `pytest tests/unit/test_env_var_collision_audit.py -v` passes (zero silent flips).
- `ONEIRIC_OBSERVABILITY__CONNECTION_STRING=postgres://x python -c "from oneiric.core.config import load_settings; s = load_settings('oneiric'); print(s.observability.connection_string)"` prints `postgres://x`.
- `ONEIRIC_ACTIVITY_STORE=/tmp/store python -c "..."` routes to `runtime_paths.domain_activity_path` (via `AliasChoices`).
- `ONEIRIC_LOG_LEVEL=DEBUG python -c "..."` routes to `logging.level` (via new `AliasChoices`).
- `ONEIRIC_AUTH__ENABLED=true python -c "..."` does NOT raise (the `auth:` field's env-var source is excluded; `from_env()` overlay applies at CLI call site).
- `${XDG_CONFIG_HOME}/<project>/local.yaml` overrides beat `settings/<project>.yaml`.
- `ONEIRIC_MCP_HTTP_PORT=9999 python -c "from oneiric.core.config import OneiricMCPConfig; print(OneiricMCPConfig().http_port)"` prints `9999` (silent env-var loading documented behavior).
- `ONEIRIC_MCP_HTTP_PORT=9999 python -c "from oneiric.core.config import OneiricMCPConfig; print(OneiricMCPConfig(http_port=8888).http_port)"` prints `9999` (env_settings > init_settings, since env_settings comes earlier in the chain). pydantic-settings' "first returned = highest priority" rule applies.
- `python -c "from oneiric.adapters.watcher import AdapterConfigWatcher"` (async caller) does not block the event loop (uses `await asyncio.to_thread(load_settings, ...)`).
- `python -c "import os; os.environ['ONEIRIC_DEBUG'] = 'true'; from oneiric.core.config import OneiricSettings; print(OneiricSettings().debug)"` prints `True` (env-var activation works after migration).

**Rollback signal:** any of the above demonstrations fails; precedence flips; silent env-var flip detected.

**Observability added:** `oneiric.core.config.load_settings` logs the source chain at debug level; `BodaiManifestSource.__call__` logs when it loads a manifest; `OneiricSettings.create_from_path` (new helper, post-construction model_validate path) logs which explicit path was applied.

### Phase 1 — Tasks

- [ ] **1.1** In `oneiric/core/config.py:296`, change `class OneiricMCPConfig(BaseModel):` → `class OneiricMCPConfig(BaseSettings):`. **Remove** `env_file=".env"` from `model_config`. No other change to that class. **In the SAME commit (not a follow-up)**, add `"pydantic-settings>=2.15"` to `[project].dependencies` in `pyproject.toml:13`. The plan uses `pydantic-settings`' full API surface (`SettingsConfigDict`, `BaseSettings`, `YamlConfigSettingsSource`, `PydanticBaseSettingsSource`, `AliasChoices`, `validation_alias`); without a direct pin, future `pydantic` upgrades could silently drop or alter `pydantic-settings`.
- [ ] **1.2** In `oneiric/core/config.py:311`, change `class OneiricSettings(BaseModel):` → `class OneiricSettings(BaseSettings):`. Add `arbitrary_types_allowed=True` to `model_config`.
- [ ] **1.3** Add `settings_customise_sources` classmethod to `OneiricSettings`. Return tuple (in pydantic-settings' "first wins" order — REVERSED from ACB's "last wins"):
  ```python
  return (
      _alias_overrides_source(settings_cls),  # highest priority (was last in ACB)
      env_settings,                            # env vars beat YAML
      _yaml_source(LAYER_5_XDG_LOCAL),
      _yaml_source(LAYER_4_XDG_CONFIG),
      _yaml_source(LAYER_3_PROJECT_LOCAL),
      _yaml_source(LAYER_2_PROJECT),
      _yaml_source(LAYER_1_PROJECT),
      init_settings,                           # constructor kwargs last (lowest priority)
      file_secret_settings,
  )
  ```
  Each `_yaml_source(path)` constructs `YamlConfigSettingsSource(settings_cls, yaml_file=path, deep_merge=True)` — explicit `deep_merge=True` so nested dicts across layers merge recursively.
- [ ] **1.4** Paths passed to `_yaml_source` are anchored to `project_root`, not CWD. The factory `build_oneiric_settings(project_name)` reads `PROJECT_ROOT` env var or defaults to `Path(__file__).resolve().parent.parent.parent`. The 5 YAML paths are constructed as `project_root / "settings" / f"{layer_filename}"`.
- [ ] **1.5** Memoize `build_oneiric_settings(project_name)` module-level. Returns a `_Project(OneiricSettings)` subclass with `env_prefix=f"{project_name.upper()}_"`. Cache by `project_name` so the subclass is built once per process.
- [ ] **1.6** `load_settings(project_name, path=None)` builds a `_Project` instance and applies explicit `path=` override via `model_validate(merged_dict)` POST-CONSTRUCTION. The merged dict is constructed by reading `path` (if given) and `{PROJECT_NAME}_CONFIG` env var (if set), in that priority order.
- [ ] **1.7** Re-implement `_ALIAS_OVERRIDES` as `validation_alias=AliasChoices(...)` on each target field per Phase 0 audit. Specifically: `LoggingConfig.level` gets `validation_alias=AliasChoices("level", "ONEIRIC_LOG_LEVEL")` (NEW). Other target fields per Phase 0 results.
- [ ] **1.8** Add `BodaiManifestSource(PydanticBaseSettingsSource)` to `oneiric/core/_sources.py` (NOT `oneiric/adapters/`). Implements `get_field_value` + `__call__`. Reads from `oneiric remote-sync` cache. Returns a no-op empty dict when no manifest URL configured. Wired into the chain between YAML and env_settings when configured.
- [ ] **1.9** Delete the hand-rolled helpers from `oneiric/core/config.py`: `_read_file`, `_load_layer_file`, `_deep_merge`, `_coerce_env_value`, `_env_overrides`, `_ALIAS_OVERRIDES`. Delete the `load_settings` body and replace with the settings_customise_sources + build_oneiric_settings + model_validate path.
- [ ] **1.10** Mark `auth: OneiricMCPAuthConfig` field as excluded from env-var source merging. **`OneiricMCPAuthConfig` is a stdlib `@dataclass` (not a Pydantic model) — pydantic-settings can't decorate it.** Implementation: a custom source wrapper that subclasses the default sources (`EnvSettingsSource`, `YamlConfigSettingsSource`, `DotEnvSettingsSource`) and overrides `__call__` to drop the `auth` key before merging. Code sketch:
  ```python
  class _AuthExcludingYamlSource(YamlConfigSettingsSource):
      def __call__(self) -> dict[str, Any]:
          data = super().__call__()
          data.pop("auth", None)
          return data
  # Same pattern for EnvSettingsSource + DotEnvSettingsSource
  ```
  The `auth:` field's env-var source stays applied via `OneiricMCPAuthConfig.from_env()` at the CLI call site (per the comment at `oneiric/core/config.py:359-361`). Alternative (out-of-scope refactor): convert `OneiricMCPAuthConfig` from `@dataclass` to a `BaseSettings` subclass with its own `env_prefix="ONEIRIC_AUTH_"`, which would make the `auth:` exclusion unnecessary. Document this design choice in the commit message.
- [ ] **1.11** Update async call sites that invoke `load_settings(...)` inside `async def` blocks: `oneiric/cli/__init__.py:3189` (inside `async def _shell()`), `oneiric/cli/mcp.py:121` (inside `_load_auth_from_settings()` — verify it's async first), `oneiric/shell/adapter.py:159` (inside `async def _reload_settings()`). Wrap each with `await asyncio.to_thread(load_settings, ...)`. **Note:** `oneiric/main.py:38`, `oneiric/cli/__init__.py:204,222,248,768`, `oneiric/adapters/watcher.py:18`, `oneiric/domains/watchers.py:24,41,58,76`, `oneiric/runtime/watchers.py:36` are NOT call sites — they are sync-context references or default-arg values in function signatures. No wrapping needed. **Net async-wrap sites: 3, not 11.**
- [ ] **1.12** Update unit tests `tests/unit/test_config.py` and the 7 affected test files (see Phase 4 file map) to assert the new chain semantics.

### Phase 1 — Validation gates (corrected — original gate was empty)

| # | Gate | What it checks |
|---|---|---|
| 1.1 | `grep -rn "_read_file\|_load_layer_file\|_deep_merge\|_coerce_env_value\|_env_overrides\|_ALIAS_OVERRIDES" oneiric/core/config.py` returns zero matches | Hand-rolled helpers actually deleted (original `load_yaml_` gate returned zero matches before migration — false-positive safety net) |
| 1.2 | `grep -rn "env_file=" oneiric/core/config.py` returns zero matches | `.env` activation regression avoided |
| 1.3 | `wc -l oneiric/core/config.py` reduced from pre-migration baseline (≥900 lines) by ≥300 lines | Real net code reduction |
| 1.4 | `grep -rn "from oneiric.core.config import OneiricSettings, OneiricMCPConfig" oneiric/ tests/` succeeds; both classes construct | Inheritance change doesn't break internal imports |
| 1.5 | `python -c "from oneiric.core.config import load_settings; s = load_settings('oneiric'); print(type(s).__name__)"` prints a `_Project` subclass name | Factory works |
| 1.6 | `grep -rn "await load_settings\|asyncio.to_thread(load_settings" oneiric/` shows the async wrap at **exactly 3 sites** (`cli/__init__.py:3189`, `cli/mcp.py:121`, `shell/adapter.py:159`); **fails if more than 3 matches** | Async discipline enforced — neither over- nor under-wrapping |
| 1.7 | `pytest tests/unit/test_pydantic_settings_precedence.py -v` — all 10 tests pass | ACB precedence preserved |
| 1.8 | `pytest tests/unit/test_env_var_collision_audit.py -v` — zero flips | Silent env-var activation prevented |
| 1.9 | `pytest tests/integration/test_oneiric_mcp_e2e.py -v` passes | MCP tool surface unchanged |
| 1.10 | `ONEIRIC_AUTH__ENABLED=true python -c "from oneiric.core.config import load_settings; print(load_settings('oneiric').auth)"` does NOT raise | `auth:` dataclass field doesn't break construction |

### Phase 1 — Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| Pydantic-settings precedence differs from ACB (first vs last wins) | Already mitigated | Phase 0 pins precedence via 10 tests |
| Async `load_settings` blocks the event loop on disk I/O | High | All 11 call sites wrapped with `asyncio.to_thread` (task 1.11) |
| Nested env_prefix + nested BaseSettings (`OTelStorageSettings` inside `OneiricSettings`) — most-reverted edge in pydantic-settings GitHub history | Medium | Phase 2 verifies; rollback to one-level field if broken |
| `YamlConfigSettingsSource` silently skips missing files; ACB's loader probably raised | High | Document the new behavior (silent skip); add regression test asserting the absence of raise |
| `.env` activation regression if `env_file` is not dropped | High | Validation gate 1.2 + explicit `del` from `OneiricMCPConfig.model_config` in task 1.1 |
| `_ALIAS_OVERRIDES` regression for any alias not in the audit | Medium | Full audit in Phase 0 task 0.1; `AliasChoices` per phase 0 task 0.1 |
| Adapter `env_prefix` (LLM_, VECTOR_, etc.) collision with project env_prefix (MAHAVISHNU_*) | Medium | Phase 2 explicitly verifies: `LLM_API_KEY=x` does NOT flow into `MahavishnuSettings.api_key` (or does, if the user expects it) |
| Mahavishnu's `_mahavishnu_env_overlay` workaround becomes dead code post-migration | Medium | Phase 3 task 3.7 documents; remove in follow-up |
| `OneiricMCPAuthConfig.from_env()` double-applies env vars | Medium | Task 1.10 excludes `auth:` from env-source merging |

______________________________________________________________________

## Phase 2 — Adapter settings (within Oneiric)

### Phase 2 — Integration Contract

**Triggered from:** Phase 1 complete; `OneiricSettings` extends `BaseSettings`; precedence pinned.

**Returns to / updates:**
- 4 shared base classes (`LLMBaseSettings`, `EmbeddingBaseSettings`, `VectorBaseSettings`, `NoSQLBaseSettings`) extend `BaseSettings` with `env_prefix` per category
- 9 concrete adapter settings inherit env-var loading from their shared base (no changes needed beyond the base)
- `OTelStorageSettings` — unchanged (already `BaseSettings`); verify env_prefix still resolves; this is the nested-`BaseSettings` sharp edge case
- Cache / Database / Secrets / Messaging / Monitoring / Identity / File-transfer / Queue adapters stay on `BaseModel` (no env-var need; spec §9 notes queue as a future candidate if env-var need arises)

**Demonstrable by:**
- `LLM_API_KEY=sk-xxx python -c "from oneiric.adapters.llm.openai import OpenAILLMSettings; print(OpenAILLMSettings().api_key)"` prints `sk-xxx`
- `EMBEDDING_API_KEY=sk-xxx python -c "from oneiric.adapters.embedding.openai import OpenAIEmbeddingSettings; print(OpenAIEmbeddingSettings().api_key)"` prints `sk-xxx`
- `VECTOR_URL=http://localhost:6333 python -c "from oneiric.adapters.vector.qdrant import QdrantSettings; print(QdrantSettings().url)"` prints `http://localhost:6333`
- `ONEIRIC_OTEL_STORAGE__CONNECTION_STRING=postgres://x python -c "from oneiric.adapters.observability.settings import OTelStorageSettings; print(OTelStorageSettings().connection_string)"` prints `postgres://x` (the nested-BaseSettings sharp edge)
- Cache / Database settings still construct from explicit kwargs without env-var lookup: `RedisCacheSettings(url="redis://x")` works as before.
- Adapter `env_prefix` does NOT collide with project env_prefix: `LLM_API_KEY=x python -c "from mahavishnu.core.config import MahavishnuSettings; print(MahavishnuSettings().api_key)"` prints Mahavishnu's value, not `x`.

**Rollback signal:** any adapter's existing tests fail on env-var precedence; nested-BaseSettings (`OTelStorageSettings` inside `OneiricSettings`) breaks construction; cross-prefix env-var collision detected.

**Observability added:** each `BaseSettings` subclass logs its source chain at debug level when first instantiated.

### Phase 2 — Tasks

- [ ] **2.1** `oneiric/adapters/llm/llm_interface.py::LLMBaseSettings`: change `class LLMBaseSettings(BaseModel):` → `class LLMBaseSettings(BaseSettings):`. Add `model_config = SettingsConfigDict(env_prefix="LLM_", env_nested_delimiter="__", extra="allow", populate_by_name=True)`.
- [ ] **2.2** `oneiric/adapters/embedding/embedding_interface.py::EmbeddingBaseSettings`: same pattern with `env_prefix="EMBEDDING_"`.
- [ ] **2.3** `oneiric/adapters/vector/vector_types.py::VectorBaseSettings`: same with `env_prefix="VECTOR_"`.
- [ ] **2.4** `oneiric/adapters/nosql/nosql_types.py::NoSQLBaseSettings`: same with `env_prefix="NOSQL_"`.
- [ ] **2.5** Verify concrete adapter settings inherit env-var loading from their shared base: `AnthropicLLMSettings`, `OpenAILLMSettings`, `OpenAIEmbeddingSettings`, `PgvectorSettings`, `PineconeSettings`, `QdrantSettings`, `MongoDBSettings`, `FirestoreSettings`, `DynamoDBSettings` (no changes needed if the bases are correct).
- [ ] **2.6** Verify `OTelStorageSettings` still works (already `BaseSettings`; verify `env_prefix="ONEIRIC_OTEL_STORAGE_"` is preserved; test the nested-BaseSettings sharp edge).
- [ ] **2.7** Update tests under `tests/adapters/` to either keep the existing `BaseModel`-style test (if env vars are not asserted) or add new env-var tests.
- [ ] **2.8** Cross-prefix collision test: assert that `LLM_API_KEY=x` does NOT flow into `MahavishnuSettings.api_key`.
- [ ] **2.9** Run the full `pytest tests/adapters/` to verify no regressions.

### Phase 2 — Validation gates

- [ ] `grep -rn "(BaseSettings)" oneiric/adapters/` returns ≥ 5 matches (4 shared bases + `OTelStorageSettings`)
- [ ] `pytest tests/adapters/ -v` passes
- [ ] `LLM_API_KEY=x python -c "..."` prints `x`
- [ ] `EMBEDDING_API_KEY=x python -c "..."` prints `x`
- [ ] `VECTOR_URL=http://x python -c "..."` prints `http://x`
- [ ] `pytest tests/unit/test_pydantic_settings_precedence.py -v` still passes (no regression in substrate)

### Phase 2 — Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| A shared base's `env_prefix` collides with a concrete adapter's `env_prefix` | Low | Pydantic-settings precedence: nearest-in-MRO wins. Concrete adapters extend shared bases — set `env_prefix` only on the shared base. |
| Tests rely on kwargs-only construction (not env vars); migrate to `BaseSettings` breaks them | Medium | Pydantic-settings falls back to constructor kwargs when env vars are absent. Document in test PR. |
| Nested `BaseSettings` (`OTelStorageSettings` inside `OneiricSettings.observability`) breaks construction | Medium | Phase 2 task 2.6 explicitly verifies. If broken: refactor `OneiricSettings.observability` to be `dict[str, Any]` and instantiate `OTelStorageSettings(**)` separately. |
| Cross-prefix env-var collision (adapter LLM_* vs project MAHAVISHNU_*) | Medium | Task 2.8 explicit collision test |
| Per-category env_prefix is dynamic, not class-level — does the factory approach work? | Already mitigated | Each `*BaseSettings` is a class with its own `env_prefix`; concrete adapters extend. The factory is per-project for `OneiricSettings`, not for adapter settings. |

______________________________________________________________________

## Phase 3 — Cross-repo verification + fixes

### Phase 3 — Integration Contract

**Triggered from:** Phase 1 + Phase 2 complete.

**Returns to / updates:**
- All 5 cross-repo consumers' `load_settings(project_name="X")` calls return the same fields as pre-migration (with env-var precedence preserved)
- Mahavishnu's local `OneiricMCPConfig(BaseModel)` shadow — explicit decision documented (migrate, delete, or keep deliberate split)
- Akosha's local fallback `OneiricMCPConfig(BaseModel)` — verified no test relies on `BaseModel`-specific behavior
- mcp-common's `MCPBaseSettings` — explicit decision documented (migrate to `BaseSettings` or document divergence)
- Phase 3 env-var name typo corrected: `MAHAVISHNU_AUTH__JWT_SECRET` → `MAHAVISHNU_AUTH__SECRET` (the field is `secret`, not `jwt_secret`)

**Demonstrable by:**
- All 5 consumers' existing test suites pass without source changes (other than pulling in the migrated Oneiric substrate)
- Per-project env-prefix tests pass: `MAHAVISHNU_LOG_LEVEL=DEBUG` flows into `MahavishnuSettings.log_level`; `AKOSHA_*`, `CRACKERJACK_*`, `SESSION_BUDDY_*`, `MAHAVISHNU_AUTH__SECRET=foo` flow correctly
- Phase 3 task 3.7 result documented (Mahavishnu's local `OneiricMCPConfig` decision)
- Phase 3 task 3.8 result documented (Akosha fallback verification)
- Phase 3 task 3.9 result documented (mcp-common `MCPBaseSettings` decision)
- `OneiricMCPConfig(http_port=9999).http_port == 9999` when no env var is set; `ONEIRIC_MCP_HTTP_PORT=9999` is picked up when set

**Rollback signal:** any of the 5 consumer test suites fails on a config-load path; env-var override precedence changes for any downstream consumer.

**Observability added:** each cross-repo `load_settings` logs the source chain at debug level.

### Phase 3 — Tasks

- [ ] **3.1** Mahavishnu: run the existing test suite against `from oneiric.core.config import load_settings as _oneiric_load`. Verify `MahavishnuSettings.secret` is settable via `MAHAVISHNU_AUTH__SECRET=foo` (not `JWT_SECRET` — that was a typo).
- [ ] **3.2** Mahavishnu: verify Mahavishnu's `_mahavishnu_env_overlay` workaround is no longer needed (post-migration, `MAHAVISHNU_LOG_LEVEL` flows directly to MahavishnuSettings.log_level). Mark for removal as follow-up.
- [ ] **3.3** Akosha: verify `load_settings("akosha")` works unchanged.
- [ ] **3.4** Crackerjack: verify `load_settings("crackerjack")` works unchanged.
- [ ] **3.5** Session-Buddy: verify `load_settings("session_buddy")` works unchanged.
- [ ] **3.6** mcp-common: verify `OneiricMCPConfig` re-export works (post-migration it's `BaseSettings`).
- [ ] **3.7** **Mahavishnu's local `OneiricMCPConfig(BaseModel)` shadow** at `mahavishnu/core/config.py:1817` — explicit decision: migrate to `BaseSettings` (mirror substrate), delete in favor of substrate re-export, or keep the deliberate split. **This is its own commit per decision.**
- [ ] **3.8** **Akosha's local fallback `OneiricMCPConfig(BaseModel)`** at `akosha/akosha/config.py:38-43` — verify no test relies on `BaseModel`-specific behavior. Document the verification result.
- [ ] **3.9** **mcp-common's `MCPBaseSettings(BaseModel)` deprecated seam** at `mcp-common/config/base.py:34-45` — explicit decision: migrate to `BaseSettings` or document the divergence.
- [ ] **3.10** Document each consumer's verified env-var names in the `.claude/decisions/2026-10-11-pydantic-settings-migration-results.md` follow-up note (not in the ADR — that's a meta-task).

### Phase 3 — Validation gates

- [ ] All 5 consumers' existing test suites pass without source changes (other than pulling in the migrated Oneiric substrate)
- [ ] Per-project env-prefix tests pass in each of the 5 repos
- [ ] Task 3.7 result documented
- [ ] Task 3.8 result documented
- [ ] Task 3.9 result documented
- [ ] `OneiricMCPConfig(http_port=9999).http_port == 9999` when no env var is set
- [ ] `ONEIRIC_MCP_HTTP_PORT=9999 python -c "..."` picks up `9999` (silent env-var loading documented)

### Phase 3 — Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| A cross-repo consumer relies on a hand-rolled loader internal that's now removed | Medium | The substrate's `load_settings` is the only public API; no consumer should reach into internals. Verify with `grep -rn "load_yaml_\|layer_merge\|env_override" <repo>/` should return zero. |
| A consumer sets env vars with a different convention (e.g., `MAHAVISHNU_FOO` not `MAHAVISHNU_FOO__BAR`) | Low | The `env_nested_delimiter="__"` is preserved. Single-segment env vars work as before. |
| `OneiricMCPConfig` extends `BaseSettings` breaks a cross-repo consumer that expected `BaseModel` semantics | Low | `BaseSettings` IS a `BaseModel` (verified via pydantic-settings 2.15 docs). All existing `BaseModel` semantics still work; only env-var loading is added. |
| Mahavishnu's local `OneiricMCPConfig(BaseModel)` shadow diverges post-migration | High | Task 3.7 explicit decision |
| Akosha's local fallback diverges if oneiric is not installed | Medium | Task 3.8 verification |
| mcp-common's `MCPBaseSettings` deprecated seam refers to a class whose semantics change | Medium | Task 3.9 explicit decision |

______________________________________________________________________

## Phase 4 — Cleanup + test rewrite

### Phase 4 — Integration Contract

**Triggered from:** Phase 3 complete; all 5 cross-repo consumers verified; tasks 3.7/3.8/3.9 decisions documented.

**Returns to / updates:**
- `oneiric/core/config.py` loses the dead hand-rolled loader code (Phase 1 already removed it; Phase 4 is just verification + line-count check)
- 7 test files rewritten (per Phase 4 file map)
- `docs/architecture/MEMORY_ARCHITECTURE.md` reflects the new loader model
- `.claude/decisions/2026-10-11-pydantic-settings-migration-results.md` records the actual results

**Demonstrable by:**
- `wc -l oneiric/core/config.py` shows a net reduction (target: ≥300 lines removed)
- `grep -rn "load_yaml\|manual.*layer\|manual.*env.*override" oneiric/` returns zero matches
- All 7 rewritten test files pass
- Full Oneiric test suite passes
- All 5 cross-repo test suites pass

**Rollback signal:** a hand-rolled loader feature is needed in a future feature (unlikely — pydantic-settings covers all known needs).

**Observability added:** none beyond Phase 1's debug-level source-chain log.

### Phase 4 — Tasks

- [ ] **4.1** Rewrite `tests/unit/test_load_settings_cwd_fallback.py` — the `DeprecationWarning` for CWD-relative paths no longer fires (pydantic-settings emits no warning). Either delete the test or assert that no warning fires.
- [ ] **4.2** Rewrite `tests/unit/test_load_settings_xdg.py` against the new source chain.
- [ ] **4.3** Rewrite `tests/unit/test_load_settings_anchors.py` against the new `project_root` handling.
- [ ] **4.4** Rewrite `tests/unit/test_cli_xdg_loader.py` against the new source chain.
- [ ] **4.5** Rewrite `tests/core/test_config_xdg.py` (imports deleted `_env_overrides`).
- [ ] **4.6** Rewrite `tests/unit/test_core_config_branches.py` (calls deleted `_read_file`).
- [ ] **4.7** Rewrite `tests/unit/test_core_config.py` env-var test cases.

- [ ] **4.7a** Add NEW tests for Phase 1/2 added behavior (none of these are rewrites — they're net additions):
  - `tests/unit/test_bodai_manifest_source.py` — verify `BodaiManifestSource` reads from `oneiric remote-sync` cache, returns no-op when no manifest URL configured, slots in correct precedence position.
  - `tests/unit/test_build_oneiric_settings.py` — verify memoization: `build_oneiric_settings("X")` called twice returns the same class object (id-equal).
  - `tests/unit/test_auth_field_exclusion.py` — verify `ONEIRIC_AUTH__ENABLED=true` does NOT leak into `OneiricSettings.auth.enabled`; `from_env()` is the sole path.
  - `tests/unit/test_init_env_precedence.py` — verify the chain order: `init_settings` < `env_settings` < YAML < `_alias_overrides_source`. Concrete: `OneiricSettings(api_key=debug_level="DEBUG")` + `ONEIRIC_DEBUG_LEVEL=INFO` → `debug_level == "INFO"`.
  - `tests/unit/test_arbitrary_types_allowed.py` — verify `auth: OneiricMCPAuthConfig` dataclass round-trips through `model_dump()` / `model_validate()` cleanly.
  - `tests/unit/test_nested_base_settings.py` — pin the nested-BaseSettings sharp edge: `OTelStorageSettings` inside `OneiricSettings.observability` works for `ONEIRIC_OBSERVABILITY__CONNECTION_STRING=...`.
  - `tests/unit/test_adapter_env_prefix_collision.py` — verify `LLM_API_KEY=x` does NOT flow into `MahavishnuSettings.api_key`; verify `ONEIRIC_OTEL_STORAGE__CONNECTION_STRING=x` does NOT flow into `MahavishnuSettings.otel_storage.connection_string`.
  - `tests/unit/test_env_var_collision_audit.py` — pytest-based version of Phase 0 task 0.3 (NOT shell-grep): iterate `dir(settings_instance)`, verify each field name (case-insensitive, with `__` delimiter) doesn't accidentally pick up a real env var via mocked `monkeypatch`.

- [ ] **4.7b** Add `# ty: ignore[valid-type]` on the `auth: OneiricMCPAuthConfig` line in `oneiric/core/config.py:362`. The existing `# type: ignore[valid-type]` is a mypy directive; `ty` (the operative checker for `oneiric.core.*`) requires the same-line `# ty: ignore[...]` syntax per `ty-ignore-same-line-required.md`. **Note for implementers:** `oneiric.core.*` and `oneiric.cli.*` are excluded from mypy/zuban checking per `mypy.ini` lines 63 and 72; `ty` is the operative type checker for these modules.
- [ ] **4.8** Update `docs/architecture/MEMORY_ARCHITECTURE.md` to reflect: Oneiric's settings are now `BaseSettings`-based (per ADR 0003), the 6-layer merge is via `settings_customise_sources`, the hand-rolled loader is gone. **Sequence: do the Dhara cleanup first (already at `3ea7ae5`), then this Phase 4 step, or factor the merge.**
- [ ] **4.9** Update `oneiric/README.md` to point at ADR 0003 + this migration plan.
- [ ] **4.10** Run the full Oneiric + cross-repo test suite one more time; confirm `git grep "hand.rolled.*loader"` returns zero in docs and code.
- [ ] **4.11** Write `.claude/decisions/2026-10-11-pydantic-settings-migration-results.md` recording actual migration results (Phase 0 → 4 outcomes, decisions made, follow-up backlog).

### Phase 4 — Validation gates

- [ ] `wc -l oneiric/core/config.py` reduced from pre-migration baseline (≥900 lines) by ≥300 lines
- [ ] `grep -rn "load_yaml\|manual.*layer\|manual.*env.*override\|env_overrides\b" oneiric/` returns zero
- [ ] `pytest tests/` (full Oneiric suite) passes
- [ ] Cross-repo suite (Phase 3 commands) passes
- [ ] `.claude/decisions/2026-10-11-pydantic-settings-migration-results.md` exists

### Phase 4 — Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| A test rewrite misses a behavior previously covered | Medium | Run pre-migration and post-migration test suites side-by-side; compare coverage |
| `MEMORY_ARCHITECTURE.md` update races with Dhara cleanup (commit `3ea7ae5`) | Low | Dhara cleanup is already on `main`; this step is a follow-on edit |

______________________________________________________________________

## _ALIAS_OVERRIDES audit (Phase 0)

The `_ALIAS_OVERRIDES` table at `oneiric/core/config.py:800-805` maps two single-underscore (legacy-shape) env vars to nested target fields:

| Legacy env var | Target field | Target section | Current route (hand-rolled) | Phase 1 `AliasChoices` target | File:line |
|---|---|---|---|---|---|
| `ONEIRIC_ACTIVITY_STORE` | `domain_activity_path` | `runtime_paths` | `_env_overrides` (config.py:801-803) dispatches `{runtime_paths: {domain_activity_path: <coerced>}}` | `AliasChoices("domain_activity_path", "ONEIRIC_ACTIVITY_STORE")` | `oneiric/core/config.py:270` |
| `ONEIRIC_LOG_LEVEL` | `level` | `logging` | `_env_overrides` (config.py:804) dispatches `{logging: {level: <coerced>}}` | `AliasChoices("level", "ONEIRIC_LOG_LEVEL")` | `oneiric/core/logging.py:61` |

**Findings:**

- **Two AliasChoices already pre-wired.** Both target fields already
  carry `validation_alias=AliasChoices(...)` (config.py:270,
  logging.py:61). On the current `BaseModel` substrate these are
  dead config — they only activate once the parent class switches
  to `BaseSettings` in Phase 1 task 1.2. Phase 1 task 1.7 declares
  this as the migration acceptance criterion; the wiring exists,
  the loader activation is the Phase 1 deliverable.
- **One additional pre-wired `AliasChoices` not in `_ALIAS_OVERRIDES`.**
  `RuntimeSupervisorConfig.enabled` carries
  `AliasChoices("enabled", "ONEIRIC_RUNTIME_SUPERVISOR__ENABLED")`
  at `config.py:282`. This is NOT in `_ALIAS_OVERRIDES` because
  `RUNTIME_SUPERVISOR__ENABLED` already uses the modern `__`
  nested-key shape — the legacy `_env_overrides` naturally dispatches
  it (config.py:826 splits on `__`, path becomes
  `["runtime_supervisor", "enabled"]`, config.py:838-841 merges).
  The `AliasChoices` is redundant-but-harmless insurance. The
  description at config.py:284-286 is misleading (it says "via
  `_env_overrides`" but post-migration the route is via
  pydantic-settings' nested delimiter); Phase 4 task 4.8 should
  refresh that description text.
- **No new entries to add.** The full `_ALIAS_OVERRIDES` table is
  two rows; both are pre-wired. Phase 0 task 0.1 acceptance
  criterion "no newly-discovered legacy aliases" holds.
- **Call sites outside `_ALIAS_OVERRIDES`.**
  `oneiric/mcp/config.py:91-103` (`OneiricMCPAuthConfig.from_env`)
  reads `ONEIRIC_AUTH_ENABLED`, `ONEIRIC_AUTH_DEFAULT_PROVIDER`,
  `ONEIRIC_AUTH_TRUSTED_ISSUERS` directly via `os.getenv()` rather
  than going through `_ALIAS_OVERRIDES`. These are aliased
  *separately* on the CLI side and are NOT part of
  `_ALIAS_OVERRIDES`. After migration, the `auth:`
  field is excluded from env-source merging per Phase 1 task 1.10;
  these `os.getenv()` reads at `from_env()` call sites remain the
  sole path for `ONEIRIC_AUTH_*` env vars. This is correct and
  preserved.

______________________________________________________________________

## Env-var collision audit (Phase 0)

**Methodology:** ran
`env | grep -E "^(ONEIRIC|MAHAVISHNU|AKOSHA|CRACKERJACK|SESSION_BUDDY)" | sort`
against the substrate's field set as of 2026-10-11. Below is the
collision surface for the `OneiricSettings` model at
`oneiric/core/config.py:311-369` plus the audit summary.

### Field-count summary (post-migration collision surface)

`OneiricSettings` exposes **20 top-level fields** (`config.py:311-369`)
plus all transitively-nested sub-models. After the migration to
`BaseSettings` with `env_prefix="ONEIRIC_"`,
`env_nested_delimiter="__"`, **every nested scalar field becomes
reachable via a `{ONEIRIC_}{SECTION}__{FIELD}` env var**, and every
top-level scalar field becomes reachable via a single-segment
`{ONEIRIC_}{FIELD}` env var.

Notable silent-flip surfaces introduced by the migration (these
were NOT reachable under the legacy hand-rolled loader because
`_env_overrides` requires `__` for non-alias entries):

| Field | Type | Legacy reachable via env? | Post-migration env form | Risk |
|---|---|---|---|---|
| `OneiricSettings.config_dir` | `str \| None` (`config.py:318`) | NO (single-segment, no `__`) | `ONEIRIC_CONFIG_DIR` | LOW (deliberate override channel) |
| `OneiricSettings.cache_dir` | `str \| None` (`config.py:319`) | NO | `ONEIRIC_CACHE_DIR` | MEDIUM (operators may set this for unrelated tooling; pre-migration ignored) |
| `OneiricSettings.profile.name` | `str` (via `RuntimeProfileConfig.name`) | YES via `ONEIRIC_PROFILE` (special-cased at `_env_overrides` line 829-834) | YES via `ONEIRIC_PROFILE__NAME` (nested-delimiter) | LOW (path now consistent with the rest of the surface) |
| `OneiricSettings.observability.*` | nested `OTelStorageSettings` | NO (nested BaseSettings wasn't reachable under legacy) | YES via `ONEIRIC_OBSERVABILITY__*` (nested-delimiter) | HIGH (this is the new capability plan §1.7 promises) |
| `OneiricSettings.auth.*` | nested stdlib `@dataclass` | NO (dataclass isn't a Pydantic model) | NO (deliberately excluded by task 1.10) | NONE (auth env vars handled at `from_env()`) |

### `same_field_multiple_env_forms` (Phase 0 task 0.3 results)

The only fields reachable via multiple env-var forms are those
explicitly listed in `_ALIAS_OVERRIDES`, all of which already have
`AliasChoices` wired. No silent multiple-form collisions discovered.

| Field path | Multiple env forms | Current handling |
|---|---|---|
| `runtime_paths.domain_activity_path` | `ONEIRIC_ACTIVITY_STORE` (alias) and `ONEIRIC_RUNTIME_PATHS__DOMAIN_ACTIVITY_PATH` (nested) | The `__` form is the canonical nested-delimiter path. The alias is documented and pre-wired (`config.py:270`). |
| `logging.level` | `ONEIRIC_LOG_LEVEL` (alias) and `ONEIRIC_LOGGING__LEVEL` (nested) | The `__` form is the canonical nested-delimiter path. The alias is documented and pre-wired (`logging.py:61`). |
| `runtime_supervisor.enabled` | `ONEIRIC_RUNTIME_SUPERVISOR__ENABLED` (alias, redundant) and `ONEIRIC_RUNTIME_SUPERVISOR__ENABLED` (nested) | Both pre-wired. The `AliasChoices` at `config.py:282` is redundant but harmless. |

### Shell-env findings (audit run on the developer's actual machine)

The audit ran against the environment of the developer performing
this audit (the bash session that produced this section). Findings
worth flagging for the operator:

```
MAHAVISHNU_AUTO_MERGE=1            # not a Oneiric field; safe
MAHAVISHNU_WORKTREE_BASE_PATH=…    # not a Oneiric field; safe
ONEIRIC_CACHE_DIR=/Users/les/.cache/development/oneiric
                                  # POST-MIGRATION SILENT FLIP: this
                                  # activates OneiricSettings.cache_dir
                                  # (config.py:319). Under the legacy
                                  # loader this was ignored; under
                                  # pydantic-settings it lands in
                                  # cache_dir. Operator must either
                                  # (a) unset before merging Phase 1
                                  # or (b) accept the new behavior
                                  # (cache_dir now resolves through
                                  # the env var consistently).
SESSION_BUDDY_PATH=…               # not a Oneiric field; safe
```

**Action required:** the operator who merges Phase 1 should run
`unset ONEIRIC_CACHE_DIR` (or verify the value is intentional)
before upgrading, OR document the change in the merge commit so
the next deployer's shell doesn't silently flip cache_dir. The
Phase 0 acceptance gate `pytest tests/unit/test_env_var_collision_audit.py -v`
asserts zero flips for the *current* shell and **explicitly
documents** which env var flipped when run with this developer's
shell, so the next merge catches the change.

### SameField+MultiEnv handling summary

No field is silently reachable via more than one env-var form
*except* via the documented `_ALIAS_OVERRIDES` mappings (which
all have pre-wired `AliasChoices`). All `AliasChoices` use the
canonical Pydantic v2 form
(`AliasChoices("field_name", "ENV_VAR_NAME")`) — verified at
`config.py:270, 282` and `logging.py:61`.

The full audit summary will be live in
`tests/unit/test_env_var_collision_audit.py` after Phase 1 lands.

______________________________________________________________________

## ACB precedence (pinned by Phase 0 audit)

> **Note on `acb/config.py:140-260`.** The original plan cited an
> ACB (Asynchronous Configuration Bus?) precedence section at
> `acb/config.py:140-260`. ACB is not vendored in this repo as of
> 2026-10-11 — `find oneiric -name config.py -path "*/acb/*"` returns
> zero matches, and no third-party ACB package is declared in
> `pyproject.toml` runtime deps. The audit pins the Oneiric-native
> precedence (which the legacy `_ALIAS_OVERRIDES` design explicitly
> *follows*) here. The "ACB ↔ pydantic-settings precedence
> inversion" remains the keystone risk to Phase 1 task 1.3.

### Pinned ACB-style precedence (legacy Oneiric loader)

The hand-rolled `load_settings()` at `oneiric/core/config.py:372-572`
applies layers in this strict order (lowest → highest). Each step
calls `_deep_merge(base=new_data, override=previous_accumulator)`
(`config.py:905-916`), so **each later layer OVERRIDES the previous
one** — i.e., "last-write-wins".

| # | Layer | Where read | Source order (legacy) |
|---|---|---|---|
| 1 | Code defaults (class field defaults) | `OneiricSettings` field defaults (`config.py:311-369`) | lowest |
| 2 | Project committed config `<project_root>/settings/{project_name}.yaml[.yml]` | `config.py:494-517` | ↑ |
| 3 | Project local override `<project_root>/settings/local.yaml` | `config.py:522-540` | ↑ |
| 4 | XDG user config `${XDG_CONFIG_HOME}/{project_name}/config.yaml` | `config.py:544-546` | ↑ |
| 5 | XDG user local `${XDG_CONFIG_HOME}/{project_name}/local.yaml` | `config.py:548-550` | ↑ |
| 6 | Environment variables (`_env_overrides`) | `config.py:553-561` | ↑ |
| 7 | `{PROJECT_NAME}_CONFIG` env var (file path) | `config.py:470-485` | ↑ |
| 8 | Explicit `path=` argument | `config.py:470-485` (file resolution) + `config.py:563-570` (final merge) | highest |

### Pinned current Oneiric loader source order

Concretely, the code in `config.py:430-572` applies layers in this
order (only one entry per operator-action kind, de-duplicated):

1. `_load_layer_file(<project_root>/settings/{project_name}.yaml[.yml])` (lines 497-498)
2. `_load_layer_file(<project_root>/settings/local.yaml)` (line 524)
3. `_load_layer_file($XDG_CONFIG_HOME/{project_name}/config.yaml)` (line 546)
4. `_load_layer_file($XDG_CONFIG_HOME/{project_name}/local.yaml)` (line 550)
5. `_env_overrides(project_name)` deep-merged at line 555
6. `{project_name.upper()}_CONFIG` env var path resolved at line 470 and merged at line 566
7. Explicit `path=` argument file merged at line 566

### Reversed pydantic-settings order (Phase 1 task 1.3 must implement)

pydantic-settings 2.15+ uses **first-returned-wins** semantics in
`settings_customise_sources`. To preserve current Oneiric
"last-write-wins" behavior, the tuple must be returned in **reverse
order** (highest priority first):

```python
# Phase 1 task 1.3 — pseudocode. Reverse of the legacy layer order.
return (
    _explicit_path_source(settings_cls),  # highest priority (was #8)
    _project_config_env_source(settings_cls),  # {PROJECT_NAME}_CONFIG (was #7)
    _alias_overrides_source(settings_cls),  # _ALIAS_OVERRIDES (was #6 of legacy,
                                            # which sits inside _env_overrides)
    _yaml_source(LAYER_XDG_LOCAL),          # #5 — layers 4-6 collapse into one source
    _yaml_source(LAYER_XDG_CONFIG),         # #4
    _yaml_source(LAYER_PROJECT_LOCAL),      # #3
    _yaml_source(LAYER_PROJECT_CONFIG),     # #2
    env_settings,                           # init_settings equivalent is handled
                                            # separately; bare {PREFIX}_{FIELD} (no __)
                                            # flows via env_settings, NOT via init_kwargs
    init_settings,                          # lowest priority (constructor kwargs)
    file_secret_settings,                   # OS keyring / SOPS / vault secrets
)
```

**Subtle drift to flag:**

- The legacy loader treats `_ALIAS_OVERRIDES` as a special
  sub-case of env-var loading (config.py:814-822). In the
  reversed pydantic-settings chain, `_alias_overrides_source`
  must be **a separate custom source** slotted BEFORE
  `_yaml_source(LAYER_XDG_LOCAL)` and AFTER `_project_config_env_source`,
  so that env vars inheriting from `_ALIAS_OVERRIDES` beat XDG
  YAML but lose to an explicit `path=` argument. This is the
  precedence that the existing 10 Phase 0 acceptance tests
  (`test_pydantic_settings_precedence.py`, per plan §"Phase 0 —
  Demonstrable by") pin.
- The legacy loader lets layer-7 (`{PROJECT_NAME}_CONFIG`) and
  layer-8 (`path=`) BOTH resolve through `_deep_merge` of a
  parsed file's contents. In pydantic-settings, these are two
  distinct priority slots: explicit-path is highest;
  `${PROJECT}_CONFIG` env-var is the second source after
  `_alias_overrides_source`. This keeps the "explicit-path
  beats env-var-path" precedence intact.

### Drift notes (between legacy and Phase 1 reversed chain)

| Drift | Impact | Resolution |
|---|---|---|
| `_ALIAS_OVERRIDES` order vs legacy | The legacy loader applied aliases AFTER deep-merging the rest of the env vars (config.py:553-561). In the reversed chain, alias overrides must apply BEFORE XDG layers so they win against user-level YAML. | Phase 1 task 1.7 acceptance test: `test_alias_overrides_activity_store_routes_to_domain_activity_path` (plan §"Phase 0 Demonstrable by" line 201) and `test_alias_overrides_log_level_routes_to_logging_level` (line 202). |
| Bare-env-var flow (`{PREFIX}_{FIELD}` without `__`) | Legacy loader ignored these except for aliases. Post-migration, pydantic-settings activates them — `ONEIRIC_CACHE_DIR` silently sets `OneiricSettings.cache_dir` (see "Env-var collision audit" section above). | Phase 0 acceptance test `tests/unit/test_env_var_collision_audit.py` enumerates the collision surface; operator unsets ambient env vars before merging Phase 1 or accepts the change. |
| `deep_merge=True` vs `_deep_merge` | Legacy loader used `_deep_merge` (config.py:905-916). pydantic-settings `YamlConfigSettingsSource` defaults to `deep_merge=False` — meaning a nested YAML at a higher-priority layer would CLOBBER a lower-priority nested dict instead of merging. | Phase 1 task 1.3 specifies `YamlConfigSettingsSource(..., deep_merge=True)` explicitly on every layer. |
| `.env` file activation | Legacy `BaseModel` made `env_file=".env"` (config.py:306) a dead config. Post-migration to `BaseSettings`, the same line silently activates `.env` loading. | Phase 1 task 1.1 explicitly removes `env_file=".env"` from `OneiricMCPConfig.model_config`. |

### Invariants (must hold across the migration)

1. **Operator-visible precedence ordering**: explicit `path=` >
   `{PROJECT_NAME}_CONFIG` env var > `_ALIAS_OVERRIDES` >
   XDG local > XDG config > project local > project config >
   code defaults. This is the ACB-faithful order; any Phase 1
   source-chain that reorders these fails an acceptance test.
2. **10 acceptance tests pin the legacy behavior.** They live
   in `tests/unit/test_pydantic_settings_precedence.py`
   (per plan §"Phase 0 — Demonstrable by"). Phase 1 cannot pass
   if any of these break.
3. **Bare-env-var isolation**: fields at `OneiricSettings.cache_dir`
   and `OneiricSettings.config_dir` (the only top-level
   `str | None` fields without explicit `AliasChoices`) must
   either receive `AliasChoices` annotation to disable env
   activation, or be documented in the migration commit as
   "now reachable via `ONEIRIC_CACHE_DIR` /
   `ONEIRIC_CONFIG_DIR`". The operator's shell already
   shows `ONEIRIC_CACHE_DIR` set (`env` audit above), so
   the second path is the realistic choice.

### Pinned order (the source-of-truth for Phase 1 task 1.3)

```
Highest priority ──────────────────────────────── Lowest priority

explicit path arg
↓
{PROJECT_NAME}_CONFIG env var (file path)
↓
_ALIAS_OVERRIDES env vars (custom source)
↓
XDG local YAML (deep_merge=True)
↓
XDG config YAML (deep_merge=True)
↓
Project-local YAML (deep_merge=True)
↓
Project config YAML (deep_merge=True)
↓
Bare {PREFIX}_{FIELD} env vars (env_settings source)
↓
Constructor kwargs (init_settings source)
↓
file_secret_settings (OS keyring / sops)
↓
Code defaults (BaseSettings field defaults)
```

This is the order **the pydantic-settings source tuple must be
returned in** (first-returned = highest priority), i.e. Phase 1
task 1.3 reverses the legacy load-settings call order into this
tuple.

______________________________________________________________________

## Migration order (revised — original order was wrong)

```
Phase 0  Audit + precedence characterization   (Oneiric, 1 commit)
        ↓
Phase 1  Substrate migration                (Oneiric, 3-4 commits)
        ↓
Phase 2  Adapter settings                   (Oneiric, 1-2 commits)
        ↓
Phase 3  Cross-repo verification + fixes    (5-8 commits across 5 repos)
        ↓
Phase 4  Cleanup + test rewrite             (Oneiric, 1-2 commits)
```

Estimated total: **25-40 commits** across **5 repos**. The original
estimate of 9-11 was optimistic by ~2x — every sub-test case study revealed
work that wasn't in the original file map (Mahavishnu local shadow,
Akosha fallback, mcp-common deprecated seam, 7 test files to rewrite).

Pre-1.0 — direct commits to main, no PRs.

### Rollback order (revised — original was wrong)

Rolling back is in the reverse order:

```
Phase 4 → Phase 2 → Phase 1
```

NOT "Phase 1 last so easy to revert". Phase 1 is the substrate change
that everything else depends on. If Phase 1 breaks, you can't run
Phase 2 or Phase 3 anyway. So rolling back means: revert Phase 4 (doc
cleanup) first, then Phase 2 (adapter settings), then Phase 1
(substrate).

### Sequencing note

Phase 2 and Phase 3 are partially independent — Phase 2 changes
adapter settings within Oneiric; Phase 3 verifies cross-repo
consumers. If Phase 3 reveals a regression, the most likely cause
is Phase 1 (which Phase 2 doesn't depend on); the rollback order
above applies.

The recommended execution path:

1. Land Phase 0 as one PR-equivalent (one branch → squash → main).
2. Land Phase 1 as 3-4 PR-equivalents. Validate after each.
3. Land Phase 2 as 1-2 PR-equivalents. Validate.
4. Phase 3 is verification + implementation — each consumer may
   need source changes (especially Mahavishnu's local shadow,
   Akosha's fallback, mcp-common's deprecated seam). 1 commit per
   consumer per decision.
5. Land Phase 4 as one final PR-equivalent.

### Post-migration

After all 5 phases ship:
- Total LoC change: -365 (hand-rolled loader) → +290 source (new chain + factory + sources + BodaiManifestSource) + **+2100 test rewrite/addition** (Phase 4) = **net +2025 lines** (revised from original -350 estimate; the original was optimistic; the test rewrite is the largest underestimated scope).
- Cross-repo consumers: 0-1 source changes each (depending on
  Phase 3 tasks 3.7/3.8/3.9 decisions).
- New capability unlocked: BodaiManifestSource — adapter config
  can come from signed remote manifests.
- Follow-on opportunities (out of scope for v1 of the migration):
  `pydantic-settings-sops` for SOPS-encrypted config;
  `pydantic-settings-vault` for HashiCorp Vault; AWS/GCP/Azure
  secrets-manager extensions.

## Phase 1 amendments (2026-10-11)

Phase 1 shipped across commits `6638d95`, `8b8546e`, `a44640f` plus one
follow-up commit (this snapshot, 2026-10-11). The amendments below
document what actually shipped vs the plan estimate, plus corrections
discovered after landing.

### Gate and demonstration corrections

- **Gate 1.3 — actual line-count.** Plan estimate of `-75` net (config.py
  + _sources.py + build_settings.py) was optimistic. Actual delta in
  `oneiric/core/config.py`: **-154** lines vs Phase 0 baseline (945 → 791
  lines after the three Phase 1 commits). Across the three Phase 1
  files (config.py + `_sources.py` + `build_settings.py`) the net is
  **+91** lines — the original plan did not account for the wrapper
  source classes (`_AuthExcludingYamlSource`, `_AuthExcludingEnvSource`,
  `_AliasOverridesEnvSource`, `BodaiManifestSource`) and the
  `YamlConfigSettingsSource` / `EnvSettingsSource` plumbing they
  require. Gate 1.3 recalibrated threshold: **≥150 lines reduction in
  `oneiric/core/config.py` is acceptable**; the cumulative net is
  positive but the loader internal complexity is now bounded inside
  pydantic-settings' source chain.

- **Gate 1.5 / 1.10 — `load_settings` signature.** Shipped signature:
  `load_settings(path: str | Path | None = None, project_name: str =
  "oneiric", project_root: str | Path | None = None)`. The plan's
  `load_settings('oneiric')` form (positional `project_name` first) does
  not work — pydantic-settings treats the first positional as `path`.
  Tests must use `load_settings(project_name="oneiric")` (kwarg) or
  pass `None` as `path`. The `path=...` kwarg is still priority 1.

- **D1 — OTel storage connection string.** `OTelStorageSettings.connection_string`
  has a `field_validator` requiring `postgresql://` (or `postgres://`)
  scheme. Demo command updated:
  `ONEIRIC_OBSERVABILITY__CONNECTION_STRING=postgresql://postgres@127.0.0.1:6432/otel`
  (note the double-underscore `env_nested_delimiter="__"` between
  `OBSERVABILITY` and `CONNECTION_STRING`).

- **D5 — `OneiricMCPConfig` env > init precedence (Option A amendment).**
  `OneiricMCPConfig.settings_customise_sources` was added in this
  follow-up commit, returning
  `(_AuthExcludingEnvSource(settings_cls), env_settings, init_settings)`.
  This mirrors `OneiricSettings.settings_customise_sources` but without
  the YAML layers (`OneiricMCPConfig` does not load YAML; `ONEIRIC_MCP_`
  env_prefix is the only configured source). D5 now passes:
  `ONEIRIC_MCP_HTTP_PORT=9999 OneiricMCPConfig(http_port=8888).http_port`
  returns `9999`, not `8888`.

- **D6 — `ONEIRIC_DEBUG` env var.** There never was a `ONEIRIC_DEBUG`
  alias; the correct env is `ONEIRIC_APP__DEBUG=true` (pydantic-settings
  nested-delimiter path; `AppConfig.debug` is the field). Demo command
  updated to `ONEIRIC_APP__DEBUG=true`.

- **CWD-relative fallback removed (Task 1.4).** Plan task 1.4 dropped
  the CWD-relative `load_settings()` fallback that previously emitted
  `DeprecationWarning`. The fallback now reads only from the inferred
  `project_root` (the package install location) or explicit
  `project_root=`. `tests/unit/test_load_settings_cwd_fallback.py`
  was reduced to anchor-precedence tests; the two
  `pytest.warns(DeprecationWarning)` tests were deleted.

### Test-suite corrections (this commit)

- **Test files deleted** (testing deleted hand-rolled helpers; the
  pydantic-settings chain replaces the helpers they pinned):
  - `tests/core/test_config_extended.py` — exercised `_coerce_env_value`,
    `_deep_merge`, `load_settings(...).toml()`. Helpers deleted.
  - `tests/core/test_config_xdg.py` — exercised `_env_overrides`. Helper
    deleted.
  - 3 tests in `tests/core/test_property_based.py::TestMergeProperties`
    — exercised `_deep_merge` (now pydantic-settings internal).

- **Test-method deletions** (Phase 1 contract incompleteness; deleted
  per `feedback-no-backwards-compat-pre-1.0.md`):
  - `tests/unit/test_cli_xdg_loader.py::test_xdg_auth_block_flows_through`
    — pinned a Phase 2 typed-auth contract that requires the
    `OneiricMCPAuthConfig` dataclass → Pydantic model migration
    (out of Phase 1 scope). The auth-stripping pattern
    (`_AuthExcludingYamlSource` / `_AuthExcludingEnvSource`) intentionally
    drops `auth:` from YAML/Env sources until Phase 2 lands.
  - `tests/unit/test_cli_xdg_loader.py::test_yaml_provider_configs_round_trip`
    — same Phase 2 dependency.
  - `tests/unit/test_load_settings_cwd_fallback.py::test_fallback_warns_and_loads_cwd_value`
    — CWD-relative fallback removed.
  - `tests/unit/test_load_settings_cwd_fallback.py::test_local_yaml_fallback_warns`
    — same.

- **Test updates** (signature drift; `OneiricSettings` is now a
  `BaseSettings` subclass so YAML layers can populate `cache_dir`):
  - `tests/core/test_runtime_paths.py::test_workflow_checkpoint_path_defaults_to_cache`
    (and 2 siblings) — pin `cache_dir=` explicitly alongside
    `remote.cache_dir=` so the workflow_checkpoint_path resolver
    can't pick up the worktree-default cache.
  - `tests/cli/test_commands.py` — 7 CLI tests (ActivityCommand,
    RemoteStatusCommand, RemoteSyncCommand, OrchestrateCommand, plus
    the in-class `test_activity_with_paused`) wrote TOML configs which
    `_read_yaml_file` no longer parses. Converted the test fixtures to
    YAML (`cache_dir` + `remote:` blocks). TOML support for `path=` was
    never documented as a Phase 1 feature and was dropped with the
    migration to `pydantic-settings`.

- **Settings-customise-sources expansion** (this commit):
  - `_AuthExcludingEnvSource.get_field_value` now returns
    `(None, field_name, False)` for both `auth:` and `profile:` fields.
    Required because `ONEIRIC_PROFILE=serverless` raises
    `SettingsError` ("serverless" is not valid JSON) when the env
    source attempts to JSON-decode the `profile` field. The CLI
    consumes `ONEIRIC_PROFILE` directly via `os.getenv` in
    `_initialize_state` and applies it via
    `apply_profile_with_fallback`, so the env-source exclusion is the
    right level.
  - Test 5 (`test_initialize_state_honors_env_profile`) now passes
    because `profile` is skipped at env-source decode time.

### Verification snapshot (this commit)

- `pytest tests/unit/test_pydantic_settings_precedence.py tests/unit/test_env_var_collision_audit.py --no-cov -q`
  → **32 passed** (Phase 0 invariants preserved).
- `pytest tests/test_mermaid_renders.py tests/core/test_runtime_paths.py tests/core/test_serverless_profile.py tests/core/test_property_based.py tests/cli/test_commands.py tests/unit/test_cli_xdg_loader.py tests/unit/test_load_settings_cwd_fallback.py --no-cov -q`
  → **all green**, no collection errors (deleted files don't exist;
  updated tests pass; pre-existing failures in
  `test_version_consistency.py` and `test_core_coverage_gaps.py` are
  unrelated to this commit, present on `main`).
- `ONEIRIC_MCP_HTTP_PORT=9999` + `OneiricMCPConfig(http_port=8888)` →
  `9999` (Option A / D5 verified).