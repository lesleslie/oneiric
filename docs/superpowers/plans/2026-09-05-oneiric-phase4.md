# Oneiric Phase 4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the 4 HIGH-severity bugs and 4 MED-severity documentation/coverage drift findings from the oneiric audit memo in a single coordinated release, turning the build from RED (6 failing tests) to GREEN.

**Architecture:** Three tightly-scoped doc/code fixes (TypeError→ValueError, version bump, CLAUDE.md rewrite) plus one test-coverage improvement task. All work in oneiric. No cross-repo coordination with crackerjack. No new release-audit check needed (existing one covers CLAUDE.md/CHANGELOG drift detection).

**Tech Stack:** Python 3.14, pytest, mypy, ty optional, bandit B101.

**Spec:** `/Users/les/Projects/oneiric/docs/audits/2026-09-05-oneiric-audit.md`

## Global Constraints

- **Repo**: `/Users/les/Projects/oneiric` only — always `cd` there first
- **Branch**: local `main` only — no PRs, no pushes (user handles push manually)
- **Author email**: `les@wedgwoodwebworks.com` (use `-c user.email=...` in every commit)
- **Pre-commit hooks**: must pass cleanly — do NOT use `--no-verify`
- **Version bump**: NOT done in this plan — user initiates via `crackerjack -p patch` after all tasks complete
- **PyPI publish**: NOT done in this plan — user handles manually
- **Test framework**: `.venv/bin/pytest` (NOT bare `pytest` — wrong venv)
- **Bug IDs from audit memo** referenced by each task

---

## Pre-flight scan (read before dispatching Task 1)

| Pair / Item | Concern | Ruling |
|---|---|---|
| Task 1 (TypeError fix) ↔ Task 2 (version bump) | Independent — different files, no shared interface | Ruling: parallel OK |
| Task 1 ↔ Task 3 (embeddings tests) | Independent — different files, no shared interface | Ruling: parallel OK |
| Task 2 (version bump) ↔ Task 4 (CLAUDE.md rewrite) | Task 2 edits CLAUDE.md Status line. Task 4 rewrites CLAUDE.md completely. If both run in parallel, Task 4's edit will clobber Task 2's bump. | **Ruling: Task 4 must wait until Task 2 lands.** Add Task 2 as Task 4's blockedBy. |
| Working tree state between tasks | Pre-commit hooks may auto-stage bundled changes (per `drift-bundling-recovery.md` memory) | Ruling: each implementer runs `git status --short` after committing to verify only expected files landed. |
| Bash CWD | Each implementer may inherit wrong CWD | Ruling: every brief includes `cd /Users/les/Projects/oneiric` before any command. |
| embeddings.py 31% coverage | Need to verify the untested paths are reachable from production (per otel.py importer). If reachable, add tests. If dead, prune. | Ruling: Task 3 implementer must read the file first to decide. |

---

## Tasks

| # | Title | Status |
|---|---|---|
| 1 | Fix TypeError→ValueError in remote loader + cli manifest helpers (Bugs A.2, A.3) | pending |
| 2 | Bump version 0.21.0 → 0.21.1 in 3 doc files (Bug B) | pending |
| 3 | Add test coverage for `oneiric/adapters/observability/embeddings.py` probe chain (Bug D) | pending |
| 4 | Rewrite CLAUDE.md to fix internal contradiction + test count + coverage + architecture tree + Python floor (Bugs C, E, F, G) | pending (blocked by Task 2) |
| 5 | End-to-end verification: full pytest suite green + coverage ratchet still passes | pending (blocked by Tasks 1-4) |

---

### Task 1: Fix TypeError→ValueError in remote loader + cli manifest helpers

**Files:**
- Modify: `oneiric/remote/loader.py:516`
- Modify: `oneiric/cli/__init__.py:554` (and parallel function for actions — likely ~line 580-600)
- Tests: `tests/remote/test_loader.py::test_parse_manifest_invalid_top_level`, `tests/remote/test_loader_comprehensive.py::test_rejects_non_mapping`, `tests/cli/test_helper_branches.py::test_cli_notification_and_manifest_helpers`

**Interfaces:**
- Consumes: existing `_parse_manifest`, `_manifest_entry_from_adapter`, `_manifest_entry_from_action` signatures (unchanged)
- Produces: same signatures, exception class changes from `TypeError` to `ValueError`

**Bug IDs**: A.2 (remote loader), A.3 (cli manifest helpers)

**Background** (read carefully):
- 3 tests on `main` fail because they `with pytest.raises(ValueError, match="must be a mapping")` (or `ValueError` plain) but production raises `TypeError`.
- `_parse_manifest` at `oneiric/remote/loader.py:516` raises `TypeError("Remote manifest must be a mapping at the top level.")` — test expects `ValueError("must be a mapping")`.
- `_manifest_entry_from_adapter` at `oneiric/cli/__init__.py:554` raises `TypeError(f"Unsupported factory type: {type(adapter.factory)}")` — test expects `ValueError`.
- `_manifest_entry_from_action` likely has a parallel `else: raise TypeError(...)` branch — same fix.
- A list `[1, 2, 3]` parsed from JSON is the right **type** (Python list) but wrong **value** (not a mapping), so `ValueError` is semantically correct.
- An int `factory=123` is the right **type** (`int`) for an `Any`-typed field but wrong **value** (not str or callable), so `ValueError` is semantically correct.

- [ ] **Step 1: Read the exact production lines to confirm the exception class**

Run:
```bash
cd /Users/les/Projects/oneiric && sed -n '510,525p' oneiric/remote/loader.py
```
And:
```bash
cd /Users/les/Projects/oneiric && sed -n '548,560p' oneiric/cli/__init__.py
```
And search for the parallel `_manifest_entry_from_action` branch:
```bash
cd /Users/les/Projects/oneiric && grep -n "_manifest_entry_from_action\|Unsupported factory type" oneiric/cli/__init__.py
```
Expected: discover the precise text of each `raise TypeError(...)` call site.

- [ ] **Step 2: Confirm the failing tests currently fail for the documented reason**

Run:
```bash
cd /Users/les/Projects/oneiric && .venv/bin/pytest tests/remote/test_loader.py::TestManifestParsing::test_parse_manifest_invalid_top_level tests/remote/test_loader_comprehensive.py::TestParseManifest::test_rejects_non_mapping tests/cli/test_helper_branches.py::test_cli_notification_and_manifest_helpers --no-cov 2>&1 | tail -25
```
Expected: 3 failed, each with `TypeError` shown in the trace.

- [ ] **Step 3: Fix `oneiric/remote/loader.py` — change `TypeError` → `ValueError`**

Edit `oneiric/remote/loader.py:516`. Replace:
```python
            raise TypeError("Remote manifest must be a mapping at the top level.")
```
with:
```python
            raise ValueError("Remote manifest must be a mapping at the top level.")
```

- [ ] **Step 4: Verify the remote loader fix**

Run:
```bash
cd /Users/les/Projects/oneiric && .venv/bin/pytest tests/remote/test_loader.py::TestManifestParsing::test_parse_manifest_invalid_top_level tests/remote/test_loader_comprehensive.py::TestParseManifest::test_rejects_non_mapping --no-cov 2>&1 | tail -10
```
Expected: 2 passed.

- [ ] **Step 5: Fix `oneiric/cli/__init__.py` — change `TypeError` → `ValueError` in both functions**

Edit `oneiric/cli/__init__.py`. Replace:
```python
            raise TypeError(f"Unsupported factory type: {type(adapter.factory)}")
```
with:
```python
            raise ValueError(f"Unsupported factory type: {type(adapter.factory)}")
```

Also find and fix the parallel `raise TypeError(...)` in `_manifest_entry_from_action`:
```bash
cd /Users/les/Projects/oneiric && grep -n "raise TypeError" oneiric/cli/__init__.py
```
Replace each occurrence with `raise ValueError(...)` keeping the f-string contents intact.

- [ ] **Step 6: Verify the CLI manifest helper fix**

Run:
```bash
cd /Users/les/Projects/oneiric && .venv/bin/pytest tests/cli/test_helper_branches.py::test_cli_notification_and_manifest_helpers --no-cov 2>&1 | tail -10
```
Expected: 1 passed.

- [ ] **Step 7: Run the full test suite to confirm no regressions**

Run:
```bash
cd /Users/les/Projects/oneiric && .venv/bin/pytest tests/ --no-cov -q 2>&1 | tail -10
```
Expected: only the 3 version_consistency tests fail (those are fixed by Task 2). All other tests pass.

- [ ] **Step 8: Commit**

```bash
cd /Users/les/Projects/oneiric && git -c user.email=les@wedgwoodwebworks.com add oneiric/remote/loader.py oneiric/cli/__init__.py
git -c user.email=les@wedgwoodwebworks.com commit -m "fix(oneiric): raise ValueError not TypeError for invalid manifest + factory

Bug A.2 and A.3 from docs/audits/2026-09-05-oneiric-audit.md:
3 tests on main were failing because they expected ValueError
(per Python convention: ValueError = right type wrong value;
TypeError = wrong type) but production raised TypeError.

Affected sites:
- oneiric/remote/loader.py:516 (top-level non-mapping manifest)
- oneiric/cli/__init__.py:_manifest_entry_from_adapter (int factory)
- oneiric/cli/__init__.py:_manifest_entry_from_action (parallel)

Both are semantically ValueError: a JSON-parsed list IS the right
type (Python list) but wrong value (not a mapping); an int factory
IS the right type (int) but wrong value (not str or callable).

Turns build from RED to partial-GREEN (3 of 6 failing tests fixed;
remaining 3 are version_consistency doc drifts, fixed in next commit)."
```

---

### Task 2: Bump version 0.21.0 → 0.21.1 in 3 doc files

**Files:**
- Modify: `CLAUDE.md` (Status header)
- Modify: `README.md` (version badge / banner)
- Modify: `docs/CLI_REFERENCE.md` OR `docs/cli-reference.md` (header — exact path to be discovered by implementer)
- Tests: `tests/unit/test_version_consistency.py::TestVersionConsistency::test_claude_status_matches`, `test_readme_banner_matches`, `test_cli_reference_header_matches`

**Bug ID**: B

**Background**:
- `pyproject.toml` version is `0.21.1`. CLAUDE.md, README, CLI reference header all still say `0.21.0`.
- `tests/unit/test_version_consistency.py` is the test that catches the drift — already failing on `main`.

- [ ] **Step 1: Discover exact lines that need bumping**

Run:
```bash
cd /Users/les/Projects/oneiric && grep -n "0.21.0" CLAUDE.md README.md docs/CLI_REFERENCE.md 2>/dev/null
```
Expected: each file has the string `0.21.0` once, on a line that's a header or version stamp.

If `docs/CLI_REFERENCE.md` doesn't exist, find the actual CLI reference file:
```bash
cd /Users/les/Projects/oneiric && find docs/ -iname "*cli*ref*" -o -iname "*reference*" 2>/dev/null | head -10
```
The test expects the file at whatever path `tests/unit/test_version_consistency.py` configures (read the test for the exact path).

- [ ] **Step 2: Read the test to know the exact expected format**

Run:
```bash
cd /Users/les/Projects/oneiric && sed -n '1,80p' tests/unit/test_version_consistency.py
```
Expected: discover the patterns/regex used to extract versions from each doc file, so the edit matches.

- [ ] **Step 3: Fix CLAUDE.md Status line**

Edit `CLAUDE.md`. Find the line containing `0.21.0` (likely near top: `**Status:** Production Ready (0.21.0)`). Replace `0.21.0` with `0.21.1`.

- [ ] **Step 4: Fix README.md version stamp**

Edit `README.md`. Find the line containing `0.21.0` (likely a badge `[![Version](...0.21.0...)]()` or banner). Replace `0.21.0` with `0.21.1`.

- [ ] **Step 5: Fix the CLI reference header**

Edit the file at the path discovered in Step 1 (most likely `docs/CLI_REFERENCE.md`). Replace `0.21.0` with `0.21.1` in its header line.

- [ ] **Step 6: Verify all 3 version_consistency tests pass**

Run:
```bash
cd /Users/les/Projects/oneiric && .venv/bin/pytest tests/unit/test_version_consistency.py --no-cov -v 2>&1 | tail -15
```
Expected: 5 passed (or 4 passed + 1 skipped — same as baseline before Task 1 fixed).

- [ ] **Step 7: Commit**

```bash
cd /Users/les/Projects/oneiric && git -c user.email=les@wedgwoodwebworks.com add CLAUDE.md README.md docs/CLI_REFERENCE.md
git -c user.email=les@wedgwoodwebworks.com commit -m "docs(oneiric): bump version stamp 0.21.0 -> 0.21.1 across CLAUDE.md, README, CLI ref

Bug B from docs/audits/2026-09-05-oneiric-audit.md:
pyproject.toml was bumped to 0.21.1 in commit 52f25cb but the three
doc files that hard-code the version were not updated. Test
test_version_consistency.py caught the drift on every CI run since
the bump.

Turns the remaining 3 failing tests on main green.

The CLAUDE.md rewrite in the next commit (Task 4) will tighten the
status header and update test/coverage counts; this commit only
fixes the version stamp string."
```

---

### Task 3: Add test coverage for `oneiric/adapters/observability/embeddings.py` probe chain

**Files:**
- Read first: `oneiric/adapters/observability/embeddings.py` (490 lines)
- Existing tests: `tests/adapters/test_observability_embeddings.py` and `tests/adapters/observability/test_embeddings.py` — review what's already covered
- Add tests: extend the existing test file (likely `tests/adapters/test_observability_embeddings.py`)

**Bug ID**: D

**Background**:
- `embeddings.py` is 31% covered (145/211 statements untested). Lowest module in the audit.
- Class `EmbeddingService` is imported by `oneiric/adapters/observability/otel.py:11` — production code uses it.
- Untested line ranges per coverage agent: 110-135 and 285-490. The 285-490 range is likely the probe chain (`_probe_llama_cpp`, `_probe_ollama`, `_probe_minimax`, `_probe_model2vec`, `_encode_llama_cpp`, `_encode_ollama`, `_encode_minimax`, `_encode_model2vec`) and `_probe_encode_via`.
- The probe chain is the EMBEDDING BACKEND DISCOVERY logic — if it silently fails, production has no embeddings and doesn't know it. High-value test target.

- [ ] **Step 1: Read the existing test file to understand conventions**

Run:
```bash
cd /Users/les/Projects/oneiric && wc -l tests/adapters/test_observability_embeddings.py tests/adapters/observability/test_embeddings.py 2>/dev/null
cd /Users/les/Projects/oneiric && head -50 tests/adapters/test_observability_embeddings.py 2>/dev/null
```
Expected: discover existing test patterns, fixtures, mocking conventions.

- [ ] **Step 2: Read the untested probe chain methods to understand the surface**

Run:
```bash
cd /Users/les/Projects/oneiric && sed -n '284,490p' oneiric/adapters/observability/embeddings.py
```
Expected: see the full `_probe_*` and `_encode_*` family.

- [ ] **Step 3: Verify which methods are reachable from production**

Run:
```bash
cd /Users/les/Projects/oneiric && grep -n "_probe\|encode_llama\|encode_ollama\|encode_minimax\|encode_model2vec" oneiric/adapters/observability/embeddings.py
```
Expected: confirm the probe chain is called from `initialize()` (which otel.py calls). All methods should be reachable.

- [ ] **Step 4: Write failing tests for the probe chain**

Add tests to `tests/adapters/test_observability_embeddings.py`. Cover:
- `_probe_llama_cpp` returns False when subprocess fails, True when llama-server responds
- `_probe_ollama` returns False when HTTP request fails, True when /api/tags returns
- `_probe_minimax` returns False when API call fails, True when API responds
- `_probe_model2vec` returns True when model2vec is available
- `_encode_llama_cpp` calls HTTP with correct payload, returns parsed embeddings
- `_encode_ollama` calls HTTP with correct payload, returns parsed embeddings
- `_encode_minimax` calls HTTP with correct payload, returns parsed embeddings
- `_encode_model2vec` returns model2vec embeddings

Use the existing test patterns (likely `unittest.mock.AsyncMock`, `pytest.MonkeyPatch`, etc.) — match the file's conventions.

- [ ] **Step 5: Run the new tests to verify they fail**

Run:
```bash
cd /Users/les/Projects/oneiric && .venv/bin/pytest tests/adapters/test_observability_embeddings.py --no-cov -v 2>&1 | tail -25
```
Expected: new tests fail (because the implementation isn't there yet) — but that's wrong. Actually, since the methods EXIST but aren't tested, the tests should PASS when the assertions are correct. The "failing test" step here means: run them and see what coverage report says.

- [ ] **Step 6: Run coverage to verify improvement**

Run:
```bash
cd /Users/les/Projects/oneiric && rm -f .coverage && .venv/bin/pytest tests/adapters/test_observability_embeddings.py --cov=oneiric.adapters.observability.embeddings --cov-report=term-missing --no-cov= 2>&1 | tail -30
```
Wait, that's wrong syntax. Use:
```bash
cd /Users/les/Projects/oneiric && rm -f .coverage && .venv/bin/pytest tests/adapters/test_observability_embeddings.py --cov=oneiric.adapters.observability.embeddings --cov-report=term-missing 2>&1 | tail -40
```
Expected: coverage of `embeddings.py` rises from 31% toward 60%+.

- [ ] **Step 7: Run full test suite to confirm no regressions**

Run:
```bash
cd /Users/les/Projects/oneiric && .venv/bin/pytest tests/ --no-cov -q 2>&1 | tail -10
```
Expected: 0 failed (after Task 1 + Task 2 fixes); all previously-passing tests still pass.

- [ ] **Step 8: Commit**

```bash
cd /Users/les/Projects/oneiric && git -c user.email=les@wedgwoodwebworks.com add tests/adapters/test_observability_embeddings.py
git -c user.email=les@wedgwoodwebworks.com commit -m "test(oneiric): add coverage for EmbeddingService probe chain

Bug D from docs/audits/2026-09-05-oneiric-audit.md:
oneiric/adapters/observability/embeddings.py was at 31% coverage
(145 of 211 statements untested). The probe chain methods
(_probe_llama_cpp, _probe_ollama, _probe_minimax, _probe_model2vec)
and encode-via-X methods were the largest untested block (lines
285-490).

If the probe chain silently fails, production loses embeddings
without knowing it. Added tests for the probe and encode paths
to surface regressions and document expected behavior.

Coverage target: 60%+ on embeddings.py (from 31%)."
```

---

### Task 4: Rewrite CLAUDE.md to fix internal contradiction + test count + coverage + architecture tree + Python floor

**Files:**
- Modify: `CLAUDE.md` (header section, status line, architecture tree, version floor)
- Tests: `tests/unit/test_version_consistency.py::TestVersionConsistency::test_claude_status_matches` (must stay green)

**Bug IDs**: C, E, F, G (all in CLAUDE.md)

**Background**:
- CLAUDE.md has an internal contradiction: line 11 says "Production Ready (0.21.0)" / "Score: 95/100"; line 527 area says "Score: 68/100" for v0.16.2 (audit history).
- Test count claim: 4112 (actual: 4196).
- Coverage claim: 83% (actual: 98.04%).
- Architecture tree claims `oneiric/cli.py` exists; actual is `oneiric/cli/` package + `oneiric/core/cli.py`.
- Python floor claim: 3.13+ (actual: >=3.14 in pyproject.toml).
- Task 2 already bumped the Status line version from 0.21.0 to 0.21.1. This task tightens the rest of the Status header and updates the body.

- [ ] **Step 1: Read the current CLAUDE.md Status section and audit history**

Run:
```bash
cd /Users/les/Projects/oneiric && sed -n '1,30p' CLAUDE.md
```
And:
```bash
cd /Users/les/Projects/oneiric && grep -n "Score:\|4112\|83%\|3.13+\|oneiric/cli.py" CLAUDE.md
```
Expected: discover the exact lines and their context.

- [ ] **Step 2: Rewrite the Status header to be self-consistent**

Replace the Status header at the top of CLAUDE.md (currently 1-3 lines around `Production Ready (0.21.0)`) with:

```markdown
**Status:** Production Ready (0.21.1) — see `docs/STAGE5_FINAL_AUDIT_REPORT.md` for the most recent comprehensive audit. Current state: 4196 tests passing, 98.04% coverage, +19pp margin over the 78.75% ratchet baseline.

**Python Version:** 3.14+ (async-first, modern type hints)
```

This addresses:
- Bug B (already done by Task 2; this rewrites for clarity)
- Bug C (eliminates the dual score by pointing to the canonical report)
- Bug E (corrects test count and coverage)
- Bug G (corrects Python floor to 3.14+)

- [ ] **Step 3: Fix the architecture tree to match reality**

Find the architecture tree block (likely under `## Architecture` / `### Key Components`). Replace any reference to `oneiric/cli.py` with the correct path. The current state:

```
oneiric/cli.py           # CLI module
```
or similar. Replace with:
```
oneiric/cli/             # CLI package (Typer commands, bridge helpers)
oneiric/core/cli.py      # Core CLI primitives
```

This addresses Bug F.

- [ ] **Step 4: Find and fix any remaining stale numbers in the body**

Run:
```bash
cd /Users/les/Projects/oneiric && grep -n "4112\|83%\|3.13+\|0.16.2" CLAUDE.md
```
For each match: either correct the number to current state OR explicitly label the line as historical ("as of v0.16.2 audit" / "before the 0.20.x rewrite"). Do not silently update — make it clear what's historical.

- [ ] **Step 5: Verify CLAUDE.md version_consistency test still passes**

Run:
```bash
cd /Users/les/Projects/oneiric && .venv/bin/pytest tests/unit/test_version_consistency.py --no-cov -v 2>&1 | tail -15
```
Expected: 5 passed (or 4 passed + 1 skipped).

- [ ] **Step 6: Cross-check all audit claims against reality one more time**

Run:
```bash
cd /Users/les/Projects/oneiric && .venv/bin/pytest tests/ --collect-only -q 2>&1 | tail -3
```
Cross-check: did the test count change since the audit? If it did by more than ±10, update the CLAUDE.md number again.

- [ ] **Step 7: Commit**

```bash
cd /Users/les/Projects/oneiric && git -c user.email=les@wedgwoodwebworks.com add CLAUDE.md
git -c user.email=les@wedgwoodwebworks.com commit -m "docs(oneiric): rewrite CLAUDE.md to fix drift (Bugs C, E, F, G)

Bug C: Status header now points to STAGE5_FINAL_AUDIT_REPORT.md as
the canonical audit; eliminates the dual-score contradiction
between the header (95/100 / 0.21.0) and the historical line
near the bottom (68/100 / 0.16.2).

Bug E: Updated test count (4112 -> 4196) and coverage (83% ->
98.04%). Coverage is now ABOVE the 78.75% ratchet by +19pp.

Bug F: Architecture tree now shows oneiric/cli/ package and
oneiric/core/cli.py separately instead of a non-existent
oneiric/cli.py file.

Bug G: Python floor corrected from 3.13+ to 3.14+ (matching
pyproject.toml requires-python).

Bug B version bump (0.21.0 -> 0.21.1) was already landed in the
previous commit (Task 2); this commit tightens the Status header
to make the version stamp self-consistent."
```

---

### Task 5: End-to-end verification

**Files:**
- Read: all changed files (verify no orphan drift)
- Run: full pytest suite, coverage report, mypy, bandit

- [ ] **Step 1: Run full pytest suite with coverage**

Run:
```bash
cd /Users/les/Projects/oneiric && rm -f .coverage coverage.xml && .venv/bin/pytest tests/ --cov=oneiric --cov-report=term --cov-report=xml -q 2>&1 | tail -15
```
Expected: 0 failed, coverage >= 98.04% (Tasks 1-3 should not regress; Task 3 should raise coverage further if it lands).

- [ ] **Step 2: Run mypy on changed files**

Run:
```bash
cd /Users/les/Projects/oneiric && .venv/bin/mypy oneiric/remote/loader.py oneiric/cli/__init__.py 2>&1 | tail -10
```
Expected: 0 errors (no new type issues from changing `TypeError` → `ValueError`).

- [ ] **Step 3: Run bandit on changed files**

Run:
```bash
cd /Users/les/Projects/oneiric && .venv/bin/bandit -r oneiric/remote/loader.py oneiric/cli/__init__.py 2>&1 | tail -20
```
Expected: no new HIGH severity issues.

- [ ] **Step 4: Verify git status is clean (modulo inventory artifacts)**

Run:
```bash
cd /Users/les/Projects/oneiric && git status --short
```
Expected: 0 modified files outside inventory gitignored dir.

- [ ] **Step 5: Verify all 4 task commits landed on main**

Run:
```bash
cd /Users/les/Projects/oneiric && git log --oneline -5
```
Expected: 4 commits from this plan + the audit memo commit (`docs(oneiric): add audit memo...`) as the 5th.

- [ ] **Step 6: Update inventory ledger with completion**

Edit `/Users/les/Projects/oneiric/.superpowers/sdd/2026-09-05-oneiric-audit/progress.md` (create if doesn't exist):
```markdown
# SDD ledger — Phase 4 plan

## Tasks
| # | Title | Status | Commit |
|---|---|---|---|
| 1 | Fix TypeError→ValueError | complete | (filled by implementer) |
| 2 | Version bump docs | complete | (filled) |
| 3 | embeddings.py coverage | complete | (filled) |
| 4 | CLAUDE.md rewrite | complete | (filled) |
| 5 | End-to-end verification | complete | (no commit — verification only) |
```

- [ ] **Step 7: Final report**

Report to user:
- All 6 originally-failing tests now green
- Coverage delta (e.g., 98.04% → 98.5%+)
- 4 task commit SHAs
- Any concerns / follow-up items (LOW-severity bugs H, I, K not addressed in this plan)

---

## Rulings (decisions made on your behalf)

**Ruling (Task 4 blocked by Task 2):** Both edits target CLAUDE.md. If parallel, Task 4 clobbers Task 2's version bump. Sequential required: Task 2 → Task 4. Add blockedBy in TaskList.

**Ruling (Bug A.2 + A.3 same fix pattern):** Both bugs are `TypeError` → `ValueError`. Combined into one task (Task 1) since the diff is mechanical and the rationale is identical. Keeps the task count manageable (4 implementation tasks vs 6).

**Ruling (embeddings.py tests not prune):** `otel.py` imports `EmbeddingService`. Code is reachable. Add tests, don't prune. Decision recorded in Task 3 Step 3.

**Ruling (LOW-severity items H, I, K deferred):** These are style cleanups. mcp-common Phase 2 showed that audit-counted bug entries (e.g., "10 print() sites") often close as no-op after pre-flight. Defer to a follow-up plan after this one ships.

---

## Cross-repo coordination

**None.** All work in `/Users/les/Projects/oneiric`. No crackerjack changes. No mcp-common changes. The existing release-audit check (added in mcp-common Phase 1) covers oneiric CHANGELOG/CLAUDE.md drift detection at publish time, so this plan improves CLAUDE.md quality before the next oneiric release.
