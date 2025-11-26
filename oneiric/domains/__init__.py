"""Resolver-backed bridges for services, tasks, events, and workflows."""

from .base import DomainBridge, DomainHandle
from .services import ServiceBridge
from .tasks import TaskBridge
from .events import EventBridge
from .workflows import WorkflowBridge
from .watchers import (
    ServiceConfigWatcher,
    TaskConfigWatcher,
    EventConfigWatcher,
    WorkflowConfigWatcher,
)

__all__ = [
    "DomainBridge",
    "DomainHandle",
    "ServiceBridge",
    "TaskBridge",
    "EventBridge",
    "WorkflowBridge",
    "ServiceConfigWatcher",
    "TaskConfigWatcher",
    "EventConfigWatcher",
    "WorkflowConfigWatcher",
]
