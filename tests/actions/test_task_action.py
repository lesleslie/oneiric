from __future__ import annotations

import pytest
from freezegun import freeze_time

from oneiric.actions.bootstrap import register_builtin_actions
from oneiric.actions.bridge import ActionBridge
from oneiric.actions.task import TaskScheduleAction, TaskScheduleSettings
from oneiric.core.config import LayerSettings
from oneiric.core.lifecycle import LifecycleError, LifecycleManager
from oneiric.core.resolution import Resolver


@pytest.mark.asyncio
async def test_task_schedule_interval_preview() -> None:
    with freeze_time("2024-01-01T00:00:00Z"):
        action = TaskScheduleAction(TaskScheduleSettings(max_preview_runs=3))
        result = await action.execute(
            {
                "task_type": "reports.refresh",
                "interval_seconds": 60,
                "preview_runs": 3,
                "payload": {"region": "us"},
            }
        )

    assert result["status"] == "scheduled"
    assert result["rule"]["queue"] == "default"
    assert len(result["upcoming_runs"]) == 3
    assert result["upcoming_runs"][0].startswith("2024-01-01T00:01:00")
    assert result["rule"]["tags"]["scheduled"] == "true"


@pytest.mark.asyncio
async def test_task_schedule_cron_window() -> None:
    with freeze_time("2024-01-01T08:15:00Z"):
        action = TaskScheduleAction()
        result = await action.execute(
            {
                "task_type": "deploy.notify",
                "cron_expression": "*/30 9-10 * * 1-5",
                "preview_runs": 2,
            }
        )

    assert result["next_run"].startswith("2024-01-01T09:00:00")
    assert result["upcoming_runs"][1].startswith("2024-01-01T09:30:00")


@pytest.mark.asyncio
async def test_task_schedule_via_bridge(tmp_path) -> None:
    resolver = Resolver()
    register_builtin_actions(resolver)
    lifecycle = LifecycleManager(resolver, status_snapshot_path=str(tmp_path / "status.json"))
    settings = LayerSettings(selections={"task.schedule": "builtin-task-schedule"})
    bridge = ActionBridge(resolver, lifecycle, settings)
    with freeze_time("2024-02-01T10:00:00Z"):
        handle = await bridge.use("task.schedule")
        result = await handle.instance.execute(
            {
                "task_type": "cleanup.jobs",
                "interval_seconds": 300,
                "queue": "maintenance",
                "preview_runs": 1,
            }
        )

    assert result["rule"]["queue"] == "maintenance"
    assert result["next_run"].startswith("2024-02-01T10:05:00")


@pytest.mark.asyncio
async def test_task_schedule_requires_cron_or_interval() -> None:
    action = TaskScheduleAction()
    with pytest.raises(LifecycleError):
        await action.execute({"task_type": "demo"})
