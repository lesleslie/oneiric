---
name: state-policy
description: "Workflow state policy for the Bodai ecosystem. Distinguishes input, process, and output state. Defines the four rules for how each kind should be used by oneiric workflow consumers (mahavishnu, crackerjack, akosha, session-buddy). Crackerjack is the reference implementation."
status: active
role: canonical
topic: workflow-state
date: 2026-10-13
last_reviewed: 2026-10-13
---

# Workflow State Policy

The Bodai ecosystem runs many workflows through oneiric's `WorkflowBridge.execute_dag`. Each workflow is shaped by what state it carries, how it carries it, and how that state is invalidated or shared. This document is the cross-cutting policy for **all** Bodai workflow consumers.

Crackerjack is the reference implementation. The two crackerjack decision notes that implement this policy are the canonical examples:

- `crackerjack/.claude/decisions/2026-10-13-checkpoint-disabled.md` — Rules 1 and 2
- `crackerjack/.claude/decisions/2026-10-13-ratchet-staleness.md` — Rule 3

## The three kinds of state

| Kind | Definition | Example | Lifetime |
|---|---|---|---|
| **Input state** | Exists before the workflow starts; the workflow reads it but does not own it. | git working tree, `coverage.json`, source files, settings files, `.coverage-ratchet.json` | Pre-existing; preserved across runs |
| **Process state** | Created by the workflow during a single run; ideally discarded on completion. | oneiric checkpoint store, in-memory DAG state, session trackers, pids | Created during a run; should be fresh each time |
| **Output state** | Persists after the workflow ends; consumed by humans, by other workflows, by release tools. | ratchet files, log files, git commits, run records | Persists across runs; read by external consumers |

The most common source of subtle bugs is conflating these. Oneiric's persistent checkpoint store is a process state mechanism that, if used, can masquerade as output state to readers. State policies that don't explicitly categorize each kind drift over time.

## The four rules

### Rule 1: Quality-gate workflows should not checkpoint between phases

A workflow whose job is to verify state (crackerjack's entire purpose) should re-run every step every time. "Already passed" is a function of the previous input, not the current input. If a phase is expensive enough that you want to skip it on retry, that's a signal the phase belongs in a different (long-running) workflow, not a quality gate.

**Reference implementation:** crackerjack's `build_oneiric_runtime` constructs `RuntimeOrchestrator` with `enable_workflow_checkpoints=False`. The bridge's `_checkpoint_store` and `_execution_store` are both `None`. The in-memory DAG checkpoint in `oneiric/runtime/dag.py` is preserved for within-run information flow, but no state crosses run boundaries.

**Allowed exceptions:**

- **Long-running workflows** (deploys, migrations, distributed test fleets) where total runtime is hours and "resume after crash" saves real time. These should be **separate workflows**, not embedded in a quality-gate workflow.
- **Workflows with intentional retry semantics** for idempotency. Use the in-memory DAG checkpoint (the `checkpoint` MutableMapping in `execute_dag`) for this; do not persist.

### Rule 2: Process state must be invalidated at workflow start

If a workflow has any persisted process state, the **first** thing it does is wipe that state. Anything else means a stale state from a prior run can silently skip work.

**Reference implementation:** crackerjack's previous-session fix was a workaround for this rule: `_clear_oneiric_cache(runtime)` ran at the start of every run to wipe the persistent task state. The current (better) implementation is "disable the cache at the consumer level" — no cache to wipe, no race condition possible.

**Why this matters concretely:** in a 2026-10-12 crackerjack session, the persistent cache was a write-then-wipe no-op (cache filled during run, cleared at next run start). The cache was a "state file that existed only to be cleared" — a code smell that pointed to the underlying problem. Rule 2 says: if state only exists to be invalidated, it shouldn't exist.

**Concurrent-process hazard:** two agents on the same repo, both running a workflow, share the cache directory. Their `clear` calls interleave. Even with a perfect "clear at start" implementation, the cache is a coordination point. The cleanest fix is to remove the cache; the second-cleanest is to use per-workflow-key namespaces with strong ownership.

### Rule 3: Output state should self-describe its staleness

A `.coverage-ratchet.json` from last year is not equivalent to one from yesterday. Output state should include a generation timestamp and, when derived from other state, a reference to that source. Consumers (release audit, publish manager, dashboards) should refuse to use output state that is too old or whose source has drifted.

**Reference implementation:** `.coverage-ratchet.json` carries three new fields:
- `generated_at` (ISO-8601 timestamp of the write)
- `coverage_data_path` (absolute path to the `coverage.json` that produced the ratchet)
- `coverage_data_mtime` (mtime of that `coverage.json`)

The reader (`_read_ratchet_floor` at `crackerjack/checks/release_audit.py`) refuses ratchets older than `RATCHET_MAX_AGE_DAYS` (30 days) or whose `coverage_data_mtime` no longer matches the on-disk file. A stale ratchet is treated as missing.

**Pattern for other consumers:**

| State kind | Self-describe with | Consumer check |
|---|---|---|
| Coverage floor | `generated_at` + source path + source mtime | Refuse if older than N days OR source has changed |
| Build artifact index | `built_at` + source commit hash | Refuse if commit moved |
| Cache index | `rebuilt_at` + content hash | Refuse if hash mismatch |
| Run history | `started_at` + `ended_at` + run ID | Read all, no staleness check needed |

**Tunable window:** every staleness threshold should be configurable per-repo via settings, not hardcoded constants. Crackerjack currently has the constant in code; the follow-up moves it to `CrackerjackSettings.documentation.coverage_ratchet_max_age_days`.

### Rule 4: Concurrent agents need isolated state

Multiple agents/sessions on the same repo need separate process state. The merge workflow contract uses git worktrees for git state isolation; workflows need analogous isolation for any persisted process state.

**Concrete patterns:**

- **Per-worktree cache directories** keyed off `Path.cwd()` (oneiric's default). Two worktrees from the same repo have different cwds, so their caches don't collide.
- **Per-workflow-key namespaces** within a shared store. Crackerjack's `"crackerjack"` key in the oneiric checkpoint store is the model — different consumers (mahavishnu, akosha, session-buddy) use their own keys.
- **Per-session IDs** for long-running workflows that survive across agent sessions.

**Anti-pattern:** sharing process state across "the same repo" without isolation. If two agents on the same main checkout both run the workflow, their state interleaves. This is a silent failure mode (no error, just wrong results) and the policy is: don't share, isolate.

## Serverless considerations

Oneiric's `WorkflowCheckpointStore` is **file-based SQLite** at `oneiric/runtime/checkpoints.py:60` (`sqlite3.connect(self.path)`). This is **dead-on-arrival for serverless**:

- Lambda / Cloud Function / Vercel / Fly containers have ephemeral `/tmp` storage.
- Container recycle wipes the file.
- Cross-invocation state is impossible.
- Cold-start sees a fresh filesystem; the "first run" is always cold.

**For serverless consumers, the only viable state policy is Rule 1: do not checkpoint between phases.** The SQLite file cannot survive the runtime boundary, so any workflow that depends on cross-run state will silently lose it.

**For durable execution tracing (Store 2) on serverless:** the in-progress follow-up splits the unified `enable_workflow_checkpoints` flag into `enable_task_resume` (Store 1, file-based, NOT serverless-safe) and `enable_execution_tracing` (Store 2, pluggable backend). The Store 2 backend plugs into existing oneiric adapters (Redis, Postgres, S3) via the `AdapterProtocol` surface — no fresh storage abstraction. Serverless consumers configure their preferred adapter at startup.

## Migration guidance for existing consumers

| Consumer | Current state | Recommended action |
|---|---|---|
| **crackerjack** | Already migrated (2026-10-13) | Reference implementation |
| **mahavishnu** | Uses oneiric for workflow execution; pool tasks may persist intermediate state | Audit: are any pool tasks doing "skip what already passed"? Disable checkpointing if not. |
| **akosha** | Pattern-detection workflows; long-running but state is in the analysis output (DB rows), not the workflow | Likely already correct. Confirm checkpointing is disabled if analysis is deterministic. |
| **session-buddy** | Restore flows; cross-session state IS the point | Keep checkpointing. Add explicit staleness check on the restored state. |
| **oneiric CLI** | Multi-workflow; some workflows are short-lived, some long | Make `enable_workflow_checkpoints` per-workflow-key, not global. |

## The Store 1 / Store 2 split (next-workflow follow-up)

Oneiric's two stores are currently gated by the same boolean:

- **`WorkflowCheckpointStore`** (Store 1, task-completion resume) — file-based SQLite, file-bound, NOT serverless-safe
- **`WorkflowExecutionStore`** (Store 2, execution tracing) — also file-based SQLite currently, but the concept is portable to Redis/Postgres/S3

The recommended shape:

1. Oneiric splits the `enable_workflow_checkpoints` flag into `enable_task_resume` (Store 1) and `enable_execution_tracing` (Store 2), independently togglable.
2. Store 2's backend is pluggable via existing oneiric adapters (Redis, Postgres, S3) using the `AdapterProtocol` surface.
3. Crackerjack opts in to Store 2 only (no Store 1).
4. Mahavishnu's long-running pool tasks opt in to both, with Store 2 backed by Redis (serverless-friendly).
5. Akosha and session-buddy make their own decisions based on their state lifecycle.

This is a multi-PR rollout; track as separate work in each component.

## Decision status

Active. All Bodai workflow consumers are expected to follow these four rules. New code is expected to comply from the start; existing code is expected to migrate as part of its next maintenance cycle. Compliance is reviewed as part of the monthly Bodai-wide audit (per the mcp-backend-wiring-discipline cadence).

Reference implementations:
- `crackerjack/.claude/decisions/2026-10-13-checkpoint-disabled.md` — Rules 1 and 2
- `crackerjack/.claude/decisions/2026-10-13-ratchet-staleness.md` — Rule 3
- (Future) per-consumer decision notes when each component migrates to this policy.
