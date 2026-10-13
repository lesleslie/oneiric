## Context

`RuntimeOrchestrator` previously took a single
`enable_workflow_checkpoints: bool | None` flag that gated BOTH
`WorkflowCheckpointStore` (Store 1, task-completion resume) AND
`WorkflowExecutionStore` (Store 2, execution tracing). The two stores
have different durability characteristics:

- **Store 1** is file-based SQLite intended for long-running, resumable
  workflows on hosts with persistent disks. It is **not** serverless-safe.
- **Store 2** is intended for fine-grained execution tracing, observability,
  and postmortem analysis. It benefits from a pluggable backend (Redis,
  Postgres, S3) so serverless consumers can use their existing adapters.

A single boolean forced consumers to either accept both stores or reject
both, even when their use cases only wanted one. Crackerjack disables
both (quality gates re-execute every phase from a fresh state); other
consumers may want Store 2 without Store 1 (or vice versa).

## Decision rule

Split the unified flag into two independent flags:

- `enable_task_resume: bool | None` — gates Store 1 only.
- `enable_execution_tracing: bool | None` — gates Store 2 only.

**Back-compat**: if neither new flag is set explicitly, fall back to the
legacy `workflow_checkpoints_enabled` setting so existing callers do
not break. The legacy `enable_workflow_checkpoints` keyword argument
remains supported and overrides both new flags (sets both to its value)
to preserve existing call-site behavior.

## Implementation surface

| File | Change |
|---|---|
| `oneiric/runtime/orchestrator.py` | Accept both new flags. Set `self._task_resume_enabled` and `self._execution_tracing_enabled`. Construct the corresponding store only when its flag is true. |
| `oneiric/domains/workflows.py` | `WorkflowBridge.__init__` accepts both flags. The bridge drops `_checkpoint_store` when `enable_task_resume=False` and skips building `_execution_hooks` when `enable_execution_tracing=False`. |
| `oneiric/modes/utils.py` | The supervisor-disabled auto-disable still sets `workflow_checkpoints_enabled=False`; that flows through the back-compat path and turns off both stores. |
| `oneiric/runtime/durable.py` | `WorkflowExecutionStore` accepts an optional `adapter: OneiricAdapter | None`. When provided and the adapter duck-types the `WorkflowExecutionStoreProtocol` methods (`start_run`/`finish_run`/`start_node`/`finish_node`), writes are routed through the adapter. The store remains functional without an adapter (SQLite-only default) for dev/CI use. |

The pluggability surface is `OneiricAdapter` per the canonical adapter
contract. Adapters that satisfy the execution-store duck type route
writes through themselves; the SQLite path remains as the local
fallback for `load_run` / `load_nodes` so reads always work.

## Status

Implemented on branch `feat/store-2-split`. Crackerjack's opt-in to
`enable_execution_tracing=True` ships separately on branch
`feat/store-2-only` (one PR per repo, in keeping with the pre-1.0
merge-policy).