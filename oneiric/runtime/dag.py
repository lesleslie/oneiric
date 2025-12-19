"""NetworkX-backed DAG builder/executor prototype for orchestration parity."""

from __future__ import annotations

import inspect
import time
from collections.abc import Awaitable, Callable, Iterable, MutableMapping, Sequence
from dataclasses import dataclass, field
from typing import Any, TypedDict
from uuid import uuid4

import anyio
import networkx as nx

from oneiric.core.logging import get_logger
from oneiric.core.observability import observed_span
from oneiric.core.resiliency import run_with_retry
from oneiric.runtime.metrics import record_workflow_node_metrics

TaskCallable = Callable[[], Awaitable[Any]]
HookCallable = Callable[..., Awaitable[None] | None]

logger = get_logger("runtime.dag")


class _TaskFailedAfterRetries(Exception):
    """Internal exception to propagate retry attempt count."""

    def __init__(self, attempts: int, original_error: Exception):
        self.attempts = attempts
        self.original_error = original_error
        super().__init__(f"Task failed after {attempts} attempts")


@dataclass(slots=True)
class DAGTask:
    """Task definition used by the DAG prototype."""

    key: str
    depends_on: Sequence[str] = field(default_factory=tuple)
    runner: TaskCallable | None = None
    retry_policy: dict[str, Any] | None = None


class DAGExecutionError(RuntimeError):
    """Raised when DAG execution fails."""


@dataclass(slots=True)
class DAGExecutionHooks:
    """Optional callbacks invoked during DAG execution."""

    on_run_start: HookCallable | None = None
    on_run_complete: HookCallable | None = None
    on_run_error: HookCallable | None = None
    on_generation_start: HookCallable | None = None
    on_generation_complete: HookCallable | None = None
    on_node_start: HookCallable | None = None
    on_node_complete: HookCallable | None = None
    on_node_skip: HookCallable | None = None
    on_node_error: HookCallable | None = None


class DAGRunResult(TypedDict):
    run_id: str
    results: dict[str, Any]


def build_graph(tasks: Iterable[DAGTask]) -> nx.DiGraph:
    """Build a NetworkX DiGraph from the provided DAG tasks."""

    graph = nx.DiGraph()
    for task in tasks:
        graph.add_node(task.key, task=task)
        for dep in task.depends_on:
            graph.add_edge(dep, task.key)

    if not nx.is_directed_acyclic_graph(graph):
        raise ValueError("Task graph contains cycles")
    return graph


def plan_levels(graph: nx.DiGraph) -> list[list[str]]:
    """Return execution generations for the DAG."""

    return [list(generation) for generation in nx.topological_generations(graph)]


async def execute_dag(
    graph: nx.DiGraph,
    *,
    checkpoint: MutableMapping[str, Any] | None = None,
    workflow_key: str | None = None,
    run_id: str | None = None,
    hooks: DAGExecutionHooks | None = None,
) -> DAGRunResult:
    """Execute the DAG level-by-level using anyio TaskGroups.

    Args:
        graph: NetworkX DAG produced by :func:`build_graph`.
        checkpoint: Optional mutable mapping used to persist node results across runs.
            When provided, completed node outputs/durations/attempts are stored in the
            mapping, and pre-existing snapshots allow nodes to be skipped on retries.

    Returns:
        Mapping containing the resolved run_id and node execution results.
    """
    results: dict[str, Any] = {}
    workflow_label = workflow_key or "unknown"
    resolved_run_id = run_id or uuid4().hex

    log_context = {
        "domain": "workflow",
        "key": workflow_label,
        "workflow": workflow_label,
        "run_id": resolved_run_id,
    }
    span_attrs = {
        "oneiric.workflow.key": workflow_label,
        "oneiric.workflow.run_id": resolved_run_id,
    }
    with observed_span(
        "workflow.run",
        component="runtime.workflow",
        attributes=span_attrs,
        log_context=log_context,
    ) as span:
        await _maybe_call_hook(
            hooks.on_run_start if hooks else None,
            run_id=resolved_run_id,
            workflow_key=workflow_label,
        )

        try:
            for index, generation in enumerate(plan_levels(graph)):
                await _maybe_call_hook(
                    hooks.on_generation_start if hooks else None,
                    run_id=resolved_run_id,
                    workflow_key=workflow_label,
                    generation=list(generation),
                    index=index,
                )
                try:
                    async with anyio.create_task_group() as tg:
                        for node in generation:
                            tg.start_soon(
                                _execute_task_node,
                                node,
                                graph,
                                results,
                                checkpoint,
                                workflow_label,
                                resolved_run_id,
                                hooks,
                            )
                except* (
                    DAGExecutionError
                ) as exc_group:  # pragma: no cover - exercised in tests
                    raise exc_group.exceptions[0]
                await _maybe_call_hook(
                    hooks.on_generation_complete if hooks else None,
                    run_id=resolved_run_id,
                    workflow_key=workflow_label,
                    generation=list(generation),
                    index=index,
                )
        except Exception as exc:
            span.record_exception(exc)
            span.set_attributes({"oneiric.workflow.success": False})
            await _maybe_call_hook(
                hooks.on_run_error if hooks else None,
                run_id=resolved_run_id,
                workflow_key=workflow_label,
                error=str(exc),
            )
            raise
        else:
            span.set_attributes({"oneiric.workflow.success": True})
            await _maybe_call_hook(
                hooks.on_run_complete if hooks else None,
                run_id=resolved_run_id,
                workflow_key=workflow_label,
            )
            return {"run_id": resolved_run_id, "results": results}


async def _execute_task_node(
    task_node: str,
    graph: nx.DiGraph,
    results: dict[str, Any],
    checkpoint: MutableMapping[str, Any] | None,
    workflow_label: str,
    run_id: str,
    hooks: DAGExecutionHooks | None,
) -> None:
    """Execute a single task node with checkpointing and retry."""
    task: DAGTask = graph.nodes[task_node]["task"]
    if not task.runner:
        raise DAGExecutionError(f"Task {task.key} missing runner")

    log_context = {
        "domain": "workflow",
        "key": workflow_label,
        "workflow": workflow_label,
        "run_id": run_id,
        "node": task.key,
    }
    span_attrs = {
        "oneiric.workflow.key": workflow_label,
        "oneiric.workflow.run_id": run_id,
        "oneiric.workflow.node": task.key,
    }
    with observed_span(
        "workflow.node",
        component="runtime.workflow",
        attributes=span_attrs,
        log_context=log_context,
    ) as span:
        await _maybe_call_hook(
            hooks.on_node_start if hooks else None,
            run_id=run_id,
            workflow_key=workflow_label,
            node=task.key,
        )

        if _load_from_checkpoint(task, checkpoint, results):
            span.set_attributes({"oneiric.workflow.node.skipped": True})
            await _maybe_call_hook(
                hooks.on_node_skip if hooks else None,
                run_id=run_id,
                workflow_key=workflow_label,
                node=task.key,
            )
            return

        start = time.perf_counter()
        retry_config = _parse_retry_policy(task.retry_policy or {})

        try:
            attempts, value = await _run_task_with_retry(task, retry_config)
        except _TaskFailedAfterRetries as retry_exc:
            duration = time.perf_counter() - start
            span.record_exception(retry_exc.original_error)
            span.set_attributes(
                {
                    "oneiric.workflow.node.success": False,
                    "oneiric.workflow.node.attempts": retry_exc.attempts,
                    "oneiric.workflow.node.duration_ms": duration * 1000.0,
                }
            )
            _record_failure_metrics(task, workflow_label, start, retry_exc.attempts)
            await _maybe_call_hook(
                hooks.on_node_error if hooks else None,
                run_id=run_id,
                workflow_key=workflow_label,
                node=task.key,
                attempts=retry_exc.attempts,
                duration=duration,
                error=str(retry_exc.original_error),
            )
            raise DAGExecutionError(
                f"Task {task.key} failed after {retry_exc.attempts} attempt(s): {retry_exc.original_error}"
            ) from retry_exc.original_error

        _store_task_results(task, value, start, attempts, results, checkpoint)
        _record_success_metrics(task, workflow_label, start, attempts)
        duration = time.perf_counter() - start
        span.set_attributes(
            {
                "oneiric.workflow.node.success": True,
                "oneiric.workflow.node.attempts": attempts,
                "oneiric.workflow.node.duration_ms": duration * 1000.0,
            }
        )
        await _maybe_call_hook(
            hooks.on_node_complete if hooks else None,
            run_id=run_id,
            workflow_key=workflow_label,
            node=task.key,
            attempts=attempts,
            duration=duration,
            result=value,
        )


def _load_from_checkpoint(
    task: DAGTask, checkpoint: MutableMapping[str, Any] | None, results: dict[str, Any]
) -> bool:
    """Load task results from checkpoint if available."""
    if not checkpoint or task.key not in checkpoint:
        return False

    results[task.key] = checkpoint[task.key]
    duration_key = f"{task.key}__duration"
    attempts_key = f"{task.key}__attempts"
    if duration_key in checkpoint:
        results[duration_key] = checkpoint[duration_key]
    if attempts_key in checkpoint:
        results[attempts_key] = checkpoint[attempts_key]
    return True


def _parse_retry_policy(policy: dict[str, Any]) -> dict[str, Any]:
    """Parse and normalize retry policy configuration."""
    max_attempts = int(policy.get("attempts") or policy.get("max_attempts") or 1)
    base_delay = float(policy.get("base_delay") or policy.get("initial_delay") or 0.0)
    max_delay = float(
        policy.get("max_delay") or policy.get("max_backoff") or base_delay
    )
    jitter = float(policy.get("jitter") or policy.get("backoff_jitter") or 0.25)

    max_attempts = max(max_attempts, 1)
    if max_delay < base_delay:
        max_delay = base_delay

    return {
        "max_attempts": max_attempts,
        "base_delay": base_delay,
        "max_delay": max_delay,
        "jitter": jitter,
    }


async def _run_task_with_retry(
    task: DAGTask, config: dict[str, Any]
) -> tuple[int, Any]:
    """Run task with retry logic, returning (attempts, value)."""
    attempts = 0

    async def _execute() -> Any:
        nonlocal attempts
        attempts += 1
        return await task.runner()  # type: ignore[misc]

    try:
        if config["max_attempts"] > 1:
            value = await run_with_retry(
                _execute,
                attempts=config["max_attempts"],
                base_delay=config["base_delay"],
                max_delay=config["max_delay"],
                jitter=config["jitter"],
                adaptive_key=f"workflow:{task.key}",
                attributes={
                    "domain": "workflow",
                    "operation": "task",
                    "node": task.key,
                },
            )
        else:
            value = await _execute()
    except Exception as exc:
        raise _TaskFailedAfterRetries(max(attempts, 1), exc) from exc

    return max(attempts, 1), value


def _store_task_results(
    task: DAGTask,
    value: Any,
    start: float,
    attempts: int,
    results: dict[str, Any],
    checkpoint: MutableMapping[str, Any] | None,
) -> None:
    """Store task execution results."""
    duration = time.perf_counter() - start
    results[task.key] = value
    results[f"{task.key}__duration"] = duration
    results[f"{task.key}__attempts"] = attempts

    if checkpoint is not None:
        checkpoint[task.key] = value
        checkpoint[f"{task.key}__duration"] = duration
        checkpoint[f"{task.key}__attempts"] = attempts


def _record_success_metrics(
    task: DAGTask, workflow_label: str, start: float, attempts: int
) -> None:
    """Record successful task execution metrics."""
    duration = time.perf_counter() - start
    record_workflow_node_metrics(
        workflow=workflow_label,
        node=task.key,
        success=True,
        duration_ms=duration * 1000.0,
        attempts=attempts,
    )


def _record_failure_metrics(
    task: DAGTask, workflow_label: str, start: float, attempts: int
) -> None:
    """Record failed task execution metrics."""
    duration = time.perf_counter() - start
    record_workflow_node_metrics(
        workflow=workflow_label,
        node=task.key,
        success=False,
        duration_ms=duration * 1000.0,
        attempts=attempts,
    )


async def _maybe_call_hook(hook: HookCallable | None, **kwargs: Any) -> None:
    if hook is None:
        return
    try:
        result = hook(**kwargs)
        if inspect.isawaitable(result):
            await result
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("dag-hook-failed", hook=str(hook), error=str(exc))
