"""Comprehensive tests for oneiric.runtime.dag.

Covers the ``DAGTask`` dataclass, ``build_graph`` / ``plan_levels`` pure
functions, the async ``execute_dag`` runner, ``DAGExecutionHooks`` ordering
and sync/awaitable handling, retry policy, cycle detection, and integration
with ``WorkflowCheckpointStore``. Includes one property-based test via
Hypothesis that asserts ``plan_levels`` respects dependencies for randomly
generated DAGs.

Source under test: ``oneiric/runtime/dag.py``
Style template: ``tests/unit/test_core_resolution.py`` (class-based, typed).
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

import networkx as nx
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from oneiric.runtime.dag import (
    DAGExecutionError,
    DAGExecutionHooks,
    DAGRunResult,
    DAGTask,
    HookCallable,
    TaskCallable,
    build_graph,
    execute_dag,
    plan_levels,
)
from oneiric.runtime.checkpoints import WorkflowCheckpointStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _async_value(value: Any) -> TaskCallable:
    """Build a runner that resolves to ``value`` on each call."""

    async def _runner() -> Any:
        return value

    return _runner


def _async_raising(exc: Exception) -> TaskCallable:
    """Build a runner that always raises ``exc``."""

    async def _runner() -> Any:
        raise exc

    return _runner


def _async_failing_then_value(
    failures: int, value: Any, exc: Exception | None = None
) -> TaskCallable:
    """Build a runner that fails ``failures`` times then returns ``value``."""
    state = {"calls": 0, "exc": exc or RuntimeError("planned failure")}

    async def _runner() -> Any:
        state["calls"] += 1
        if state["calls"] <= failures:
            raise state["exc"]
        return value

    return _runner


# ---------------------------------------------------------------------------
# DAGTask
# ---------------------------------------------------------------------------


class TestDAGTask:
    def test_minimal_construction(self) -> None:
        task = DAGTask(key="alpha")
        assert task.key == "alpha"
        assert task.depends_on == ()
        assert task.runner is None
        assert task.retry_policy is None

    def test_full_construction(self) -> None:
        runner = _async_value("result")
        task = DAGTask(
            key="beta",
            depends_on=("alpha",),
            runner=runner,
            retry_policy={"attempts": 3, "base_delay": 0.0},
        )
        assert task.key == "beta"
        assert task.depends_on == ("alpha",)
        assert task.runner is runner
        assert task.retry_policy == {"attempts": 3, "base_delay": 0.0}

    def test_depends_on_is_tuple_immutable(self) -> None:
        task = DAGTask(key="x", depends_on=("a", "b"))
        # Default factory produces a tuple, not a list — immutable by design.
        assert isinstance(task.depends_on, tuple)

    def test_retry_policy_is_dict_or_none(self) -> None:
        assert DAGTask(key="a").retry_policy is None
        assert isinstance(DAGTask(key="b", retry_policy={"attempts": 2}).retry_policy, dict)

    def test_runner_is_async_callable(self) -> None:
        runner = _async_value("v")
        task = DAGTask(key="async", runner=runner)
        assert task.runner is not None
        assert inspect.iscoroutinefunction(task.runner)


# ---------------------------------------------------------------------------
# build_graph
# ---------------------------------------------------------------------------


class TestBuildGraph:
    def test_empty_input_produces_empty_graph(self) -> None:
        graph = build_graph([])
        assert isinstance(graph, nx.DiGraph)
        assert graph.number_of_nodes() == 0
        assert graph.number_of_edges() == 0

    def test_single_node_no_edges(self) -> None:
        graph = build_graph([DAGTask(key="solo", runner=_async_value(1))])
        assert graph.number_of_nodes() == 1
        assert graph.number_of_edges() == 0
        assert "solo" in graph.nodes

    def test_linear_chain(self) -> None:
        tasks = [
            DAGTask(key="a", runner=_async_value(1)),
            DAGTask(key="b", depends_on=("a",), runner=_async_value(2)),
            DAGTask(key="c", depends_on=("b",), runner=_async_value(3)),
        ]
        graph = build_graph(tasks)
        assert graph.number_of_nodes() == 3
        assert list(graph.edges) == [("a", "b"), ("b", "c")]
        assert nx.is_directed_acyclic_graph(graph) is True

    def test_diamond(self) -> None:
        tasks = [
            DAGTask(key="root", runner=_async_value(0)),
            DAGTask(key="left", depends_on=("root",), runner=_async_value(1)),
            DAGTask(key="right", depends_on=("root",), runner=_async_value(2)),
            DAGTask(key="join", depends_on=("left", "right"), runner=_async_value(3)),
        ]
        graph = build_graph(tasks)
        assert graph.number_of_nodes() == 4
        assert graph.number_of_edges() == 4
        assert ("root", "left") in graph.edges
        assert ("root", "right") in graph.edges
        assert ("left", "join") in graph.edges
        assert ("right", "join") in graph.edges

    def test_fanout_and_fanin(self) -> None:
        tasks = [
            DAGTask(key="a", runner=_async_value(0)),
            DAGTask(key="b", runner=_async_value(0)),
            DAGTask(key="c", runner=_async_value(0)),
            DAGTask(key="merge", depends_on=("a", "b", "c"), runner=_async_value(0)),
        ]
        graph = build_graph(tasks)
        indeg = dict(graph.in_degree)
        assert indeg["merge"] == 3
        assert indeg["a"] == indeg["b"] == indeg["c"] == 0

    def test_direct_cycle_raises_value_error(self) -> None:
        # A -> B and B -> A forms a 2-cycle.
        tasks = [
            DAGTask(key="A", depends_on=("B",), runner=_async_value(0)),
            DAGTask(key="B", depends_on=("A",), runner=_async_value(0)),
        ]
        with pytest.raises(ValueError, match="[Cc]ycle"):
            build_graph(tasks)

    def test_indirect_cycle_raises_value_error(self) -> None:
        # A -> B -> C -> A is a 3-cycle.
        tasks = [
            DAGTask(key="A", depends_on=("C",), runner=_async_value(0)),
            DAGTask(key="B", depends_on=("A",), runner=_async_value(0)),
            DAGTask(key="C", depends_on=("B",), runner=_async_value(0)),
        ]
        with pytest.raises(ValueError, match="[Cc]ycle"):
            build_graph(tasks)


# ---------------------------------------------------------------------------
# plan_levels
# ---------------------------------------------------------------------------


class TestPlanLevels:
    def test_independent_nodes_share_single_level(self) -> None:
        graph = build_graph(
            [
                DAGTask(key="a", runner=_async_value(0)),
                DAGTask(key="b", runner=_async_value(0)),
                DAGTask(key="c", runner=_async_value(0)),
            ]
        )
        levels = plan_levels(graph)
        assert levels == [["a", "b", "c"]]

    def test_multi_level_respects_dependencies(self) -> None:
        graph = build_graph(
            [
                DAGTask(key="a", runner=_async_value(0)),
                DAGTask(key="b", depends_on=("a",), runner=_async_value(0)),
                DAGTask(key="c", depends_on=("a",), runner=_async_value(0)),
                DAGTask(key="d", depends_on=("b", "c"), runner=_async_value(0)),
            ]
        )
        levels = plan_levels(graph)
        # First level must contain "a"; last level must contain "d".
        assert levels[0] == ["a"]
        assert levels[-1] == ["d"]
        assert set(graph.nodes) == {node for level in levels for node in level}

    def test_total_node_count_matches_graph(self) -> None:
        keys = [f"n{i}" for i in range(6)]
        tasks: list[DAGTask] = []
        for idx, key in enumerate(keys):
            deps = tuple(keys[:idx])
            tasks.append(DAGTask(key=key, depends_on=deps, runner=_async_value(0)))
        graph = build_graph(tasks)
        levels = plan_levels(graph)
        flattened = [node for level in levels for node in level]
        assert sorted(flattened) == sorted(keys)
        assert len(flattened) == graph.number_of_nodes()

    def test_no_intra_level_edges(self) -> None:
        graph = build_graph(
            [
                DAGTask(key="a", runner=_async_value(0)),
                DAGTask(key="b", runner=_async_value(0)),
                DAGTask(key="c", depends_on=("a", "b"), runner=_async_value(0)),
            ]
        )
        levels = plan_levels(graph)
        # Build the set of nodes per level and ensure no edge lies within a level.
        for level in levels:
            within = set(level)
            for src, _dst in graph.edges:
                if src in within:
                    assert _dst not in within, (
                        f"intra-level edge {src}->{_dst} in level {level}"
                    )


# ---------------------------------------------------------------------------
# execute_dag — linear happy paths
# ---------------------------------------------------------------------------


class TestExecuteDag:
    async def test_single_task_no_deps_generates_run_id(self) -> None:
        graph = build_graph([DAGTask(key="solo", runner=_async_value(42))])
        result: DAGRunResult = await execute_dag(graph, workflow_key="wf-single")

        assert isinstance(result["run_id"], str)
        assert len(result["run_id"]) == 32  # uuid4().hex
        # Hex characters only.
        int(result["run_id"], 16)
        assert result["results"]["solo"] == 42

    async def test_linear_chain_executes_in_dependency_order(self) -> None:
        order: list[str] = []

        async def _make_runner(name: str) -> TaskCallable:
            async def _runner() -> str:
                order.append(name)
                return name

            return _runner

        tasks = [
            DAGTask(key="a", runner=await _make_runner("a")),
            DAGTask(key="b", depends_on=("a",), runner=await _make_runner("b")),
            DAGTask(key="c", depends_on=("b",), runner=await _make_runner("c")),
        ]
        graph = build_graph(tasks)
        result = await execute_dag(graph, workflow_key="wf-linear")

        assert order == ["a", "b", "c"]
        assert result["results"]["a"] == "a"
        assert result["results"]["b"] == "b"
        assert result["results"]["c"] == "c"

    async def test_diamond_runs_parallel_middle_layer(self) -> None:
        order: list[str] = []

        def _make_recorder(name: str) -> TaskCallable:
            async def _runner() -> str:
                order.append(name)
                return name

            return _runner

        tasks = [
            DAGTask(key="root", runner=_make_recorder("root")),
            DAGTask(key="left", depends_on=("root",), runner=_make_recorder("left")),
            DAGTask(key="right", depends_on=("root",), runner=_make_recorder("right")),
            DAGTask(
                key="join", depends_on=("left", "right"), runner=_make_recorder("join")
            ),
        ]
        graph = build_graph(tasks)
        await execute_dag(graph, workflow_key="wf-diamond")

        # root runs first, join runs last; left and right sandwich the join.
        assert order[0] == "root"
        assert order[-1] == "join"
        assert {"left", "right"}.issubset(set(order[1:-1]))


# ---------------------------------------------------------------------------
# execute_dag — failure semantics and retries
# ---------------------------------------------------------------------------


class TestExecuteDagFailures:
    async def test_task_failure_raises_dag_execution_error(self) -> None:
        graph = build_graph(
            [DAGTask(key="boom", runner=_async_raising(RuntimeError("nope")))]
        )
        with pytest.raises(DAGExecutionError):
            await execute_dag(graph, workflow_key="wf-fail")

    async def test_retry_policy_runs_runner_three_times(self) -> None:
        # Runner always fails; policy says 3 attempts; result is DAGExecutionError
        # and the runner is invoked exactly 3 times.
        call_count = {"n": 0}

        async def _always_fail() -> None:
            call_count["n"] += 1
            raise RuntimeError(f"failure #{call_count['n']}")

        graph = build_graph(
            [DAGTask(key="r", runner=_always_fail, retry_policy={"attempts": 3})]
        )
        with pytest.raises(DAGExecutionError):
            await execute_dag(graph, workflow_key="wf-retry")

        assert call_count["n"] == 3

    async def test_attempts_reflected_in_results_on_success(self) -> None:
        # Succeeds on the second attempt; the ``attempts`` key should be 2.
        graph = build_graph(
            [
                DAGTask(
                    key="flaky",
                    runner=_async_failing_then_value(1, "ok"),
                    retry_policy={"attempts": 3, "base_delay": 0.0},
                )
            ]
        )
        result = await execute_dag(graph, workflow_key="wf-attempts")

        assert result["results"]["flaky"] == "ok"
        assert result["results"]["flaky__attempts"] == 2


# ---------------------------------------------------------------------------
# execute_dag — run_id semantics
# ---------------------------------------------------------------------------


class TestExecuteDagRunId:
    async def test_provided_run_id_is_preserved(self) -> None:
        seen: dict[str, str] = {}

        def _on_run_start(**kwargs: Any) -> None:
            seen["run_id"] = kwargs["run_id"]
            seen["workflow_key"] = kwargs["workflow_key"]

        hooks = DAGExecutionHooks(on_run_start=_on_run_start)
        graph = build_graph([DAGTask(key="x", runner=_async_value(1))])
        result = await execute_dag(
            graph, workflow_key="wf-rid", run_id="rid-deadbeef", hooks=hooks
        )

        assert result["run_id"] == "rid-deadbeef"
        assert seen["run_id"] == "rid-deadbeef"
        assert seen["workflow_key"] == "wf-rid"

    async def test_run_id_is_generated_when_missing(self) -> None:
        graph = build_graph([DAGTask(key="y", runner=_async_value(1))])
        result = await execute_dag(graph, workflow_key="wf-rid-gen")
        run_id = result["run_id"]
        assert isinstance(run_id, str)
        assert len(run_id) == 32
        int(run_id, 16)  # hex-only; raises if not


# ---------------------------------------------------------------------------
# execute_dag — hook ordering and sync/async tolerance
# ---------------------------------------------------------------------------


class TestExecuteDagHooks:
    async def test_hooks_fire_in_documented_order(self) -> None:
        events: list[tuple[str, str | int]] = []

        def _on_run_start(**_kwargs: Any) -> None:
            events.append(("on_run_start", "run"))

        def _on_node_start(**kwargs: Any) -> None:
            events.append(("on_node_start", kwargs["node"]))

        def _on_node_complete(**kwargs: Any) -> None:
            events.append(("on_node_complete", kwargs["node"]))

        def _on_run_complete(**_kwargs: Any) -> None:
            events.append(("on_run_complete", "run"))

        hooks = DAGExecutionHooks(
            on_run_start=_on_run_start,
            on_node_start=_on_node_start,
            on_node_complete=_on_node_complete,
            on_run_complete=_on_run_complete,
        )
        graph = build_graph(
            [
                DAGTask(key="a", runner=_async_value(1)),
                DAGTask(key="b", depends_on=("a",), runner=_async_value(2)),
            ]
        )
        await execute_dag(graph, workflow_key="wf-hooks", hooks=hooks)

        # on_run_start is the first event; on_run_complete is the last.
        assert events[0][0] == "on_run_start"
        assert events[-1][0] == "on_run_complete"
        # on_node_start fires before on_node_complete for the same key.
        for key in ("a", "b"):
            starts = [i for i, (name, payload) in enumerate(events) if name == "on_node_start" and payload == key]
            completes = [
                i for i, (name, payload) in enumerate(events) if name == "on_node_complete" and payload == key
            ]
            assert starts and completes
            assert starts[0] < completes[0]

    async def test_hooks_may_be_sync_or_async(self) -> None:
        events: list[str] = []

        def _sync_hook(**_kwargs: Any) -> None:
            events.append("sync")

        async def _async_hook(**_kwargs: Any) -> None:
            events.append("async")

        hooks = DAGExecutionHooks(
            on_run_start=_async_hook, on_run_complete=_sync_hook
        )
        graph = build_graph([DAGTask(key="a", runner=_async_value(1))])
        await execute_dag(graph, workflow_key="wf-mixed", hooks=hooks)

        assert events == ["async", "sync"]

    async def test_on_node_error_fires_on_failure(self) -> None:
        error_seen: dict[str, Any] = {}

        def _on_node_error(**kwargs: Any) -> None:
            error_seen["node"] = kwargs["node"]
            error_seen["attempts"] = kwargs["attempts"]
            error_seen["error"] = kwargs["error"]

        hooks = DAGExecutionHooks(on_node_error=_on_node_error)
        graph = build_graph(
            [DAGTask(key="bad", runner=_async_raising(ValueError("kapow")))]
        )
        with pytest.raises(DAGExecutionError):
            await execute_dag(graph, workflow_key="wf-node-err", hooks=hooks)

        assert error_seen["node"] == "bad"
        assert error_seen["attempts"] == 1
        assert "kapow" in error_seen["error"]

    async def test_hook_exception_is_swallowed(self) -> None:
        def _bad_hook(**_kwargs: Any) -> None:
            raise RuntimeError("hook exploded")

        hooks = DAGExecutionHooks(on_run_start=_bad_hook)
        graph = build_graph([DAGTask(key="a", runner=_async_value(1))])

        # The run should still succeed even though the hook raised.
        result = await execute_dag(graph, workflow_key="wf-bad-hook", hooks=hooks)
        assert result["results"]["a"] == 1


# ---------------------------------------------------------------------------
# DAGExecutionHooks dataclass
# ---------------------------------------------------------------------------


class TestDAGExecutionHooks:
    def test_all_nine_fields_default_to_none(self) -> None:
        hooks = DAGExecutionHooks()
        for field_name in (
            "on_run_start",
            "on_run_complete",
            "on_run_error",
            "on_generation_start",
            "on_generation_complete",
            "on_node_start",
            "on_node_complete",
            "on_node_skip",
            "on_node_error",
        ):
            assert getattr(hooks, field_name) is None

    def test_setting_a_hook_is_recorded(self) -> None:
        def _hook(**_kwargs: Any) -> None:
            return None

        hooks = DAGExecutionHooks(on_run_start=_hook)
        assert hooks.on_run_start is _hook

    def test_mix_sync_and_async_callables(self) -> None:
        def _sync(**_kwargs: Any) -> None:
            return None

        async def _async(**_kwargs: Any) -> None:
            return None

        hooks = DAGExecutionHooks(
            on_run_start=_async,
            on_run_complete=_sync,
            on_node_error=_async,
        )
        assert inspect.iscoroutinefunction(hooks.on_run_start)
        assert not inspect.iscoroutinefunction(hooks.on_run_complete)
        assert inspect.iscoroutinefunction(hooks.on_node_error)


# ---------------------------------------------------------------------------
# Failure-after-retries semantics
# ---------------------------------------------------------------------------


class TestTaskFailedAfterRetries:
    async def test_retry_exhaustion_raises_dag_execution_error(self) -> None:
        # Runner fails every time; policy has attempts=2 → 2 calls, then raise.
        graph = build_graph(
            [
                DAGTask(
                    key="retryable",
                    runner=_async_raising(RuntimeError("boom")),
                    retry_policy={"attempts": 2, "base_delay": 0.0},
                )
            ]
        )
        with pytest.raises(DAGExecutionError) as exc_info:
            await execute_dag(graph, workflow_key="wf-retry-exhaust")

        msg = str(exc_info.value)
        assert "retryable" in msg
        assert "2 attempt" in msg

    async def test_dag_execution_error_wraps_original(self) -> None:
        original = RuntimeError("inner reason")
        graph = build_graph(
            [
                DAGTask(
                    key="wrap",
                    runner=_async_raising(original),
                    retry_policy={"attempts": 1},
                )
            ]
        )
        with pytest.raises(DAGExecutionError) as exc_info:
            await execute_dag(graph, workflow_key="wf-wrap")
        # The DAGExecutionError is chained from the original RuntimeError.
        assert exc_info.value.__cause__ is original


# ---------------------------------------------------------------------------
# Cycle detection
# ---------------------------------------------------------------------------


class TestCycleDetection:
    def test_two_cycle_rejected(self) -> None:
        tasks = [
            DAGTask(key="X", depends_on=("Y",), runner=_async_value(0)),
            DAGTask(key="Y", depends_on=("X",), runner=_async_value(0)),
        ]
        with pytest.raises(ValueError):
            build_graph(tasks)

    def test_three_cycle_rejected(self) -> None:
        tasks = [
            DAGTask(key="P", depends_on=("R",), runner=_async_value(0)),
            DAGTask(key="Q", depends_on=("P",), runner=_async_value(0)),
            DAGTask(key="R", depends_on=("Q",), runner=_async_value(0)),
        ]
        with pytest.raises(ValueError):
            build_graph(tasks)


# ---------------------------------------------------------------------------
# Integration with WorkflowCheckpointStore
# ---------------------------------------------------------------------------


class TestCheckpointIntegration:
    async def test_checkpoint_mutated_after_each_node(
        self, checkpoint_store: WorkflowCheckpointStore
    ) -> None:
        graph = build_graph(
            [
                DAGTask(key="one", runner=_async_value(10)),
                DAGTask(key="two", depends_on=("one",), runner=_async_value(20)),
            ]
        )
        # Pre-populate the store to mirror the runtime case where a workflow
        # resumes from a partially completed run.
        checkpoint_store.save("wf-checkpoint", {"one": 10, "one__attempts": 1})
        checkpoint = checkpoint_store.load("wf-checkpoint")

        await execute_dag(
            graph, workflow_key="wf-checkpoint", checkpoint=checkpoint
        )
        # execute_dag mutates the in-memory mapping; persist it back so we
        # can verify the store reflects every node's completion.
        checkpoint_store.save("wf-checkpoint", checkpoint)

        saved = checkpoint_store.load("wf-checkpoint")
        assert saved["one"] == 10
        assert saved["one__attempts"] == 1
        assert saved["two"] == 20
        assert "two__attempts" in saved
        assert "two__duration" in saved

    async def test_skip_when_checkpoint_already_has_value(
        self, checkpoint_store: WorkflowCheckpointStore
    ) -> None:
        # Pre-store a result for node "skip-me"; its runner must not run.
        invocations: list[str] = []

        def _runner_skip() -> TaskCallable:
            async def _r() -> str:
                invocations.append("skip-me")
                return "should-not-run"

            return _r

        def _runner_run() -> TaskCallable:
            async def _r() -> str:
                invocations.append("run-me")
                return "ran"

            return _r

        checkpoint_store.save(
            "wf-skip",
            {
                "skip-me": "cached",
                "skip-me__attempts": 1,
                "skip-me__duration": 0.01,
            },
        )

        graph = build_graph(
            [
                DAGTask(key="skip-me", runner=_runner_skip()),
                DAGTask(key="run-me", runner=_runner_run()),
            ]
        )
        result = await execute_dag(
            graph,
            workflow_key="wf-skip",
            checkpoint=checkpoint_store.load("wf-skip"),
        )

        # "skip-me" was loaded from checkpoint; only "run-me" executed.
        assert invocations == ["run-me"]
        assert result["results"]["skip-me"] == "cached"
        assert result["results"]["run-me"] == "ran"


# ---------------------------------------------------------------------------
# Property test: plan_levels respects dependencies
# ---------------------------------------------------------------------------


@st.composite
def _dag_strategy(draw: st.DrawFn) -> list[DAGTask]:
    """Generate a random acyclic list of DAGTasks."""
    n = draw(st.integers(min_value=1, max_value=8))
    keys = [f"k{i}" for i in range(n)]
    tasks: list[DAGTask] = []
    for i, key in enumerate(keys):
        # Any key whose index is < i is eligible to be a dependency. Drawing
        # the empty tuple produces nodes with no dependencies, which is valid.
        possible = keys[:i]
        if possible and draw(st.booleans()):
            subset_size = draw(st.integers(min_value=1, max_value=len(possible)))
            deps = tuple(draw(st.sampled_from(possible)) for _ in range(subset_size))
            # Deduplicate while preserving order.
            seen: set[str] = set()
            unique_deps = tuple(d for d in deps if not (d in seen or seen.add(d)))
        else:
            unique_deps = ()
        tasks.append(DAGTask(key=key, depends_on=unique_deps, runner=_async_value(0)))
    return tasks


class TestPlanLevelsProperty:
    @given(tasks=_dag_strategy())
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_plan_levels_respects_dependencies(self, tasks: list[DAGTask]) -> None:
        # Some generated graphs may still be acyclic only by luck of selection.
        # Skip the rare case where a cycle was generated rather than masking it.
        try:
            graph = build_graph(tasks)
        except ValueError:
            pytest.skip("hypothesis produced a cyclic graph; reroll")

        levels = plan_levels(graph)
        # Index of each node by its level.
        node_level: dict[str, int] = {}
        for idx, level in enumerate(levels):
            for node in level:
                node_level[node] = idx

        # Every dependency must live in a strictly earlier level.
        for task in tasks:
            for dep in task.depends_on:
                assert dep in node_level, f"dep {dep} missing from levels"
                assert node_level[dep] < node_level[task.key], (
                    f"dep {dep} (level {node_level[dep]}) is not before "
                    f"{task.key} (level {node_level[task.key]})"
                )

        # Total node count must match.
        flattened = [node for level in levels for node in level]
        assert len(flattened) == graph.number_of_nodes()
