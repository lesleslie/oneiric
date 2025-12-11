"""Config watchers for domain bridges."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from oneiric.core.config import OneiricSettings, load_settings
from oneiric.runtime.watchers import SelectionWatcher

from .base import DomainBridge


def _layer_selector(name: str) -> Callable[[OneiricSettings], Any]:
    def selector(settings: OneiricSettings):
        return getattr(settings, f"{name}s")

    return selector


class ServiceConfigWatcher(SelectionWatcher):
    def __init__(
        self,
        bridge: DomainBridge,
        *,
        settings_loader=load_settings,
        poll_interval: float = 5.0,
    ) -> None:
        super().__init__(
            "service",
            bridge,
            layer_selector=_layer_selector("service"),
            settings_loader=settings_loader,
            poll_interval=poll_interval,
        )


class TaskConfigWatcher(SelectionWatcher):
    def __init__(
        self,
        bridge: DomainBridge,
        *,
        settings_loader=load_settings,
        poll_interval: float = 5.0,
    ) -> None:
        super().__init__(
            "task",
            bridge,
            layer_selector=_layer_selector("task"),
            settings_loader=settings_loader,
            poll_interval=poll_interval,
        )


class EventConfigWatcher(SelectionWatcher):
    def __init__(
        self,
        bridge: DomainBridge,
        *,
        settings_loader=load_settings,
        poll_interval: float = 5.0,
    ) -> None:
        super().__init__(
            "event",
            bridge,
            layer_selector=_layer_selector("event"),
            settings_loader=settings_loader,
            poll_interval=poll_interval,
            refresh_on_every_tick=True,
        )


class WorkflowConfigWatcher(SelectionWatcher):
    def __init__(
        self,
        bridge: DomainBridge,
        *,
        settings_loader=load_settings,
        poll_interval: float = 5.0,
    ) -> None:
        super().__init__(
            "workflow",
            bridge,
            layer_selector=_layer_selector("workflow"),
            settings_loader=settings_loader,
            poll_interval=poll_interval,
            refresh_on_every_tick=True,
        )
