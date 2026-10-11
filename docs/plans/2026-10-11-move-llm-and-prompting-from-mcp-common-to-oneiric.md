---
title: Move LLM and Prompting Subsystems from mcp-common to oneiric
description: Hard break. Delete `mcp_common/llm/` and `mcp_common/prompting/` entirely. Move the LLM subsystem into the existing `oneiric/adapters/llm/` package; create new `oneiric/adapters/prompt/` and `oneiric/adapters/video/` packages for the prompt and HailuoAdapter code. Update direct consumers in session-buddy and crackerjack in lockstep. No backward-compat shims per pre-1.0 policy.
audience: oneiric maintainer + mcp-common maintainer + session-buddy + crackerjack
created: 2026-10-11
status: active
role: implementation
topic: adapter-registry
date: 2026-10-11
last_reviewed: 2026-10-11
superseded_by: null
blocks_on: []
---

# Move LLM and Prompting Subsystems from mcp-common to oneiric

## Brief (intent-driven)

### Goal

The `mcp-common` package stops shipping LLM/prompting/video code. That code lives in `oneiric.adapters.{llm,prompt,video}` instead — the natural home for foundation-level adapters that any Python project (not just MCP servers) can depend on. mcp-common is left as a thin MCP-server foundation library (settings bases, FastMCP re-exports, MCP-specific glue, prompts backend bridge).

### Constraints

1. **Hard break.** Per `feedback-no-backwards-compat-pre-1.0.md` — no re-export shims, no `DeprecationWarning`, no deprecation windows. Delete the source, update consumers in lockstep, ship.
2. **Pre-1.0 — direct merge to `main`**, no PR, per `feedback-bodai-pre-1.0-merge-policy.md`. Apply per-repo within the same worktree cycle; each repo lands on its own `main` push (user-controlled per `feedback-bodai-push-is-user-controlled.md`).
3. **`oneiric` already ships `httpx2>=0.28.1` as a hard dep** (5 occurrences in `pyproject.toml`: lines 306, 351, 364, 367, 400). The HailuoAdapter's `httpx2` requirement does not add weight to oneiric.
4. **Existing `oneiric/adapters/llm/` subpackage** is the natural home for the LLM-flavored code being moved. Do not invent a parallel `adapters/llm_providers` namespace; extend the existing one.
5. **New packages `adapters/prompt/` and `adapters/video/`** are created in oneiric. They follow the same shape as the existing `adapters/llm/`, `adapters/storage/`, `adapters/secrets/` etc. (each gets an `__init__.py` and a `protocol.py` if the family needs an abstract base).
6. **Oneiric's adapter catalog (`OneiricAdapterRegistry`)** updates its `factory_path` strings for the moved classes. The migration is registered against `domain:key:provider` triples consistent with ADR 0002's adapter contract.
7. **No version bump in any `pyproject.toml`** — per `feedback-mcp-common-version-bump-is-user.md`, the user does all version bumps.
8. **This plan must coordinate with the in-flight `BodaiAdapter` Protocol session** (the protocol session is extracting a fleet-wide adapter Protocol). Confirm shape alignment before Phase 3 starts; the moved classes are expected to satisfy whatever structural shape lands.

### Failure Conditions (verifier-only)

1. `mcp_common/llm/` and `mcp_common/prompting/` directories do not exist after the change.
2. `mcp_common/llm/` had 8 files (`__init__.py`, `_security.py`, `config.py`, `exceptions.py`, `fallback.py`, `hailuo.py`, `provider.py`, `types.py`); none remain.
3. `mcp_common/prompting/` had 6 files (`__init__.py`, `adapter.py`, `base.py`, `factory.py`, `models.py`, `exceptions.py`); none remain. (`MIGRATION.md` and `README.md` may be deleted or moved to `oneiric/docs/`; the user's call — see Phase 5.)
4. `oneiric/adapters/video/hailuo.py` exists with the moved `HailuoAdapter` class (verify by class name and import path).
5. `oneiric/adapters/prompt/` exists with at minimum: `__init__.py`, `adapter.py` (PromptAdapter), `base.py` (PromptBackend), `factory.py` (create_prompt_adapter), `models.py` (PromptAdapterSettings), `exceptions.py` (BackendUnavailableError).
6. `oneiric/adapters/llm/` contains the moved LLM code: `fallback.py` (FallbackChain), `config.py` (LLMSettings, ProviderConfig), `exceptions.py` (LLMError), `provider.py`, `types.py` (TaskType), `_security.py`. (No `hailuo.py` here — it moves to `adapters/video/`.)
7. `git grep -nE "from mcp_common.llm\|from mcp_common.prompting" -- '*.py'` returns zero matches across the fleet (mahavishnu, akosha, session-buddy, crackerjack, oneiric, mcp-common).
8. `oneiric/adapters/video/hailuo.HailuoAdapter`, `oneiric/adapters/llm.fallback.FallbackChain`, `oneiric/adapters/llm.config.LLMSettings`, `oneiric/adapters/llm.config.ProviderConfig`, `oneiric/adapters/prompt.adapter.PromptAdapter`, `oneiric/adapters/prompt.base.PromptBackend`, `oneiric/adapters/prompt.factory.create_prompt_adapter`, `oneiric/adapters/prompt.models.PromptAdapterSettings` — all import cleanly.
9. The `OneiricAdapterRegistry` registrations for these classes use the new factory paths (`oneiric.adapters.video.hailuo.HailuoAdapter`, `oneiric.adapters.prompt.adapter.PromptAdapter`, `oneiric.adapters.llm.fallback.FallbackChain`).
10. `pytest tests/` in each affected repo exits 0 after the consumer updates.
11. The pre-existing `mcp_common/backends/toolkit.py:19` (`from mcp_common.prompting.base import PromptBackend`) is updated to `from oneiric.adapters.prompt.base import PromptBackend` and continues to work.

## Context

### Why move (decisions behind this plan)

- mcp-common's LLM subsystem is already past the MCP boundary: `session-buddy/session_buddy/llm_providers.py:10` and `crackerjack/crackerjack/adapters/ai/unified.py:8-9` both import from `mcp_common.llm`. Hosting LLM utilities in an MCP-specific package is a historical accident, not a deliberate boundary.
- The `BodaiAdapter` Protocol session (in flight in another session) wants fleet-wide adapter discovery. The natural catalog for non-MCP-flavored adapters is oneiric's `OneiricAdapterRegistry`; that registry already accepts `domain:key:provider` triples and `metadata.category` filters, so the moved adapters register under `domain="video"`, `domain="prompt"`, and `domain="llm"`.
- Oneiric already has the shape: `adapters/llm/` subpackage exists; new `adapters/video/` and `adapters/prompt/` subpackages slot in alongside it.
- `httpx2` is already a hard dep of oneiric — moving `HailuoAdapter` adds zero dep weight.
- Per `feedback-no-backwards-compat-pre-1.0.md`, the policy is "replace not extend" — a clean break is the right call.

### Inventory of what's moving

**From `mcp_common/llm/`:**

| File | Class / function | New location |
|---|---|---|
| `__init__.py` | re-exports | `oneiric/adapters/llm/__init__.py` (re-exports updated) |
| `_security.py` | security helper | `oneiric/adapters/llm/_security.py` |
| `config.py` | `LLMSettings`, `ProviderConfig` | `oneiric/adapters/llm/config.py` |
| `exceptions.py` | `LLMError` | `oneiric/adapters/llm/exceptions.py` |
| `fallback.py` | `FallbackChain` | `oneiric/adapters/llm/fallback.py` |
| `hailuo.py` | `HailuoAdapter` | **`oneiric/adapters/video/hailuo.py`** (different family) |
| `provider.py` | generic provider | `oneiric/adapters/llm/provider.py` |
| `types.py` | `TaskType` etc. | `oneiric/adapters/llm/types.py` |

**From `mcp_common/prompting/`:**

| File | Class / function | New location |
|---|---|---|
| `__init__.py` | re-exports | `oneiric/adapters/prompt/__init__.py` (re-exports updated) |
| `adapter.py` | `PromptAdapter` | `oneiric/adapters/prompt/adapter.py` |
| `base.py` | `PromptBackend` | `oneiric/adapters/prompt/base.py` |
| `factory.py` | `create_prompt_adapter`, `list_available_backends` | `oneiric/adapters/prompt/factory.py` |
| `models.py` | `PromptAdapterSettings`, `NotificationLevel`, `DialogResult` | `oneiric/adapters/prompt/models.py` |
| `exceptions.py` | `BackendUnavailableError` etc. | `oneiric/adapters/prompt/exceptions.py` |
| `MIGRATION.md` | historical mcp-common migration notes | **drop** (this plan is the migration) |
| `README.md` | package README | **move to `oneiric/docs/legacy/mcp-common-prompting-README.md`** with a redirect note in `oneiric/adapters/prompt/__init__.py` docstring |

### Current consumers (must update in lockstep)

`git grep -rn "from mcp_common.llm\|from mcp_common.prompting" -- '*.py'` found these:

- `session-buddy/session_buddy/llm_providers.py:10` — `from mcp_common.llm import FallbackChain, LLMSettings`
- `crackerjack/crackerjack/adapters/ai/unified.py:8` — `from mcp_common.llm import FallbackChain`
- `crackerjack/crackerjack/adapters/ai/unified.py:9` — `from mcp_common.llm.config import LLMSettings, ProviderConfig`
- `crackerjack/tests/adapters/test_provider_chain.py:66` — `from mcp_common.llm import FallbackChain`
- `mcp-common/mcp_common/backends/toolkit.py:19` — `from mcp_common.prompting.base import PromptBackend`

### Coordination with the in-flight `BodaiAdapter` Protocol session

That session is extracting a fleet-wide adapter Protocol (one per category) — `BodaiAdapter` shape: `name`, `capabilities`, `init`, `health_check`, `execute`, `shutdown`. If it lands before this plan, the moved classes must satisfy the protocol's structural shape. The decision rule:

- **`HailuoAdapter`**: currently standalone (not extending any base). Confirm it satisfies the protocol via duck typing; if not, add the missing methods before Phase 1.
- **`PromptAdapter`**: also standalone; same check.
- **`FallbackChain`**: standalone; same check.
- **`LLMSettings` / `PromptAdapterSettings`**: settings classes, not adapters. They're dependencies of the adapter classes, not adapters themselves — no conformance check needed.

If the protocol session hasn't landed, the classes still move; conformance can be added in a follow-up.

## Approach

Five phases. Each phase ends with the consumer-side smoke test for the affected repo: `uv sync` then `pytest tests/` for the consumer, `crackerjack run` for crackerjack, and `python -c "import oneiric.adapters.video.hailuo"` for oneiric.

### Phase 1 — Move the LLM code to `oneiric.adapters.llm`

**New files in `oneiric/`:**
- `oneiric/adapters/llm/_security.py` ← moved from `mcp_common/llm/_security.py`
- `oneiric/adapters/llm/config.py` ← moved from `mcp_common/llm/config.py`
- `oneiric/adapters/llm/exceptions.py` ← moved from `mcp_common/llm/exceptions.py`
- `oneiric/adapters/llm/fallback.py` ← moved from `mcp_common/llm/fallback.py`
- `oneiric/adapters/llm/provider.py` ← moved from `mcp_common/llm/provider.py`
- `oneiric/adapters/llm/types.py` ← moved from `mcp_common/llm/types.py`
- `oneiric/adapters/llm/__init__.py` ← updated to re-export from same-package modules (no longer re-exporting from `mcp_common`)

**Edit:** each moved file's internal imports. `mcp_common.llm.fallback` and others may have intra-package imports; those become relative imports (e.g., `from .exceptions import LLMError` instead of `from mcp_common.llm.exceptions import LLMError`).

**Files deleted in `mcp-common/`:**
- `mcp_common/llm/_security.py`
- `mcp_common/llm/config.py`
- `mcp_common/llm/exceptions.py`
- `mcp_common/llm/fallback.py`
- `mcp_common/llm/provider.py`
- `mcp_common/llm/types.py`
- `mcp_common/llm/__init__.py`

**Integration Contract:**
- Triggered from: this plan (manual edits)
- Returns to / updates: `oneiric/adapters/llm/` (added 6 files, updated 1), `mcp_common/llm/` (deleted 7 files)
- Demonstrable by: `uv run python -c "import oneiric.adapters.llm; from oneiric.adapters.llm import FallbackChain, LLMSettings, ProviderConfig, LLMError, TaskType"` exits 0; `uv run python -c "import mcp_common.llm"` raises `ModuleNotFoundError`
- Rollback signal: any consumer (session-buddy, crackerjack) fails to import `FallbackChain` / `LLMSettings`
- Observability added: none

### Phase 2 — Move `HailuoAdapter` to `oneiric.adapters.video`

**New files in `oneiric/`:**
- `oneiric/adapters/video/__init__.py` — package marker, re-exports `HailuoAdapter`
- `oneiric/adapters/video/hailuo.py` ← moved from `mcp_common/llm/hailuo.py`, with internal imports updated to absolute paths into the new `oneiric.adapters.llm` package (`from oneiric.adapters.llm.exceptions import LLMError` instead of `from mcp_common.llm.exceptions import LLMError`)

**Files deleted in `mcp-common/`:**
- `mcp_common/llm/hailuo.py` (the last file in `mcp_common/llm/`)

**At end of this phase, `mcp_common/llm/` does not exist as a directory.**

**Integration Contract:**
- Triggered from: Phase 1 complete
- Returns to / updates: `oneiric/adapters/video/` (new), `mcp_common/llm/hailuo.py` (deleted)
- Demonstrable by: `uv run python -c "from oneiric.adapters.video.hailuo import HailuoAdapter"` exits 0; `ls mcp_common/llm/` returns "No such file or directory"
- Rollback signal: any consumer fails to import `HailuoAdapter`
- Observability added: none

### Phase 3 — Move the prompting subsystem to `oneiric.adapters.prompt`

**New files in `oneiric/`:**
- `oneiric/adapters/prompt/__init__.py` — package marker, re-exports `PromptAdapter`, `PromptBackend`, `create_prompt_adapter`, `PromptAdapterSettings`, etc.
- `oneiric/adapters/prompt/adapter.py` ← moved from `mcp_common/prompting/adapter.py`
- `oneiric/adapters/prompt/base.py` ← moved from `mcp_common/prompting/base.py`
- `oneiric/adapters/prompt/factory.py` ← moved from `mcp_common/prompting/factory.py`
- `oneiric/adapters/prompt/models.py` ← moved from `mcp_common/prompting/models.py`
- `oneiric/adapters/prompt/exceptions.py` ← moved from `mcp_common/prompting/exceptions.py`

**Edit:** each moved file's internal imports (e.g., `from mcp_common.prompting.exceptions import BackendUnavailableError` → `from .exceptions import BackendUnavailableError`).

**Files deleted in `mcp-common/`:**
- `mcp_common/prompting/adapter.py`
- `mcp_common/prompting/base.py`
- `mcp_common/prompting/factory.py`
- `mcp_common/prompting/models.py`
- `mcp_common/prompting/exceptions.py`
- `mcp_common/prompting/__init__.py`

**Decision: `mcp_common/prompting/MIGRATION.md` and `README.md`?** Per hard-break, drop both — they describe the mcp-common state, which no longer exists. The historical content is preserved in git history. If desired, copy `README.md` content to `oneiric/docs/legacy/mcp-common-prompting-README.md` and add a redirect note in `oneiric/adapters/prompt/__init__.py` docstring. (The user's call; flag in Phase 5 for the explicit decision.)

**Integration Contract:**
- Triggered from: Phase 2 complete
- Returns to / updates: `oneiric/adapters/prompt/` (new), `mcp_common/prompting/` (deleted)
- Demonstrable by: `uv run python -c "from oneiric.adapters.prompt.adapter import PromptAdapter; from oneiric.adapters.prompt.base import PromptBackend; from oneiric.adapters.prompt.factory import create_prompt_adapter; from oneiric.adapters.prompt.models import PromptAdapterSettings"` exits 0; `ls mcp_common/prompting/` returns "No such file or directory"
- Rollback signal: any consumer fails to import from the new locations; `mcp_common/backends/toolkit.py:19` still references the old path
- Observability added: none

### Phase 4 — Update consumers in lockstep

**Edit:**
- `session-buddy/session_buddy/llm_providers.py:10` — `from mcp_common.llm import FallbackChain, LLMSettings` → `from oneiric.adapters.llm import FallbackChain, LLMSettings`
- `crackerjack/crackerjack/adapters/ai/unified.py:8` — same swap
- `crackerjack/crackerjack/adapters/ai/unified.py:9` — `from mcp_common.llm.config import LLMSettings, ProviderConfig` → `from oneiric.adapters.llm.config import LLMSettings, ProviderConfig`
- `crackerjack/tests/adapters/test_provider_chain.py:66` — same as crackerjack/unified
- `mcp-common/mcp_common/backends/toolkit.py:19` — `from mcp_common.prompting.base import PromptBackend` → `from oneiric.adapters.prompt.base import PromptBackend`

**Run after edits:** `git grep -nE "from mcp_common.llm|from mcp_common.prompting" -- '*.py'` across the fleet. Must return zero matches.

**Edit oneiric catalog registrations (if any exist):** The pre-existing oneiric catalog may have registrations for these classes under the old factory paths. Audit by:
```bash
find /Users/les/oneiric -name "*.yaml" -o -name "*.json" 2>/dev/null | xargs grep -l "mcp_common.llm\|mcp_common.prompting" 2>/dev/null
```
Update any matches to the new factory paths.

**Integration Contract:**
- Triggered from: Phases 1-3 complete (all the moved code is in place; consumers just need to point at the new locations)
- Returns to / updates: 4 import sites (session-buddy, crackerjack x2, mcp-common/backends/toolkit.py) + 1 test site (crackerjack test) + any oneiric catalog registrations
- Demonstrable by: `git grep -nE "from mcp_common.llm|from mcp_common.prompting" -- '*.py'` returns zero; `pytest tests/` exits 0 in session-buddy, crackerjack, oneiric, mcp-common
- Rollback signal: any consumer test suite fails after the import swap
- Observability added: none

### Phase 5 — Docs cleanup + final validation

**Decision point (raised to the user):** `mcp_common/prompting/MIGRATION.md` and `mcp_common/prompting/README.md` — drop or archive? The hard-break policy says drop, but the README might contain user-facing examples worth preserving. Default to drop (git history retains the content). Override if there's reason to keep.

**Files to delete in mcp-common:** (if not already deleted in earlier phases)
- `mcp_common/prompting/MIGRATION.md`
- `mcp_common/prompting/README.md`

**Edit:** `oneiric/CLAUDE.md` or `oneiric/docs/README.md` — add a one-line note under the adapters section: "`oneiric.adapters.{llm,prompt,video}` host foundation-level adapters; mcp-common no longer ships concrete adapters."

**Final validation across all affected repos:**
- `uv sync` in oneiric, mcp-common, session-buddy, crackerjack
- `pytest tests/` in each — exits 0
- `python -c "import oneiric.adapters.video.hailuo; import oneiric.adapters.prompt.adapter; import oneiric.adapters.llm.fallback; from oneiric.adapters.llm import FallbackChain, LLMSettings"` exits 0
- `python -c "import mcp_common.llm; import mcp_common.prompting"` raises `ModuleNotFoundError`
- `crackerjack run` on `crackerjack/` — exits 0
- `session-buddy` MCP server starts and serves healthcheck

**Integration Contract:**
- Triggered from: Phase 4 complete
- Returns to / updates: `mcp-common/` (final deletion of stray files), `oneiric/CLAUDE.md` (one-line note)
- Demonstrable by: all of the above checks pass
- Rollback signal: any check fails
- Observability added: none

## Resolved decisions

1. **Hard break, no shims.** The user explicitly said "we don't care about backwards compat or legacy support". No re-export shims, no `DeprecationWarning`, no deprecation windows.
2. **`HailuoAdapter` lands in `adapters/video/`, not `adapters/llm/`.** The user said "adapters.video and adapters.prompt" — video is a distinct category from llm. LLM subsystem is provider-routing/general; video is media generation. Different families.
3. **The rest of `mcp_common/llm/` lands in the existing `adapters/llm/`.** It already exists; extending it is the natural home for provider routing, settings, and the LLMError exception.
4. **All of `mcp_common/prompting/` lands in new `adapters/prompt/`.** Single package; no split between abstract base and concrete adapter.
5. **No ADR change.** ADR 0002 (Oneiric Adapter Contract) is canonical and unaffected by this move — the contract is about shape, not location. The moved classes must satisfy ADR 0002's conformance requirements; that's a separate concern.
6. **No `pyproject.toml` version bumps.** Per `feedback-mcp-common-version-bump-is-user.md`. The user does all version bumps.
7. **No spec doc.** This is a code-move; the design (where video and prompt categories live in oneiric) is implicit in the package layout. If the user wants an explicit design doc, write one as a follow-up.
8. **Drop `MIGRATION.md` and `README.md`** from the old `mcp_common/prompting/` location. Hard break; git history retains the content. User can override in Phase 5 if they want them preserved.

## Risks

1. **Hidden consumers of `mcp_common.llm` / `mcp_common.prompting`.** The grep found 5 known sites. There may be others in fleet repos I haven't audited (e.g., `akosha`, `mahavishnu`). Mitigation: re-grep across `/Users/les/Projects/{mahavishnu,akosha,session-buddy,crackerjack,oneiric,mcp-common}` before Phase 4 completes. Any missed consumer breaks at import time, which is loud but disruptive.
2. **Circular imports between `oneiric.adapters.llm` and `oneiric.adapters.prompt`.** Unlikely (no historical cross-imports between the mcp-common versions) but possible if the new layout forces a fresh import path. Mitigation: Phase 4 consumer test runs will surface this.
3. **`mcp_common/backends/toolkit.py` may have other latent imports** of the moved packages beyond line 19. Mitigation: full re-grep of `mcp-common/` itself after the deletions; if anything remains, update it.
4. **The `BodaiAdapter` Protocol session's shape** may require extra methods on the moved classes (e.g., explicit `init` / `health_check` / `shutdown`). If those don't exist, the classes need patching before the protocol session lands. Mitigation: confirm protocol shape with that session before Phase 1; if the shape is unknown, land the move anyway and add methods in a follow-up.
5. **The `[llm]` extra in `mcp-common/pyproject.toml`** may declare `httpx2` as an optional dep. With `mcp_common/llm/` gone, that extra becomes useless and the dep declaration should come out. Mitigation: audit and clean `mcp-common/pyproject.toml` in Phase 5.
6. **Cross-repo push coordination.** Per `feedback-bodai-push-is-user-controlled.md`, the user does all `git push` for bodai. This plan lands in 4 repos (oneiric, mcp-common, session-buddy, crackerjack). The user must push them in a coordinated order — oneiric first (so consumers can pull the new code), then consumers, then mcp-common last (since removing `mcp_common/llm` and `mcp_common/prompting` will break any repo that hasn't yet updated). The plan does not specify a merge order; that belongs in the user's coordination.

## References

- Memory `feedback-no-backwards-compat-pre-1.0.md` — hard-break policy
- Memory `bodai-pre-1.0-merge-policy.md` — direct merge to main
- Memory `feedback-bodai-push-is-user-controlled.md` — user does all `git push`
- Memory `feedback-mcp-common-version-bump-is-user.md` — no version bumps in this plan
- Memory `feedback-keep-plan-files-tracked.md` — `git add docs/plans/*.md` first
- Memory `docs-audit-removed-but-referenced.md` — every Bodai deletion PR should grep docs for removed symbols
- `docs/adr/0002-oneiric-adapter-contract.md` — existing canonical adapter contract
- `docs/specs/2026-10-11-adapter-contract-design.md` — existing canonical authoring spec
- Plan template: `docs/plans/2026-10-11-pydantic-settings-migration.md` (most recent template reference)
- Related: `docs/plans/2026-10-11-remove-zuban-skylos-lsp-from-crackerjack.md` (crackerjack-side) — orthogonal but same hard-break philosophy

## Estimated scope

| Phase | Effort |
|---|---|
| 1. Move LLM code to `oneiric.adapters.llm` | 30 min |
| 2. Move `HailuoAdapter` to `oneiric.adapters.video` | 15 min |
| 3. Move prompting to `oneiric.adapters.prompt` | 30 min |
| 4. Update consumers (session-buddy, crackerjack, mcp-common) + catalog registrations | 30 min |
| 5. Docs + final validation | 15 min |
| **Total** | ~2 hr |

Ship target: this week (4 repos, all trivial, hard break avoids deprecation cycle).

## Coordination notes

- **Push order is critical.** oneiric first (so consumers can pull the new code), then session-buddy + crackerjack (so they reference the new locations), then mcp-common last (it deletes the old locations, and any consumer that hasn't updated yet breaks at import time).
- **The `BodaiAdapter` Protocol session is in flight.** Confirm the protocol's structural shape with that session before Phase 1; if the shape is finalized, the moved classes can be patched in lockstep.
- **Per `feedback-keep-plan-files-tracked.md`:** when committing, run `git add docs/plans/2026-10-11-move-llm-and-prompting-from-mcp-common-to-oneiric.md docs/plans/PLAN_INDEX.md` first to land the plan atomically.
- **PLAN_INDEX.md is auto-regenerated** by `scripts/regenerate_plan_index.py` per the file's header. The hand-edit added in Phase 5 will be overwritten by the next regeneration; verify the regeneration picks up the new frontmatter (the script reads frontmatter from each plan file). If regeneration misses the entry, that's a script bug worth fixing separately.
