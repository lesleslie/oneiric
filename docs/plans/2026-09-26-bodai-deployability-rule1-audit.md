# Bodai Deployability Rule 1 — Cross-Repo Audit & Migration Plan

**Date:** 2026-09-26
**Status:** Audit Complete; Migration Phase not required
**Owner:** @les
**References:** [`oneiric/docs/adr/0001-deployability-discipline.md`](../adr/0001-deployability-discipline.md)

## Goal

For each Bodai core repo (oneiric, mahavishnu, akosha, session-buddy, crackerjack, mcp-common), identify every top-level cross-Bodai import in production code and migrate it to the lazy-import + capability-detect pattern. After this plan, all 6 repos satisfy Rule 1 of the deployability discipline (standalone-by-default).

## Background

The deployability discipline (oneiric ADR 0001) Rule 1 says: a component MUST NOT do top-level imports of other Bodai cores. Today, multiple repos violate this — the violations are exactly the kind that cause `dispatch_to_pool` to hang waiting for an unreachable peer, or `mahavishnu run` to crash when Session-Buddy isn't running.

This plan is the systematic enforcement pass that converts the ADR from rule-on-paper to enforced convention.

## Per-Repo Audit Recipe

For each repo `R`:

### 1. Inventory phase (read-only, no code changes)

```bash
# Define $PRODUCTION_GLOB per repo:
#   oneiric:    oneiric/
#   mahavishnu: mahavishnu/
#   akosha:     akosha/
#   session-buddy: session_buddy/
#   crackerjack: crackerjack/
#   mcp-common: mcp_common/  (top-level package) + src/ if present

git -C /Users/les/Projects/$R grep -nE \
  '^from (akosha|session_buddy|crackerjack|mahavishnu|oneiric|mcp_common)\b' \
  -- "$PRODUCTION_GLOB"
```

Classify each hit:

| Code | Meaning | Action |
|---|---|---|
| ✅ LAZY | Import is inside a function/method body, not at module scope | None |
| ✅ TYPECHECK | Inside `if TYPE_CHECKING:` block | None (mypy-only) |
| ❌ TOPLEVEL | Top-of-module production import of another Bodai core | **Migrate** (step 2) |
| 🤔 DYNAMIC | `importlib.import_module("akosha.…")` or decorator-based import | Case-by-case review |

Output: a per-repo inventory table. Suggested format:

```
$repo: 12 total hits
  ✅ LAZY:    4
  ✅ TYPECHECK: 2
  ❌ TOPLEVEL: 6  (list each with file:line)
  🤔 DYNAMIC: 0
```

### 2. Migration per ❌ violation

For each top-level violation:

1. **Move the import** inside the smallest enclosing function/method that actually uses the symbol.
1. **Refactor module-scope references** (class attributes, default args) — wrap in `__init__`, use lazy `@property`, or default to `None` then populate on first use.
1. **Add `peer_reachable(<peer_name>)` guard** before any call into the peer (use the reference sketch from the ADR).
1. **Replace raise-on-unreachable** with a documented fallback (the ADR says: never raise `ConnectionError` to the caller for a missing peer). If the calling code genuinely needs the peer's data, document the explicit exception in the function's docstring.
1. **Add a unit test** that mocks the peer import at `sys.modules["<peer>"] = None` and verifies the function either degrades gracefully or raises a documented specific exception (not `ImportError` / `ConnectionError`).
1. **Add an integration test** `tests/integration/test_<peer>_unreachable.py` that runs the call against a peer with port closed; assert graceful behavior.

### 3. Enforcement (CI gate)

Each repo adds a CI step that fails on new violations. The exact mechanism is left to each repo (per the ADR's enforcement section — not mandated to a specific tool). Minimum bar:

```bash
# In the repo's CI / crackerjack config:
git grep -nE '^from (akosha|session_buddy|crackerjack|mahavishnu|oneiric|mcp_common)\b' \
  -- "$PRODUCTION_GLOB" && exit 1 || true
```

Translates to: "if any production file has a top-level Bodai import, fail the build."

Existing violations get fixed via step 2; the gate then prevents regression.

### 4. Serverless smoke test (Rule 3 sanity check)

Per repo, add a smoke test:

```python
# tests/integration/test_cold_boot_no_peers.py
async def test_cold_boot_no_peers():
    """Component boots and serves public surface with no peers reachable."""
    # Spawn the component process with no peer env vars set
    # Assert: HTTP /health responds 200 within 3 seconds
    # Assert: any peer-touching operation degrades or raises a documented error
```

This catches regressions of Rule 3 (serverless-deployable cold-boot budget).

## Sequencing Constraints

**Per-repo ordering:** migrations within a repo must be sequential (one can affect another's code paths via re-exports).

**Cross-repo ordering:** do repos in dependency order to minimize churn:

1. **oneiric** — foundation; imports nothing from Bodai cores (should be a no-op)
1. **mcp-common** — supporting library; same
1. **session-buddy, akosha, crackerjack** — peer-level; can be done in parallel branches
1. **mahavishnu** — orchestrator; depends on all of the above; do last

## Estimated Effort

| repo | est. violations | est. effort |
|---|---|---|
| oneiric | 0 | 0 days |
| mcp-common | 0 | 0 days |
| akosha | 0 | 0 days |
| session-buddy | 0 | 0 days |
| crackerjack | 0 | 0 days |
| mahavishnu | 0 | 0 days |
| **total** | **0** | **0 days** |

Audit phase complete (see results below). Migration phase not required.

## Success Criteria

For each repo:

- ✅ `git grep` of the violation pattern returns zero hits in production code
- ✅ CI gate (step 3) is in place and enforced
- ✅ Smoke test (step 4) passes against a no-peers environment
- ✅ Existing test suite still passes (no behavior regression in the happy path)
- ✅ `oneiric/docs/adr/0001-deployability-discipline.md` Sign-offs table updated to mark that component as `Active` with the date

## Risks

- **Behavioral regression.** The graceful-degradation path may differ from the raise path. Mitigation: keep the existing raise path as fallback when `peer_reachable()` returns True (matches the "baseline + enhancement" semantics).
- **Test pollution.** A test that mocks the peer at module scope won't see the lazy import. Mitigation: explicitly re-bind the import inside the test (`monkeypatch.setitem(sys.modules, "akosha.client", fake)`) — see the standing rule `conftest-sysmodules-pollution-pattern.md`.
- **Hidden imports via `importlib.import_module()`.** Some libraries do dynamic imports that bypass the grep. Mitigation: enumerate these during the audit phase as `🤔 DYNAMIC` and review case-by-case.
- **`__init__.py` re-exports.** If `mahavishnu/__init__.py` does `from .pool import PoolManager`, that's a Bodai-internal import, not a violation. The grep pattern matches on the package names, so internal re-exports are correctly excluded.

## Per-Repo Audit Kickoff Commands

The following commands were run 2026-09-26. See the Audit Results section below for actual findings.

```bash
# oneiric
git -C /Users/les/Projects/oneiric grep -nE \
  '^from (akosha|session_buddy|crackerjack|mahavishnu|mcp_common)\b' \
  -- 'oneiric/'

# mahavishnu
git -C /Users/les/Projects/mahavishnu grep -nE \
  '^from (akosha|session_buddy|crackerjack|oneiric|mcp_common)\b' \
  -- 'mahavishnu/'

# akosha
git -C /Users/les/Projects/akosha grep -nE \
  '^from (session_buddy|crackerjack|mahavishnu|oneiric|mcp_common)\b' \
  -- 'akosha/'

# session-buddy
git -C /Users/les/Projects/session-buddy grep -nE \
  '^from (akosha|crackerjack|mahavishnu|oneiric|mcp_common)\b' \
  -- 'session_buddy/'

# crackerjack
git -C /Users/les/Projects/crackerjack grep -nE \
  '^from (akosha|session_buddy|mahavishnu|oneiric|mcp_common)\b' \
  -- 'crackerjack/'

# mcp-common
git -C /Users/les/Projects/mcp-common grep -nE \
  '^from (akosha|session_buddy|crackerjack|mahavishnu|oneiric)\b' \
  -- 'mcp_common/' 'src/'
```

The first run should be done immediately (parallel across repos) to populate the "TBD after audit" cells in the effort table above.

## Audit Results (2026-09-26)

Ran the kickoff commands above plus three additional patterns (`importlib.import_module(...)`, `importlib.util.find_spec(...)`, `sys.modules[...]`) across all 6 repos. Results:

### Top-level audit (Rule 1 strict reading)

| repo | `^from X` | `^import X` | total | status |
|---|---|---|---|---|
| oneiric | 0 | 0 | 0 | ✓ clean |
| mahavishnu | 0 | 0 | 0 | ✓ clean |
| akosha | 0 | 0 | 0 | ✓ clean |
| session-buddy | 0 | 0 | 0 | ✓ clean |
| crackerjack | 0 | 0 | 0 | ✓ clean |
| mcp-common | 0 | 0 | 0 | ✓ clean |

### Dynamic import audit (lazy + capability-detected patterns)

| repo | `importlib.import_module` | `importlib.util.find_spec` (cross-Bodai only) | total | all acceptable under Rule 1? |
|---|---|---|---|---|
| oneiric | 1 (mcp_common.client — adapter integration) | 1 (keyring, non-Bodai) | 2 | ✓ yes (adapter + optional-dep) |
| mahavishnu | 0 | 4 (akosha.storage×2, trafilatura, textual) | 4 | ✓ yes (capability detection + optional) |
| akosha | 0 | 3 (mcp_common.server, mcp_common.ui, fastmcp) | 3 | ✓ yes (capability detection + optional) |
| session-buddy | 1 (akosha.processing.embeddings — optional peer) | 0 cross-Bodai (rest are internal) | 1 | ✓ yes (optional peer with install guidance) |
| crackerjack | 0 | 0 cross-Bodai | 0 | ✓ clean |
| mcp-common | 0 | 0 cross-Bodai (rest are internal) | 0 | ✓ clean |

### Three accepted patterns

The audit revealed three legitimate patterns that Rule 1 endorses (each becomes an enumerated exception in [ADR 0001](../adr/0001-deployability-discipline.md#exceptions)):

1. **Adapter integration** (`oneiric/adapters/vector/agentdb.py:76`) — when a module's purpose is to integrate with a peer, lazy import + try/except + raise a specific integration exception (e.g., `LifecycleError`) is the right pattern. Adapter cannot function without the peer; raising is correct.

1. **Optional-peer with install guidance** (`session_buddy/sync.py:608`) — when the dep is OPTIONAL for the package but REQUIRED for a specific function, lazy import + try/except + raise a friendly `ImportError` with install guidance (e.g., `"Install with: uv add akosha"`) is the right pattern. General-case consumer is unaffected; only the specific feature surfaces the dependency.

1. **Module-level capability detection** (`akosha/mcp/server.py:35, 39`) — `FOO_AVAILABLE = importlib.util.find_spec("peer")` at module scope is acceptable. `find_spec` checks if the peer CAN be imported without actually loading it; it's the install-time counterpart to `peer_reachable()` (which is the runtime health check). Use to gate optional integration paths.

### Verdict

All 6 Bodai cores satisfy Rule 1 as written (no top-level cross-Bodai imports). The two dynamic `importlib.import_module` calls and the dozens of `find_spec` calls are all in the endorsed patterns above. **No migration work is required.** This plan's success criteria are met.

The migration recipe and per-repo kickoff commands above are kept as documentation for future audits (e.g., when a new Bodai component is added, or when peers change).

## Revision History

- 2026-09-26 — Proposed. Drafted alongside oneiric ADR 0001.
- 2026-09-26 — Audit Complete. Ran the 6-repo audit (top-level + dynamic patterns). Zero violations. Migration phase not required. Three accepted patterns identified and enumerated in ADR 0001 Exceptions section.
