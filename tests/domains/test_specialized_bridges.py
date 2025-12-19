"""Tests for specialized domain bridges (Service, Task, Event, Workflow)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from oneiric.core.config import LayerSettings
from oneiric.core.lifecycle import LifecycleManager
from oneiric.core.resolution import Candidate, CandidateSource, Resolver
from oneiric.domains.base import DomainHandle
from oneiric.domains.events import EventBridge
from oneiric.domains.services import ServiceBridge
from oneiric.domains.tasks import TaskBridge
from oneiric.domains.workflows import WorkflowBridge
from oneiric.runtime.activity import DomainActivityStore
from oneiric.runtime.checkpoints import WorkflowCheckpointStore

# Test helpers


class MockComponent:
    """Mock component for testing."""

    def __init__(self, name: str):
        self.name = name


class DemoEventHandler:
    def __init__(self, recorder: list[str]):
        self.recorder = recorder

    async def handle(self, envelope):
        self.recorder.append(envelope.topic)
        return {"topic": envelope.topic}


class DemoTaskRunner:
    def __init__(self, label: str, recorder: list[str]):
        self.label = label
        self.recorder = recorder

    async def run(self, payload: Any = None):
        self.recorder.append(f"{self.label}:{payload}")
        return self.label.upper()


class FlakyTaskRunner:
    """Task runner that fails the first attempt."""

    def __init__(self, label: str, recorder: list[str]):
        self.label = label
        self.recorder = recorder
        self.calls = 0

    async def run(self, payload: Any = None):
        self.calls += 1
        self.recorder.append(f"{self.label}:{self.calls}")
        if self.calls < 2:
            raise RuntimeError("flaky-task-error")
        return self.label.upper()


class ControlledTaskRunner:
    """Task runner that can toggle failure across invocations."""

    def __init__(self, label: str, recorder: list[str], should_fail: bool = False):
        self.label = label
        self.recorder = recorder
        self.should_fail = should_fail

    async def run(self, payload: Any = None):
        self.recorder.append(f"{self.label}:{payload}")
        if self.should_fail:
            raise RuntimeError(f"{self.label}-fail")
        return self.label.upper()


class FakeQueueAdapter:
    """Minimal queue adapter recording enqueue payloads."""

    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    async def enqueue(self, payload: dict[str, Any]) -> str:
        self.payloads.append(payload)
        return f"fake-task-{len(self.payloads)}"


@dataclass
class FakeQueueHandle:
    category: str
    provider: str
    instance: Any
    settings: dict[str, Any]
    metadata: dict[str, Any]


class FakeQueueBridge:
    """Stubbed queue bridge for testing enqueue logic."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.adapter = FakeQueueAdapter()

    async def use(
        self, category: str, *, provider: str | None = None, force_reload: bool = False
    ) -> FakeQueueHandle:
        provider_name = provider or "default-provider"
        self.calls.append((category, provider_name))
        return FakeQueueHandle(
            category=category,
            provider=provider_name,
            instance=self.adapter,
            settings={},
            metadata={},
        )


class TestServiceBridge:
    """Test ServiceBridge domain-specific functionality."""

    def test_service_bridge_initialization(self):
        """ServiceBridge initializes with 'service' domain."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()

        bridge = ServiceBridge(resolver, lifecycle, settings)

        assert bridge.domain == "service"
        assert bridge.resolver is resolver
        assert bridge.lifecycle is lifecycle

    @pytest.mark.asyncio
    async def test_service_bridge_use(self):
        """ServiceBridge.use() activates service components."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = ServiceBridge(resolver, lifecycle, settings)

        resolver.register(
            Candidate(
                domain="service",
                key="api",
                provider="fastapi",
                factory=lambda: MockComponent("api"),
                source=CandidateSource.MANUAL,
            )
        )

        handle = await bridge.use("api")

        assert isinstance(handle, DomainHandle)
        assert handle.domain == "service"
        assert handle.key == "api"
        assert handle.provider == "fastapi"

    def test_service_bridge_active_candidates(self):
        """ServiceBridge lists only service domain candidates."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = ServiceBridge(resolver, lifecycle, settings)

        resolver.register(
            Candidate(
                domain="service",
                key="api",
                provider="fastapi",
                factory=lambda: None,
                source=CandidateSource.MANUAL,
            )
        )
        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: None,
                source=CandidateSource.MANUAL,
            )
        )

        active = bridge.active_candidates()

        assert len(active) == 1
        assert active[0].domain == "service"

    def test_service_bridge_activity_management(self):
        """ServiceBridge manages activity state for services."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = ServiceBridge(resolver, lifecycle, settings)

        state = bridge.set_paused("api", True, note="maintenance")

        assert state.paused is True
        assert state.note == "maintenance"


class TestTaskBridge:
    """Test TaskBridge domain-specific functionality."""

    def test_task_bridge_initialization(self):
        """TaskBridge initializes with 'task' domain."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()

        bridge = TaskBridge(resolver, lifecycle, settings)

        assert bridge.domain == "task"

    @pytest.mark.asyncio
    async def test_task_bridge_use(self):
        """TaskBridge.use() activates task components."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = TaskBridge(resolver, lifecycle, settings)

        resolver.register(
            Candidate(
                domain="task",
                key="email-sender",
                provider="celery",
                factory=lambda: MockComponent("email"),
                source=CandidateSource.MANUAL,
            )
        )

        handle = await bridge.use("email-sender")

        assert handle.domain == "task"
        assert handle.key == "email-sender"
        assert handle.provider == "celery"

    def test_task_bridge_active_candidates(self):
        """TaskBridge lists only task domain candidates."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = TaskBridge(resolver, lifecycle, settings)

        resolver.register(
            Candidate(
                domain="task",
                key="email-sender",
                provider="celery",
                factory=lambda: None,
                source=CandidateSource.MANUAL,
            )
        )
        resolver.register(
            Candidate(
                domain="service",
                key="api",
                provider="fastapi",
                factory=lambda: None,
                source=CandidateSource.MANUAL,
            )
        )

        active = bridge.active_candidates()

        assert len(active) == 1
        assert active[0].domain == "task"

    def test_task_bridge_activity_management(self):
        """TaskBridge manages activity state for tasks."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = TaskBridge(resolver, lifecycle, settings)

        state = bridge.set_draining("email-sender", True, note="draining queue")

        assert state.draining is True
        assert state.note == "draining queue"


class TestEventBridge:
    """Test EventBridge domain-specific functionality."""

    def test_event_bridge_initialization(self):
        """EventBridge initializes with 'event' domain."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()

        bridge = EventBridge(resolver, lifecycle, settings)

        assert bridge.domain == "event"

    @pytest.mark.asyncio
    async def test_event_bridge_use(self):
        """EventBridge.use() activates event components."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = EventBridge(resolver, lifecycle, settings)

        resolver.register(
            Candidate(
                domain="event",
                key="user-signup",
                provider="rabbitmq",
                factory=lambda: MockComponent("signup"),
                source=CandidateSource.MANUAL,
            )
        )

        handle = await bridge.use("user-signup")

        assert handle.domain == "event"
        assert handle.key == "user-signup"
        assert handle.provider == "rabbitmq"

    def test_event_bridge_active_candidates(self):
        """EventBridge lists only event domain candidates."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = EventBridge(resolver, lifecycle, settings)

        resolver.register(
            Candidate(
                domain="event",
                key="user-signup",
                provider="rabbitmq",
                factory=lambda: None,
                source=CandidateSource.MANUAL,
            )
        )
        resolver.register(
            Candidate(
                domain="task",
                key="email-sender",
                provider="celery",
                factory=lambda: None,
                source=CandidateSource.MANUAL,
            )
        )

        active = bridge.active_candidates()

        assert len(active) == 1
        assert active[0].domain == "event"

    def test_event_bridge_activity_management(self):
        """EventBridge manages activity state for events."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = EventBridge(resolver, lifecycle, settings)

        state = bridge.set_paused("user-signup", True, note="event processing paused")

        assert state.paused is True

    @pytest.mark.asyncio
    async def test_event_bridge_dispatch_filters_topics(self):
        """EventBridge dispatches events only to handlers interested in the topic."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = EventBridge(resolver, lifecycle, settings)
        recorder: list[str] = []

        resolver.register(
            Candidate(
                domain="event",
                key="user-handler",
                provider="remote",
                factory=lambda: DemoEventHandler(recorder),
                metadata={"topics": ["user.created"]},
                source=CandidateSource.MANUAL,
            )
        )

        bridge.refresh_dispatcher()

        results = await bridge.emit("user.created", {"user_id": 123})
        assert len(results) == 1
        assert recorder == ["user.created"]

        recorder.clear()
        results = await bridge.emit("order.created", {"order_id": 42})
        assert results == []
        assert recorder == []

    @pytest.mark.asyncio
    async def test_event_bridge_applies_metadata_filters(self):
        """EventBridge honors payload filters derived from manifest metadata."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = EventBridge(resolver, lifecycle, settings)
        recorder: list[str] = []

        resolver.register(
            Candidate(
                domain="event",
                key="regional-handler",
                provider="remote",
                factory=lambda: DemoEventHandler(recorder),
                metadata={
                    "topics": ["demo.topic"],
                    "filters": [{"path": "payload.region", "equals": "us"}],
                },
                source=CandidateSource.MANUAL,
            )
        )

        bridge.refresh_dispatcher()

        results = await bridge.emit("demo.topic", {"region": "us"})
        assert len(results) == 1
        assert recorder == ["demo.topic"]  # filter allowed payload

        recorder.clear()
        results = await bridge.emit("demo.topic", {"region": "eu"})
        assert results == []
        assert recorder == []

    @pytest.mark.asyncio
    async def test_event_bridge_enforces_exclusive_fanout_priority(self):
        """Exclusive fan-out handlers execute highest priority only."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = EventBridge(resolver, lifecycle, settings)
        recorder: list[str] = []

        resolver.register(
            Candidate(
                domain="event",
                key="low-priority",
                provider="remote",
                factory=lambda: DemoEventHandler(recorder),
                metadata={
                    "topics": ["demo.topic"],
                    "event_priority": 5,
                    "fanout_policy": "exclusive",
                },
                source=CandidateSource.MANUAL,
            )
        )
        resolver.register(
            Candidate(
                domain="event",
                key="high-priority",
                provider="remote",
                factory=lambda: DemoEventHandler(recorder),
                metadata={
                    "topics": ["demo.topic"],
                    "event_priority": 50,
                    "fanout_policy": "exclusive",
                },
                source=CandidateSource.MANUAL,
            )
        )
        resolver.register(
            Candidate(
                domain="event",
                key="broadcast-handler",
                provider="remote",
                factory=lambda: DemoEventHandler(recorder),
                metadata={"topics": ["demo.topic"]},
                source=CandidateSource.MANUAL,
            )
        )

        bridge.refresh_dispatcher()

        results = await bridge.emit("demo.topic", {"region": "us"})
        assert len(results) == 1
        assert recorder == ["demo.topic"]
        assert results[0].handler.startswith("high-priority")


class TestWorkflowBridge:
    """Test WorkflowBridge domain-specific functionality."""

    def test_workflow_bridge_initialization(self):
        """WorkflowBridge initializes with 'workflow' domain."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()

        bridge = WorkflowBridge(resolver, lifecycle, settings)

        assert bridge.domain == "workflow"

    @pytest.mark.asyncio
    async def test_workflow_bridge_use(self):
        """WorkflowBridge.use() activates workflow components."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = WorkflowBridge(resolver, lifecycle, settings)

        resolver.register(
            Candidate(
                domain="workflow",
                key="onboarding",
                provider="temporal",
                factory=lambda: MockComponent("onboarding"),
                source=CandidateSource.MANUAL,
            )
        )

        handle = await bridge.use("onboarding")

        assert handle.domain == "workflow"
        assert handle.key == "onboarding"
        assert handle.provider == "temporal"

    def test_workflow_bridge_active_candidates(self):
        """WorkflowBridge lists only workflow domain candidates."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = WorkflowBridge(resolver, lifecycle, settings)

        resolver.register(
            Candidate(
                domain="workflow",
                key="onboarding",
                provider="temporal",
                factory=lambda: None,
                source=CandidateSource.MANUAL,
            )
        )
        resolver.register(
            Candidate(
                domain="event",
                key="user-signup",
                provider="rabbitmq",
                factory=lambda: None,
                source=CandidateSource.MANUAL,
            )
        )

        active = bridge.active_candidates()

        assert len(active) == 1
        assert active[0].domain == "workflow"

    def test_workflow_bridge_activity_management(self):
        """WorkflowBridge manages activity state for workflows."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        bridge = WorkflowBridge(resolver, lifecycle, settings)

        state = bridge.set_draining(
            "onboarding", True, note="draining workflow instances"
        )

        assert state.draining is True


class TestCrossDomainIntegration:
    """Test multiple domain bridges working together."""

    @pytest.mark.asyncio
    async def test_multiple_domains_coexist(self):
        """Multiple domain bridges share resolver and lifecycle."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()

        service_bridge = ServiceBridge(resolver, lifecycle, settings)
        task_bridge = TaskBridge(resolver, lifecycle, settings)
        event_bridge = EventBridge(resolver, lifecycle, settings)
        workflow_bridge = WorkflowBridge(
            resolver, lifecycle, settings, task_bridge=task_bridge
        )

        # Register components in each domain
        resolver.register(
            Candidate(
                domain="service",
                key="api",
                provider="fastapi",
                factory=lambda: MockComponent("api"),
                source=CandidateSource.MANUAL,
            )
        )
        resolver.register(
            Candidate(
                domain="task",
                key="email",
                provider="celery",
                factory=lambda: MockComponent("email"),
                source=CandidateSource.MANUAL,
            )
        )
        resolver.register(
            Candidate(
                domain="event",
                key="signup",
                provider="rabbitmq",
                factory=lambda: MockComponent("signup"),
                source=CandidateSource.MANUAL,
            )
        )
        resolver.register(
            Candidate(
                domain="workflow",
                key="onboarding",
                provider="temporal",
                factory=lambda: MockComponent("onboarding"),
                source=CandidateSource.MANUAL,
            )
        )

        # Use components from each domain
        await service_bridge.use("api")
        await task_bridge.use("email")
        await event_bridge.use("signup")
        await workflow_bridge.use("onboarding")

        # Each bridge only sees its own domain
        assert len(service_bridge.active_candidates()) == 1
        assert len(task_bridge.active_candidates()) == 1
        assert len(event_bridge.active_candidates()) == 1
        assert len(workflow_bridge.active_candidates()) == 1

        # All domains use shared lifecycle
        assert lifecycle.get_instance("service", "api") is not None
        assert lifecycle.get_instance("task", "email") is not None
        assert lifecycle.get_instance("event", "signup") is not None
        assert lifecycle.get_instance("workflow", "onboarding") is not None

    @pytest.mark.asyncio
    async def test_workflow_bridge_executes_dag_with_tasks(self):
        """WorkflowBridge executes DAG definitions using the task bridge."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        task_settings = LayerSettings()
        workflow_settings = LayerSettings()
        task_bridge = TaskBridge(resolver, lifecycle, task_settings)
        workflow_bridge = WorkflowBridge(
            resolver,
            lifecycle,
            workflow_settings,
            task_bridge=task_bridge,
        )
        recorder: list[str] = []

        resolver.register(
            Candidate(
                domain="task",
                key="extract-task",
                provider="worker",
                factory=lambda: DemoTaskRunner("extract", recorder),
                source=CandidateSource.MANUAL,
            )
        )
        resolver.register(
            Candidate(
                domain="task",
                key="notify-task",
                provider="worker",
                factory=lambda: DemoTaskRunner("notify", recorder),
                source=CandidateSource.MANUAL,
            )
        )
        resolver.register(
            Candidate(
                domain="workflow",
                key="demo-workflow",
                provider="dag",
                factory=lambda: MockComponent("wf"),
                metadata={
                    "dag": {
                        "nodes": [
                            {"id": "extract", "task": "extract-task"},
                            {
                                "id": "notify",
                                "task": "notify-task",
                                "depends_on": ["extract"],
                                "payload": {"channel": "ops"},
                            },
                        ]
                    }
                },
                source=CandidateSource.MANUAL,
            )
        )

        workflow_bridge.refresh_dags()

        run_result = await workflow_bridge.execute_dag(
            "demo-workflow", context={"tenant": "default"}
        )
        results = run_result["results"]

        assert recorder == [
            "extract:{'tenant': 'default'}",
            "notify:{'channel': 'ops'}",
        ]
        assert results["extract"] == "EXTRACT"
        assert results["notify"] == "NOTIFY"

    @pytest.mark.asyncio
    async def test_workflow_bridge_retry_policy(self):
        """WorkflowBridge honors DAG node retry metadata."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        task_settings = LayerSettings()
        workflow_settings = LayerSettings()
        recorder: list[str] = []
        task_bridge = TaskBridge(resolver, lifecycle, task_settings)
        workflow_bridge = WorkflowBridge(
            resolver,
            lifecycle,
            workflow_settings,
            task_bridge=task_bridge,
        )

        resolver.register(
            Candidate(
                domain="task",
                key="flaky-task",
                provider="worker",
                factory=lambda: FlakyTaskRunner("flaky", recorder),
                source=CandidateSource.MANUAL,
            )
        )
        resolver.register(
            Candidate(
                domain="workflow",
                key="retry-workflow",
                provider="dag",
                factory=lambda: MockComponent("wf"),
                metadata={
                    "dag": {
                        "nodes": [
                            {
                                "id": "flaky",
                                "task": "flaky-task",
                                "retry_policy": {
                                    "attempts": 3,
                                    "base_delay": 0.01,
                                    "max_delay": 0.02,
                                    "jitter": 0.0,
                                },
                            }
                        ]
                    }
                },
                source=CandidateSource.MANUAL,
            )
        )

        workflow_bridge.refresh_dags()

        run_result = await workflow_bridge.execute_dag("retry-workflow")
        results = run_result["results"]

        assert results["flaky"] == "FLAKY"
        assert results["flaky__attempts"] == 2
        assert "flaky:1" in recorder and "flaky:2" in recorder

    @pytest.mark.asyncio
    async def test_workflow_bridge_checkpoint_store(self, tmp_path):
        """WorkflowBridge persists checkpoints between DAG executions."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        task_settings = LayerSettings()
        workflow_settings = LayerSettings()
        recorder: list[str] = []
        task_bridge = TaskBridge(resolver, lifecycle, task_settings)
        checkpoint_store = WorkflowCheckpointStore(tmp_path / "checkpoints.sqlite")
        workflow_bridge = WorkflowBridge(
            resolver,
            lifecycle,
            workflow_settings,
            task_bridge=task_bridge,
            checkpoint_store=checkpoint_store,
        )

        stable_runner = DemoTaskRunner("stable", recorder)
        flaky_runner = ControlledTaskRunner("fail", recorder, should_fail=True)

        resolver.register(
            Candidate(
                domain="task",
                key="stable-task",
                provider="worker",
                factory=lambda: stable_runner,
                source=CandidateSource.MANUAL,
            )
        )
        resolver.register(
            Candidate(
                domain="task",
                key="fail-task",
                provider="worker",
                factory=lambda: flaky_runner,
                source=CandidateSource.MANUAL,
            )
        )
        resolver.register(
            Candidate(
                domain="workflow",
                key="checkpoint-workflow",
                provider="dag",
                factory=lambda: MockComponent("wf"),
                metadata={
                    "dag": {
                        "nodes": [
                            {"id": "stable", "task": "stable-task"},
                            {
                                "id": "fail",
                                "task": "fail-task",
                                "depends_on": ["stable"],
                                "retry_policy": {
                                    "attempts": 1,
                                    "base_delay": 0.0,
                                    "max_delay": 0.0,
                                    "jitter": 0.0,
                                },
                            },
                        ]
                    }
                },
                source=CandidateSource.MANUAL,
            )
        )

        workflow_bridge.refresh_dags()

        with pytest.raises(Exception):
            await workflow_bridge.execute_dag("checkpoint-workflow")

        checkpoint = checkpoint_store.load("checkpoint-workflow")
        assert "stable" in checkpoint

        # Allow failing runner to succeed and rerun
        flaky_runner.should_fail = False
        recorder.clear()
        run_result = await workflow_bridge.execute_dag("checkpoint-workflow")
        results = run_result["results"]

        assert results["fail"] == "FAIL"
        # Stable task should not rerun
        assert recorder == ["fail:None"]
        assert checkpoint_store.load("checkpoint-workflow") == {}

    @pytest.mark.asyncio
    async def test_enqueue_workflow_uses_metadata_scheduler(self):
        """metadata.scheduler sets queue category/provider defaults."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        queue_bridge = FakeQueueBridge()
        workflow_bridge = WorkflowBridge(
            resolver,
            lifecycle,
            settings,
            queue_bridge=queue_bridge,
            queue_category=None,
        )
        resolver.register(
            Candidate(
                domain="workflow",
                key="metadata-workflow",
                provider="demo",
                factory=lambda: MockComponent("wf"),
                metadata={
                    "scheduler": {
                        "queue_category": "queue.scheduler",
                        "provider": "cloudtasks",
                    }
                },
                source=CandidateSource.MANUAL,
            )
        )

        result = await workflow_bridge.enqueue_workflow(
            "metadata-workflow",
            context={"tenant": "demo"},
        )

        assert result["queue_category"] == "queue.scheduler"
        assert result["queue_provider"] == "cloudtasks"
        assert queue_bridge.calls == [("queue.scheduler", "cloudtasks")]
        assert queue_bridge.adapter.payloads[0]["context"] == {"tenant": "demo"}

    @pytest.mark.asyncio
    async def test_enqueue_workflow_allows_overrides(self):
        """Explicit CLI overrides supersede scheduler metadata."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        queue_bridge = FakeQueueBridge()
        workflow_bridge = WorkflowBridge(
            resolver,
            lifecycle,
            settings,
            queue_bridge=queue_bridge,
            queue_category=None,
        )
        resolver.register(
            Candidate(
                domain="workflow",
                key="override-workflow",
                provider="demo",
                factory=lambda: MockComponent("wf"),
                metadata={
                    "scheduler": {
                        "queue_category": "queue.scheduler",
                        "provider": "cloudtasks",
                    }
                },
                source=CandidateSource.MANUAL,
            )
        )

        result = await workflow_bridge.enqueue_workflow(
            "override-workflow",
            queue_category="queue.events",
            provider="pubsub",
        )

        assert result["queue_category"] == "queue.events"
        assert result["queue_provider"] == "pubsub"
        assert queue_bridge.calls == [("queue.events", "pubsub")]

    @pytest.mark.asyncio
    async def test_enqueue_workflow_uses_settings_queue_category(self):
        """LayerSettings.options controls fallback queue category."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings(options={"queue_category": "queue.scheduler"})
        queue_bridge = FakeQueueBridge()
        workflow_bridge = WorkflowBridge(
            resolver,
            lifecycle,
            settings,
            queue_bridge=queue_bridge,
            queue_category=None,
        )
        resolver.register(
            Candidate(
                domain="workflow",
                key="settings-workflow",
                provider="demo",
                factory=lambda: MockComponent("wf"),
                metadata={},
                source=CandidateSource.MANUAL,
            )
        )

        result = await workflow_bridge.enqueue_workflow("settings-workflow")

        assert result["queue_category"] == "queue.scheduler"
        assert queue_bridge.calls == [("queue.scheduler", "default-provider")]

    def test_shared_activity_store(self, tmp_path):
        """Multiple domain bridges share activity store."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        store_path = tmp_path / "activity.sqlite"
        activity_store = DomainActivityStore(store_path)

        service_bridge = ServiceBridge(
            resolver, lifecycle, settings, activity_store=activity_store
        )
        task_bridge = TaskBridge(
            resolver, lifecycle, settings, activity_store=activity_store
        )

        # Set activity in different domains
        service_bridge.set_paused("api", True, note="service maintenance")
        task_bridge.set_draining("email", True, note="task draining")

        # Both domains persist to same store
        snapshot = activity_store.snapshot()
        assert "service" in snapshot
        assert "task" in snapshot
        assert snapshot["service"]["api"].paused is True
        assert snapshot["task"]["email"].draining is True
