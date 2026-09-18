"""WorkflowTaskProcessor behavioral tests (legacy file).

T19 migrated ``WorkflowTaskProcessor`` to ``oneiric.mcp.scheduler`` and
deleted the aiohttp :class:`SchedulerHTTPServer`. This file retains only
the pre-existing ``WorkflowTaskProcessor`` smoke test for backward
compatibility with the original ``tests/runtime/`` import path; the
behavioral-equivalence suite lives in ``tests/mcp/test_scheduler.py``.
"""
from __future__ import annotations

from typing import Any

import pytest

from oneiric.mcp.scheduler import WorkflowTaskProcessor


class FakeWorkflowBridge:
    """Fake bridge recording execute calls."""

    def __init__(self) -> None:
        self.calls: list[
            tuple[
                str,
                dict[str, Any] | None,
                dict[str, Any] | None,
                str | None,
            ]
        ] = []

    async def execute_dag(
        self,
        workflow_key: str,
        *,
        context: dict[str, Any] | None,
        checkpoint: dict[str, Any] | None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append((workflow_key, context, checkpoint, run_id))
        return {
            "run_id": run_id or "generated-run-id",
            "results": {
                "workflow": workflow_key,
                "context": context or {},
                "checkpoint": checkpoint or {},
            },
        }


@pytest.mark.asyncio
async def test_workflow_task_processor_executes_workflow():
    bridge = FakeWorkflowBridge()
    processor = WorkflowTaskProcessor(bridge)  # type: ignore[arg-type]
    payload = {
        "workflow": "demo",
        "run_id": "abc123",
        "context": {"tenant": "demo"},
        "checkpoint": {"step": "extract"},
    }

    result = await processor.process(payload)

    assert result["workflow"] == "demo"
    assert result["run_id"] == "abc123"
    assert bridge.calls == [
        ("demo", {"tenant": "demo"}, {"step": "extract"}, "abc123"),
    ]
