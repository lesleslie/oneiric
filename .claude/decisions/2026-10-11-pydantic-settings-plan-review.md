# 5-agent ensemble review of pydantic-settings migration plan

**Date:** 2026-10-11
**Status:** recorded
**Topic:** oneiric-config
**Subject plan:** `docs/plans/2026-10-11-pydantic-settings-migration.md`

## Context

The plan at `docs/plans/2026-10-11-pydantic-settings-migration.md` was
written in v1 to migrate Oneiric's hand-rolled settings loader onto
`pydantic-settings.BaseSettings`. The user asked for a **4-agent
ensemble review** plus **1 random generalist agent** — the standard
multi-agent-review-catches-blind-spots routine from the Mahavishnu
trunk-based agent-review workflow.

The five lenses were:

1. **oneiric-substrate** — knows the Oneiric-specific patterns (XDG, ACB
   legacy, project_root anchoring, the `__` nested-key convention).
2. **python-idioms** — Python 3.14 stdlib, Pydantic v2, type-system
   best-practices, `from __future__ import annotations` discipline.
3. **mcp-integration** — knows mcp-common's `OneiricMCPConfig` re-export
   shape, the FastMCP server lifecycle, MCP tool surface stability.
4. **process-discipline** — Bodai pre-1.0 merge policy, integration
   contract gates, audit-orphans wiring check, validation gates.
5. **general-purpose** — random generalist for non-domain blind spots.

This decision note records the findings (v1 review), the 17 issues
caught, the corrections land in v2, and the **3 follow-up BLOCKERs**
caught by the 2-agent v3 review that landed in v3.

## The 5 lenses — what each one caught

| Lens | Caught issues | Examples |
|---|---|---|
| oneiric-substrate | ACB precedence inversion, `_ALIAS_OVERRIDES` regression, `.env` activation regression, XDG anchoring to project_root, `OneiricSettings.auth` dataclass collision | Issue #2, #5, #7 (substrate-level) |
| python-idioms | `from __future__ import annotations` placement, `BaseModel` vs `BaseSettings` semantics, `validation_alias` redundancy, `Any` escape patterns | Issue #3, #8, #14 |
| mcp-integration | Mahavishnu's local `OneiricMCPConfig(BaseModel)` shadow, mcp-common's `MCPBaseSettings` deprecated seam, `OneiricMCPAuthConfig.from_env()` double-apply risk | Issue #11, #12, #13 |
| process-discipline | Integration-contract gates (originally empty!), validation gates with no command, deprecation-window violation under pre-1.0 policy | Issue #15, #16 |
| general-purpose | Silent env-var flip risk (e.g. `ONEIRIC_CACHE_DIR` after migration), Pre-1.0 merge policy alignment, commit-count optimism, `create_async()` is a phantom method | Issue #6, #9, #10 |

## Findings table — the 17 issues caught by the v1 review

For each: the lens that caught it, severity (BLOCKER / HIGH / MEDIUM
/ LOW), the v1 claim, the corrected claim, and how v2 addresses it.

| # | Lens | Severity | v1 claim | Corrected claim | v2 resolution |
|---|---|---|---|---|---|
| 1 | oneiric-substrate | BLOCKER | "Phase 1 deliverables: 9-11 commits across 5 phases" | Realistic count: 25-40 commits (7 test files to rewrite, Phase 3 cross-repo work per consumer) | v2 plan §"Migration order" updated to 25-40; §"Estimated total" line corrected |
| 2 | oneiric-substrate | BLOCKER | ACB source order (YAML > env > aliases) — implied, never pinned | pydantic-settings is "first-returned-wins"; ACB-style is "last-write-wins". The phases-1 chain must reverse order | v2 plan §"Phase 1 Tasks" task 1.3 specifies the reversed tuple; v3 plan adds the explicit "ACB precedence" section |
| 3 | python-idioms | BLOCKER | `MahavishnuSettings extends OneiricMCPConfig` | `MahavishnuSettings extends BaseSettings` directly (`mahavishnu/core/config.py:2689`); `OneiricMCPConfig` is a nested field at `mahavishnu/core/config.py:2984` | v2 plan §"Class relationship" documents the correction; explicit errata note at lines 69-83 |
| 4 | python-idioms | BLOCKER | `BaseSettings` inherits from `BaseModel` so behavior is automatic | Both work the same for `model_validate` / `model_dump`; only env-var activation differs | v2 plan spells out the differential explicitly; v3 test gates pin behavior |
| 5 | oneiric-substrate | HIGH | `auth: OneiricMCPAuthConfig` flows through pydantic-settings normally | `OneiricMCPAuthConfig` is a stdlib `@dataclass` (`oneiric/mcp/config.py:60-65`), NOT a Pydantic model. pydantic-settings can't decorate it; env-source merging would crash on nested-delimiter dispatch | v2 plan §"Phase 1 Tasks" task 1.10 specifies the `_AuthExcludingYamlSource` wrapper + document-the-choice for the migration commit |
| 6 | general-purpose | HIGH | "Env-var loading silently activates; verify no flips" | Specific flip surface: bare `{PREFIX}_{FIELD}` (no `__`) now flows. `ONEIRIC_CACHE_DIR` flips `OneiricSettings.cache_dir` silently | v2 plan adds "Env-var collision audit" requirement; v3 plan pins the audit results |
| 7 | oneiric-substrate | HIGH | `.env` loading was dead config on BaseModel — fine to keep | Substrate changes to `BaseSettings` activate `env_file=".env"` (`oneiric/core/config.py:306`) — creates a `.env` file lookup that the legacy code never did | v2 plan §"Phase 1 Tasks" task 1.1 explicitly removes `env_file=".env"` |
| 8 | python-idioms | HIGH | `OneiricSettings: BaseModel` → `BaseSettings` — single-line semantic swap | Pydantic v2 + `from __future__` + nested `BaseSettings` is a sharp edge (`OTelStorageSettings` inside `OneiricSettings`); verified by Phase 0 acceptance test | v2 plan §"Phase 1 Tasks" task 1.2 adds `arbitrary_types_allowed=True` + task 1.3 documents test coverage for the nested case |
| 9 | general-purpose | MEDIUM | `settings.create_async()` exists | `create_async()` is a phantom method in pydantic-settings 2.15+ — only `model_validate({...})` exists | v2 plan drops the `create_async` reference |
| 10 | general-purpose | MEDIUM | Pre-1.0 policy: "deprecation window then delete" | Pre-1.0 policy (`feedback-no-backwards-compat-pre-1.0.md`): direct commit to main, no deprecation window | v2 plan §"Tech Stack" lines 28 call out the pre-1.0 direct commit to main; no backwards-compat rewiring |
| 11 | mcp-integration | MEDIUM | Mahavishnu consumes OneiricSettings via `from oneiric.core.config import load_settings` — straightforward | Mahavishnu has a *local* re-declaration of `OneiricMCPConfig(BaseModel)` at `mahavishnu/core/config.py:1817` that diverges post-migration unless explicitly handled | v2 plan §"Phase 3 Tasks" task 3.7 makes the decision task explicit |
| 12 | mcp-integration | MEDIUM | mcp-common re-exports the substrate's `OneiricMCPConfig` — unchanged | Re-export site at `mcp_common/fastmcp/__init__.py:31` works after migration; the seam exists in mcp-common's `MCPBaseSettings` (`mcp-common/config/base.py:34-45`) too | v2 plan §"Phase 3 Tasks" task 3.9 makes the seam decision explicit |
| 13 | mcp-integration | MEDIUM | `OneiricMCPAuthConfig.from_env()` continues to work — documented but not gated | Post-migration, env-source merging could double-apply env vars that `from_env()` also reads | v2 plan §"Phase 1 Tasks" task 1.10 excludes `auth:` from env-source merging |
| 14 | python-idioms | LOW | `validation_alias=AliasChoices("level", "ONEIRIC_LOG_LEVEL")` on `LoggingConfig.level` is a duplicate | Confirmed duplicate (logging.py:61); both `_ALIAS_OVERRIDES["LOG_LEVEL"]` (config.py:804) and `AliasChoices` cover `logging.level`. Pre-wired correct | v2 plan §"Phase 0 Tasks" task 0.1 documents this is the migration acceptance; no change needed |
| 15 | process-discipline | BLOCKER | "Phase 1 — Validation gates" is mostly empty in v1 | Phase 1 has 10+ tests that must pass; v1 left them as comments | v2 plan §"Phase 1 — Validation gates" lists 10 numbered gates |
| 16 | process-discipline | HIGH | "Phase 0 — Validation gates" exits on Plan-then-Execute | Plan's Phase 0 gates test against CURRENT hand-rolled loader — exercises legacy behavior; v1 missed this | v2 plan §"Phase 0 — Validation gates" pins 4 numbered gates |
| 17 | python-idioms | MEDIUM | "Phase 1 env-var name typo `MAHAVISHNU_AUTH__JWT_SECRET`" — note only | The field is `secret` not `jwt_secret` (verify at `mahavishnu/core/config.py` around line 2689) | v2 plan §"Phase 3 — Integration Contract" corrects the env-var name throughout; §"Phase 3 Tasks" task 3.1 fixes the example |

## The 3 follow-up BLOCKERs caught by the 2-agent v3 review

After v2 was committed, a **2-agent v3 review** (oneiric-substrate +
process-discipline) caught three issues the original 5-agent review
missed:

### v3-BLOCKER-1: ACB source-order inversion still under-specified in v2

**v2 state:** §"Phase 1 Tasks" task 1.3 listed the reversed tuple but
didn't explicitly document that pydantic-settings is "first returned =
highest priority" (the opposite of ACB-style "last-write-wins").

**v3 fix:** v3 plan adds an explicit "ACB precedence (pinned by Phase
0 audit)" section that:
- Confirms the ACB-style layered precedence (last-write-wins via
  `_deep_merge`)
- Confirms pydantic-settings 2.15+ semantics (first-returned-wins)
- Pins the reversed tuple order with file:line citations
- Lists the drift points between legacy and post-migration
- Asserts the 3 invariants that must hold across migration
- Cites where ACB precedence is documented (`acb/config.py:140-260`
  is not vendored locally — the audit pins the Oneiric-native
  precedence instead)

### v3-BLOCKER-2: `OneiricMCPAuthConfig` `@dataclass` collision with `BaseSettings`

**v2 state:** §"Phase 1 — Tasks" task 1.10 documented the
`_AuthExcludingYamlSource` wrapper but missed that **on the v2 read,
the `@dataclass` already imports cleanly into the `OneiricSettings.auth`
field via `Field(...)`** because of the lazy import in
`_default_auth_config()` (oneiric/core/config.py:57-83). The risk:
once `OneiricSettings` extends `BaseSettings`, pydantic-settings
recursively tries to read env vars for every nested field — and
fails on a `@dataclass` because it's not a Pydantic model.

**v3 fix:** v3 plan task 1.10 splits into two sub-decisions:
1. **Default (in-scope):** exclude `auth:` from env-source merging
   via the wrapper source. Document in commit message.
2. **Optional (out-of-scope):** convert `OneiricMCPAuthConfig` from
   `@dataclass` to `BaseSettings` with `env_prefix="ONEIRIC_AUTH_"`.
   This would make the exclusion unnecessary. Document the design
   choice in the commit message; do NOT convert in v1 of the
   migration (`feedback-no-backwards-compat-pre-1.0.md`).

### v3-BLOCKER-3: `.env` activation regression

**v2 state:** §"Phase 1 — Tasks" task 1.1 already noted the `.env`
file activation but did not specifically gate the line removal.
Without a gate, the task could be marked complete while leaving
`env_file=".env"` on the model_config.

**v3 fix:** v3 plan adds a Phase 1 validation gate **1.2** that
runs `grep -rn "env_file=" oneiric/core/config.py` and asserts zero
matches. The gate is non-bypassable; if the search hits, Phase 1
is incomplete.

## Decisions made in v2 / v3 revisions that resolved each issue

| Issue | v2 / v3 decision |
|---|---|
| #1 commit-count optimism | v2 plan §"Migration order" updates the count to 25-40 |
| #2 ACB precedence inversion | v3 plan adds the "ACB precedence" section pinning the reversed tuple |
| #3 OneiricMCPConfig inheritance | v2 plan §"Class relationship" correction note (lines 69-83); MahavishnuSettings declared `extends BaseSettings` directly |
| #4 BaseModel vs BaseSettings semantic swap | v2 plan spells out the differential; v3 plan verifies via acceptance test |
| #5 OneiricMCPAuthConfig dataclass | v2 plan task 1.10 + v3 plan split into "default (in-scope)" and "optional (out-of-scope)" |
| #6 silent env-var flip | v2 plan adds env-var collision audit; v3 plan pins the results (the `ONEIRIC_CACHE_DIR` finding) |
| #7 .env activation regression | v2 plan task 1.1 removes `env_file`; v3 plan adds gate 1.2 (`grep -rn "env_file="` returns zero) |
| #8 nested BaseSettings sharp edge | v2 plan task 1.2 (arbitrary_types_allowed) + test coverage for `OTelStorageSettings` |
| #9 phantom create_async | v2 plan drops the reference |
| #10 pre-1.0 no deprecation | v2 plan §"Tech Stack" calls out direct commit to main |
| #11 Mahavishnu local OneiricMCPConfig shadow | v2 plan task 3.7 makes the decision explicit |
| #12 mcp-common MCPBaseSettings seam | v2 plan task 3.9 makes the decision explicit |
| #13 OneiricMCPAuthConfig.from_env() double-apply | v2 plan task 1.10 wraps env-source merging |
| #14 AliasChoices duplicates | v2 plan task 0.1 confirms no change needed |
| #15 Phase 1 gates empty | v2 plan adds 10 numbered gates |
| #16 Phase 0 gates too thin | v2 plan adds 4 numbered gates |
| #17 MAHAVISHNU_AUTH__JWT_SECRET typo | v2 plan corrects env-var names throughout |

## Open follow-ups for the migration to track

1. **`acb/config.py:140-260` does not exist locally.** If a vendored
   ACB library is added (or the historical import path is restored),
   re-pin the "ACB precedence" section against the actual source
   rather than the Oneiric-native precedence currently cited.

2. **`ONEIRIC_CACHE_DIR` shell-state warning.** The audit found
   `ONEIRIC_CACHE_DIR=/Users/les/.cache/development/oneiric` set
   in the developer's shell. Post-migration this activates
   `OneiricSettings.cache_dir`. Operator action: either unset before
   merging Phase 1 or accept the new behavior. Document in merge
   commit either way.

3. **`AuthExcludingYamlSource` may need to handle nested
   `DotEnvSettingsSource`** in addition to `EnvSettingsSource` and
   `YamlConfigSettingsSource`. The v3 task 1.10 lists the YAML and
   env variants but the `.env` file source may also need wrapping
   if Phase 1 re-enables `.env` activation anywhere else.

4. **Mahavishnu's local `OneiricMCPConfig(BaseModel)` shadow**
   (`mahavishnu/core/config.py:1817`) — Phase 3 task 3.7 keeps the
   split by default. Revisit if mcp-common migrates `MCPBaseSettings`
   post-migration (task 3.9); the seam may collapse naturally.

5. **7 test files to rewrite.** Phase 4 file map at plan §"File
   map (revised)" lists `test_load_settings_cwd_fallback.py`,
   `test_load_settings_xdg.py`, `test_load_settings_anchors.py`,
   `test_cli_xdg_loader.py`, `test_config_xdg.py`,
   `test_core_config_branches.py`, `test_core_config.py`. The
   v3 Phase 4 task 4.7 adds 8 new tests (none are rewrites).

6. **Realistic total: 25-40 commits** (revised from v1's 9-11).
   Tracker should not mark migration complete until all phases
   ship.

7. **Phase 0 audit results land in this decision note's amended
   plan.** The amended plan at the path above has the three new
   sections ("_ALIAS_OVERRIDES audit (Phase 0)", "Env-var collision
   audit (Phase 0)", "ACB precedence (pinned by Phase 0 audit)")
   inserted at lines 521, 569, 657 — BEFORE the "Migration order"
   section at line 812. Phase 1 task 1.3 reads these sections to
   know exactly what source-chain to build.

8. **Pre-1.0 policy reminder (`feedback-no-backwards-compat-pre-1.0.md`):**
   no deprecation windows, no backwards-compat rewiring. If a
   downstream consumer breaks on Phase 1, the consumer migrates
   or the migration is broken — there is no middle ground.
