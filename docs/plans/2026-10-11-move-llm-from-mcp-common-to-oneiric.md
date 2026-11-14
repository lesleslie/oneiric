---
title: Move the LLM Subsystem from mcp-common to oneiric; delete the prompting, backends, and AppleScript subsystems
description: Hard break. Move `mcp_common/llm/` into the existing `oneiric/adapters/llm/` package (3 live production consumers). Delete `mcp_common/prompting/`, `mcp_common/backends/`, and `mcp_common/apple_script/` outright, and delete `HailuoAdapter` — all four have zero production consumers across the 29 local repos that depend on mcp-common. Update the three live LLM consumers in lockstep. No backward-compat shims per pre-1.0 policy.
audience: oneiric maintainer + mcp-common maintainer + session-buddy + crackerjack + mahavishnu
created: 2026-10-11
status: active
role: implementation
topic: adapter-registry
date: 2026-10-11
last_reviewed: 2026-11-14
revised: 2026-11-14
superseded_by: null
blocks_on: []
---

# Move the LLM Subsystem from mcp-common to oneiric; delete the unused prompting stack

> **Revised 2026-11-14.** The original plan (dated 2026-10-11) moved three
> subsystems to oneiric: `llm`, `prompting`, and `HailuoAdapter` (video). A
> consumer audit on 2026-11-14 found that only the `llm` half has any
> production consumers. The prompting stack, the macOS backends, the AppleScript
> bridge, and `HailuoAdapter` have **zero** — across all 29 local repos that
> depend on mcp-common. Those four are now **deleted outright** rather than
> relocated. The original reasoning ("oneiric is the foundation home for
> adapters") was sound but was applied to code nobody calls; relocating dead
> code preserves its maintenance cost and adds oneiric's adapter-registration
> and health-feed obligations on top.

## Brief (intent-driven)

### Goal

`mcp_common/llm/` moves into the existing `oneiric/adapters/llm/` package,
which already owns the LLM *providers* — the chaining layer belongs next to
the things it chains over. The three live consumers (mahavishnu's cloud
worker, session-buddy's LLM manager, crackerjack's code-fixer adapter) are
updated in lockstep.

Everything else mcp-common shipped in the prompting family — the prompting
package, the PyObjC and prompt-toolkit backends, the AppleScript bridge, and
`HailuoAdapter` — is **deleted**. It has no callers. Per
`docs/decisions/wire-up-contract.md`: *"If the audit reports recently-added
symbols with zero callers, the feature is not done — either wire it or remove
it."*

mcp-common is left as a thin MCP-server foundation library (settings bases,
FastMCP re-exports, MCP-specific glue, prompts backend bridge).

### Policy: No backwards compatibility / legacy support

Per `feedback-no-backwards-compat-pre-1.0.md`. No re-export shims, no
`DeprecationWarning`, no deprecation windows. Delete the source, update
consumers in lockstep, ship.

### Constraints

1. **Hard break.** Delete the source, update consumers in lockstep, ship.
2. **Pre-1.0 — direct merge to `main`**, no PR, per `feedback-bodai-pre-1.0-merge-policy.md`. Apply per-repo within the same worktree cycle; each repo lands on its own `main` (user-controlled per `feedback-bodai-push-is-user-controlled.md`).
3. **`oneiric` already ships `httpx2>=0.28.1` as a hard dep.** The moved LLM code's `httpx2` requirement adds no weight.
4. **Existing `oneiric/adapters/llm/` subpackage** is the home for the moved code. Do not invent a parallel `adapters/llm_providers` namespace; extend the existing one.
5. **No new `oneiric/adapters/prompt/` or `oneiric/adapters/video/` packages are created.** That was the original plan's shape; the 2026-11-14 audit removed the justification for both.
6. **No version bump in any `pyproject.toml`** — per `feedback-mcp-common-version-bump-is-user.md`, the user does all version bumps.
7. **Coordinate with the in-flight `BodaiAdapter` Protocol session** (extracting a fleet-wide adapter Protocol). Confirm shape alignment before Phase 1; if the protocol has not landed, the classes still move and conformance is a follow-up.
8. **The deleted mcp-common modules leave no compatibility shim.** `mcp_common.prompting`, `mcp_common.backends`, `mcp_common.apple_script`, and `mcp_common.llm.hailuo` all raise `ModuleNotFoundError` after this plan.

### Failure Conditions (verifier-only)

1. `mcp_common/llm/` does not exist as a directory after the change (8 files: `__init__.py`, `_security.py`, `config.py`, `exceptions.py`, `fallback.py`, `hailuo.py`, `provider.py`, `types.py` — none remain).
2. `mcp_common/prompting/` (8 files), `mcp_common/backends/` (3 files), and `mcp_common/apple_script/` (3 files) do not exist after the change.
3. `oneiric/adapters/llm/` contains the moved LLM code: `fallback.py` (`FallbackChain`, `CircuitBreaker`), `config.py` (`LLMSettings`, `ProviderConfig`), `exceptions.py` (`LLMError`), `provider.py` (`OpenAICompatibleProvider`), `types.py` (`TaskType`), `_security.py` (`sanitize_error`). **No `hailuo.py` — that is deleted, not moved.**
4. `oneiric.adapters.llm.fallback.FallbackChain`, `oneiric.adapters.llm.config.LLMSettings`, `oneiric.adapters.llm.config.ProviderConfig`, `oneiric.adapters.llm.exceptions.LLMError`, `oneiric.adapters.llm.types.TaskType` all import cleanly.
5. `git grep -nE "from mcp_common\.llm|from mcp_common\.prompting|from mcp_common\.backends|from mcp_common\.apple_script" -- '*.py'` returns zero matches across the fleet (mahavishnu, akosha, session-buddy, crackerjack, oneiric, mcp-common).
6. `pytest tests/` in each affected repo exits 0 after the consumer updates.
7. `mcp_common/pyproject.toml` declares no `macos-prompts` or `terminal-prompts` dependency-group, and `[tool.coverage.run].omit` no longer lists `mcp_common/backends/pyobjc.py`.
8. `mcp-common/uv.lock` no longer resolves `pyobjc-core`, `pyobjc-framework-cocoa`, or `prompt-toolkit`.
9. `session-buddy/docs/developer/PROMPTING_ADAPTER_QUICK_REFERENCE.md` carries frontmatter `status: complete` + `role: superseded` + `superseded_by: ext:oneiric/docs/plans/2026-10-11-move-llm-from-mcp-common-to-oneiric.md`, and the duplicate root copy `session-buddy/PROMPTING_ADAPTER_QUICK_REFERENCE.md` is removed.
10. `mahavishnu/tests/unit/test_apple_script_bridge_conformance.py` is deleted (it tested the removed `mcp_common.apple_script` bridge).
11. The `OneiricAdapterRegistry` registrations for the moved classes use the new factory paths (`oneiric.adapters.llm.fallback.FallbackChain`).

## Context

### Why move the LLM code

- mcp-common's LLM subsystem is already past the MCP boundary: `mahavishnu/mahavishnu/workers/cloud_worker.py:20`, `session-buddy/session_buddy/llm_providers.py:10`, and `crackerjack/crackerjack/adapters/ai/unified.py:8-9` all import from `mcp_common.llm`. Hosting LLM utilities in an MCP-specific package is a historical accident, not a deliberate boundary.
- Oneiric already has the shape: `adapters/llm/` exists and owns the *providers* (anthropic, bifrost, openai). `FallbackChain` is the layer that chains over providers — it belongs beside them, not in a different repo.
- Oneiric's own `adapters/llm/bifrost.py` already documents `mcp_common.llm.OpenAICompatibleProvider` as the transport callers are expected to hand off to (`bifrost.py:6,44,502`) — without importing it. The move closes that soft coupling by putting the transport in the same package as the adapter that references it.
- Per `feedback-no-backwards-compat-pre-1.0.md`, the policy is "replace not extend" — a clean break is the right call.

### The zero-consumer finding (2026-11-14)

The original plan moved three subsystems. An audit of every local repo that
depends on mcp-common established which of them are actually called:

| Subsystem | Production consumers | Verdict |
|---|---|---|
| `mcp_common/llm/` | **3** (mahavishnu, session-buddy, crackerjack) | Move |
| `mcp_common/prompting/` | **0** | Delete |
| `mcp_common/backends/` (pyobjc, toolkit) | **0** | Delete |
| `mcp_common/apple_script/` | **0** | Delete |
| `mcp_common/llm/hailuo.py` (`HailuoAdapter`) | **0** | Delete |

**Method.** Swept all 29 local repos whose `pyproject.toml` declares
`mcp-common`/`mcp_common` (akosha, archive-org-mcp, bifrost-mcp,
chat-bridge-mcp, cmux-mcp, crackerjack, css-mcp, excalidraw-mcp, fastblocks,
graphics-mcp, langsmith-mcp, mahavishnu, mailgun-mcp, mdinject, medium-mcp,
neo4j-mcp, oneiric, opera-cloud-mcp, penpot-api-mcp, porkbun-dns-mcp,
porkbun-domain-mcp, raindropio-mcp, scapy-mcp, session-buddy, splashstand,
spline-mcp, synxis-crs-mcp, synxis-pms-mcp, unifi-mcp) for
`mcp_common.prompting`, `mcp_common.backends`, `mcp_common.apple_script`, and
`create_prompt_adapter`. **Every one returned zero hits** outside mcp-common's
own package, its `examples/`, and its test suite. No MCP tool in
`mcp_common/tools/` or `mcp_common/server/` referenced any of them.

**Why delete rather than relocate.** Three reasons:

1. **Relocation preserves implementation cost and adds obligations.** Deleting removes ~2,071 lines and two dependency-groups. Moving to oneiric keeps them *and* adds oneiric's adapter contract: `AdapterMetadata` (category/provider/factory/settings_model), registration in `adapters/bootstrap.py`, the `init`/`health`/`cleanup` shape (`adapters/protocol.py:46-117`), the per-feed health aggregates required by `docs/decisions/mcp-backend-wiring-discipline.md`, and an e2e test per registered adapter. More work, same zero consumers — and a registered-but-uncalled adapter is exactly what the wire-up-contract audit flags as a failure.
2. **The install path was already broken.** mcp-common's `[project.optional-dependencies]` section no longer exists (`pyproject.toml:361` references it only historically), so `pip install 'mcp-common[macos-prompts]'` — the exact command printed in the deleted `mcp_common/prompting/factory.py:62,151` — already failed for every external consumer. The PEP 735 migration broke it before this decision.
3. **Git preserves it.** Deletion is a revert away. The cost of *keeping* it is not zero: it gets rediscovered and re-litigated, and it kept a decision doc (`session-buddy/PROMPTING_ADAPTER_QUICK_REFERENCE.md`, frontmatter `role: canonical`) asserting the opposite of the active plan.

**What is lost.** Nothing callable. The one plausible future consumer — a
native-dialog push for mahavishnu's approval flow, which is today
pull-only (`request_approval` → durable store → human polls
`get_pending_approvals` → `respond_to_approval`) — would need new work
regardless: a modal dialog blocks the MCP tool call, so delivery must be
non-blocking with a callback bridge, and the modern notification API needs the
`UserNotifications` framework, which is absent from the dependency tree
(`pyobjc-framework-Cocoa` depends on `pyobjc-core` only). Such a feature
would be written fresh against a named requirement, borrowing the ~50 lines of
`NSAlert`/`NSOpenPanel` call patterns from git history if useful.

**Note on the archived decision doc.** `session-buddy/PROMPTING_ADAPTER_QUICK_REFERENCE.md`
argued for keeping the prompting adapter in mcp-common ("DO NOT CHANGE") on
the stated grounds that it had "9+ MCP servers" as consumers. That premise was
false — 29 dependents, zero users. The doc is archived as a historical
artifact with `superseded_by` pointing here, not deleted: it records a real
past decision, and its reasoning error is itself worth preserving.

### Inventory of what's moving

**From `mcp_common/llm/` → `oneiric/adapters/llm/`:**

| Source | Destination | Exports |
|---|---|---|
| `_security.py` | `oneiric/adapters/llm/_security.py` | `sanitize_error` |
| `config.py` | `oneiric/adapters/llm/config.py` | `LLMSettings`, `ProviderConfig` |
| `exceptions.py` | `oneiric/adapters/llm/exceptions.py` | `LLMError` |
| `fallback.py` | `oneiric/adapters/llm/fallback.py` | `FallbackChain`, `CircuitBreaker` |
| `provider.py` | `oneiric/adapters/llm/provider.py` | `OpenAICompatibleProvider` |
| `types.py` | `oneiric/adapters/llm/types.py` | `TaskType` |
| `__init__.py` | `oneiric/adapters/llm/__init__.py` | re-exports the above |

**Also moved:** `mcp-common/tests/test_llm.py` and
`mcp-common/tests/unit/test_llm_additional.py` → oneiric's test tree (with
the Hailuo test classes removed).

### Consumers (must update in lockstep)

**Production — 3 sites:**

| File | Line | Current import |
|---|---|---|
| `mahavishnu/mahavishnu/workers/cloud_worker.py` | 20 | `from mcp_common.llm import FallbackChain, LLMSettings` |
| `session-buddy/session_buddy/llm_providers.py` | 10 | `from mcp_common.llm import FallbackChain, LLMSettings` |
| `crackerjack/crackerjack/adapters/ai/unified.py` | 8-9 | `from mcp_common.llm import FallbackChain` / `from mcp_common.llm.config import LLMSettings, ProviderConfig` |

**Tests — 3 files:**

| File | Lines |
|---|---|
| `mahavishnu/tests/unit/workers/test_cloud_worker.py` | 133, 169, 201, 241 |
| `session-buddy/tests/unit/test_llm_providers_bifrost_router.py` | 89, 133, 168, 208 |
| `crackerjack/tests/adapters/test_provider_chain.py` | 85 |

**Liveness proof for each production consumer** (so a future reader knows
these are not vestigial):

- `mahavishnu`: `CloudWorker` is exported from `mahavishnu/workers/__init__.py:33`; the chain is built at `cloud_worker.py:204` via `FallbackChain.from_settings(settings)`.
- `session-buddy`: `LLMManager`/`LLMMessage` are imported by `session_buddy/memory/entity_extractor.py:327,356`; availability is probed by `session_buddy/mcp/tools/intelligence/llm_tools.py:45`.
- `crackerjack`: `FallbackChainCodeFixer` is instantiated via `crackerjack/adapters/ai/registry.py:69` and `crackerjack/adapters/factory.py:103`.

> **Inventory correction (2026-11-14).** The original plan's grep listed 5
> consumer sites and omitted `mahavishnu/workers/cloud_worker.py:20` — a
> production consumer in the orchestrator. The original grep was `git grep`
> (tracked files only) run in one repo, and the plan's own risk #1 predicted
> exactly this miss. Any re-audit must sweep **all** fleet repos, not one.

### Coordination with the in-flight `BodaiAdapter` Protocol session

That session is extracting a fleet-wide adapter Protocol (one per category) — `BodaiAdapter` shape: `name`, `capabilities`, `init`, `health_check`, `execute`, `shutdown`. If it lands before this plan, the moved classes must satisfy the protocol's structural shape. The decision rule:

- **`FallbackChain`**: currently standalone (not extending any base). Confirm it satisfies the protocol via duck typing; if not, add the missing methods before Phase 1.
- **`LLMSettings` / `ProviderConfig`**: settings classes, not adapters. They're dependencies of the adapter classes, not adapters themselves — no conformance check needed.

If the protocol session hasn't landed, the classes still move; conformance can be added in a follow-up.

## Approach

Five phases. Each phase ends with the consumer-side smoke test for the affected repo: `uv sync` then `pytest tests/` for the consumer, `crackerjack run` for crackerjack, and `python -c "import oneiric.adapters.llm.fallback"` for oneiric.

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
- Rollback signal: any consumer (mahavishnu, session-buddy, crackerjack) fails to import `FallbackChain` / `LLMSettings`
- Observability added: none

### Phase 2 — Delete `HailuoAdapter` and the mcp-common prompting stack

The original plan moved `HailuoAdapter` to `oneiric/adapters/video/` and the
prompting subsystem to `oneiric/adapters/prompt/`. The 2026-11-14 audit found
zero consumers for both, so they are deleted instead. No new oneiric packages
are created.

**Files deleted in `mcp-common/`:**
- `mcp_common/llm/hailuo.py` (the last file in `mcp_common/llm/`)
- `mcp_common/prompting/` — `__init__.py`, `adapter.py`, `base.py`, `exceptions.py`, `factory.py`, `models.py`, `MIGRATION.md`, `README.md`
- `mcp_common/backends/` — `__init__.py`, `pyobjc.py`, `toolkit.py`
- `mcp_common/apple_script/` — `__init__.py`, `bridge.py`, `exceptions.py`
- `examples/prompting_advanced.py`, `examples/prompting_basics.py`, `examples/prompt_demo.py`, `examples/prompting_file_selection.py`
- `tests/test_prompting_adapter.py`, `tests/unit/test_pyobjc_backend.py`, `tests/unit/test_apple_script_bridge.py`, `tests/unit/test_prompting/` (6 files)
- `docs/iterm2-applescript-protocol.md` (the escaping protocol spec, orphaned by the bridge's removal)

**Edit `mcp-common/pyproject.toml`:**
- Drop the `macos-prompts` dependency-group (`pyobjc-core>=12.2.2`, `pyobjc-framework-Cocoa>=10.0`).
- Drop the `terminal-prompts` dependency-group (`prompt-toolkit>=3.0.53`). `prompt_toolkit` has no other consumer in mcp-common.
- Drop `"mcp_common/backends/pyobjc.py"` from `[tool.coverage.run].omit`.
- Update the install-line comment at the top of `[dependency-groups]` to drop `--group macos-prompts --group terminal-prompts`.
- Regenerate `uv.lock` — `pyobjc-core`, `pyobjc-framework-cocoa`, and `prompt-toolkit` must no longer resolve.

**Edit `mcp-common/CLAUDE.md`:** remove the `mcp_common/apple_script/`, `mcp_common/backends/`, and `mcp_common/prompting/` subpackage bullets; drop `pyobjc (macOS)` from the optional-dep-adapter list.

**Edit `mcp-common/AGENTS.md`:** drop `prompting/`, `apple_script/`, and `backends/` from the module list.

**Edit `mcp-common/docs/reference/service-dependencies.md`:** remove the `macos-prompts` and `terminal-prompts` rows from the dependency-group table, the two entries in the `[dependency-groups]` sample block, and the group names in the "not part of the runtime tree" note.

**Edit `mcp-common/docs/audits/2026-09-05-coverage-ratchet-memo.md`:** the memo is a dated historical decision record — do not rewrite its history. Append a dated amendment recording the deletion, the coverage effect, and the updated omit list. Per the memo's own decision rule, also sync `.coverage-ratchet.json` and `pyproject.toml --cov-fail-under` if the re-measured baseline moved.

**Edit `mcp-common/scripts/_frontmatter_apply_P7B.py`:** remove the `docs/iterm2-applescript-protocol.md` entry — the file it would rewrite no longer exists.

**At end of this phase, `mcp_common/llm/`, `mcp_common/prompting/`, `mcp_common/backends/`, and `mcp_common/apple_script/` do not exist as directories.**

**Integration Contract:**
- Triggered from: Phase 1 complete
- Returns to / updates: `mcp_common/llm/hailuo.py` (deleted), `mcp_common/prompting/` (deleted), `mcp_common/backends/` (deleted), `mcp_common/apple_script/` (deleted), `mcp-common/pyproject.toml` (2 groups + 1 omit entry removed), `mcp-common/uv.lock` (regenerated), `mcp-common/CLAUDE.md`, `mcp-common/AGENTS.md`, `mcp-common/docs/reference/service-dependencies.md`, `mcp-common/docs/audits/2026-09-05-coverage-ratchet-memo.md`
- Demonstrable by: `ls mcp_common/prompting/ mcp_common/backends/ mcp_common/apple_script/ mcp_common/llm/` returns "No such file or directory" for all four; `uv run python -c "import mcp_common.prompting, mcp_common.backends, mcp_common.apple_script"` raises `ModuleNotFoundError`; `uv lock --check` passes; `rg pyobjc uv.lock` returns no matches
- Rollback signal: any consumer fails to import from the removed locations; `uv lock --check` fails
- Observability added: none

### Phase 3 — Archive the superseded decision doc; delete the orphaned conformance test

**`session-buddy`:**
- Delete the duplicate root copy `PROMPTING_ADAPTER_QUICK_REFERENCE.md` (byte-identical to the `docs/developer/` copy; the root copy was the older file).
- Keep `docs/developer/PROMPTING_ADAPTER_QUICK_REFERENCE.md` **in place** — session-buddy has no archive/deprecated directory convention, so the repo's own mechanism is the frontmatter chain. Restore its frontmatter to the canonical fenced form and mark it `status: complete` + `role: superseded` + `superseded_by: ext:oneiric/docs/plans/2026-10-11-move-llm-from-mcp-common-to-oneiric.md` (the `ext:` form is required because the plan lives in oneiric, so a repo-relative path could not resolve).
- Add a prominent `SUPERSEDED` banner under the frontmatter naming the plan and calling out the two false premises in the body. **Do not edit the historical body** — it is a record of a real past decision, and annotating it is more honest than rewriting it. (The plan's earlier draft proposed editing the body in place; that was revised 2026-11-14.)

**`mahavishnu`:**
- Delete `tests/unit/test_apple_script_bridge_conformance.py`. It tested `mcp_common.apple_script.bridge` and was `skipif(not OSASCRIPT_AVAILABLE)` — on macOS it *ran*, so it breaks on Phase 2's deletion.

**Integration Contract:**
- Triggered from: Phase 2 complete
- Returns to / updates: `session-buddy/PROMPTING_ADAPTER_QUICK_REFERENCE.md` (deleted), `session-buddy/docs/developer/PROMPTING_ADAPTER_QUICK_REFERENCE.md` (frontmatter reconciled + SUPERSEDED banner), `mahavishnu/tests/unit/test_apple_script_bridge_conformance.py` (deleted)
- Demonstrable by: `rg -l 'PROMPTING_ADAPTER_QUICK_REFERENCE' session-buddy/` shows only `docs/developer/`; the doc's frontmatter parses as YAML and yields `role: superseded`; `rg -c 'apple_script' mahavishnu/tests/` returns zero
- Rollback signal: session-buddy's doc linter rejects the reconciled frontmatter; mahavishnu's test suite references a removed module
- Observability added: none

### Phase 4 — Update consumers in lockstep

**Edit:**
- `mahavishnu/mahavishnu/workers/cloud_worker.py:20` — `from mcp_common.llm import FallbackChain, LLMSettings` → `from oneiric.adapters.llm import FallbackChain, LLMSettings`
- `session-buddy/session_buddy/llm_providers.py:10` — same swap
- `crackerjack/crackerjack/adapters/ai/unified.py:8` — same swap
- `crackerjack/crackerjack/adapters/ai/unified.py:9` — `from mcp_common.llm.config import LLMSettings, ProviderConfig` → `from oneiric.adapters.llm.config import LLMSettings, ProviderConfig`
- `mahavishnu/tests/unit/workers/test_cloud_worker.py:133,169,201,241` — same swap
- `session-buddy/tests/unit/test_llm_providers_bifrost_router.py:89,133,168,208` — same swap
- `crackerjack/tests/adapters/test_provider_chain.py:85` — same swap

**Run after edits:** `git grep -nE "from mcp_common\.llm|from mcp_common\.prompting|from mcp_common\.backends|from mcp_common\.apple_script" -- '*.py'` across the fleet. Must return zero matches.

**Edit oneiric catalog registrations (if any exist):** the oneiric catalog may have registrations for these classes under the old factory paths. Audit by:
```bash
rg -l "mcp_common\.llm|mcp_common\.prompting" --glob '*.yaml' --glob '*.json' oneiric/
```
Update any matches to the new factory paths.

**Integration Contract:**
- Triggered from: Phases 1-2 complete (the moved code is in place; consumers just need to point at the new locations)
- Returns to / updates: 3 production import sites (mahavishnu, session-buddy, crackerjack) + 3 test files + any oneiric catalog registrations
- Demonstrable by: the fleet-wide `git grep` returns zero; `pytest tests/` exits 0 in mahavishnu, session-buddy, crackerjack, oneiric
- Rollback signal: any consumer test suite fails after the import swap
- Observability added: none

### Phase 5 — Docs cleanup + final validation

**Edit:** `oneiric/CLAUDE.md` or `oneiric/docs/README.md` — add a one-line note under the adapters section: "`oneiric.adapters.llm` hosts the LLM subsystem (providers, fallback chain, settings); mcp-common no longer ships LLM or prompting code."

**Regenerate** `oneiric/docs/plans/PLAN_INDEX.md` via `uv run python scripts/regenerate_plan_index.py` — the plan was renamed, so the index entry path changes. Verify the regenerated entry picks up the revised title.

**Final validation across all affected repos:**
- `uv sync` in oneiric, mcp-common, session-buddy, crackerjack, mahavishnu
- `pytest tests/` in each — exits 0
- `python -c "import oneiric.adapters.llm.fallback; from oneiric.adapters.llm import FallbackChain, LLMSettings"` exits 0
- `python -c "import mcp_common.llm; import mcp_common.prompting; import mcp_common.backends; import mcp_common.apple_script"` raises `ModuleNotFoundError`
- `crackerjack run` on `crackerjack/` — exits 0
- `session-buddy` MCP server starts and serves healthcheck

**Integration Contract:**
- Triggered from: Phase 4 complete
- Returns to / updates: `oneiric/CLAUDE.md` (one-line note), `oneiric/docs/plans/PLAN_INDEX.md` (regenerated)
- Demonstrable by: all of the above checks pass
- Rollback signal: any check fails
- Observability added: none

## Resolved decisions

1. **Hard break, no shims.** The user explicitly said "we don't care about backwards compat or legacy support". No re-export shims, no `DeprecationWarning`, no deprecation windows.
2. **The prompting stack is deleted, not moved.** Zero production consumers across 29 mcp-common-dependent repos. Relocation would preserve ~2,071 lines of maintenance cost and add oneiric's adapter-registration and health-feed obligations for a capability nobody calls.
3. **`HailuoAdapter` is deleted, not moved to `adapters/video/`.** Zero consumers; no `oneiric/adapters/video/` package exists or is warranted. Git retains it if a video feature is ever specced.
4. **The rest of `mcp_common/llm/` lands in the existing `adapters/llm/`.** It already exists and owns the providers; extending it is the natural home for provider routing, settings, and the LLMError exception.
5. **No `oneiric/adapters/prompt/` or `oneiric/adapters/video/` packages are created.** This reverses the original plan's shape, per the 2026-11-14 audit.
6. **The archived session-buddy decision doc keeps its historical body.** It records a real past decision and a real reasoning error; both are worth preserving. Only its frontmatter and its two actively-misleading verdicts get annotated.
7. **No ADR change.** ADR 0002 (Oneiric Adapter Contract) is canonical and unaffected — the contract is about shape, not location.
8. **No `pyproject.toml` version bumps.** Per `feedback-mcp-common-version-bump-is-user.md`. The user does all version bumps.
9. **No spec doc.** This is a code-move plus a deletion; the design is implicit in the package layout.

## Risks

1. **Hidden consumers of `mcp_common.llm`.** The original plan's grep found 5 sites and missed `mahavishnu/workers/cloud_worker.py:20`. Any re-audit must sweep all fleet repos, not one. Mitigation: the fleet-wide `git grep` in Phase 4 is the gate; a missed consumer breaks at import time, which is loud but disruptive.
2. **`mcp_common/llm/` may have intra-package imports that only surface at runtime.** Mitigation: Phase 1's import smoke test plus each consumer's test suite.
3. **The `BodaiAdapter` Protocol session's shape** may require extra methods on the moved classes (e.g., explicit `init` / `health_check` / `shutdown`). If those don't exist, the classes need patching before the protocol session lands. Mitigation: confirm protocol shape with that session before Phase 1; if unknown, land the move anyway and add methods in a follow-up.
4. **The `llm` dependency-group in `mcp-common/pyproject.toml`** may declare `httpx2` as an optional dep. With `mcp_common/llm/` gone, that group should come out too — audit in Phase 5. (Note: `mcp_common/llm/` is itself excluded from coverage as an optional-dep module, so its *tests* may not run in CI; verify the moved tests still execute under oneiric's CI.)
5. **Deleting the coverage omit entry and the low-coverage modules moves the coverage baseline.** `mcp_common/apple_script/bridge.py` (52.63%) and `exceptions.py` (50.00%) were measured and sub-95%; removing them should *raise* the ratio, but the ratchet must be re-measured and the memo amended per its own decision rule.
6. **Cross-repo push coordination.** Per `feedback-bodai-push-is-user-controlled.md`, the user does all `git push`. This plan lands in 5 repos (oneiric, mcp-common, session-buddy, crackerjack, mahavishnu). The user must push them in a coordinated order — oneiric first (so consumers can pull the new code), then consumers, then mcp-common last (since removing `mcp_common/llm` breaks any repo that hasn't updated).

## References

- Memory `feedback-no-backwards-compat-pre-1.0.md` — hard-break policy
- Memory `bodai-pre-1.0-merge-policy.md` — direct merge to main
- Memory `feedback-bodai-push-is-user-controlled.md` — user does all `git push`
- Memory `feedback-mcp-common-version-bump-is-user.md` — no version bumps in this plan
- Memory `feedback-keep-plan-files-tracked.md` — `git add docs/plans/*.md` first
- Memory `docs-audit-removed-but-referenced.md` — every Bodai deletion PR should grep docs for removed symbols
- `docs/decisions/wire-up-contract.md` — zero callers ⇒ remove
- `docs/adr/0002-oneiric-adapter-contract.md` — existing canonical adapter contract
- `docs/specs/2026-10-11-adapter-contract-design.md` — existing canonical authoring spec
- `session-buddy/PROMPTING_ADAPTER_QUICK_REFERENCE.md` — the archived, superseded decision doc

## Estimated scope

| Phase | Effort |
|---|---|
| 1. Move LLM code to `oneiric.adapters.llm` | 30 min |
| 2. Delete `HailuoAdapter` + prompting stack + backends + AppleScript | 30 min |
| 3. Archive the decision doc; delete the orphaned conformance test | 15 min |
| 4. Update consumers (mahavishnu, session-buddy, crackerjack) | 30 min |
| 5. Docs + index regeneration + final validation | 15 min |
| **Total** | ~2 hr |

## Coordination notes

- **Push order is critical.** oneiric first (so consumers can pull the new code), then session-buddy + crackerjack + mahavishnu (so they reference the new locations), then mcp-common last (it deletes the old locations, and any consumer that hasn't updated yet breaks at import time).
- **The `BodaiAdapter` Protocol session is in flight.** Confirm the protocol's structural shape with that session before Phase 1; if the shape is finalized, the moved classes can be patched in lockstep.
- **Per `feedback-keep-plan-files-tracked.md`:** when committing, run `git add docs/plans/2026-10-11-move-llm-from-mcp-common-to-oneiric.md docs/plans/PLAN_INDEX.md` first to land the plan atomically.
- **`PLAN_INDEX.md` is auto-regenerated** by `scripts/regenerate_plan_index.py`. Regenerate it rather than hand-editing; verify the regeneration picks up the renamed path and the revised frontmatter.
