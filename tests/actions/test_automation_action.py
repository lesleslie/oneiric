from __future__ import annotations

import pytest

from oneiric.actions.automation import AutomationTriggerAction
from oneiric.core.lifecycle import LifecycleError


@pytest.mark.asyncio
async def test_automation_trigger_matches_rules() -> None:
    action = AutomationTriggerAction()
    result = await action.execute(
        {
            "context": {
                "payload": {"status": "success", "attempts": 2},
                "env": "prod",
            },
            "rules": [
                {
                    "name": "notify-success",
                    "action": "workflow.notify",
                    "conditions": [
                        {
                            "field": "payload.status",
                            "operator": "equals",
                            "value": "success",
                        },
                        {"field": "env", "operator": "equals", "value": "prod"},
                    ],
                },
                {
                    "name": "retry",
                    "action": "workflow.retry",
                    "conditions": [
                        {
                            "field": "payload.attempts",
                            "operator": "greater_than",
                            "value": 3,
                        },
                    ],
                },
            ],
        }
    )

    assert result["status"] == "triggered"
    assert len(result["matched_rules"]) == 1
    assert result["matched_rules"][0]["action"] == "workflow.notify"


@pytest.mark.asyncio
async def test_automation_trigger_stop_on_first_match() -> None:
    action = AutomationTriggerAction()
    result = await action.execute(
        {
            "context": {"payload": {"status": "failed", "attempts": 4}},
            "stop_on_first_match": True,
            "rules": [
                {
                    "name": "retry",
                    "action": "workflow.retry",
                    "conditions": [
                        {
                            "field": "payload.status",
                            "operator": "equals",
                            "value": "failed",
                        },
                    ],
                },
                {
                    "name": "fallback-notify",
                    "action": "workflow.notify",
                    "conditions": [
                        {
                            "field": "payload.status",
                            "operator": "equals",
                            "value": "failed",
                        },
                    ],
                },
            ],
        }
    )

    assert len(result["matched_rules"]) == 1
    assert result["matched_rules"][0]["name"] == "retry"
    assert result["evaluated_rules"] == 1


@pytest.mark.asyncio
async def test_automation_trigger_requires_mapping_context() -> None:
    action = AutomationTriggerAction()
    with pytest.raises(LifecycleError):
        await action.execute(
            {
                "context": "invalid",
                "rules": [{"name": "noop", "action": "workflow.notify"}],
            }
        )
