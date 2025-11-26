"""Tests for specialized domain bridges (Service, Task, Event, Workflow)."""

from __future__ import annotations

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


# Test helpers


class MockComponent:
    """Mock component for testing."""

    def __init__(self, name: str):
        self.name = name


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

        state = bridge.set_draining("onboarding", True, note="draining workflow instances")

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
        workflow_bridge = WorkflowBridge(resolver, lifecycle, settings)

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
        service_handle = await service_bridge.use("api")
        task_handle = await task_bridge.use("email")
        event_handle = await event_bridge.use("signup")
        workflow_handle = await workflow_bridge.use("onboarding")

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

    def test_shared_activity_store(self, tmp_path):
        """Multiple domain bridges share activity store."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        settings = LayerSettings()
        store_path = tmp_path / "activity.json"
        activity_store = DomainActivityStore(store_path)

        service_bridge = ServiceBridge(resolver, lifecycle, settings, activity_store=activity_store)
        task_bridge = TaskBridge(resolver, lifecycle, settings, activity_store=activity_store)

        # Set activity in different domains
        service_bridge.set_paused("api", True, note="service maintenance")
        task_bridge.set_draining("email", True, note="task draining")

        # Both domains persist to same store
        snapshot = activity_store.snapshot()
        assert "service" in snapshot
        assert "task" in snapshot
        assert snapshot["service"]["api"].paused is True
        assert snapshot["task"]["email"].draining is True
