# Oneiric Audit — 2026-09-05

**Repo**: `/Users/les/Projects/oneiric` (version 0.21.1)
**Scope**: production bugs + coverage gaps + code smells + documentation drift
**Method**: 4 parallel inventory subagents (coverage, bugs, doc-drift, smells)
**Status**: read-only inventory — no code changes proposed in this document
**Sister audit**: `mahavishnu/docs/superpowers/specs/2026-09-05-mcp-common-phase1-design.md`

---

## TL;DR

oneiric is **production-ready** but has accumulated drift between docs and reality:

| # | Severity | Finding | Effort |
|---|---|---|---|
| A | **HIGH** | **6 tests failing on `main`** (3 version-consistency, 2 remote loader, 1 CLI helper). Build is RED. | small |
| B | **HIGH** | CLAUDE.md / README / CLI ref claim **version 0.21.0** but pyproject is **0.21.1**. 3 doc files drifted. | trivial |
| C | **HIGH** | CLAUDE.md **internal contradiction**: line 11 says "v0.21.0 / 95-100 score", line 527 says "v0.16.2 / 68-100 score". | trivial |
| D | **MED** | `oneiric/adapters/observability/embeddings.py` only **31% covered** (145 of 211 stmts untested). Lowest module by far. | medium |
| E | **MED** | **CLAUDE.md drift on hard numbers**: claims 4112 tests (actual 4196 = +84) and 83% coverage (actual 98.04% = +15pp). | trivial |
| F | **MED** | `oneiric/cli.py` referenced in CLAUDE.md architecture tree but **does not exist** (actual: `oneiric/cli/` package + `oneiric/core/cli.py`). | small |
| G | **MED** | Python version floor drift: README badge + CLAUDE.md claim **3.13+**, but `pyproject.toml` `requires-python = ">=3.14"`. | trivial |
| H | **LOW** | 13 Python 2 `except X, Y:` sites — **style, not correctness** under PEP 758 (Python 3.14 accepts unparenthesized form). Same pattern as mcp-common Phase 2 Bug #9. | trivial |
| I | **LOW** | 7 production `assert` sites — bandit B101 violation, vanish under `python -O`. | trivial |
| J | **LOW** | 198 `print()` calls — but 90%+ are doctest `>>>` examples + Rich `console.print()`. Real production print() count likely <20. | trivial (probably no-op) |
| K | **LOW** | `# ty: ignore` (40) > `# type: ignore` (31) — in-flight ty migration needs canonicalization (5 lines carry both). | trivial |

**No** suspected "new" bugs beyond the 6 already-failing tests. Static type-checker (mypy) available; ty not installed in venv. Recent commit history (60 days) shows 15 fix commits — active maintenance, mostly quality-gate hygiene (ty, ruff, import sort).

---

## Detailed findings

### A. Failing tests on `main` (HIGH)

Six tests fail when running `pytest tests/ --no-cov`:

```
FAILED tests/cli/test_helper_branches.py::test_cli_notification_and_manifest_helpers
FAILED tests/remote/test_loader.py::TestManifestParsing::test_parse_manifest_invalid_top_level
FAILED tests/remote/test_loader_comprehensive.py::TestParseManifest::test_rejects_non_mapping
FAILED tests/unit/test_version_consistency.py::TestVersionConsistency::test_readme_banner_matches
FAILED tests/unit/test_version_consistency.py::TestVersionConsistency::test_cli_reference_header_matches
FAILED tests/unit/test_version_consistency.py::TestVersionConsistency::TestVersionConsistency::test_claude_status_matches
```

**Group 1 — version_consistency (3 failures, BUG #B fix above)**:
- All three assert that a string in some doc file matches the version in `pyproject.toml`
- All fail because docs say `0.21.0`, pyproject says `0.21.1`
- Fix: bump doc strings to `0.21.1`

**Group 2 — remote loader (2 failures)**:
- `test_parse_manifest_invalid_top_level` and `test_rejects_non_mapping` both feed `[1, 2, 3]` to `_parse_manifest()` and expect... a specific exception class.
- Current production code raises bare `TypeError("Remote manifest must be a mapping at the top level.")` (see `oneiric/remote/loader.py:516`).
- Test expects (need to read both tests) likely a `RemoteManifestError` or similar custom exception.
- This is a **real bug** in `oneiric/remote/loader.py`: it raises the wrong exception type. The test was written against an interface that the code doesn't match. Either:
  - The test is wrong (the production behavior is correct, raise bare TypeError)
  - The code is wrong (should raise a custom exception like `RemoteManifestError`)
- Needs a maintainer ruling.

**Group 3 — CLI helper (1 failure)**:
- `test_cli_notification_and_manifest_helpers` — a CLI helper branch test. Could be related to the recent BodaiCLIBase→OneiricCLIBase rename (commit `64bf1ec`).
- Likely same root cause as the loader bugs: post-rename test/code drift.

**Next step**: read each failing test's assertion message and the production code it's testing. The 3 version_consistency ones are doc fixes (Bug #B). The 3 loader/CLI ones need a maintainer call on whether to fix the test or the code.

---

### B. Version drift in CLAUDE.md / README / CLI ref (HIGH)

```
CLAUDE.md Status line says '0.21.0' but pyproject says '0.21.1'.
```

Three doc files all hard-code the version string and were not updated when `pyproject.toml` was bumped from 0.21.0 → 0.21.1.

**Verification needed**: spot-check that the 3 failing tests point to the right files. Likely:
- `CLAUDE.md` (line ~11, "Production Ready (X.Y.Z)" header)
- `README.md` (banner image / version badge)
- `docs/CLI_REFERENCE.md` or similar (header line)

Fix: bump the 3 strings to `0.21.1`. Trivial — likely 1-line changes per file.

---

### C. CLAUDE.md internal contradiction (HIGH)

Doc-drift agent found a self-contradiction in CLAUDE.md:

- Line 11 area: claims "**Status:** Production Ready (**0.21.0**)" + "**Score: 95/100**"
- Line 527 area: cites "**Score: 68/100**" for **v0.16.2** as part of the audit history

The "95/100 / v0.21.0" appears to be aspirational/copy-paste from a stale draft; the "68/100 / v0.16.2" is the historical fact. **CLAUDE.md should make the timeline clear** instead of presenting both numbers in different sections without context.

Fix: rewrite the status header to be self-consistent with the version (Bug #B fix) and either remove the audit history line or label it clearly as historical.

---

### D. Low-coverage module: `embeddings.py` 31% (MED)

`oneiric/adapters/observability/embeddings.py` has 211 statements, 145 untested. The largest untested blocks are line ranges 110-135 and 285-490 — likely the embedding serialization/deserialization paths and the cache tier logic.

**Action**: either add tests for the untested paths or — if those paths are not actually used in production — consider removing them. Likely requires reading the file to know.

Other low-coverage modules (less severe, > 60%):
- `oneiric/adapters/observability/__init__.py` — 36% (small file, may be re-exports)
- `oneiric/adapters/observability/streaming_compression.py` — 65%

---

### E. CLAUDE.md hard-number drift (MED)

| Claim | Documented | Actual | Drift |
|---|---|---|---|
| Test count | 4112 | 4196 | +84 |
| Coverage | 83% | 98.04% | +15pp |
| Audit score | 95/100 | unverified | possibly stale (see #C) |

The 98.04% actual coverage is significantly better than the 83% claim — the doc understates quality. Fix: update CLAUDE.md numbers to match reality.

---

### F. CLAUDE.md architectural tree drift (MED)

CLAUDE.md architecture tree claims a file `oneiric/cli.py` that does not exist. Actual layout:

```
oneiric/cli/           ← package
oneiric/core/cli.py    ← separate file
```

CLAUDE.md's `python -m oneiric.cli` examples may or may not still work depending on which one is the entry point. **Action**: update CLAUDE.md to match the actual `oneiric/cli/` package structure and verify the entry point.

---

### G. Python version floor drift (MED)

- README badge / CLAUDE.md: claim Python 3.13+
- `pyproject.toml`: `requires-python = ">=3.14"`
- `mypy.ini` / `.python-version`: likely also 3.14 (needs spot-check)

**Action**: update README badge + CLAUDE.md to say 3.14+. Affects install instructions.

---

### H. Python 2 except-comma sites (LOW — style only)

13 sites use `except X, Y:` (bare-identifier or dotted-name form). Under Python 3.14 PEP 758, this is **valid syntax**, not a bug. Same pattern as mcp-common Phase 2 Bug #9 (where 13 sites were parenthesized for modernization).

Fix: optional — wrap in parens for consistency with modern Python style. Trivial but mechanical.

**Locations** (per smells.md): spans `core/`, `runtime/`, `shell/`, `adapters/monitoring/`, `tools/`.

---

### I. Production `assert` sites (LOW)

7 sites. Each is a bandit B101 violation (asserts vanish under `python -O`). Same pattern as mcp-common Phase 2 Bug #7.

Fix: optional — replace with explicit `if not cond: raise RuntimeError(...)`. Trivial but mechanical.

**Note**: one of the 7 may be inside a docstring (mcp-common's Bug #7 was a docstring example). Verify before fixing.

---

### J. `print()` sites (LOW — likely no-op)

198 sites, but inflated by:
- Doctest `>>>` examples (e.g., `oneiric/core/ulid.py`)
- Rich `console.print()` (e.g., `oneiric/tools/mermaid_validator/renderer.py`)
- Legitimate CLI prompts and progress output

Real production `print()` count likely <20. Same pattern as mcp-common Phase 2 Bug #5 (which closed as no-op after pre-flight).

**Recommended action**: do not fix unless a specific site is identified as a real bug. Audit-on-demand only.

---

### K. `# ty: ignore` vs `# type: ignore` migration (LOW)

- `# ty: ignore`: 40 sites
- `# type: ignore`: 31 sites
- 5 lines carry both

Suggests an in-flight ty migration. Recommend: canonicalize to whichever tool is now authoritative (probably `# ty: ignore` per `crackerjack`'s default + the ty-rollout memory). Trivial.

---

## Things explicitly NOT found

- No open TODO/FIXME/XXX/HACK markers in production code (grep returned 0).
- No mutable default arguments (grep returned 0).
- No `time.sleep` in async code (grep returned 0).
- No `import requests` in async code (grep returned 0).
- No bare `except:` clauses (grep returned 0).
- Coverage gate is **PASSING** (98.04% ≥ 78.75% ratchet baseline, +19.29pp margin).
- Recent commits show active quality maintenance (15 fix commits in last 60 days).

---

## Recommended fix scope (proposed)

For the implementation plan (Phase 4), I'd recommend shipping these in a single coordinated release:

**Definitely ship (HIGH severity)**:
1. Fix the 3 version_consistency doc files → bumps tests pass (Bug #B)
2. Resolve CLAUDE.md internal contradiction (Bug #C)
3. Triage the 3 loader/CLI failures: maintainer ruling on whether test or code is right (Bug #A groups 2 + 3)

**Should ship (MED severity)**:
4. Rewrite CLAUDE.md to match current state: version, test count, coverage, Python floor, architecture tree (Bugs #E, #F, #G combined — single CLAUDE.md rewrite like mcp-common Phase 1)
5. Add coverage for `embeddings.py` core paths OR prune untested code (Bug #D)

**Optional (LOW severity)**:
6. Modernize 13 except-comma sites (Bug #H)
7. Replace 7 production asserts (Bug #I)
8. Canonicalize ty vs type ignores (Bug #K)

**Skip (no-op)**:
9. print() cleanup (Bug #J) — pre-flight would close as no-op

Total estimated effort: 3-5 commits across 2 repos (oneiric + maybe crackerjack if a new release-audit check is added).
