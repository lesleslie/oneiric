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
async def test_workflow_audit_event_required() -> None:
    from oneiric.actions.workflow import WorkflowAuditSettings

    action = WorkflowAuditAction(WorkflowAuditSettings(default_event=""))
    with pytest.raises(LifecycleError, match="workflow-audit-event-required"):
        await action.execute({"details": {}})


@pytest.mark.asyncio
async def test_workflow_audit_details_must_be_dict() -> None:
    action = WorkflowAuditAction()
    with pytest.raises(LifecycleError, match="workflow-audit-details-invalid"):
        await action.execute({"event": "deploy", "details": "string"})


@pytest.mark.asyncio
async def test_workflow_audit_extra_redact_fields_from_payload() -> None:
    action = WorkflowAuditAction()
    result = await action.execute(
        {
            "event": "deploy",
            "details": {"password": "secret", "user": "alice"},
            "redact_fields": ["password"],
        }
    )
    assert result["details"]["password"] == "***"
    assert result["details"]["user"] == "alice"


@pytest.mark.asyncio
async def test_workflow_audit_redacts_list_with_nested_dicts() -> None:
    action = WorkflowAuditAction()
    result = await action.execute(
        {
            "event": "batch",
            "details": {"items": [{"token": "abc", "id": 1}, "plain-string"]},
        }
    )
    assert result["details"]["items"][0]["token"] == "***"
    assert result["details"]["items"][1] == "plain-string"


@pytest.mark.asyncio
async def test_workflow_notify_message_not_string_raises() -> None:
    action = WorkflowNotifyAction()
    with pytest.raises(LifecycleError, match="workflow-notify-message-invalid"):
        await action.execute({"message": 42})


@pytest.mark.asyncio
async def test_workflow_notify_require_message_raises_when_missing() -> None:
    from oneiric.actions.workflow import WorkflowNotifySettings

    action = WorkflowNotifyAction(WorkflowNotifySettings(require_message=True))
    with pytest.raises(LifecycleError, match="workflow-notify-message-required"):
        await action.execute({"channel": "ops"})


@pytest.mark.asyncio
async def test_workflow_notify_channel_invalid_raises() -> None:
    action = WorkflowNotifyAction()
    with pytest.raises(LifecycleError, match="workflow-notify-channel-invalid"):
        await action.execute({"message": "hi", "channel": 99})


@pytest.mark.asyncio
async def test_workflow_notify_context_not_dict_raises() -> None:
    action = WorkflowNotifyAction()
    with pytest.raises(LifecycleError, match="workflow-notify-context-invalid"):
        await action.execute({"message": "hi", "context": "string"})


@pytest.mark.asyncio
async def test_workflow_notify_recipients_as_string() -> None:
    action = WorkflowNotifyAction()
    result = await action.execute({"message": "hi", "recipients": "ops@example.com"})
    assert result["recipients"] == ["ops@example.com"]


@pytest.mark.asyncio
async def test_workflow_notify_recipients_as_empty_list() -> None:
    action = WorkflowNotifyAction()
    result = await action.execute({"message": "hi", "recipients": []})
    assert result["recipients"] == []


@pytest.mark.asyncio
async def test_workflow_notify_recipients_as_iterable() -> None:
    action = WorkflowNotifyAction()
    result = await action.execute(
        {"message": "hi", "recipients": ("a@x.com", "b@x.com")}
    )
    assert result["recipients"] == ["a@x.com", "b@x.com"]


@pytest.mark.asyncio
async def test_workflow_notify_unknown_level_falls_back_to_info() -> None:
    action = WorkflowNotifyAction()
    result = await action.execute({"message": "hi", "level": "verbose"})
    assert result["level"] == "info"


@pytest.mark.asyncio
async def test_workflow_notify_recipients_invalid_type_raises() -> None:
    action = WorkflowNotifyAction()
    with pytest.raises(LifecycleError, match="workflow-notify-recipients-invalid"):
        await action.execute({"message": "hi", "recipients": 42})


@pytest.mark.asyncio
async def test_workflow_orchestrator_empty_steps_raises() -> None:
    action = WorkflowOrchestratorAction()
    with pytest.raises(LifecycleError, match="workflow-orchestrate-steps-required"):
        await action.execute({"workflow_id": "empty", "steps": []})


@pytest.mark.asyncio
async def test_workflow_orchestrator_target_not_in_steps_raises() -> None:
    action = WorkflowOrchestratorAction()
    with pytest.raises(LifecycleError, match="workflow-orchestrate-target-missing"):
        await action.execute(
            {
                "workflow_id": "x",
                "target_steps": ["ghost"],
                "steps": [{"step_id": "real", "name": "Real", "action": "x"}],
            }
        )


@pytest.mark.asyncio
async def test_workflow_orchestrator_duplicate_step_raises() -> None:
    action = WorkflowOrchestratorAction()
    with pytest.raises(LifecycleError, match="workflow-orchestrate-duplicate-step"):
        await action.execute(
            {
                "workflow_id": "dup",
                "steps": [
                    {"step_id": "s1", "name": "S1", "action": "x"},
                    {"step_id": "s1", "name": "S1-again", "action": "x"},
                ],
            }
        )


@pytest.mark.asyncio
async def test_workflow_orchestrator_self_dependency_raises() -> None:
    action = WorkflowOrchestratorAction()
    with pytest.raises(LifecycleError, match="workflow-orchestrate-self-dependency"):
        await action.execute(
            {
                "workflow_id": "self",
                "steps": [
                    {
                        "step_id": "s1",
                        "name": "S1",
                        "action": "x",
                        "depends_on": ["s1"],
                    }
                ],
            }
        )


@pytest.mark.asyncio
async def test_workflow_orchestrator_dedupes_empty_dependencies() -> None:
    action = WorkflowOrchestratorAction()
    plan = await action.execute(
        {
            "workflow_id": "dedup",
            "steps": [
                {
                    "step_id": "s1",
                    "name": "S1",
                    "action": "x",
                    "depends_on": ["", "s2", "s2"],
                },
                {"step_id": "s2", "name": "S2", "action": "x"},
            ],
        }
    )
    assert plan["status"] == "planned"


@pytest.mark.asyncio
async def test_workflow_retry_invalid_attempt_raises() -> None:
    action = WorkflowRetryAction()
    with pytest.raises(LifecycleError, match="workflow-retry-attempt-invalid"):
        await action.execute({"attempt": -1})


@pytest.mark.asyncio
async def test_workflow_retry_invalid_max_attempts_raises() -> None:
    action = WorkflowRetryAction()
    with pytest.raises(LifecycleError, match="workflow-retry-max-attempts-invalid"):
        await action.execute({"attempt": 0, "max_attempts": 0})


@pytest.mark.asyncio
async def test_workflow_retry_negative_base_delay_raises() -> None:
    action = WorkflowRetryAction()
    with pytest.raises(LifecycleError, match="workflow-retry-base-delay-invalid"):
        await action.execute({"attempt": 0, "base_delay_seconds": -1.0})


@pytest.mark.asyncio
async def test_workflow_retry_multiplier_less_than_one_raises() -> None:
    action = WorkflowRetryAction()
    with pytest.raises(LifecycleError, match="workflow-retry-multiplier-invalid"):
        await action.execute({"attempt": 0, "multiplier": 0.5})


@pytest.mark.asyncio
async def test_workflow_retry_negative_max_delay_raises() -> None:
    action = WorkflowRetryAction()
    with pytest.raises(LifecycleError, match="workflow-retry-max-delay-invalid"):
        await action.execute({"attempt": 0, "max_delay_seconds": -5.0})


@pytest.mark.asyncio
async def test_workflow_orchestrator_deduplicates_shared_dependencies() -> None:
    action = WorkflowOrchestratorAction()
    plan = await action.execute(
        {
            "workflow_id": "shared-dep",
            "target_steps": ["b", "c"],
            "steps": [
                {"step_id": "a", "name": "A", "action": "x"},
                {"step_id": "b", "name": "B", "action": "x", "depends_on": ["a"]},
                {"step_id": "c", "name": "C", "action": "x", "depends_on": ["a"]},
            ],
        }
    )
    # "a" is a shared dep — _visit("a") is called twice, second time hits early return
    assert "a" in plan["ordered_steps"]
    assert plan["ordered_steps"].count("a") == 1


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
