---
status: partial
role: implementation
date: 2026-10-29
last_reviewed: 2026-10-29
superseded_by: null
blocks_on: []
topic: resolver
---

# Resolver Precedence Contract and Empty-Result Explanation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Oneiric's resolver contract verifiable and truthful — align the canonical spec with the code's capability-coverage tier, pin both the registration-order tiebreak and the spec↔code relationship with tests, rewrite the user-facing `resolve-components` skill so it describes the real API instead of a fictional one, and make an empty resolution report *why* nothing won.

**Architecture:** The resolver is a single-winner selector. Candidates register per `(domain, key)` and are ranked by a descending lexicographic tuple `(override_score, capability_score, priority, stack_level, registry_sequence)`. **This plan changes no ranking behavior.** Task 1 reconciles the canonical spec with the code and pins the result. Task 2 rewrites a user-facing skill that documents an API which does not exist. Task 3 adds a `filtered` channel to `ResolutionExplanation` so capability-incompatible candidates are reported rather than silently dropped.

**Tech Stack:** Python 3.14, Pydantic v2, pytest (`asyncio_mode = "auto"`), `oneiric.plan_index.regenerate` for the plan index.

**Spec:** `docs/RESOLUTION_LAYER_SPEC.md` (role: `canonical`, status: `active`, topic: `resolver`)

## Global Constraints

- Canonical resolution contract is `docs/RESOLUTION_LAYER_SPEC.md`. Where this plan and that spec disagree, the spec wins — amend the spec explicitly, never silently.
- The resolver is a **single-winner total order**. Do not introduce search, backtracking, or constraint solving.
- The ranking tuple order is `(override_score, capability_score, priority, stack_level, registry_sequence)` — `oneiric/core/resolution.py:278`. Higher wins at every position.
- Registration order resolves **last registered wins** (`docs/RESOLUTION_LAYER_SPEC.md`, Precedence Rules tier 4).
- No new runtime dependencies. No new public constructor arguments on `Candidate`, `ResolverSettings`, or `CandidateRegistry`.
- Tests live at repo root `tests/` in oneiric, not `oneiric/tests/`.
- Every task's change must leave `crackerjack run -v -f` green for the touched paths.

## Review Focus

Input classes the spec implies but no existing test exercises, most likely to bite first:

1. **Re-registering an existing provider** must make it win the equal-priority tiebreak, because `registry_sequence` increments on every registration. Covered by Task 1.
2. **A configured selection naming a provider that was never registered.** `override_score` is 0 for every candidate, so ranking falls through to normal rules — but `explain()` currently appends "selection override prefers X" to *every* candidate's reasons, which reads as if the override were doing work. Covered by Task 1.
3. **A candidate with no `capabilities` metadata at all** must be excluded when capabilities are requested and `require_all=True`, and must score zero coverage under `require_all=False`. Covered by Task 3.
4. **A candidate matching only some requested capabilities** under `require_all=False` — coverage count is compared *before* priority, so a low-priority candidate with broader coverage wins. Covered by Task 3.
5. **Concurrent registration of equal-priority candidates.** The winner is whichever registration lands last, which is not deterministic across runs. This is inherent to the current design and is *documented*, not fixed.

## File Structure

| Path | Responsibility |
|---|---|
| `docs/RESOLUTION_LAYER_SPEC.md` | Canonical precedence contract. Task 1 amends the Precedence Rules list; Task 3 amends the Observability and API sections. |
| `oneiric/core/resolution.py` | Resolver implementation. Task 3 adds `FilteredCandidate` and the `filtered` field. |
| `tests/core/test_resolution.py` | Registry behaviour tests (classes `TestCandidateRegistry`, `TestResolutionPrecedence`, `TestExplainAPI`, `TestResolverFacade`). Task 1 and Task 3 add tests here. |
| `tests/core/test_resolution_comprehensive.py` | Dataclass-level tests (class `TestResolutionExplanation`). Task 3 adds tests here. |
| `tests/core/test_resolution_spec_sync.py` | **New.** Guards that the spec text and the code agree. Created by Task 1. |
| `~/.claude/skills/resolve-components/SKILL.md` | **New in Task 2 — outside the repository.** User-level skill; no repo-local source exists. |

---

### Task 1: Reconcile the spec with the code and pin the precedence contract

**Files:**
- Modify: `docs/RESOLUTION_LAYER_SPEC.md` (Precedence Rules section, ~line 29–65)
- Modify: `tests/core/test_resolution.py` (class `TestResolutionPrecedence`, ~line 281)
- Create: `tests/core/test_resolution_spec_sync.py`

**Interfaces:**
- Consumes: `CandidateRegistry.register_candidate(candidate: Candidate) -> None`; `CandidateRegistry.resolve(domain: str, key: str, provider: str | None = None, capabilities: Iterable[str] | None = None, *, require_all: bool = True) -> Candidate | None`; `CandidateRegistry.explain(domain: str, key: str, *, capabilities: Iterable[str] | None = None, require_all: bool = True) -> ResolutionExplanation`; `Candidate(domain=..., key=..., provider=..., priority=..., factory=..., metadata=..., source=...)`.
- Produces: no new API. Two test modules that pin existing behavior and guard the spec↔code relationship.

- [ ] **Step 1: Amend the spec's Precedence Rules list**

In `docs/RESOLUTION_LAYER_SPEC.md`, the "Precedence Order (highest to lowest)" numbered list currently reads: Explicit override → Inferred priority → Candidate metadata stack_level → Registration order. The code ranks **capability coverage above priority** (`oneiric/core/resolution.py:278`).

Insert capability coverage as a new tier between "Explicit override" and "Inferred priority", and add a clarifying paragraph that:

- With `require_all=True` (the default), candidates lacking any required capability are **excluded before ranking**, so coverage is uniform among survivors and does not differentiate.
- With `require_all=False`, candidates are **ranked** by the number of requested capabilities they satisfy, and that count is compared *before* priority — so a candidate with lower `priority` but broader coverage wins.

Update the `mermaid` precedence flowchart in the same section to match the new tier order.

Also append a paragraph to the same section noting that **registration order is order-dependent under concurrency**: when two equal-priority candidates register concurrently, the winner is whichever registration lands last, which is not deterministic across runs. This is inherent to the current design and is documented here deliberately, not fixed.

- [ ] **Step 2: Write the tiebreak pin test**

Add `test_last_registered_wins_at_equal_priority` to class `TestResolutionPrecedence` in `tests/core/test_resolution.py`. Register two `Candidate` objects with identical `domain="adapter"`, `key="cache"`, `priority=0`, `source=CandidateSource.MANUAL`, and distinct `provider` values (`"older"` then `"newer"`), both with `factory=lambda: None`. Assert:

```python
resolved = registry.resolve("adapter", "cache")
assert resolved is not None
assert resolved.provider == "newer"
```

Also assert `registry.explain("adapter", "cache").winner.provider == "newer"`, and that `explain().ordered` lists `"newer"` before `"older"`.

- [ ] **Step 3: Write the re-registration pin test**

Add `test_reregistered_provider_wins_equal_priority_tiebreak` to the same class. Register provider `"alpha"`, then register provider `"alpha"` again with identical `priority`. Assert the resolved provider is `"alpha"` and that the two `explain().ordered` entries carry distinct `registry_sequence` values, with the later one ordered first.

- [ ] **Step 4: Write the unmatched-selection test**

Add `test_selection_override_naming_unregistered_provider` to the same class. Construct `CandidateRegistry(ResolverSettings(selections={"adapter": {"cache": "ghost"}}))`, register one candidate with provider `"real"`. Assert `registry.resolve("adapter", "cache").provider == "real"` — the override matched nothing, so normal ranking applies. Also assert the resolved candidate's `reasons` list contains `"selection override prefers ghost"`.

- [ ] **Step 5: Run the new tests and confirm they pin current behavior**

Run: `./.venv/bin/pytest tests/core/test_resolution.py::TestResolutionPrecedence -v`

Expected: **PASS**. These are characterization tests for behavior that already exists.

> If any test in Steps 2–4 **FAILS**, the implementation contradicts `docs/RESOLUTION_LAYER_SPEC.md`. Stop. Reconcile the spec and the code deliberately — do **not** edit the assertion to match the code. The spec is canonical; either the code or the spec is wrong, and deciding which is the point of the task.

- [ ] **Step 6: Create the spec↔code sync guard**

Create `tests/core/test_resolution_spec_sync.py`. It must assert two things:

1. The spec text contains the string `"Registration order (last registered wins)"` — locate the file relative to the test via `Path(__file__).resolve().parents[2] / "docs" / "RESOLUTION_LAYER_SPEC.md"`.
2. The code's registration-sequence tiebreak is last in the ranking tuple, and last-registered wins — by registering two equal-priority candidates and asserting `explain().ordered[0].candidate.provider == "newer"`.

Read the spec with `read_text(encoding="utf-8")`. Do not assert on the full spec body; assert on the specific precedence strings so that unrelated spec edits do not break the guard.

- [ ] **Step 7: Run the sync guard**

Run: `./.venv/bin/pytest tests/core/test_resolution_spec_sync.py -v`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add docs/RESOLUTION_LAYER_SPEC.md tests/core/test_resolution.py tests/core/test_resolution_spec_sync.py
git commit --only docs/RESOLUTION_LAYER_SPEC.md tests/core/test_resolution.py tests/core/test_resolution_spec_sync.py -m "docs(resolver): align precedence spec with capability-coverage tier and pin tiebreak"
```

#### Integration Contract

- **Triggered from**: No runtime call path changes. This task is invoked by the resolver's existing public API (`CandidateRegistry.resolve`, `CandidateRegistry.explain`) through the new characterization tests.
- **Returns to / updates**: `docs/RESOLUTION_LAYER_SPEC.md` (Precedence Rules section only). No state, no store, no downstream artifact is mutated.
- **Demonstrable by**: `./.venv/bin/pytest tests/core/test_resolution.py::TestResolutionPrecedence tests/core/test_resolution_spec_sync.py -v` — all pass.
- **Rollback signal**: `tests/core/test_resolution_spec_sync.py` fails after an unrelated resolver change, or the spec's numbered precedence list no longer matches the tuple order at `oneiric/core/resolution.py:278`.
- **Observability added**: none at runtime. The guard converts a silent spec/code divergence into a failing test.

---

### Task 2: Rewrite the `resolve-components` skill to describe the real API

> **✅ Completed 2026-10-29** (out of band, from the mahavishnu planning
> session — the skill is user-level, so no repo commit was involved).
> Verified two ways: (a) all 17 ```python blocks scanned for the fictional
> symbols — **zero** matches; the only remaining mentions of
> `oneiric.core.resolver`, `oneiric.core.priority`, and `@priority` are in the
> prose, where they are named deliberately to warn against them. (b) every
> runnable example was **executed** against `oneiric/core/resolution.py` in
> oneiric's venv and asserted — resolve, explain, `as_dict()` shape, reasons
> list, shadowed list, override-wins-over-priority, capability filtering, and
> the precedence-holds block all pass. One correction came out of that run:
> `as_dict()["ordered"][i]["score"]` is a **tuple** in Python, not a JSON
> array — the skill now shows the tuple form and notes the JSON conversion.

**Files:**
- Modify: `~/.claude/skills/resolve-components/SKILL.md` (absolute path — this skill exists only at user level; there is no repo-local copy)

**Interfaces:**
- Consumes: the real public surface of `oneiric/core/resolution.py` — `Resolver`, `CandidateRegistry`, `Candidate`, `CandidateSource`, `ResolverSettings`, `ResolutionExplanation`.
- Produces: a corrected skill file. No Python API changes.

**Background the implementer needs (all verified against the source):**

The current skill documents an API that does not exist. These symbols have **zero** definitions in the oneiric source tree and must not appear in the rewritten skill:

`clear_selection`, `candidates`, `conflicts`, `set_priority`, `register_hook`, `ResolutionHook`, `candidates_with_capability`, `candidates_with_metadata`, `has_selection`, `get_selection`, and the module path `oneiric.core.resolver` (the real module is `oneiric.core.resolution`).

The current skill also documents `from oneiric.core.priority import priority` and an `@priority(...)` decorator. **Neither `oneiric/core/priority.py` nor any `priority` decorator exists.** Priority is a plain field: `Candidate(priority=...)`, or the `priority` argument of `register_pkg`.

The current skill's precedence table says registration order means "first registered wins" and places "Stack Order" above "Priority". Both contradict the spec and the code: registration order is **last registered wins**, and `stack_level` ranks **below** `priority`.

- [x] **Step 1: Replace the import and API surface**

Rewrite the "Implementation" section to use the real API:

```python
from oneiric.core.resolution import (
    Candidate,
    CandidateRegistry,
    CandidateSource,
    Resolver,
    ResolverSettings,
)
```

Real methods, with their exact signatures:

| Method | Signature |
|---|---|
| `CandidateRegistry.register_candidate` | `(candidate: Candidate) -> None` |
| `CandidateRegistry.resolve` | `(domain, key, provider=None, capabilities=None, *, require_all=True) -> Candidate \| None` |
| `CandidateRegistry.explain` | `(domain, key, *, capabilities=None, require_all=True) -> ResolutionExplanation` |
| `CandidateRegistry.list_active` | `(domain) -> list[Candidate]` |
| `CandidateRegistry.list_shadowed` | `(domain) -> list[Candidate]` |
| `Resolver.register` | `(candidate: Candidate) -> None` |
| `Resolver.resolve` | `(domain, key, provider=None, capabilities=None, *, require_all=True) -> Candidate \| None` |
| `Resolver.explain` | `(domain, key, *, capabilities=None, require_all=True) -> ResolutionExplanation` |

Note `Resolver.explain` takes `capabilities` as keyword-only; `CandidateRegistry.explain` accepts it as keyword too. Use keyword arguments for `capabilities` in both.

- [x] **Step 2: Replace the precedence table**

Replace the "Resolver Precedence" tier table with one matching `docs/RESOLUTION_LAYER_SPEC.md` exactly:

| Tier | Mechanism | Example | Precedence |
|---|---|---|---|
| 1. Explicit override | `ResolverSettings.selections[domain][key]` names a provider | `ResolverSettings(selections={"adapters": {"database": "postgres"}})` | Highest |
| 2. Capability coverage | count of requested capabilities satisfied | `metadata={"capabilities": [...]}` | High (only differentiates when `require_all=False`) |
| 3. Priority | `Candidate.priority`, higher wins | `Candidate(priority=100)` | Medium |
| 4. Stack level | `Candidate.stack_level`, higher wins | `Candidate(stack_level=10)` | Low |
| 5. Registration order | `registry_sequence`, **last registered wins** | register `"a"` then `"b"` → `"b"` wins | Lowest |

State explicitly that with `require_all=True` (the default) capability-incompatible candidates are excluded before ranking, so tier 2 does not differentiate.

- [x] **Step 3: Replace the fictional selection API**

There is no `resolver.select()` / `resolver.clear_selection()`. Selection is a *setting*, read via `ResolverSettings.selection_for(domain, key)`. Rewrite that section to show:

```python
settings = ResolverSettings(selections={"adapters": {"database": "postgres"}})
registry = CandidateRegistry(settings)
assert settings.selection_for("adapters", "database") == "postgres"
```

- [x] **Step 4: Replace the fictional priority API**

Remove the `@priority(100)` decorator example. Show the real mechanism:

```python
registry.register_candidate(
    Candidate(
        domain="adapters",
        key="database",
        provider="postgres",
        priority=100,
        factory=PostgresAdapter,
        source=CandidateSource.LOCAL_PKG,
    )
)
```

and note that `register_pkg(..., priority=...)` sets the priority for candidates that do not carry one (`oneiric/core/resolution.py:312`).

- [x] **Step 5: Remove the unsupported sections**

Delete the "Resolution Hooks" section (`ResolutionHook`, `register_hook`) and the "Component Metadata" subsections that call `candidates_with_capability` / `candidates_with_metadata`. Replace with the real metadata-bearing path: `Candidate.metadata` plus the `capabilities` argument on `resolve` / `explain`.

Keep the "Shadowed candidates" and "Conflict" material, but rewrite it to use `registry.list_shadowed(domain)` and `registry.explain(domain, key)` — the real read paths.

- [x] **Step 6: Add a source-of-truth pointer**

Add a line under the Overview:

> The canonical contract is `docs/RESOLUTION_LAYER_SPEC.md` in the oneiric repository. If this skill and that spec disagree, the spec is correct.

- [x] **Step 7: Verify every symbol in the rewritten skill exists**

For each Python symbol the skill names, confirm it is defined or exported in `oneiric/core/resolution.py`:

Run: `grep -nE "def (select|clear_selection|candidates|conflicts|set_priority|register_hook)|class ResolutionHook|oneiric\.core\.resolver|oneiric\.core\.priority" ~/.claude/skills/resolve-components/SKILL.md`

Expected: **no output** from the code blocks. Scope the check to the file's
```python blocks before running it — the prose deliberately names the fictions
in the Common Mistakes table and the priority note, so a naive whole-file
grep produces false positives. Any match inside a code block is a surviving
fiction — remove it.

Run: `grep -c "oneiric.core.resolution" ~/.claude/skills/resolve-components/SKILL.md`

Expected: at least 1.

- [x] **Step 8: Spot-check the corrected examples**

Confirm the skill's worked examples type-check against the real signatures by running the central one in oneiric's interpreter:

Run: `cd ~/Projects/oneiric && ./.venv/bin/python -c "from oneiric.core.resolution import Candidate, CandidateRegistry, CandidateSource, Resolver, ResolverSettings; r = CandidateRegistry(); r.register_candidate(Candidate(domain='adapters', key='database', provider='postgres', priority=100, factory=lambda: None, source=CandidateSource.LOCAL_PKG)); assert r.resolve('adapters','database').provider == 'postgres'; print('ok')"`

Expected: prints `ok`.

- [x] **Step 9: Commit**

The skill lives outside the repository, so it is not part of the repo commit. Commit only any repo-side change made in Step 1 or 2 of this task (there should be none — the spec was amended in Task 1):

```bash
git status --short
```

Expected: no new files beyond what Task 1 committed.

#### Integration Contract

- **Triggered from**: A user invoking the `resolve-components` skill, or an agent loading it to understand why a component was selected.
- **Returns to / updates**: `~/.claude/skills/resolve-components/SKILL.md` only. No repository file, no runtime state.
- **Demonstrable by**: The Step 7 greps return no matches, and the Step 8 snippet prints `ok`.
- **Rollback signal**: The skill names a symbol that `grep` confirms is absent from `oneiric/core/resolution.py`, or an example in the skill raises `AttributeError`/`ImportError` when run.
- **Observability added**: none. The skill is documentation; its correctness gate is the symbol-existence check in Step 7.

---

### Task 3: Explain an empty resolution instead of returning a bare `None`

**Files:**
- Modify: `oneiric/core/resolution.py` (`ResolutionExplanation` at ~line 76; `_score_candidates` at ~line 217; `as_dict` at ~line 89)
- Modify: `tests/core/test_resolution.py` (class `TestExplainAPI`)
- Modify: `tests/core/test_resolution_comprehensive.py` (class `TestResolutionExplanation`)
- Modify: `docs/RESOLUTION_LAYER_SPEC.md` (Observability section, ~line 319; API list, ~line 112)

**Interfaces:**
- Consumes: `CandidateRegistry.explain(domain, key, *, capabilities=None, require_all=True) -> ResolutionExplanation`; `Candidate.metadata` (capabilities live under `metadata["capabilities"]`); `_candidate_supports_capabilities(candidate, required, require_all=...) -> bool`; `_normalize_capabilities(capabilities) -> list[str]`.
- Produces:
  - `FilteredCandidate` dataclass — `candidate: Candidate`, `missing_capabilities: list[str]`.
  - `ResolutionExplanation` gains a new field `filtered: list[FilteredCandidate] = field(default_factory=list)`, appended **after** the existing required fields so existing positional construction keeps working.
  - `ResolutionExplanation.as_dict()` gains a `"filtered"` key: a list of `{"provider": str | None, "missing_capabilities": list[str]}`.

**Problem being solved:** `_score_candidates` drops capability-incompatible candidates *before* ranking (`oneiric/core/resolution.py`, the `continue` inside the candidate loop). They therefore never appear in `explain().ordered`. A caller whose resolution returned `None` sees an empty explanation and cannot distinguish "nothing was registered" from "three candidates existed and all were filtered out."

- [ ] **Step 1: Write the failing test for filtered candidates**

In `tests/core/test_resolution_comprehensive.py`, class `TestResolutionExplanation`, add a test that registers two candidates for `("adapter", "cache")`:

- `"full"` with `metadata={"capabilities": ["read", "write"]}`
- `"partial"` with `metadata={"capabilities": ["read"]}`

Then call `registry.explain("adapter", "cache", capabilities=["read", "write"])` and assert:

```python
assert explanation.winner is None
assert [e.candidate.provider for e in explanation.ordered] == []
assert len(explanation.filtered) == 1
assert explanation.filtered[0].candidate.provider == "partial"
assert explanation.filtered[0].missing_capabilities == ["write"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./.venv/bin/pytest tests/core/test_resolution_comprehensive.py::TestResolutionExplanation -v`

Expected: FAIL with `AttributeError: 'ResolutionExplanation' object has no attribute 'filtered'`.

- [ ] **Step 3: Implement `FilteredCandidate` and the new field**

In `oneiric/core/resolution.py`:

1. Change the import at line 7 to `from dataclasses import dataclass, field`.
2. Add immediately above the `ResolutionExplanation` dataclass:

```python
@dataclass
class FilteredCandidate:
    """A candidate excluded from ranking because it lacked required capabilities."""

    candidate: Candidate
    missing_capabilities: list[str]
```

3. Add to `ResolutionExplanation`, after `ordered`:

```python
    filtered: list[FilteredCandidate] = field(default_factory=list)
```

4. Extend `as_dict()` to include a `"filtered"` key mapping each entry to `{"provider": entry.candidate.provider, "missing_capabilities": entry.missing_capabilities}`.

- [ ] **Step 4: Populate `filtered` in `_score_candidates`**

In `_score_candidates`, the candidate loop currently skips incompatible candidates with a bare `continue`. Change it to record the exclusion instead. Compute the missing capabilities as the required capabilities the candidate does not satisfy, then append a `FilteredCandidate` to a local list and include that list in the returned `ResolutionExplanation`.

The missing-capability computation must handle the two `require_all` modes:

- `require_all=True`: every required capability is missing for a filtered candidate.
- `require_all=False`: only the required capabilities the candidate lacks are missing.

Reuse the existing capability helpers (`_candidate_capabilities`, `_normalize_capabilities`) rather than re-deriving capability sets inline. The set difference must be deterministic — return missing capabilities in the order they appear in the normalized required list, not in set-iteration order.

- [ ] **Step 5: Run the new test to verify it passes**

Run: `./.venv/bin/pytest tests/core/test_resolution_comprehensive.py::TestResolutionExplanation -v`

Expected: PASS.

- [ ] **Step 6: Write the remaining edge-case tests**

Add to `tests/core/test_resolution_comprehensive.py`, class `TestResolutionExplanation`:

- `test_filtered_empty_when_registry_has_no_candidates` — `explain("adapter", "cache")` on an empty registry yields `filtered == []` (backward compatible with the existing `test_explain_empty_registry`).
- `test_filtered_empty_when_candidate_lacks_capability_metadata_entirely` — a candidate with no `capabilities` in metadata, requested capabilities `["read"]`, `require_all=True` → excluded and listed in `filtered` with `missing_capabilities == ["read"]`.
- `test_partial_match_is_ranked_not_filtered` — under `require_all=False`, a candidate matching some capabilities appears in `ordered` (not `filtered`) and outranks an equal-priority candidate with zero coverage.

Add to `tests/core/test_resolution.py`, class `TestExplainAPI`:

- `test_explain_as_dict_includes_filtered` — `as_dict()` contains a `"filtered"` key; with one excluded candidate its entry has `provider` and `missing_capabilities` keys.
- `test_explain_as_dict_filtered_empty_list` — `as_dict()["filtered"] == []` when nothing was filtered.

- [ ] **Step 7: Run the full resolver test suite**

Run: `./.venv/bin/pytest tests/core/test_resolution.py tests/core/test_resolution_comprehensive.py tests/unit/test_core_resolution.py tests/core/test_resolution_spec_sync.py -v`

Expected: all PASS.

- [ ] **Step 8: Update the spec**

In `docs/RESOLUTION_LAYER_SPEC.md`:

- In the **Observability** section, extend the "Decision trace: show which rule decided the winner" bullet to state that the trace also reports candidates excluded by capability filtering, together with the capabilities they lacked.
- In the **APIs** section, amend the `explain(domain, key) -> decision trace` line to note the returned `ResolutionExplanation` carries `ordered` (ranked candidates), `winner`, and `filtered` (excluded candidates with their missing capabilities).
- In the **Precedence Rules** section, note that capability-incompatible candidates are excluded before ranking and are reported separately rather than ranked.

- [ ] **Step 9: Run the spec sync guard**

Run: `./.venv/bin/pytest tests/core/test_resolution_spec_sync.py -v`

Expected: PASS. The guard asserts on specific precedence strings, so the Task 3 spec edits must not remove them.

- [ ] **Step 10: Regenerate the plan index**

The plan index is auto-generated; do not hand-edit it.

Run: `cd ~/Projects/oneiric && ./.venv/bin/python -c "from pathlib import Path; from oneiric.plan_index.regenerate import regenerate; regenerate(Path('.').resolve())"`

Expected: `docs/plans/PLAN_INDEX.md` is rewritten and now lists this plan with status `active`.

- [ ] **Step 11: Commit**

```bash
git add oneiric/core/resolution.py tests/core/test_resolution.py tests/core/test_resolution_comprehensive.py docs/RESOLUTION_LAYER_SPEC.md docs/plans/PLAN_INDEX.md
git commit --only oneiric/core/resolution.py tests/core/test_resolution.py tests/core/test_resolution_comprehensive.py docs/RESOLUTION_LAYER_SPEC.md docs/plans/PLAN_INDEX.md -m "feat(resolver): report capability-filtered candidates in explain()"
```

#### Integration Contract

- **Triggered from**: `CandidateRegistry.explain(domain, key, capabilities=...)` and `Resolver.explain(domain, key, capabilities=...)` — reached from operator diagnostics (`oneiric explain` CLI, per `docs/RESOLUTION_LAYER_SPEC.md` → CLI Diagnostics) and from the resolver decision-trace logging in `CandidateRegistry.register_candidate`.
- **Returns to / updates**: The `ResolutionExplanation` returned to the caller. `winner` and `ordered` are **unchanged**; `filtered` is additive. `as_dict()` gains a key — any consumer that asserts an exact dict shape must be updated (grep the repo for `as_dict()` consumers of `ResolutionExplanation` before merging).
- **Demonstrable by**: `./.venv/bin/pytest tests/core/test_resolution_comprehensive.py::TestResolutionExplanation tests/core/test_resolution.py::TestExplainAPI -v` — all pass; and `registry.explain("adapter", "cache", capabilities=["read", "write"]).filtered` is non-empty for an incompatible candidate.
- **Rollback signal**: Any consumer of `ResolutionExplanation.as_dict()` breaks on the new `"filtered"` key, or `explain()` starts reporting candidates in `ordered` that were previously filtered out.
- **Observability added**: The decision trace now distinguishes "nothing registered" from "everything filtered out", so a failed capability negotiation is diagnosable from the trace alone instead of requiring registry introspection.

---

## Parking

This plan is **partially implemented** — `status: partial` in frontmatter.
**Task 2 is complete**; Tasks 1 and 3 remain parked for a dedicated
implementation session.

| Field | Value |
|---|---|
| Parked on | 2026-10-29 |
| Parked by | Claude (planning session, mahavishnu) |
| Reason | Deferred to a dedicated implementation session; no resolver behavior changes were wanted inside a planning session |
| Task 2 completed | 2026-10-29, out of band — the skill is user-level (`~/.claude/skills/`), so no repo commit was involved |
| Still parked | Task 1 (spec ↔ code reconciliation, tiebreak pins, spec sync guard), Task 3 (`filtered` channel on `ResolutionExplanation`) |
| Resume trigger | Any future session that needs to change resolver precedence, explainability, or resolver documentation |
| Working location | A worktree at `~/.local/state/mahavishnu/worktrees/oneiric/` (per the user-level worktree convention), **not** inside the oneiric repository |
| Implementation skill | `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` |

### Handoff notes for the implementing session

1. **Read `docs/RESOLUTION_LAYER_SPEC.md` first.** It is the canonical contract; Task 1 amends it.
2. **Do not change ranking behavior.** Every task here is documentation, pinning, or additive reporting. If a task seems to require changing the score tuple at `oneiric/core/resolution.py:278`, stop and re-read the spec.
3. **Task 2 is outside the repository.** `~/.claude/skills/resolve-components/SKILL.md` is user-level; it is not covered by the repo commit in Task 2, Step 9.
4. **Regenerate the plan index, never hand-edit it.** Use `oneiric.plan_index.regenerate` (Task 3, Step 10).
5. **Leave `uv.lock` alone.** It was already modified in the working tree at park time and belongs to other work.

### Related

- **Plan B:** `docs/plans/2026-10-29-resolver-scope-deferrals-and-triggers.md` — records which resolver features are deliberately *not* being adopted and the triggers that would reopen them.
- **Spec:** `docs/RESOLUTION_LAYER_SPEC.md`
