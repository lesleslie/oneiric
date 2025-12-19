"""Workflow bridge with DAG orchestration helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from oneiric.core.config import LayerSettings
from oneiric.core.lifecycle import LifecycleError, LifecycleManager
from oneiric.core.resolution import Candidate, Resolver
from oneiric.runtime.activity import DomainActivityStore
from oneiric.runtime.dag import (
    DAGExecutionHooks,
    DAGRunResult,
    DAGTask,
    build_graph,
    execute_dag,
)
from oneiric.runtime.durable import build_durable_execution_hooks
from oneiric.runtime.protocols import (
    WorkflowCheckpointStoreProtocol,
    WorkflowExecutionStoreProtocol,
)
from oneiric.runtime.supervisor import ServiceSupervisor
from oneiric.runtime.telemetry import RuntimeTelemetryRecorder

from .base import DomainBridge
from .protocols import TaskHandlerProtocol
from .tasks import TaskBridge

if TYPE_CHECKING:  # pragma: no cover - hints only
    from oneiric.adapters.bridge import AdapterBridge
    from oneiric.adapters.queue.protocols import QueueAdapterProtocol


class WorkflowBridge(DomainBridge):
    """Domain bridge that can execute DAG-driven workflows."""

    def __init__(
        self,
        resolver: Resolver,
        lifecycle: LifecycleManager,
        settings: LayerSettings,
        activity_store: DomainActivityStore | None = None,
        task_bridge: TaskBridge | None = None,
        checkpoint_store: WorkflowCheckpointStoreProtocol | None = None,
        execution_store: WorkflowExecutionStoreProtocol | None = None,
        queue_bridge: AdapterBridge | None = None,
        queue_category: str | None = "queue",
        supervisor: ServiceSupervisor | None = None,
        telemetry: RuntimeTelemetryRecorder | None = None,
    ) -> None:
        super().__init__(
            "workflow",
            resolver,
            lifecycle,
            settings,
            activity_store=activity_store,
            supervisor=supervisor,
        )
        self._task_bridge = task_bridge
        self._dag_specs: dict[str, dict[str, Any]] = {}
        self._checkpoint_store = checkpoint_store
        self._execution_hooks: DAGExecutionHooks | None = (
            build_durable_execution_hooks(execution_store)
            if execution_store is not None
            else None
        )
        self._queue_bridge = queue_bridge
        self._queue_category_override = queue_category
        self._queue_category = (
            self._queue_category_override
            or self._queue_category_from_settings(settings)
        )
        self._telemetry = telemetry
        self.refresh_dags()

    def update_settings(self, settings: LayerSettings) -> None:
        super().update_settings(settings)
        if self._queue_category_override is None:
            self._queue_category = self._queue_category_from_settings(settings)
        self.refresh_dags()

    def refresh_dags(self) -> None:
        dag_map: dict[str, dict[str, Any]] = {}
        for candidate in self.resolver.list_active(self.domain):
            dag_spec = candidate.metadata.get("dag")
            if dag_spec:
                dag_map[candidate.key] = dag_spec
        self._dag_specs = dag_map

    def dag_specs(self) -> dict[str, dict[str, Any]]:
        """Return a snapshot of known DAG specifications."""

        return dict(self._dag_specs)

    async def execute_dag(
        self,
        workflow_key: str,
        *,
        context: dict[str, Any] | None = None,
        checkpoint: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> DAGRunResult:
        """Execute the DAG associated with the workflow key."""
        # Validate workflow and dependencies
        dag_spec = self._get_dag_spec(workflow_key)
        self._ensure_activity_allowed(workflow_key)
        if not self._task_bridge:
            raise LifecycleError("workflow-dag-missing-task-bridge")

        # Build task definitions and graph
        task_defs = self._build_task_definitions(dag_spec, context)
        graph = build_graph(task_defs)

        # Load or create checkpoint data
        checkpoint_data = self._load_checkpoint_data(workflow_key, checkpoint)

        # Execute DAG with checkpoint handling
        run_result = await self._execute_with_checkpoint(
            graph, workflow_key, checkpoint_data, run_id
        )
        if self._telemetry:
            self._telemetry.record_workflow_execution(
                workflow_key, dag_spec, run_result["results"]
            )
        return run_result

    async def enqueue_workflow(
        self,
        workflow_key: str,
        *,
        context: dict[str, Any] | None = None,
        queue_category: str | None = None,
        provider: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Enqueue workflow execution via configured queue adapter."""

        if not self._queue_bridge:
            raise LifecycleError("workflow-queue-bridge-missing")
        candidate = self.resolver.resolve(self.domain, workflow_key)
        if not candidate:
            raise LifecycleError(f"workflow-missing ({workflow_key})")
        category, target_provider = self._resolve_scheduler_details(
            candidate,
            override_category=queue_category,
            override_provider=provider,
        )

        handle = await self._queue_bridge.use(category, provider=target_provider)
        queue = cast("QueueAdapterProtocol", handle.instance)
        enqueue = getattr(queue, "enqueue", None)
        if not callable(enqueue):
            raise LifecycleError("workflow-queue-adapter-missing-enqueue")

        payload = self._build_queue_payload(
            workflow_key,
            context=context,
            metadata=metadata,
            workflow_provider=candidate.provider,
        )
        task_name = await enqueue(payload)
        result = {
            "workflow": workflow_key,
            "run_id": payload["run_id"],
            "task_name": task_name,
            "queue_category": category,
            "queue_provider": handle.provider,
            "queued_at": payload["queued_at"],
        }
        self._logger.info("workflow-enqueued", **result)
        return result

    def _get_dag_spec(self, workflow_key: str) -> dict[str, Any]:
        """Get and validate DAG specification."""
        dag_spec = self._dag_specs.get(workflow_key)
        if not dag_spec:
            raise LifecycleError(f"workflow-dag-missing ({workflow_key})")
        return dag_spec

    def _build_task_definitions(
        self, dag_spec: dict[str, Any], context: dict[str, Any] | None
    ) -> list[DAGTask]:
        """Build task definitions from DAG specification."""
        nodes_raw: Any = dag_spec.get("nodes") or dag_spec.get("tasks") or []
        nodes: list[dict[str, Any]] = nodes_raw if isinstance(nodes_raw, list) else []
        task_defs: list[DAGTask] = []

        for node in nodes:
            node_id = node.get("id") or node.get("key")
            task_key = node.get("task")
            if not node_id or not task_key:
                raise LifecycleError("workflow-dag-node-missing-fields")

            task_defs.append(
                DAGTask(
                    key=node_id,
                    depends_on=node.get("depends_on") or [],
                    runner=self._runner_for_task(
                        task_key, node.get("payload"), context
                    ),
                    retry_policy=node.get("retry_policy"),
                )
            )

        return task_defs

    def _load_checkpoint_data(
        self, workflow_key: str, checkpoint: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Load checkpoint data from provided checkpoint or store."""
        if checkpoint is not None:
            return dict(checkpoint)
        elif self._checkpoint_store:
            return self._checkpoint_store.load(workflow_key)
        return {}

    async def _execute_with_checkpoint(
        self,
        graph: Any,
        workflow_key: str,
        checkpoint_data: dict[str, Any],
        run_id: str | None,
    ) -> DAGRunResult:
        """Execute DAG with checkpoint save/clear handling."""
        try:
            run_result = await execute_dag(
                graph,
                checkpoint=checkpoint_data,
                workflow_key=workflow_key,
                run_id=run_id,
                hooks=self._execution_hooks,
            )
        except Exception:
            if self._checkpoint_store:
                self._checkpoint_store.save(workflow_key, checkpoint_data)
            raise
        else:
            if self._checkpoint_store:
                self._checkpoint_store.clear(workflow_key)
            return run_result

    def _runner_for_task(
        self,
        task_key: str,
        node_payload: dict[str, Any] | None,
        context: dict[str, Any] | None,
    ):
        async def _run():
            assert self._task_bridge is not None  # Type guard
            handle = await self._task_bridge.use(task_key)  # type: ignore[arg-type]
            instance = cast(TaskHandlerProtocol, handle.instance)
            runner = getattr(instance, "run", None)
            if not callable(runner):
                raise LifecycleError(f"workflow-dag-task-missing-run ({task_key})")
            payload = node_payload if node_payload is not None else context
            return await runner(payload) if payload is not None else await runner()

        return _run

    def _build_queue_payload(
        self,
        workflow_key: str,
        *,
        context: dict[str, Any] | None,
        metadata: dict[str, Any] | None,
        workflow_provider: str | None,
    ) -> dict[str, Any]:
        """Construct payload passed to queue adapters."""

        return {
            "workflow": workflow_key,
            "run_id": uuid4().hex,
            "workflow_provider": workflow_provider,
            "context": dict(context or {}),
            "metadata": dict(metadata or {}),
            "queued_at": datetime.now(UTC).isoformat(),
        }

    def _resolve_scheduler_details(
        self,
        candidate: Candidate,
        *,
        override_category: str | None,
        override_provider: str | None,
    ) -> tuple[str, str | None]:
        scheduler_cfg = candidate.metadata.get("scheduler") or {}
        if not isinstance(scheduler_cfg, dict):
            scheduler_cfg = {}
        category = (
            override_category
            or scheduler_cfg.get("queue_category")
            or scheduler_cfg.get("category")
            or self._queue_category
        )
        if not category:
            raise LifecycleError("workflow-queue-category-missing")
        provider = override_provider or scheduler_cfg.get("provider")
        return category, provider

    def _queue_category_from_settings(self, settings: LayerSettings) -> str | None:
        options = getattr(settings, "options", None)
        if isinstance(options, dict):
            category = options.get("queue_category") or options.get(
                "default_queue_category"
            )
            if category:
                return category
        return "queue"
