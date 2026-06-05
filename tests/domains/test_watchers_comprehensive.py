"""Comprehensive tests for oneiric.domains.watchers.

Covers the four ConfigWatcher subclasses (Service/Task/Event/Workflow) and the
private ``_layer_selector`` helper. Each subclass fixes ``domain``,
``layer_selector``, and (for event/workflow) ``refresh_on_every_tick`` on top
of the real ``SelectionWatcher`` parent — we deliberately do not mock that
parent and exercise the actual ``_tick`` behavior with a ``_FakeBridge``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from oneiric.core.config import OneiricSettings
from oneiric.domains.watchers import (
    EventConfigWatcher,
    ServiceConfigWatcher,
    TaskConfigWatcher,
    WorkflowConfigWatcher,
    _layer_selector,
)
from oneiric.runtime.watchers import SelectionWatcher

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeBridge:
    """Records ``update_settings`` calls and exposes refresh hooks.

    The real ``EventBridge.refresh_dispatcher`` / ``WorkflowBridge.refresh_dags``
    are not invoked by the watcher itself — they are called by the orchestrator
    after ``update_settings`` lands. The fake wires that cascade so the
    integration test can verify the watcher hands control off cleanly.
    """

    def __init__(self, domain: str) -> None:
        self.domain = domain
        self.update_calls: list[Any] = []
        self.refresh_calls: list[str] = []

    def update_settings(self, settings: Any) -> None:
        self.update_calls.append(settings)
        if self.domain == "event":
            self.refresh_dispatcher()
        elif self.domain == "workflow":
            self.refresh_dags()

    def refresh_dispatcher(self) -> None:
        self.refresh_calls.append("dispatcher")

    def refresh_dags(self) -> None:
        self.refresh_calls.append("dags")


def _settings_loader() -> Callable[[], OneiricSettings]:
    """Return a fresh ``OneiricSettings`` for every loader invocation."""

    def _load() -> OneiricSettings:
        return OneiricSettings()

    return _load


# ---------------------------------------------------------------------------
# ServiceConfigWatcher
# ---------------------------------------------------------------------------


class TestServiceConfigWatcher:
    def test_domain_attribute(self) -> None:
        bridge = _FakeBridge("service")
        watcher = ServiceConfigWatcher(bridge, settings_loader=_settings_loader())
        assert watcher.name == "service"

    def test_inherits_from_selection_watcher(self) -> None:
        bridge = _FakeBridge("service")
        watcher = ServiceConfigWatcher(bridge, settings_loader=_settings_loader())
        assert isinstance(watcher, SelectionWatcher)
        assert SelectionWatcher in watcher.__class__.__mro__

    def test_layer_selector_returns_services(self) -> None:
        bridge = _FakeBridge("service")
        watcher = ServiceConfigWatcher(bridge, settings_loader=_settings_loader())
        settings = OneiricSettings()
        assert watcher.layer_selector(settings) is settings.services

    def test_poll_interval_propagated(self) -> None:
        bridge = _FakeBridge("service")
        watcher = ServiceConfigWatcher(
            bridge, settings_loader=_settings_loader(), poll_interval=12.5
        )
        assert watcher.poll_interval == 12.5

    def test_refresh_on_every_tick_defaults_false(self) -> None:
        bridge = _FakeBridge("service")
        watcher = ServiceConfigWatcher(bridge, settings_loader=_settings_loader())
        assert watcher._refresh_on_every_tick is False


# ---------------------------------------------------------------------------
# TaskConfigWatcher
# ---------------------------------------------------------------------------


class TestTaskConfigWatcher:
    def test_domain_attribute(self) -> None:
        bridge = _FakeBridge("task")
        watcher = TaskConfigWatcher(bridge, settings_loader=_settings_loader())
        assert watcher.name == "task"

    def test_inherits_from_selection_watcher(self) -> None:
        bridge = _FakeBridge("task")
        watcher = TaskConfigWatcher(bridge, settings_loader=_settings_loader())
        assert isinstance(watcher, SelectionWatcher)
        assert SelectionWatcher in watcher.__class__.__mro__

    def test_layer_selector_returns_tasks(self) -> None:
        bridge = _FakeBridge("task")
        watcher = TaskConfigWatcher(bridge, settings_loader=_settings_loader())
        settings = OneiricSettings()
        assert watcher.layer_selector(settings) is settings.tasks

    def test_poll_interval_propagated(self) -> None:
        bridge = _FakeBridge("task")
        watcher = TaskConfigWatcher(
            bridge, settings_loader=_settings_loader(), poll_interval=2.0
        )
        assert watcher.poll_interval == 2.0

    def test_refresh_on_every_tick_defaults_false(self) -> None:
        bridge = _FakeBridge("task")
        watcher = TaskConfigWatcher(bridge, settings_loader=_settings_loader())
        assert watcher._refresh_on_every_tick is False


# ---------------------------------------------------------------------------
# EventConfigWatcher
# ---------------------------------------------------------------------------


class TestEventConfigWatcher:
    def test_domain_attribute(self) -> None:
        bridge = _FakeBridge("event")
        watcher = EventConfigWatcher(bridge, settings_loader=_settings_loader())
        assert watcher.name == "event"

    def test_inherits_from_selection_watcher(self) -> None:
        bridge = _FakeBridge("event")
        watcher = EventConfigWatcher(bridge, settings_loader=_settings_loader())
        assert isinstance(watcher, SelectionWatcher)
        assert SelectionWatcher in watcher.__class__.__mro__

    def test_layer_selector_returns_events(self) -> None:
        bridge = _FakeBridge("event")
        watcher = EventConfigWatcher(bridge, settings_loader=_settings_loader())
        settings = OneiricSettings()
        assert watcher.layer_selector(settings) is settings.events

    def test_poll_interval_propagated(self) -> None:
        bridge = _FakeBridge("event")
        watcher = EventConfigWatcher(
            bridge, settings_loader=_settings_loader(), poll_interval=0.5
        )
        assert watcher.poll_interval == 0.5

    def test_refresh_on_every_tick_enabled(self) -> None:
        bridge = _FakeBridge("event")
        watcher = EventConfigWatcher(bridge, settings_loader=_settings_loader())
        assert watcher._refresh_on_every_tick is True


# ---------------------------------------------------------------------------
# WorkflowConfigWatcher
# ---------------------------------------------------------------------------


class TestWorkflowConfigWatcher:
    def test_domain_attribute(self) -> None:
        bridge = _FakeBridge("workflow")
        watcher = WorkflowConfigWatcher(bridge, settings_loader=_settings_loader())
        assert watcher.name == "workflow"

    def test_inherits_from_selection_watcher(self) -> None:
        bridge = _FakeBridge("workflow")
        watcher = WorkflowConfigWatcher(bridge, settings_loader=_settings_loader())
        assert isinstance(watcher, SelectionWatcher)
        assert SelectionWatcher in watcher.__class__.__mro__

    def test_layer_selector_returns_workflows(self) -> None:
        bridge = _FakeBridge("workflow")
        watcher = WorkflowConfigWatcher(bridge, settings_loader=_settings_loader())
        settings = OneiricSettings()
        assert watcher.layer_selector(settings) is settings.workflows

    def test_poll_interval_propagated(self) -> None:
        bridge = _FakeBridge("workflow")
        watcher = WorkflowConfigWatcher(
            bridge, settings_loader=_settings_loader(), poll_interval=7.5
        )
        assert watcher.poll_interval == 7.5

    def test_refresh_on_every_tick_enabled(self) -> None:
        bridge = _FakeBridge("workflow")
        watcher = WorkflowConfigWatcher(bridge, settings_loader=_settings_loader())
        assert watcher._refresh_on_every_tick is True


# ---------------------------------------------------------------------------
# _layer_selector helper
# ---------------------------------------------------------------------------


class TestLayerSelector:
    def test_service(self) -> None:
        selector = _layer_selector("service")
        settings = OneiricSettings()
        assert selector(settings) is settings.services

    def test_task(self) -> None:
        selector = _layer_selector("task")
        settings = OneiricSettings()
        assert selector(settings) is settings.tasks

    def test_event(self) -> None:
        selector = _layer_selector("event")
        settings = OneiricSettings()
        assert selector(settings) is settings.events

    def test_workflow(self) -> None:
        selector = _layer_selector("workflow")
        settings = OneiricSettings()
        assert selector(settings) is settings.workflows

    def test_returns_callable(self) -> None:
        selector = _layer_selector("service")
        assert callable(selector)


# ---------------------------------------------------------------------------
# Integration: real watcher + FakeBridge
# ---------------------------------------------------------------------------


class TestWatcherIntegration:
    async def test_event_watcher_invokes_update_and_refresh(self) -> None:
        bridge = _FakeBridge("event")
        watcher = EventConfigWatcher(
            bridge, settings_loader=_settings_loader(), poll_interval=1.0
        )
        await watcher.run_once()
        assert len(bridge.update_calls) == 1
        # Compare structural equivalence, not identity — each tick builds a
        # fresh OneiricSettings via the loader, so the layer is a new object.
        captured = bridge.update_calls[0]
        expected = OneiricSettings().events
        assert captured == expected
        assert bridge.refresh_calls == ["dispatcher"]

    async def test_workflow_watcher_invokes_update_and_refresh(self) -> None:
        bridge = _FakeBridge("workflow")
        watcher = WorkflowConfigWatcher(
            bridge, settings_loader=_settings_loader(), poll_interval=1.0
        )
        await watcher.run_once()
        assert len(bridge.update_calls) == 1
        captured = bridge.update_calls[0]
        expected = OneiricSettings().workflows
        assert captured == expected
        assert bridge.refresh_calls == ["dags"]

    async def test_service_watcher_no_change_does_not_invoke_update(self) -> None:
        bridge = _FakeBridge("service")
        watcher = ServiceConfigWatcher(
            bridge, settings_loader=_settings_loader(), poll_interval=1.0
        )
        # No change to selections → _tick returns early without update_settings
        await watcher.run_once()
        assert bridge.update_calls == []
        assert bridge.refresh_calls == []

    async def test_service_watcher_change_invokes_update(self) -> None:
        bridge = _FakeBridge("service")
        # Loader returns a shared OneiricSettings instance so we can mutate it
        # between the constructor's pre-load and the tick call.
        shared = OneiricSettings()
        loader_calls = {"n": 0}

        def _loader() -> OneiricSettings:
            loader_calls["n"] += 1
            # After the constructor's first read, inject a new selection so
            # the next tick sees an added/changed key.
            if loader_calls["n"] > 1:
                shared.services.selections["cache"] = "redis"
            return shared

        watcher = ServiceConfigWatcher(bridge, settings_loader=_loader)
        await watcher.run_once()
        assert len(bridge.update_calls) == 1
        assert bridge.update_calls[0] is shared.services
        # Service watcher does not trigger the event/workflow refresh path
        assert bridge.refresh_calls == []

    async def test_event_watcher_consecutive_ticks_refresh_each_time(self) -> None:
        bridge = _FakeBridge("event")
        watcher = EventConfigWatcher(
            bridge, settings_loader=_settings_loader(), poll_interval=1.0
        )
        await watcher.run_once()
        await watcher.run_once()
        assert len(bridge.update_calls) == 2
        assert bridge.refresh_calls == ["dispatcher", "dispatcher"]

    async def test_workflow_watcher_consecutive_ticks_refresh_each_time(self) -> None:
        bridge = _FakeBridge("workflow")
        watcher = WorkflowConfigWatcher(
            bridge, settings_loader=_settings_loader(), poll_interval=1.0
        )
        await watcher.run_once()
        await watcher.run_once()
        assert len(bridge.update_calls) == 2
        assert bridge.refresh_calls == ["dags", "dags"]

    async def test_event_watcher_settings_loader_invoked_each_tick(self) -> None:
        bridge = _FakeBridge("event")
        loader_calls = {"n": 0}

        def _loader() -> OneiricSettings:
            loader_calls["n"] += 1
            return OneiricSettings()

        watcher = EventConfigWatcher(bridge, settings_loader=_loader, poll_interval=1.0)
        # Constructor calls the loader once for initial state, plus each tick.
        await watcher.run_once()
        assert loader_calls["n"] == 2
