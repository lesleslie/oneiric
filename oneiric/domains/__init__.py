"""Resolver-backed bridges for services, tasks, events, and workflows."""

from .base import DomainBridge, DomainHandle
from .events import EventBridge
from .services import ServiceBridge
from .tasks import TaskBridge
from .watchers import (
    EventConfigWatcher,
    ServiceConfigWatcher,
    TaskConfigWatcher,
    WorkflowConfigWatcher,
)
from .workflows import WorkflowBridge

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
