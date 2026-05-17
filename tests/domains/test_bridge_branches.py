from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from oneiric.core.config import LayerSettings
from oneiric.core.lifecycle import LifecycleError, LifecycleManager
from oneiric.core.resolution import Candidate, CandidateSource, Resolver
from oneiric.domains.events import EventBridge
from oneiric.domains.workflows import WorkflowBridge
from oneiric.runtime.activity import DomainActivityStore
from oneiric.runtime.events import create_event_envelope


def test_event_handler_snapshot_normalizes_unset_equals(tmp_path) -> None:
    resolver = Resolver()
    lifecycle = LifecycleManager(resolver)
    bridge = EventBridge(resolver, lifecycle, LayerSettings())

    resolver.register(
        Candidate(
            domain="event",
            key="notify",
            provider="demo",
            factory=lambda: object(),
            source=CandidateSource.MANUAL,
            metadata={
                "topics": ["demo.topic"],
                "filters": [{"path": "payload.kind"}],
            },
        )
    )
    bridge.refresh_dispatcher()

    snapshot = bridge.handler_snapshot()

    assert snapshot[0]["topics"] == ["demo.topic"]
    assert snapshot[0]["filters"][0]["equals"] is None


@pytest.mark.asyncio
async def test_event_handler_missing_handle_method_raises(tmp_path) -> None:
    resolver = Resolver()
    lifecycle = LifecycleManager(resolver)
    bridge = EventBridge(resolver, lifecycle, LayerSettings())

    candidate = Candidate(
        domain="event",
        key="notify",
        provider="demo",
        factory=lambda: object(),
        source=CandidateSource.MANUAL,
        metadata={"topics": ["demo.topic"]},
    )
    handler = bridge._build_handler(candidate)
    assert handler is not None

    bridge.use = AsyncMock(return_value=SimpleNamespace(instance=object()))  # type: ignore[method-assign]

    with pytest.raises(LifecycleError, match="missing-handle-method"):
        await handler.callback(create_event_envelope("demo.topic", {}, source="test"))


def test_workflow_queue_category_defaults_from_settings() -> None:
    resolver = Resolver()
    lifecycle = LifecycleManager(resolver)
    settings = LayerSettings(options={})

    bridge = WorkflowBridge(resolver, lifecycle, settings)

    assert bridge._queue_category == "queue"


def test_workflow_resolve_scheduler_details_missing_category_raises() -> None:
    resolver = Resolver()
    lifecycle = LifecycleManager(resolver)
    bridge = WorkflowBridge(resolver, lifecycle, LayerSettings())
    bridge._queue_category = None

    candidate = Candidate(
        domain="workflow",
        key="demo",
        provider="demo",
        factory=lambda: object(),
        source=CandidateSource.MANUAL,
        metadata={},
    )

    with pytest.raises(LifecycleError, match="workflow-queue-category-missing"):
        bridge._resolve_scheduler_details(
            candidate,
            override_category=None,
            override_provider=None,
        )


@pytest.mark.asyncio
async def test_workflow_runner_for_task_and_checkpoint_paths(tmp_path, monkeypatch) -> None:
    resolver = Resolver()
    lifecycle = LifecycleManager(resolver)
    store = SimpleNamespace(saved=[], cleared=[])

    def save(workflow_key, checkpoint_data):
        store.saved.append((workflow_key, checkpoint_data))

    def clear(workflow_key):
        store.cleared.append(workflow_key)

    store.save = save
    store.clear = clear

    bridge = WorkflowBridge(
        resolver,
        lifecycle,
        LayerSettings(),
        checkpoint_store=store,  # type: ignore[arg-type]
    )

    bridge._task_bridge = SimpleNamespace(
        use=AsyncMock(return_value=SimpleNamespace(instance=object()))
    )
    runner = bridge._runner_for_task("task-1", None, None)

    with pytest.raises(LifecycleError, match="missing-run"):
        await runner()

    class TaskHandler:
        async def run(self, payload=None):
            return payload

    bridge._task_bridge = SimpleNamespace(
        use=AsyncMock(return_value=SimpleNamespace(instance=TaskHandler()))
    )
    runner = bridge._runner_for_task("task-2", {"value": 1}, None)
    assert await runner() == {"value": 1}

    async def failing_execute_dag(*args, **kwargs):
        raise RuntimeError("boom")

    async def successful_execute_dag(*args, **kwargs):
        return {"results": {"ok": True}}

    graph = object()
    monkeypatch.setattr("oneiric.domains.workflows.execute_dag", failing_execute_dag)
    with pytest.raises(RuntimeError, match="boom"):
        await bridge._execute_with_checkpoint(
            graph,
            "demo",
            {"step": 1},
            None,
            use_checkpoint_store=True,
        )
    assert store.saved == [("demo", {"step": 1})]

    monkeypatch.setattr("oneiric.domains.workflows.execute_dag", successful_execute_dag)
    result = await bridge._execute_with_checkpoint(
        graph,
        "demo",
        {"step": 2},
        None,
        use_checkpoint_store=True,
    )
    assert result == {"results": {"ok": True}}
    assert store.cleared == ["demo"]
