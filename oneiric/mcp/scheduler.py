"""MCP scheduler processor — bridges the FastMCP `schedule_task` tool to a
:class:`WorkflowBridge`.

T19 migrated this class out of ``oneiric.runtime.scheduler`` (alongside the
deleted aiohttp :class:`SchedulerHTTPServer`). The :class:`WorkflowTaskProcessor`
itself was self-contained: it has no aiohttp dependencies, only a single
``workflow_bridge`` collaborator. This module preserves the original
behavior verbatim; tests in ``tests/mcp/test_scheduler.py`` pin the
documented contract.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from oneiric.core.logging import get_logger
from oneiric.domains.workflows import WorkflowBridge


class WorkflowTaskProcessor:
    def __init__(self, workflow_bridge: WorkflowBridge) -> None:
        self._workflow_bridge = workflow_bridge
        self._logger = get_logger("mcp.scheduler.processor")

    async def process(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        workflow_key = payload.get("workflow")
        if not workflow_key or not isinstance(workflow_key, str):
            raise ValueError("workflow-key-missing")
        context = self._coerce_mapping(payload.get("context"))
        checkpoint = self._coerce_mapping(payload.get("checkpoint"))
        metadata = self._coerce_mapping(payload.get("metadata"))
        self._logger.info(
            "workflow-task-start",
            workflow=workflow_key,
            run_id=payload.get("run_id"),
        )
        run_result = await self._workflow_bridge.execute_dag(
            workflow_key,
            context=context,
            checkpoint=checkpoint,
            run_id=payload.get("run_id")
            if isinstance(payload.get("run_id"), str)
            else None,
        )
        resolved_run_id = run_result["run_id"]
        response = {
            "workflow": workflow_key,
            "run_id": resolved_run_id,
            "workflow_provider": payload.get("workflow_provider"),
            "metadata": metadata or {},
            "results": run_result["results"],
            "processed_at": datetime.now(UTC).isoformat(),
        }
        self._logger.info(
            "workflow-task-complete",
            workflow=workflow_key,
            run_id=resolved_run_id,
        )
        return response

    @staticmethod
    def _coerce_mapping(value: Any) -> dict[str, Any] | None:
        if isinstance(value, Mapping):
            return dict(value)
        return None


__all__ = ["WorkflowTaskProcessor"]