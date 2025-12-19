from __future__ import annotations

import pytest

from oneiric.actions.bootstrap import register_builtin_actions
from oneiric.actions.bridge import ActionBridge
from oneiric.actions.workflow import (
    WorkflowAuditAction,
    WorkflowNotifyAction,
    WorkflowOrchestratorAction,
    WorkflowOrchestratorSettings,
    WorkflowRetryAction,
)
from oneiric.core.config import LayerSettings
from oneiric.core.lifecycle import LifecycleError, LifecycleManager
from oneiric.core.resolution import Resolver


@pytest.mark.asyncio
async def test_workflow_audit_action_redacts_fields() -> None:
    action = WorkflowAuditAction()
    result = await action.execute(
        {
            "event": "deploy",
            "details": {
                "service": "oneiric",
                "secret": "super",
                "nested": {"token": "hidden", "ok": True},
            },
        }
    )

    assert result["status"] == "recorded"
    assert result["details"]["secret"] == "***"
    assert result["details"]["nested"]["token"] == "***"
    assert result["details"]["nested"]["ok"] is True
    assert "timestamp" in result


@pytest.mark.asyncio
async def test_action_bridge_activates_workflow_audit(tmp_path) -> None:
    resolver = Resolver()
    register_builtin_actions(resolver)
    lifecycle = LifecycleManager(
        resolver, status_snapshot_path=str(tmp_path / "status.json")
    )
    settings = LayerSettings(
        selections={"workflow.audit": "builtin-workflow-audit"},
    )
    bridge = ActionBridge(resolver, lifecycle, settings)
    handle = await bridge.use("workflow.audit")
    response = await handle.instance.execute(
        {
            "event": "deploy",
            "details": {"service": "oneiric"},
            "channel": "deploys",
        }
    )

    assert response["channel"] == "deploys"
    assert response["status"] == "recorded"


@pytest.mark.asyncio
async def test_workflow_notify_defaults() -> None:
    action = WorkflowNotifyAction()
    result = await action.execute({"message": "deploy start"})

    assert result["status"] == "logged"
    assert result["level"] == "info"
    assert result["channel"] == "workflow"
    assert result["recipients"] == []


@pytest.mark.asyncio
async def test_workflow_notify_accepts_custom_recipients(tmp_path) -> None:
    resolver = Resolver()
    register_builtin_actions(resolver)
    lifecycle = LifecycleManager(
        resolver, status_snapshot_path=str(tmp_path / "status.json")
    )
    settings = LayerSettings(selections={"workflow.notify": "builtin-workflow-notify"})
    bridge = ActionBridge(resolver, lifecycle, settings)
    handle = await bridge.use("workflow.notify")
    result = await handle.instance.execute(
        {
            "message": "deployment completed",
            "channel": "deploys",
            "level": "WARNING",
            "recipients": ["ops@example.com", "pager"],
            "context": {"service": "oneiric"},
        }
    )

    assert result["status"] == "queued"
    assert result["level"] == "warning"
    assert result["channel"] == "deploys"
    assert result["recipients"] == ["ops@example.com", "pager"]
    assert result["context"] == {"service": "oneiric"}


@pytest.mark.asyncio
async def test_workflow_retry_schedules() -> None:
    action = WorkflowRetryAction()
    result = await action.execute({"attempt": 1})

    assert result["status"] == "scheduled"
    assert result["next_attempt"] == 2
    assert result["delay_seconds"] > 0


@pytest.mark.asyncio
async def test_workflow_retry_exhausts(tmp_path) -> None:
    resolver = Resolver()
    register_builtin_actions(resolver)
    lifecycle = LifecycleManager(
        resolver, status_snapshot_path=str(tmp_path / "status.json")
    )
    settings = LayerSettings(selections={"workflow.retry": "builtin-workflow-retry"})
    bridge = ActionBridge(resolver, lifecycle, settings)
    handle = await bridge.use("workflow.retry")
    result = await handle.instance.execute({"attempt": 5, "max_attempts": 5})

    assert result["status"] == "exhausted"
    assert result["attempt"] == 5


@pytest.mark.asyncio
async def test_workflow_orchestrator_builds_schedule() -> None:
    action = WorkflowOrchestratorAction(
        WorkflowOrchestratorSettings(max_parallel_steps=2, default_version="2024.01")
    )
    plan = await action.execute(
        {
            "workflow_id": "deploy",
            "steps": [
                {"step_id": "hydrate", "name": "Hydrate", "action": "http.fetch"},
                {
                    "step_id": "notify",
                    "name": "Notify",
                    "action": "workflow.notify",
                    "depends_on": ["hydrate"],
                },
                {
                    "step_id": "audit",
                    "name": "Audit",
                    "action": "workflow.audit",
                    "depends_on": ["hydrate"],
                },
                {
                    "step_id": "cleanup",
                    "name": "Cleanup",
                    "action": "workflow.audit",
                    "depends_on": ["notify", "audit"],
                },
            ],
        }
    )

    assert plan["status"] == "planned"
    assert plan["version"] == "2024.01"
    assert plan["schedule"][0] == ["hydrate"]
    assert set(plan["schedule"][1]) == {"audit", "notify"}
    assert plan["schedule"][2] == ["cleanup"]
    assert plan["graph"]["entry_steps"] == ["hydrate"]
    assert plan["graph"]["terminal_steps"] == ["cleanup"]


@pytest.mark.asyncio
async def test_workflow_orchestrator_via_bridge(tmp_path) -> None:
    resolver = Resolver()
    register_builtin_actions(resolver)
    lifecycle = LifecycleManager(
        resolver, status_snapshot_path=str(tmp_path / "status.json")
    )
    settings = LayerSettings(
        selections={"workflow.orchestrate": "builtin-workflow-orchestrator"}
    )
    bridge = ActionBridge(resolver, lifecycle, settings)
    handle = await bridge.use("workflow.orchestrate")
    plan = await handle.instance.execute(
        {
            "workflow_id": "demo",
            "version": "1.2.3",
            "metadata": {"env": "test"},
            "steps": [
                {
                    "step_id": "prepare",
                    "name": "Prepare",
                    "action": "compression.encode",
                },
                {
                    "step_id": "ship",
                    "name": "Ship",
                    "action": "workflow.notify",
                    "depends_on": ["prepare"],
                },
            ],
        }
    )

    assert plan["workflow_id"] == "demo"
    assert plan["version"] == "1.2.3"
    assert plan["metadata"] == {"env": "test"}
    assert plan["ordered_steps"] == ["prepare", "ship"]


@pytest.mark.asyncio
async def test_workflow_orchestrator_missing_dependency() -> None:
    action = WorkflowOrchestratorAction()
    with pytest.raises(LifecycleError):
        await action.execute(
            {
                "workflow_id": "broken",
                "steps": [
                    {
                        "step_id": "deploy",
                        "name": "Deploy",
                        "action": "workflow.notify",
                        "depends_on": ["missing"],
                    }
                ],
            }
        )


@pytest.mark.asyncio
async def test_workflow_orchestrator_cycle_detection() -> None:
    action = WorkflowOrchestratorAction()
    with pytest.raises(LifecycleError):
        await action.execute(
            {
                "workflow_id": "loop",
                "steps": [
                    {
                        "step_id": "first",
                        "name": "First",
                        "action": "workflow.notify",
                        "depends_on": ["second"],
                    },
                    {
                        "step_id": "second",
                        "name": "Second",
                        "action": "workflow.audit",
                        "depends_on": ["first"],
                    },
                ],
            }
        )


@pytest.mark.asyncio
async def test_workflow_orchestrator_prunes_targets() -> None:
    action = WorkflowOrchestratorAction()
    plan = await action.execute(
        {
            "workflow_id": "targeted",
            "target_steps": ["notify"],
            "steps": [
                {"step_id": "hydrate", "name": "Hydrate", "action": "http.fetch"},
                {
                    "step_id": "notify",
                    "name": "Notify",
                    "action": "workflow.notify",
                    "depends_on": ["hydrate"],
                },
                {
                    "step_id": "audit",
                    "name": "Audit",
                    "action": "workflow.audit",
                    "depends_on": ["hydrate"],
                },
            ],
        }
    )

    assert plan["ordered_steps"] == ["hydrate", "notify"]
    assert plan["graph"]["terminal_steps"] == ["notify"]
