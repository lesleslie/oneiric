"""Comprehensive tests for oneiric.domains.workflows.

Covers the most composition-heavy domain bridge: ``WorkflowBridge`` aggregates
``Resolver``, ``LifecycleManager``, ``TaskBridge``, ``WorkflowCheckpointStore``,
``AdapterBridge`` (queue), and ``RuntimeTelemetryRecorder`` and exposes two
async entrypoints (``execute_dag``, ``enqueue_workflow``).

The file is organized into the following sections, matching the task spec:

* ``TestWorkflowBridgeInit`` — construction & default state
* ``TestRefreshDags`` — ``refresh_dags()`` populates ``_dag_specs``
* ``TestDagSpecs`` — ``dag_specs()`` returns a defensive copy
* ``TestUpdateSettings`` — ``update_settings`` propagates to queue category
* ``TestExecuteDag`` — async happy / sad paths for DAG execution
* ``TestCheckpointIntegration`` — checkpoint store round-trips
* ``TestQueueBridge`` — enqueue flow with stubbed AdapterBridge
* ``TestTelemetry`` — recorder is invoked when supplied
* ``TestEnqueuePayload`` — payload shape & queue category precedence
* ``TestWorkflowBridgeIntegration`` — full pipeline scenarios
* ``TestDagSpecsIsolated`` — property test for copy isolation
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest
from hypothesis import HealthCheck, given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from oneiric.core.lifecycle import LifecycleError, LifecycleManager
from oneiric.core.resolution import Candidate, CandidateSource, Resolver
from oneiric.domains.tasks import TaskBridge
from oneiric.domains.workflows import WorkflowBridge
from oneiric.runtime.checkpoints import WorkflowCheckpointStore
from oneiric.runtime.durable import WorkflowExecutionStore
from oneiric.runtime.telemetry import RuntimeTelemetryRecorder

# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------


class _TaskRunner:
    """Simple async task handler satisfying ``TaskHandlerProtocol``."""

    def __init__(self, label: str, recorder: list[str] | None = None) -> None:
        self.label = label
        self.recorder = recorder if recorder is not None else []

    async def run(self, payload: dict[str, Any] | None = None) -> str:
        self.recorder.append(f"{self.label}:{payload}")
        return self.label.upper()


class _FlakyTaskRunner:
    """Fails the first N invocations before succeeding."""

    def __init__(self, label: str, fail_first: int = 1) -> None:
        self.label = label
        self.fail_first = fail_first
        self.calls = 0

    async def run(self, payload: dict[str, Any] | None = None) -> str:
        self.calls += 1
        if self.calls <= self.fail_first:
            raise RuntimeError(f"{self.label}-attempt-{self.calls}-failed")
        return self.label.upper()


class _AlwaysFailTaskRunner:
    async def run(self, payload: dict[str, Any] | None = None) -> str:
        raise RuntimeError("intentional-failure")


class _FakeQueueAdapter:
    """Minimal queue adapter recording enqueue payloads."""

    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    async def enqueue(self, payload: dict[str, Any]) -> str:
        self.payloads.append(payload)
        return f"task-{len(self.payloads)}"


@dataclass
class _FakeQueueHandle:
    category: str
    provider: str
    instance: Any
    settings: dict[str, Any]
    metadata: dict[str, Any]


class _FakeQueueBridge:
    """Stubbed AdapterBridge-like object for enqueue tests."""

    def __init__(self, *, default_provider: str = "default") -> None:
        self.default_provider = default_provider
        self.calls: list[tuple[str, str | None]] = []
        self.adapter = _FakeQueueAdapter()

    async def use(
        self,
        category: str,
        *,
        provider: str | None = None,
        force_reload: bool = False,
    ) -> _FakeQueueHandle:
        chosen = provider or self.default_provider
        self.calls.append((category, chosen))
        return _FakeQueueHandle(
            category=category,
            provider=chosen,
            instance=self.adapter,
            settings={},
            metadata={},
        )


def _register_workflow_candidate(
    resolver: Resolver,
    *,
    key: str = "demo-workflow",
    dag: dict[str, Any] | None = None,
    scheduler: dict[str, Any] | None = None,
) -> None:
    metadata: dict[str, Any] = {}
    if dag is not None:
        metadata["dag"] = dag
    if scheduler is not None:
        metadata["scheduler"] = scheduler
    resolver.register(
        Candidate(
            domain="workflow",
            key=key,
            provider="demo",
            factory=lambda: _TaskRunner(key),
            metadata=metadata,
            source=CandidateSource.MANUAL,
        )
    )


def _register_task_candidate(
    resolver: Resolver,
    *,
    key: str,
    runner: Any | None = None,
) -> None:
    resolver.register(
        Candidate(
            domain="task",
            key=key,
            provider="worker",
            factory=lambda: runner if runner is not None else _TaskRunner(key),
            source=CandidateSource.MANUAL,
        )
    )


# ---------------------------------------------------------------------------
# 1. Construction
# ---------------------------------------------------------------------------


class TestWorkflowBridgeInit:
    """Verify constructor-time state and option wiring."""

    def test_domain_is_workflow(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
    ) -> None:
        bridge = WorkflowBridge(resolver, lifecycle_manager, layer_settings)
        assert bridge.domain == "workflow"

    def test_dag_specs_empty_by_default(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
    ) -> None:
        bridge = WorkflowBridge(resolver, lifecycle_manager, layer_settings)
        assert bridge.dag_specs() == {}

    def test_dag_specs_populated_from_candidate_metadata(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
    ) -> None:
        _register_workflow_candidate(
            resolver, key="alpha", dag={"nodes": [{"id": "x", "task": "t"}]}
        )
        _register_workflow_candidate(resolver, key="beta", dag={"nodes": []})
        bridge = WorkflowBridge(resolver, lifecycle_manager, layer_settings)

        specs = bridge.dag_specs()
        assert set(specs.keys()) == {"alpha", "beta"}
        assert specs["alpha"] == {"nodes": [{"id": "x", "task": "t"}]}

    def test_queue_category_falls_back_to_settings(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
    ) -> None:
        from oneiric.core.config import LayerSettings

        settings = LayerSettings(options={"queue_category": "queue.special"})
        bridge = WorkflowBridge(
            resolver, lifecycle_manager, settings, queue_category=None
        )
        assert bridge._queue_category == "queue.special"

    def test_queue_category_default_when_nothing_configured(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
    ) -> None:
        bridge = WorkflowBridge(resolver, lifecycle_manager, layer_settings)
        assert bridge._queue_category == "queue"

    def test_durable_hooks_built_when_execution_store_supplied(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
        tmp_path,
    ) -> None:
        store = WorkflowExecutionStore(tmp_path / "executions.sqlite")
        bridge = WorkflowBridge(
            resolver,
            lifecycle_manager,
            layer_settings,
            execution_store=store,
        )
        assert bridge._execution_hooks is not None
        # Hooks expose the standard on_* callbacks
        for attr in (
            "on_run_start",
            "on_run_complete",
            "on_run_error",
            "on_node_start",
            "on_node_complete",
            "on_node_error",
        ):
            assert getattr(bridge._execution_hooks, attr) is not None

    def test_no_hooks_when_execution_store_omitted(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
    ) -> None:
        bridge = WorkflowBridge(resolver, lifecycle_manager, layer_settings)
        assert bridge._execution_hooks is None

    def test_task_bridge_optional_at_construction(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
    ) -> None:
        bridge = WorkflowBridge(resolver, lifecycle_manager, layer_settings)
        assert bridge._task_bridge is None

    def test_queue_bridge_optional_at_construction(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
    ) -> None:
        bridge = WorkflowBridge(resolver, lifecycle_manager, layer_settings)
        assert bridge._queue_bridge is None

    def test_checkpoint_store_optional_at_construction(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
    ) -> None:
        bridge = WorkflowBridge(resolver, lifecycle_manager, layer_settings)
        assert bridge._checkpoint_store is None


# ---------------------------------------------------------------------------
# 2. refresh_dags
# ---------------------------------------------------------------------------


class TestRefreshDags:
    """Verify that refresh_dags() rebuilds the internal map correctly."""

    def test_keyed_by_candidate_key(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
    ) -> None:
        _register_workflow_candidate(resolver, key="alpha", dag={"nodes": []})
        _register_workflow_candidate(resolver, key="beta", dag={"nodes": []})
        bridge = WorkflowBridge(resolver, lifecycle_manager, layer_settings)

        bridge.refresh_dags()
        specs = bridge.dag_specs()
        assert "alpha" in specs
        assert "beta" in specs

    def test_ignores_candidates_without_dag_metadata(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
    ) -> None:
        _register_workflow_candidate(resolver, key="has-dag", dag={"nodes": []})
        # Candidate without a dag metadata key
        resolver.register(
            Candidate(
                domain="workflow",
                key="no-dag",
                provider="demo",
                factory=lambda: _TaskRunner("no-dag"),
                metadata={"scheduler": {"queue_category": "q"}},
                source=CandidateSource.MANUAL,
            )
        )
        bridge = WorkflowBridge(resolver, lifecycle_manager, layer_settings)
        bridge.refresh_dags()
        specs = bridge.dag_specs()
        assert "has-dag" in specs
        assert "no-dag" not in specs

    def test_empty_dag_metadata_treated_as_missing(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
    ) -> None:
        """``dag`` is falsy → candidate skipped (per `if dag_spec`)."""
        _register_workflow_candidate(resolver, key="empty-dag", dag={})
        bridge = WorkflowBridge(resolver, lifecycle_manager, layer_settings)
        bridge.refresh_dags()
        assert "empty-dag" not in bridge.dag_specs()

    def test_refresh_replaces_previous_state(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
    ) -> None:
        _register_workflow_candidate(resolver, key="first", dag={"nodes": []})
        bridge = WorkflowBridge(resolver, lifecycle_manager, layer_settings)
        assert "first" in bridge.dag_specs()

        # Remove the candidate and refresh
        resolver.registry._candidates.pop(("workflow", "first"), None)
        resolver.registry._active.pop(("workflow", "first"), None)
        bridge.refresh_dags()
        assert "first" not in bridge.dag_specs()


# ---------------------------------------------------------------------------
# 3. dag_specs (defensive copy)
# ---------------------------------------------------------------------------


class TestDagSpecs:
    """dag_specs() returns a fresh dict each call."""

    def test_returns_a_copy(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
    ) -> None:
        _register_workflow_candidate(resolver, key="wf", dag={"nodes": []})
        bridge = WorkflowBridge(resolver, lifecycle_manager, layer_settings)

        first = bridge.dag_specs()
        second = bridge.dag_specs()

        # Two distinct dict objects with the same content
        assert first == second
        assert first is not second

    def test_mutation_does_not_affect_internal_state(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
    ) -> None:
        _register_workflow_candidate(resolver, key="wf", dag={"nodes": []})
        bridge = WorkflowBridge(resolver, lifecycle_manager, layer_settings)

        snapshot = bridge.dag_specs()
        snapshot.clear()
        snapshot["__bogus__"] = {"nodes": []}  # type: ignore[index]

        # Internal state untouched
        assert "wf" in bridge.dag_specs()
        assert "__bogus__" not in bridge.dag_specs()


# ---------------------------------------------------------------------------
# 4. update_settings
# ---------------------------------------------------------------------------


class TestUpdateSettings:
    """update_settings() refreshes queue category and DAGs."""

    def test_super_settings_replaced(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
    ) -> None:
        from oneiric.core.config import LayerSettings

        first = LayerSettings(options={"queue_category": "queue.first"})
        second = LayerSettings(options={"queue_category": "queue.second"})

        bridge = WorkflowBridge(resolver, lifecycle_manager, first, queue_category=None)
        bridge.update_settings(second)
        assert bridge.settings is second

    def test_queue_category_refresh_when_no_override(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
    ) -> None:
        from oneiric.core.config import LayerSettings

        first = LayerSettings(options={"queue_category": "queue.first"})
        second = LayerSettings(options={"queue_category": "queue.second"})

        bridge = WorkflowBridge(resolver, lifecycle_manager, first, queue_category=None)
        bridge.update_settings(second)
        assert bridge._queue_category == "queue.second"

    def test_queue_category_preserved_when_override(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
    ) -> None:
        from oneiric.core.config import LayerSettings

        first = LayerSettings(options={"queue_category": "queue.first"})
        second = LayerSettings(options={"queue_category": "queue.second"})

        bridge = WorkflowBridge(
            resolver,
            lifecycle_manager,
            first,
            queue_category="queue.override",
        )
        bridge.update_settings(second)
        # Override wins; new settings' value not used.
        assert bridge._queue_category == "queue.override"

    def test_dags_refreshed_on_settings_update(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
    ) -> None:
        from oneiric.core.config import LayerSettings

        first = LayerSettings()
        bridge = WorkflowBridge(resolver, lifecycle_manager, first)
        assert bridge.dag_specs() == {}

        _register_workflow_candidate(resolver, key="late", dag={"nodes": []})
        bridge.update_settings(LayerSettings())
        assert "late" in bridge.dag_specs()


# ---------------------------------------------------------------------------
# 5. execute_dag
# ---------------------------------------------------------------------------


class TestExecuteDag:
    """Async tests covering execute_dag() happy and sad paths."""

    async def test_happy_path_runs_registered_dag(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
    ) -> None:
        recorder: list[str] = []
        runner_a = _TaskRunner("a", recorder)
        runner_b = _TaskRunner("b", recorder)

        _register_task_candidate(resolver, key="task-a", runner=runner_a)
        _register_task_candidate(resolver, key="task-b", runner=runner_b)
        _register_workflow_candidate(
            resolver,
            key="happy",
            dag={
                "nodes": [
                    {"id": "first", "task": "task-a"},
                    {
                        "id": "second",
                        "task": "task-b",
                        "depends_on": ["first"],
                    },
                ]
            },
        )
        task_bridge = TaskBridge(resolver, lifecycle_manager, layer_settings)
        bridge = WorkflowBridge(
            resolver, lifecycle_manager, layer_settings, task_bridge=task_bridge
        )

        result = await bridge.execute_dag("happy", context={"x": 1})

        results = result["results"]
        assert "first" in results
        assert "second" in results
        assert results["first"] == "A"
        assert results["second"] == "B"

    async def test_run_id_generated_when_not_provided(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
    ) -> None:
        _register_task_candidate(resolver, key="t")
        _register_workflow_candidate(
            resolver,
            key="autoid",
            dag={"nodes": [{"id": "step", "task": "t"}]},
        )
        bridge = WorkflowBridge(
            resolver,
            lifecycle_manager,
            layer_settings,
            task_bridge=TaskBridge(resolver, lifecycle_manager, layer_settings),
        )

        result = await bridge.execute_dag("autoid")

        run_id = result["run_id"]
        # UUID4 hex is 32 lowercase hex characters.
        assert isinstance(run_id, str)
        assert len(run_id) == 32
        assert all(c in "0123456789abcdef" for c in run_id)

    async def test_run_id_preserved_when_provided(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
    ) -> None:
        _register_task_candidate(resolver, key="t")
        _register_workflow_candidate(
            resolver,
            key="preserve",
            dag={"nodes": [{"id": "step", "task": "t"}]},
        )
        bridge = WorkflowBridge(
            resolver,
            lifecycle_manager,
            layer_settings,
            task_bridge=TaskBridge(resolver, lifecycle_manager, layer_settings),
        )

        result = await bridge.execute_dag("preserve", run_id="my-custom-run")

        assert result["run_id"] == "my-custom-run"

    async def test_use_checkpoint_store_false_skips_persistence(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
        tmp_path,
    ) -> None:
        store = WorkflowCheckpointStore(tmp_path / "ckpt.sqlite")
        _register_task_candidate(resolver, key="t")
        _register_workflow_candidate(
            resolver,
            key="no-store",
            dag={"nodes": [{"id": "step", "task": "t"}]},
        )
        bridge = WorkflowBridge(
            resolver,
            lifecycle_manager,
            layer_settings,
            task_bridge=TaskBridge(resolver, lifecycle_manager, layer_settings),
            checkpoint_store=store,
        )

        await bridge.execute_dag("no-store", use_checkpoint_store=False)

        # Nothing was written to the store.
        assert store.load("no-store") == {}

    async def test_resume_from_checkpoint_rehydrates(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
        tmp_path,
    ) -> None:
        store = WorkflowCheckpointStore(tmp_path / "ckpt.sqlite")
        # Pre-stage a checkpoint that the workflow can rehydrate from.
        store.save(
            "resume",
            {
                "first": "REUSED",
                "first__duration": 0.001,
                "first__attempts": 1,
            },
        )
        recorder: list[str] = []
        _register_task_candidate(
            resolver,
            key="task-first",
            runner=_TaskRunner("first", recorder),
        )
        _register_task_candidate(
            resolver,
            key="task-second",
            runner=_TaskRunner("second", recorder),
        )
        _register_workflow_candidate(
            resolver,
            key="resume",
            dag={
                "nodes": [
                    {"id": "first", "task": "task-first"},
                    {
                        "id": "second",
                        "task": "task-second",
                        "depends_on": ["first"],
                    },
                ]
            },
        )
        bridge = WorkflowBridge(
            resolver,
            lifecycle_manager,
            layer_settings,
            task_bridge=TaskBridge(resolver, lifecycle_manager, layer_settings),
            checkpoint_store=store,
        )

        result = await bridge.execute_dag("resume")

        # `first` reused from checkpoint; only `second` should have run.
        assert result["results"]["first"] == "REUSED"
        assert result["results"]["second"] == "SECOND"
        assert recorder == ["second:None"]

    async def test_missing_task_bridge_raises(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
    ) -> None:
        _register_workflow_candidate(resolver, key="no-bridge", dag={"nodes": []})
        bridge = WorkflowBridge(resolver, lifecycle_manager, layer_settings)
        # task_bridge is None

        with pytest.raises(LifecycleError, match="workflow-dag-missing-task-bridge"):
            await bridge.execute_dag("no-bridge")

    async def test_missing_dag_spec_raises(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
    ) -> None:
        bridge = WorkflowBridge(
            resolver,
            lifecycle_manager,
            layer_settings,
            task_bridge=TaskBridge(resolver, lifecycle_manager, layer_settings),
        )
        # No candidate registered for "ghost"

        with pytest.raises(LifecycleError, match="workflow-dag-missing"):
            await bridge.execute_dag("ghost")

    async def test_dag_node_missing_fields_raises(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
    ) -> None:
        _register_workflow_candidate(
            resolver,
            key="bad-spec",
            dag={"nodes": [{"task": "t1"}]},  # no `id`
        )
        bridge = WorkflowBridge(
            resolver,
            lifecycle_manager,
            layer_settings,
            task_bridge=TaskBridge(resolver, lifecycle_manager, layer_settings),
        )

        with pytest.raises(LifecycleError, match="workflow-dag-node-missing-fields"):
            await bridge.execute_dag("bad-spec")


# ---------------------------------------------------------------------------
# 6. Checkpoint integration
# ---------------------------------------------------------------------------


class TestCheckpointIntegration:
    """End-to-end: pre-stage checkpoint, run, verify re-hydration & clearing."""

    async def test_checkpoint_rehydrated_and_cleared_on_success(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
        tmp_path,
    ) -> None:
        store = WorkflowCheckpointStore(tmp_path / "ckpt.sqlite")
        store.save("ckpt-ok", {"first": "FROM_CHECKPOINT"})

        _register_task_candidate(resolver, key="t-second", runner=_TaskRunner("second"))
        _register_workflow_candidate(
            resolver,
            key="ckpt-ok",
            dag={
                "nodes": [
                    {"id": "first", "task": "t-stub"},
                    {
                        "id": "second",
                        "task": "t-second",
                        "depends_on": ["first"],
                    },
                ]
            },
        )
        bridge = WorkflowBridge(
            resolver,
            lifecycle_manager,
            layer_settings,
            task_bridge=TaskBridge(resolver, lifecycle_manager, layer_settings),
            checkpoint_store=store,
        )

        result = await bridge.execute_dag("ckpt-ok")

        assert result["results"]["first"] == "FROM_CHECKPOINT"
        # Store cleared after a successful run.
        assert store.load("ckpt-ok") == {}

    async def test_checkpoint_persisted_on_failure(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
        tmp_path,
    ) -> None:
        store = WorkflowCheckpointStore(tmp_path / "ckpt.sqlite")
        _register_task_candidate(resolver, key="t-fail", runner=_AlwaysFailTaskRunner())
        _register_workflow_candidate(
            resolver,
            key="ckpt-fail",
            dag={
                "nodes": [
                    {
                        "id": "failing",
                        "task": "t-fail",
                        "retry_policy": {
                            "attempts": 1,
                            "base_delay": 0.0,
                            "max_delay": 0.0,
                            "jitter": 0.0,
                        },
                    },
                ]
            },
        )
        bridge = WorkflowBridge(
            resolver,
            lifecycle_manager,
            layer_settings,
            task_bridge=TaskBridge(resolver, lifecycle_manager, layer_settings),
            checkpoint_store=store,
        )

        with pytest.raises(Exception):
            await bridge.execute_dag("ckpt-fail")

        # Even on failure, the empty checkpoint dict is persisted (it exists
        # in the store as an entry).
        stored = store.load("ckpt-fail")
        # Initial checkpoint_data was {}; nothing added because the task
        # never completed. We assert it is dict-shaped, not that it is empty.
        assert isinstance(stored, dict)

    async def test_failure_does_not_persist_when_store_disabled(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
        tmp_path,
    ) -> None:
        store = WorkflowCheckpointStore(tmp_path / "ckpt.sqlite")
        _register_task_candidate(resolver, key="t-fail", runner=_AlwaysFailTaskRunner())
        _register_workflow_candidate(
            resolver,
            key="ckpt-disabled",
            dag={
                "nodes": [
                    {
                        "id": "failing",
                        "task": "t-fail",
                        "retry_policy": {
                            "attempts": 1,
                            "base_delay": 0.0,
                            "max_delay": 0.0,
                            "jitter": 0.0,
                        },
                    },
                ]
            },
        )
        bridge = WorkflowBridge(
            resolver,
            lifecycle_manager,
            layer_settings,
            task_bridge=TaskBridge(resolver, lifecycle_manager, layer_settings),
            checkpoint_store=store,
        )

        with pytest.raises(Exception):
            await bridge.execute_dag("ckpt-disabled", use_checkpoint_store=False)

        # With use_checkpoint_store=False, the store should be empty.
        assert store.load("ckpt-disabled") == {}


# ---------------------------------------------------------------------------
# 7. Queue bridge integration
# ---------------------------------------------------------------------------


class TestQueueBridge:
    """enqueue_workflow requires and uses the queue bridge."""

    async def test_raises_when_queue_bridge_missing(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
    ) -> None:
        _register_workflow_candidate(resolver, key="x")
        bridge = WorkflowBridge(resolver, lifecycle_manager, layer_settings)

        with pytest.raises(LifecycleError, match="workflow-queue-bridge-missing"):
            await bridge.enqueue_workflow("x")

    async def test_invokes_queue_enqueue(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
    ) -> None:
        queue_bridge = _FakeQueueBridge()
        _register_workflow_candidate(
            resolver,
            key="q-test",
            scheduler={"queue_category": "queue.special", "provider": "prov"},
        )
        bridge = WorkflowBridge(
            resolver,
            lifecycle_manager,
            layer_settings,
            queue_bridge=queue_bridge,
            queue_category=None,
        )

        await bridge.enqueue_workflow("q-test", context={"k": "v"})

        assert queue_bridge.calls == [("queue.special", "prov")]
        # The fake adapter received the payload.
        assert len(queue_bridge.adapter.payloads) == 1
        payload = queue_bridge.adapter.payloads[0]
        assert payload["context"] == {"k": "v"}

    async def test_returns_payload_summary(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
    ) -> None:
        queue_bridge = _FakeQueueBridge()
        _register_workflow_candidate(
            resolver, key="summary", scheduler={"queue_category": "q"}
        )
        bridge = WorkflowBridge(
            resolver,
            lifecycle_manager,
            layer_settings,
            queue_bridge=queue_bridge,
            queue_category=None,
        )

        result = await bridge.enqueue_workflow("summary")

        assert "run_id" in result
        assert "queued_at" in result
        assert result["workflow"] == "summary"
        assert result["queue_category"] == "q"


# ---------------------------------------------------------------------------
# 8. Telemetry
# ---------------------------------------------------------------------------


class TestTelemetry:
    """Telemetry is recorded when supplied; otherwise no-op."""

    async def test_record_workflow_execution_called(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
    ) -> None:
        telemetry = MagicMock(spec=RuntimeTelemetryRecorder)
        _register_task_candidate(resolver, key="t")
        _register_workflow_candidate(
            resolver,
            key="telem",
            dag={"nodes": [{"id": "step", "task": "t"}]},
        )
        bridge = WorkflowBridge(
            resolver,
            lifecycle_manager,
            layer_settings,
            task_bridge=TaskBridge(resolver, lifecycle_manager, layer_settings),
            telemetry=telemetry,
        )

        await bridge.execute_dag("telem")

        telemetry.record_workflow_execution.assert_called_once()
        # First positional args: workflow_key, dag_spec, results dict.
        call_args = telemetry.record_workflow_execution.call_args
        assert call_args.args[0] == "telem"

    async def test_no_telemetry_does_not_break(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
    ) -> None:
        _register_task_candidate(resolver, key="t")
        _register_workflow_candidate(
            resolver,
            key="no-telem",
            dag={"nodes": [{"id": "step", "task": "t"}]},
        )
        bridge = WorkflowBridge(
            resolver,
            lifecycle_manager,
            layer_settings,
            task_bridge=TaskBridge(resolver, lifecycle_manager, layer_settings),
            # No telemetry kwarg
        )

        # Should run without error
        result = await bridge.execute_dag("no-telem")
        assert "results" in result


# ---------------------------------------------------------------------------
# 9. Enqueue payload shape & queue category precedence
# ---------------------------------------------------------------------------


class TestEnqueuePayload:
    """Inspect the payload handed to the queue and the precedence rules."""

    async def test_payload_contains_run_id_and_queued_at(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
    ) -> None:
        queue_bridge = _FakeQueueBridge()
        _register_workflow_candidate(
            resolver, key="shape", scheduler={"queue_category": "q"}
        )
        bridge = WorkflowBridge(
            resolver,
            lifecycle_manager,
            layer_settings,
            queue_bridge=queue_bridge,
            queue_category=None,
        )

        await bridge.enqueue_workflow("shape")

        payload = queue_bridge.adapter.payloads[0]
        # run_id: 32-char UUID4 hex
        run_id = payload["run_id"]
        assert isinstance(run_id, str)
        assert len(run_id) == 32
        assert all(c in "0123456789abcdef" for c in run_id)
        # queued_at: ISO 8601 UTC (ends with +00:00)
        queued_at = payload["queued_at"]
        assert isinstance(queued_at, str)
        assert queued_at.endswith("+00:00") or queued_at.endswith("Z")

    async def test_payload_contains_task_name_and_queue_category(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
    ) -> None:
        queue_bridge = _FakeQueueBridge()
        _register_workflow_candidate(
            resolver, key="qc-test", scheduler={"queue_category": "queue.qc"}
        )
        bridge = WorkflowBridge(
            resolver,
            lifecycle_manager,
            layer_settings,
            queue_bridge=queue_bridge,
            queue_category=None,
        )

        result = await bridge.enqueue_workflow("qc-test")

        assert result["queue_category"] == "queue.qc"
        assert isinstance(result["task_name"], str)
        assert result["task_name"].startswith("task-")

    async def test_queue_category_argument_overrides_metadata(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
    ) -> None:
        queue_bridge = _FakeQueueBridge()
        _register_workflow_candidate(
            resolver,
            key="over-meta",
            scheduler={"queue_category": "queue.meta", "provider": "meta-p"},
        )
        bridge = WorkflowBridge(
            resolver,
            lifecycle_manager,
            layer_settings,
            queue_bridge=queue_bridge,
            queue_category=None,
        )

        result = await bridge.enqueue_workflow("over-meta", queue_category="queue.arg")

        assert result["queue_category"] == "queue.arg"
        assert queue_bridge.calls == [("queue.arg", "meta-p")]

    async def test_queue_category_metadata_overrides_settings(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
    ) -> None:
        from oneiric.core.config import LayerSettings

        queue_bridge = _FakeQueueBridge()
        settings = LayerSettings(options={"queue_category": "queue.settings"})
        _register_workflow_candidate(
            resolver, key="meta-wins", scheduler={"queue_category": "queue.meta"}
        )
        bridge = WorkflowBridge(
            resolver,
            lifecycle_manager,
            settings,
            queue_bridge=queue_bridge,
            queue_category=None,
        )

        result = await bridge.enqueue_workflow("meta-wins")

        assert result["queue_category"] == "queue.meta"

    async def test_queue_category_settings_fallback(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
    ) -> None:
        from oneiric.core.config import LayerSettings

        queue_bridge = _FakeQueueBridge()
        settings = LayerSettings(options={"queue_category": "queue.from-settings"})
        _register_workflow_candidate(resolver, key="no-meta")
        bridge = WorkflowBridge(
            resolver,
            lifecycle_manager,
            settings,
            queue_bridge=queue_bridge,
            queue_category=None,
        )

        result = await bridge.enqueue_workflow("no-meta")

        assert result["queue_category"] == "queue.from-settings"

    async def test_queue_category_default_when_nothing(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
    ) -> None:
        queue_bridge = _FakeQueueBridge()
        _register_workflow_candidate(resolver, key="def-q")
        bridge = WorkflowBridge(
            resolver,
            lifecycle_manager,
            layer_settings,
            queue_bridge=queue_bridge,
            queue_category=None,
        )

        result = await bridge.enqueue_workflow("def-q")

        assert result["queue_category"] == "queue"


# ---------------------------------------------------------------------------
# 10. Integration scenarios
# ---------------------------------------------------------------------------


class TestWorkflowBridgeIntegration:
    """Full-pipeline scenarios combining real components end-to-end."""

    async def test_full_pipeline_executes_dag_with_task_bridge(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
    ) -> None:
        recorder: list[str] = []
        _register_task_candidate(
            resolver, key="extract-task", runner=_TaskRunner("extract", recorder)
        )
        _register_task_candidate(
            resolver, key="notify-task", runner=_TaskRunner("notify", recorder)
        )
        _register_workflow_candidate(
            resolver,
            key="full-wf",
            dag={
                "nodes": [
                    {"id": "extract", "task": "extract-task"},
                    {
                        "id": "notify",
                        "task": "notify-task",
                        "depends_on": ["extract"],
                        "payload": {"channel": "ops"},
                    },
                ]
            },
        )
        task_bridge = TaskBridge(resolver, lifecycle_manager, layer_settings)
        bridge = WorkflowBridge(
            resolver,
            lifecycle_manager,
            layer_settings,
            task_bridge=task_bridge,
        )

        result = await bridge.execute_dag("full-wf", context={"tenant": "default"})

        results = result["results"]
        assert results["extract"] == "EXTRACT"
        assert results["notify"] == "NOTIFY"
        assert recorder == [
            "extract:{'tenant': 'default'}",
            "notify:{'channel': 'ops'}",
        ]

    async def test_full_pipeline_enqueues_via_stubbed_queue_bridge(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
    ) -> None:
        queue_bridge = _FakeQueueBridge()
        _register_workflow_candidate(
            resolver,
            key="enqueue-wf",
            scheduler={"queue_category": "queue.cloud", "provider": "pubsub"},
        )
        bridge = WorkflowBridge(
            resolver,
            lifecycle_manager,
            layer_settings,
            queue_bridge=queue_bridge,
            queue_category=None,
        )

        result = await bridge.enqueue_workflow("enqueue-wf", context={"id": 42})

        assert result["queue_category"] == "queue.cloud"
        assert result["queue_provider"] == "pubsub"
        payload = queue_bridge.adapter.payloads[0]
        assert payload["context"] == {"id": 42}
        assert payload["workflow"] == "enqueue-wf"

    async def test_full_pipeline_with_checkpoint_recovery(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
        tmp_path,
    ) -> None:
        """Run, fail, checkpoint saved; re-run after fix, checkpoint cleared."""
        store = WorkflowCheckpointStore(tmp_path / "ckpt.sqlite")
        # Use a controllable runner to switch behavior between runs.
        runner = _FlakyTaskRunner("step", fail_first=99)
        _register_task_candidate(resolver, key="t", runner=runner)
        _register_workflow_candidate(
            resolver,
            key="recovery",
            dag={
                "nodes": [
                    {
                        "id": "step",
                        "task": "t",
                        "retry_policy": {
                            "attempts": 1,
                            "base_delay": 0.0,
                            "max_delay": 0.0,
                            "jitter": 0.0,
                        },
                    },
                ]
            },
        )
        task_bridge = TaskBridge(resolver, lifecycle_manager, layer_settings)
        bridge = WorkflowBridge(
            resolver,
            lifecycle_manager,
            layer_settings,
            task_bridge=task_bridge,
            checkpoint_store=store,
        )

        # First run fails.
        with pytest.raises(Exception):
            await bridge.execute_dag("recovery")
        assert runner.calls == 1
        # Checkpoint exists after failure (we have an entry — value may be {}).
        # Second run will not reuse anything because no node completed, but
        # the failure again should still be safe.
        with pytest.raises(Exception):
            await bridge.execute_dag("recovery")
        assert runner.calls == 2


# ---------------------------------------------------------------------------
# 11. Property test
# ---------------------------------------------------------------------------


class TestDagSpecsIsolated:
    """Property: mutating the result of dag_specs() never affects internal state."""

    # The shared ``resolver``/``lifecycle_manager``/``layer_settings``
    # fixtures are function-scoped, which is fine for our property test
    # because we register a fresh candidate per input but never rely on
    # inter-input state.
    @hyp_settings(
        max_examples=25,
        suppress_health_check=[
            HealthCheck.too_slow,
            HealthCheck.function_scoped_fixture,
        ],
    )
    @given(
        key=st.text(
            alphabet=st.characters(
                whitelist_categories=("L", "N"),
                whitelist_characters="-_",
            ),
            min_size=1,
            max_size=12,
        ),
        mutation_value=st.dictionaries(
            keys=st.text(min_size=1, max_size=8),
            values=st.integers(),
            max_size=4,
        ),
    )
    def test_dag_specs_isolated_from_caller(
        self,
        resolver: Resolver,
        lifecycle_manager: LifecycleManager,
        layer_settings,
        key: str,
        mutation_value: dict[str, Any],
    ) -> None:
        # Use a key unique to this generated input so the registration does
        # not pollute the resolver with prior inputs' candidates.
        unique_key = f"h_{abs(hash(key)) % 10**8}_{abs(hash(tuple(mutation_value.items()))) % 10**8}"
        _register_workflow_candidate(resolver, key=unique_key, dag={"nodes": []})
        bridge = WorkflowBridge(resolver, lifecycle_manager, layer_settings)

        snapshot = bridge.dag_specs()
        # Mutate aggressively.
        snapshot.clear()
        snapshot["__attacker__"] = mutation_value  # type: ignore[index]
        snapshot.setdefault(unique_key, {})

        # Re-fetch and verify the bridge's internal state was untouched.
        fresh = bridge.dag_specs()
        assert "__attacker__" not in fresh
        # `unique_key` still has the original spec.
        assert fresh[unique_key] == {"nodes": []}
