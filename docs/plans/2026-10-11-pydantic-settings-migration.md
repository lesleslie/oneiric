---
status: draft
role: implementation
date: 2026-10-11
last_reviewed: 2026-10-11
superseded_by: null
blocks_on: []
topic: oneiric-config
---

# Oneiric pydantic-settings migration — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Date:** 2026-10-11
**Status:** <!-- legacy status: draft — moved to YAML frontmatter -->
**Role:** <!-- legacy role: implementation — moved to YAML frontmatter -->

**Goal:** Drop Oneiric's ~500-line hand-rolled settings loader and adopt `pydantic_settings.BaseSettings` natively across the substrate's config, every adapter settings class that needs env-var loading, and the five cross-repo consumers (mahavishnu, akosha, crackerjack, session-buddy, mcp-common). The substrate's config declaration (`env_prefix="ONEIRIC_"`, `env_nested_delimiter="__"`, `populate_by_name=True`) already follows pydantic-settings' idiom; this plan wires up the loader instead of re-implementing it.

**Architecture:** Four coordinated phases. Phase 1 migrates the substrate's two settings classes and replaces `load_settings()` with a `settings_customise_sources` chain. Phase 2 audits and migrates per-adapter settings (only those that need env vars). Phase 3 verifies each of the five cross-repo consumers works unchanged against the new substrate. Phase 4 cleans up the dead hand-rolled loader code and validates end-to-end. Each phase has its own Integration Contract (Triggered from, Returns to / updates, Demonstrable by, Rollback signal, Observability added).

**Tech Stack:** `pydantic_settings.BaseSettings` + `SettingsConfigDict`, `YamlConfigSettingsSource`, `EnvSettingsSource`, `SecretsSettingsSource` (built-ins), `pydantic-settings-sops` extension (optional, for SOPS-encrypted config). Pre-1.0: direct commit to main per `bodai-pre-1.0-merge-policy`.

**Adjacent ADRs / specs:**
- [`docs/adr/0003-pydantic-settings-migration.md`](../adr/0003-pydantic-settings-migration.md) — the decision this plan implements
- [`docs/specs/2026-10-11-adapter-contract-design.md`](../specs/2026-10-11-adapter-contract-design.md) §4 — adapter settings contract (BaseModel vs BaseSettings)
- [`.claude/decisions/2026-10-11-dhara-substrate-refs-cleanup.md`](../../.claude/decisions/2026-10-11-dhara-substrate-refs-cleanup.md) — prior substrate-decomposition cleanup (commit `cd282ba`)

______________________________________________________________________

## Why these changes

Investigation revealed:

1. **Oneiric already declares pydantic-settings' conventions** (`env_prefix`, `env_nested_delimiter`, `env_file`, `populate_by_name`) on `model_config` blocks but inherits from `BaseModel` — so the conventions are declared and the loader is not wired up (`oneiric/core/config.py:296-317`).

2. **The hand-rolled loader is dead weight.** ~500 lines of `load_settings()`, YAML parsing, layer-merging, and env-var interpolation in `oneiric/core/config.py`. Every feature it implements is now built-in to pydantic-settings (verified via context7 docs 2026-10-11).

3. **The "I assumed pydantic-settings didn't have what we need" rationale is fully obsolete.** YAML, secrets, env vars, nested delimiter — all built-in. SOPS, Vault, AWS/GCP/Azure secrets — all available as extensions.

4. **Cross-repo consumers will not break.** `MahavishnuSettings extends OneiricMCPConfig`; `load_settings(project_name="X")` returns the same fields. The factory preserves the `${XDG_CONFIG_HOME}/<project>/{config,local}.yaml` and `settings/<project>.yaml` layered semantics. Per-project env_prefix `${PROJECT}_*__*` is preserved via a `build_oneiric_settings(project_name)` factory.

5. **No migration window.** Pre-1.0, per project policy (`feedback-no-backwards-compat-pre-1.0.md`). The hand-rolled loader is removed in the same release the `BaseSettings` inheritance lands.

The unifying fix is small: change `BaseModel` → `BaseSettings` (5 lines), replace `load_settings()` body with a `settings_customise_sources` chain (~50 lines), add a `BodaiManifestSource` for remote-manifest-driven config (~30 lines), drop the hand-rolled YAML/env-vars helpers. Net: -500 lines, +150 lines.

______________________________________________________________________

## File map

### Phase 1 — Substrate (Oneiric)

| Path | Status | Phase | Notes |
|---|---|---|---|
| `oneiric/core/config.py` | rewrite | P1 | `OneiricSettings` + `OneiricMCPConfig` → `BaseSettings`; `load_settings()` → `settings_customise_sources` chain |
| `oneiric/core/config.py` (helpers) | delete | P1 | `load_yaml_*` helpers if any, manual layer-merge, manual env-var interpolation |
| `oneiric/adapters/_bodai_sources.py` | create | P1 | `BodaiManifestSource` — Oneiric-specific custom source for `oneiric remote-sync` |
| `oneiric/core/build_settings.py` | create | P1 | `build_oneiric_settings(project_name)` factory — returns a subclass with `env_prefix=f"{project_name.upper()}_"` |
| `oneiric/core/config.py::OneiricSettings.create_async()` | adapt | P1 | Keep the async factory wrapper; internals call `asyncio.to_thread(BaseSettings.__init__)` if pydantic-settings I/O needs to be non-blocking |

### Phase 2 — Adapter settings (within Oneiric)

| Path | Status | Phase | Needs env vars? |
|---|---|---|---|
| `oneiric/adapters/llm/anthropic.py::AnthropicLLMSettings` | migrate → `BaseSettings` | P2 | yes (model, base_url) |
| `oneiric/adapters/llm/openai.py::OpenAILLMSettings` | migrate → `BaseSettings` | P2 | yes (api_key, base_url) |
| `oneiric/adapters/embedding/openai.py::OpenAIEmbeddingSettings` | migrate → `BaseSettings` | P2 | yes (api_key) |
| `oneiric/adapters/vector/pgvector.py::PgvectorSettings` | migrate → `BaseSettings` | P2 | yes (connection_string) |
| `oneiric/adapters/vector/pinecone.py::PineconeSettings` | migrate → `BaseSettings` | P2 | yes (api_key, environment) |
| `oneiric/adapters/vector/qdrant.py::QdrantSettings` | migrate → `BaseSettings` | P2 | yes (url, api_key) |
| `oneiric/adapters/nosql/mongodb.py::MongoDBSettings` | migrate → `BaseSettings` | P2 | yes (connection_string) |
| `oneiric/adapters/nosql/firestore.py::FirestoreSettings` | migrate → `BaseSettings` | P2 | yes (credentials path) |
| `oneiric/adapters/nosql/dynamodb.py::DynamoDBSettings` | migrate → `BaseSettings` | P2 | yes (region, table) |
| `oneiric/adapters/observability/settings.py::OTelStorageSettings` | already `BaseSettings` | P2 | yes — keep as-is, verify env_prefix still resolves |
| `oneiric/adapters/llm/llm_interface.py::LLMBaseSettings` | migrate → `BaseSettings` | P2 | shared base |
| `oneiric/adapters/embedding/embedding_interface.py::EmbeddingBaseSettings` | migrate → `BaseSettings` | P2 | shared base |
| `oneiric/adapters/vector/vector_types.py::VectorBaseSettings` | migrate → `BaseSettings` | P2 | shared base |
| `oneiric/adapters/nosql/nosql_types.py::NoSQLBaseSettings` | migrate → `BaseSettings` | P2 | shared base |
| `oneiric/adapters/cache/*.py` | leave on `BaseModel` | P2 | no — config constructed explicitly |
| `oneiric/adapters/database/*.py` | leave on `BaseModel` | P2 | no — config constructed explicitly |
| `oneiric/adapters/secrets/*.py` | leave on `BaseModel` | P2 | no — config constructed explicitly |
| `oneiric/adapters/messaging/*.py` | leave on `BaseModel` | P2 | no — config constructed explicitly |
| `oneiric/adapters/monitoring/*.py` | leave on `BaseModel` | P2 | no — config constructed explicitly |
| `oneiric/adapters/identity/*.py` | leave on `BaseModel` | P2 | no — config constructed explicitly |
| `oneiric/adapters/file_transfer/*.py` | leave on `BaseModel` | P2 | no — config constructed explicitly |

### Phase 3 — Cross-repo consumers

| Path | Repo | Phase | Action |
|---|---|---|---|
| `mahavishnu/core/config.py::MahavishnuSettings` | mahavishnu | P3 | Verify `load_settings(project_name="mahavishnu")` returns the same fields after substrate migration. `extends OneiricMCPConfig` — inherits the new `BaseSettings` machinery automatically. |
| `akosha/<khaorg>/config.py` (or equivalent) | akosha | P3 | Verify `load_settings(project_name="akosha")`. |
| `crackerjack/<khaorg>/config.py` | crackerjack | P3 | Verify `load_settings(project_name="crackerjack")`. |
| `session-buddy/<khaorg>/config.py` | session-buddy | P3 | Verify `load_settings(project_name="session_buddy")`. |
| `mcp-common/src/<khaorg>/config.py::OneiricMCPConfig` | mcp-common | P3 | This is the source of truth for `OneiricMCPConfig`. Verify the migration didn't introduce a cycle. |

### Phase 4 — Cleanup

| Path | Action |
|---|---|
| `oneiric/core/config.py::load_settings` body | delete (replaced by `settings_customise_sources`) |
| Any `load_yaml_*` helpers in `oneiric/core/config.py` | delete |
| Manual layer-merge logic | delete |
| Manual env-var interpolation | delete |
| `tests/unit/test_load_settings.py` (if exists) | rewrite against `settings_customise_sources` |

______________________________________________________________________

## Phase 1 — Substrate migration

### Phase 1 — Integration Contract

**Triggered from:** ADR 0003 (`docs/adr/0003-pydantic-settings-migration.md`) active; spec update at `a191bed` clarifying §4 settings contract.

**Returns to / updates:**
- `oneiric.core.config.OneiricSettings` and `OneiricMCPConfig` — inherit from `BaseSettings`
- `oneiric.core.config.load_settings(project_name)` — preserved as a function, internals now call `build_oneiric_settings(project_name)().model_dump()` (or equivalent)
- `mcp__oneiric__*` MCP tools — unchanged surface
- `mcp-common.OneiricMCPConfig` — unchanged shape (re-exports the substrate's class)
- `MahavishnuSettings` and other downstream `extends OneiricMCPConfig` subclasses — work unchanged

**Demonstrable by:**
- `pytest tests/unit/test_config.py` passes (existing tests; should be 0 changes required if behavior preserved)
- `pytest tests/integration/test_oneiric_mcp_e2e.py` passes
- `ONEIRIC_OBSERVABILITY__CONNECTION_STRING=postgres://... python -c "from oneiric.core.config import load_settings; print(load_settings('test').observability.connection_string)"` prints the env value (the canonical pre-migration test)
- `MAHAVISHNU_AUTH__JWT_SECRET=foo python -c "from mahavishnu.core.config import load_settings; print(load_settings().auth.jwt_secret)"` prints `foo` (cross-repo env-var test)
- `${XDG_CONFIG_HOME}/<project>/local.yaml` overrides still beat `settings/<project>.yaml`

**Rollback signal:** env-var override precedence breaks (e.g., `${PROJECT}_*__*` no longer overrides YAML defaults); XDG layer discovery fails; `load_settings(project_name="X")` raises during construction.

**Observability added:** `oneiric.core.config.load_settings` logs the source chain that produced the final config (debug-level; lists each `YamlConfigSettingsSource` path that was loaded).

### Phase 1 — Tasks

- [ ] **1.1** In `oneiric/core/config.py:296`, change `class OneiricMCPConfig(BaseModel):` → `class OneiricMCPConfig(BaseSettings):`. No other change to that class — `model_config` block is already correct.
- [ ] **1.2** In `oneiric/core/config.py:311`, change `class OneiricSettings(BaseModel):` → `class OneiricSettings(BaseSettings):`. Same — `model_config` already correct.
- [ ] **1.3** Add `settings_customise_sources` classmethod to `OneiricSettings`. The chain is (in order): `init_settings` (defaults) → `YamlConfigSettingsSource(settings_cls, yaml_file=Path("settings/oneiric.yaml"))` → `YamlConfigSettingsSource(settings_cls, yaml_file=Path("settings/local.yaml"))` → `YamlConfigSettingsSource(settings_cls, yaml_file=xdg_config_path())` → `YamlConfigSettingsSource(settings_cls, yaml_file=xdg_local_path())` → `env_settings` → `file_secret_settings`.
- [ ] **1.4** Create `oneiric/core/build_settings.py` with `build_oneiric_settings(project_name: str) -> type[OneiricSettings]`. The factory returns a `_Project(OneiricSettings)` subclass with `model_config = SettingsConfigDict(env_prefix=f"{project_name.upper()}_", env_nested_delimiter="__", ...)`.
- [ ] **1.5** Update `load_settings(project_name)` to call `build_oneiric_settings(project_name)()`. Preserve the existing async signature and XDG path discovery behavior.
- [ ] **1.6** Delete hand-rolled `load_yaml_*` helpers and any other custom loader code from `oneiric/core/config.py` (~300-500 lines).
- [ ] **1.7** Add `oneiric/adapters/_bodai_sources.py` with `BodaiManifestSource(PydanticBaseSettingsSource)` — implements `get_field_value` + `__call__`, reads from `oneiric remote-sync` cache. Wire into `OneiricSettings.settings_customise_sources` when a manifest URL is configured.
- [ ] **1.8** Update `oneiric/core/config.py::OneiricSettings.create_async()` (if it exists) to use `asyncio.to_thread(OneiricSettings)` if any of the source I/O is blocking.
- [ ] **1.9** Add unit tests covering: per-project env_prefix (`SESSION_BUDDY_FOO=x` → `settings.foo`), XDG layer precedence, env override beats YAML, secrets dir support (if configured).
- [ ] **1.10** Add integration test in `tests/integration/test_oneiric_mcp_e2e.py` confirming `mcp__oneiric__*` tools work unchanged.

### Phase 1 — Validation gates

- [ ] `grep -rn "BaseSettings" oneiric/core/config.py` returns at least the 2 new import / class lines
- [ ] `grep -rn "load_yaml_" oneiric/core/config.py` returns zero matches
- [ ] `pytest tests/unit/test_config.py -v` passes
- [ ] `pytest tests/integration/test_oneiric_mcp_e2e.py -v` passes
- [ ] `python -c "from oneiric.core.config import load_settings; s = load_settings('oneiric'); print(s.observability.connection_string)"` with `ONEIRIC_OBSERVABILITY__CONNECTION_STRING=postgres://x` prints `postgres://x`

### Phase 1 — Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| Pydantic-settings precedence differs from ACB's hand-rolled merge semantics | Low | The 5-source chain (init → 4 YAML → env → secrets) matches ACB's documented precedence. Write the test in 1.9 against the documented behavior, not the observed one. |
| Async settings load blocks the event loop | Medium | `BaseSettings.__init__` is sync. Wrap with `asyncio.to_thread` if any source reads from disk. |
| `load_settings(project_name="X")` semantics diverge from pre-migration | Low | The `build_oneiric_settings` factory preserves `env_prefix` + `env_nested_delimiter`. Test 1.9 covers this. |

______________________________________________________________________

## Phase 2 — Adapter settings (within Oneiric)

### Phase 2 — Integration Contract

**Triggered from:** Phase 1 complete (`OneiricSettings` extends `BaseSettings`); spec §4 cross-link in place.

**Returns to / updates:**
- 4 shared base classes (`LLMBaseSettings`, `EmbeddingBaseSettings`, `VectorBaseSettings`, `NoSQLBaseSettings`) extend `BaseSettings`
- 9 concrete adapter settings (`AnthropicLLMSettings`, `OpenAILLMSettings`, `OpenAIEmbeddingSettings`, `PgvectorSettings`, `PineconeSettings`, `QdrantSettings`, `MongoDBSettings`, `FirestoreSettings`, `DynamoDBSettings`) inherit env-var loading via their shared base
- `OTelStorageSettings` — unchanged (already `BaseSettings`); verify env_prefix still resolves
- Cache / Database / Secrets / Messaging / Monitoring / Identity / File-transfer adapters — unchanged (`BaseModel` is correct for them)

**Demonstrable by:**
- `LLM_API_KEY=sk-xxx python -c "from oneiric.adapters.llm.openai import OpenAILLMSettings; print(OpenAILLMSettings().api_key)"` prints `sk-xxx`
- `ONEIRIC_OTEL_STORAGE__CONNECTION_STRING=postgres://x python -c "from oneiric.adapters.observability.settings import OTelStorageSettings; print(OTelStorageSettings().connection_string)"` prints `postgres://x`
- `pytest tests/adapters/test_vector_types.py tests/adapters/test_llm_interface.py tests/adapters/test_nosql_types.py tests/adapters/embedding/test_embedding_interface.py` pass
- Cache / Database settings still construct from explicit kwargs without env-var lookup

**Rollback signal:** any adapter fails its existing tests after migration (likely a precedence difference between manual `__init__` kwargs and pydantic-settings' source chain); env-var resolution fails for an adapter that previously worked.

**Observability added:** each `BaseSettings` subclass logs its source chain at debug level when first instantiated (pydantic-settings' standard hook).

### Phase 2 — Tasks

- [ ] **2.1** `oneiric/adapters/llm/llm_interface.py::LLMBaseSettings`: change `class LLMBaseSettings(BaseModel):` → `class LLMBaseSettings(BaseSettings):`. Add `model_config = SettingsConfigDict(env_prefix="LLM_", env_nested_delimiter="__", extra="allow", populate_by_name=True)`.
- [ ] **2.2** `oneiric/adapters/embedding/embedding_interface.py::EmbeddingBaseSettings`: same pattern with `env_prefix="EMBEDDING_"`.
- [ ] **2.3** `oneiric/adapters/vector/vector_types.py::VectorBaseSettings`: same with `env_prefix="VECTOR_"`.
- [ ] **2.4** `oneiric/adapters/nosql/nosql_types.py::NoSQLBaseSettings`: same with `env_prefix="NOSQL_"`.
- [ ] **2.5** Verify concrete adapter settings inherit env-var loading from their shared base: `AnthropicLLMSettings`, `OpenAILLMSettings`, `OpenAIEmbeddingSettings`, `PgvectorSettings`, `PineconeSettings`, `QdrantSettings`, `MongoDBSettings`, `FirestoreSettings`, `DynamoDBSettings` (no changes needed if the bases are correct).
- [ ] **2.6** Verify `OTelStorageSettings` still works (already `BaseSettings`; verify `env_prefix="ONEIRIC_OTEL_STORAGE_"` is preserved).
- [ ] **2.7** Update tests under `tests/adapters/` to either keep the existing `BaseModel`-style test (if env vars are not asserted) or add new env-var tests.
- [ ] **2.8** Run the full `pytest tests/adapters/` to verify no regressions.

### Phase 2 — Validation gates

- [ ] `grep -rn "BaseSettings)" oneiric/adapters/` returns ≥ 4 matches (the 4 shared bases)
- [ ] `pytest tests/adapters/ -v` passes
- [ ] `LLM_API_KEY=x python -c "from oneiric.adapters.llm.openai import OpenAILLMSettings; print(OpenAILLMSettings().api_key)"` prints `x`

### Phase 2 — Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| A shared base's `env_prefix` collides with a concrete adapter's `env_prefix` | Low | Pydantic-settings precedence: nearest-in-MRO wins. Concrete adapters extend shared bases — set `env_prefix` only on the shared base. |
| Tests rely on kwargs-only construction (not env vars); migrate to `BaseSettings` breaks them | Medium | Pydantic-settings falls back to constructor kwargs when env vars are absent. Document this in the test PR. |

______________________________________________________________________

## Phase 3 — Cross-repo consumer verification

### Phase 3 — Integration Contract

**Triggered from:** Phase 1 + Phase 2 complete.

**Returns to / updates:**
- `mahavishnu.core.config.load_settings(project_name="mahavishnu")` returns the same fields as pre-migration
- `akosha.<khaorg>.config.load_settings(project_name="akosha")` — same
- `crackerjack.<khaorg>.config.load_settings(project_name="crackerjack")` — same
- `session-buddy.<khaorg>.config.load_settings(project_name="session_buddy")` — same
- `mcp-common.OneiricMCPConfig` — unchanged shape; same `model_config`; same field set

**Demonstrable by:** the existing test suite in each of the 5 repos passes (Mahavishnu, Akosha, Crackerjack, Session-Buddy, mcp-common).

**Rollback signal:** any of the 5 cross-repo test suites fails on a config-load path; env-var override precedence changes for any downstream consumer.

**Observability added:** each cross-repo `load_settings` logs the source chain at debug level; same shape as Phase 1.

### Phase 3 — Tasks

- [ ] **3.1** `mahavishnu`: `mahavishnu/core/config.py::load_settings(project_name="mahavishnu")` — run the existing test suite. Verify `MahavishnuSettings.auth.jwt_secret` is settable via `MAHAVISHNU_AUTH__JWT_SECRET=...`.
- [ ] **3.2** `akosha`: same pattern with `load_settings(project_name="akosha")`.
- [ ] **3.3** `crackerjack`: same with `load_settings(project_name="crackerjack")`.
- [ ] **3.4** `session-buddy`: same with `load_settings(project_name="session_buddy")`.
- [ ] **3.5** `mcp-common`: verify `OneiricMCPConfig` works in isolation (it's the source of truth that the substrate's `OneiricSettings` and the cross-repo `extends` relationships all derive from).
- [ ] **3.6** Document each consumer's verified env-var names in `docs/adr/0003-pydantic-settings-migration.md` § Validation as evidence the migration is correct.

### Phase 3 — Validation gates

- [ ] All 5 repos' existing test suites pass without source changes (other than pulling in the migrated Oneiric substrate)
- [ ] Per-project env-prefix tests pass in each of the 5 repos (set `MAHAVISHNU_*`, `AKOSHA_*`, etc. and verify the value flows through)

### Phase 3 — Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| A cross-repo consumer relies on a hand-rolled loader internal that's now removed | Medium | The substrate's `load_settings` is the only public API; no consumer should reach into internals. Verify with grep: `grep -rn "load_yaml\|layer_merge\|env_override" <repo>/` should return zero. |
| A consumer sets env vars with a different convention (e.g., `MAHAVISHNU_FOO` not `MAHAVISHNU_FOO__BAR`) | Low | The `env_nested_delimiter="__"` is preserved. Single-segment env vars work as before. |
| `OneiricMCPConfig` extends `BaseSettings` breaks the cross-repo `mcp-common` consumer that expected `BaseModel` semantics | Low | `BaseSettings` IS a `BaseModel` (it extends it). All existing `BaseModel` semantics still work; only env-var loading is added. |

______________________________________________________________________

## Phase 4 — Cleanup + validation

### Phase 4 — Integration Contract

**Triggered from:** Phase 3 complete; all 5 cross-repo consumers verified.

**Returns to / updates:**
- `oneiric/core/config.py` loses the hand-rolled loader code (~300-500 lines deleted)
- `oneiric/adapters/__init__.py` exports `build_oneiric_settings` if helpful (not required)
- `oneiric/adapters/_bodai_sources.py::BodaiManifestSource` is documented as a public extension point

**Demonstrable by:** `wc -l oneiric/core/config.py` shows a net reduction; `grep -rn "load_yaml\|manual.*layer\|manual.*env.*override" oneiric/` returns zero matches; full Oneiric test suite passes; full cross-repo test suite passes.

**Rollback signal:** a hand-rolled loader feature is needed in a future feature (unlikely — pydantic-settings covers everything).

**Observability added:** none beyond Phase 1's debug-level source-chain log.

### Phase 4 — Tasks

- [ ] **4.1** Delete hand-rolled `load_yaml_*` helpers from `oneiric/core/config.py` (if any survived Phase 1).
- [ ] **4.2** Delete any `extra="allow"` flattening logic that's no longer needed (pydantic-settings' nested-delimiter handles it natively).
- [ ] **4.3** Update `docs/architecture/MEMORY_ARCHITECTURE.md` to reflect: Oneiric's settings are now `BaseSettings`-based (per ADR 0003), the 6-layer merge is via `settings_customise_sources`, the hand-rolled loader is gone.
- [ ] **4.4** Update `oneiric/README.md` to point at ADR 0003 + the migration plan.
- [ ] **4.5** Run the full Oneiric + cross-repo test suite one more time; confirm `git grep "hand.rolled.*loader"` returns zero in docs and code.

### Phase 4 — Validation gates

- [ ] `wc -l oneiric/core/config.py` reduced from pre-migration baseline
- [ ] `grep -rn "load_yaml\|extra=.allow. storage" oneiric/` returns zero
- [ ] `pytest tests/` (full Oneiric suite) passes
- [ ] Cross-repo suite (Phase 3 commands) passes

______________________________________________________________________

## Migration order (final)

```
Phase 1 (substrate)        ─→  Phase 2 (adapter settings)  ─→  Phase 3 (cross-repo verify)  ─→  Phase 4 (cleanup)
[2-3 commits, Oneiric]            [1-2 commits, Oneiric]            [5 commits, one per repo]            [1 commit, Oneiric]
```

Estimated total: **9-11 commits** across **5 repos**. Pre-1.0 — direct commits to main, no PRs.

### Sequencing note

Phase 2 and Phase 3 are independent — Phase 2 changes adapter settings within Oneiric; Phase 3 verifies the cross-repo consumers. If Phase 3 reveals a regression, Phase 2 is easy to revert (its commits are within Oneiric). If Phase 4 reveals a hand-rolled-loader feature was needed, that's a separate ADR (likely none — pydantic-settings covers all known needs).

The recommended execution path:

1. Land Phase 1 as one PR-equivalent (one branch → squash → main). Validate.
2. Land Phase 2 as one PR-equivalent. Validate.
3. Phase 3 is verification, not implementation — run the 5 consumer tests against the migrated substrate. If any fails, fix in that consumer's repo.
4. Land Phase 4 as one final PR-equivalent.

### Post-migration

After all 4 phases ship:
- Total LoC change: -500 (hand-rolled loader), +150 (settings_customise_sources + BodaiManifestSource + tests). Net -350 lines.
- Cross-repo consumers: zero source changes required (verified by Phase 3).
- New capability unlocked: BodaiManifestSource — adapter config can come from signed remote manifests.
- Follow-on opportunities (out of scope): `pydantic-settings-sops` for SOPS-encrypted config; `pydantic-settings-vault` for HashiCorp Vault; AWS/GCP/Azure secrets-manager extensions.