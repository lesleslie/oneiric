"""Register builtin action kits."""

from __future__ import annotations

from pathlib import Path

from oneiric.core.resolution import Resolver

from .automation import AutomationTriggerAction
from .compression import CompressionAction, HashAction
from .data import DataSanitizeAction, DataTransformAction, ValidationSchemaAction
from .debug import DebugConsoleAction
from .event import EventDispatchAction
from .http import HttpFetchAction
from .metadata import ActionMetadata, register_action_metadata
from .security import SecuritySecureAction, SecuritySignatureAction
from .serialization import SerializationAction
from .task import TaskScheduleAction
from .workflow import (
    WorkflowAuditAction,
    WorkflowNotifyAction,
    WorkflowOrchestratorAction,
    WorkflowRetryAction,
)


def builtin_action_metadata() -> list[ActionMetadata]:
    """Return metadata for builtin action kits."""

    return [
        CompressionAction.metadata,
        HashAction.metadata,
        WorkflowAuditAction.metadata,
        WorkflowOrchestratorAction.metadata,
        WorkflowNotifyAction.metadata,
        WorkflowRetryAction.metadata,
        HttpFetchAction.metadata,
        SecuritySignatureAction.metadata,
        SecuritySecureAction.metadata,
        SerializationAction.metadata,
        DataTransformAction.metadata,
        DataSanitizeAction.metadata,
        ValidationSchemaAction.metadata,
        TaskScheduleAction.metadata,
        EventDispatchAction.metadata,
        AutomationTriggerAction.metadata,
        DebugConsoleAction.metadata,
    ]


def register_builtin_actions(resolver: Resolver) -> None:
    """Register builtin action metadata with the resolver."""

    register_action_metadata(
        resolver,
        package_name="oneiric.actions",
        package_path=str(Path(__file__).parent),
        actions=builtin_action_metadata(),
    )
