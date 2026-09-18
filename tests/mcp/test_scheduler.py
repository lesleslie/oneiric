"""Behavioral-equivalence tests for the migrated WorkflowTaskProcessor.

Verifies that the copy from oneiric.runtime.scheduler → oneiric.mcp.scheduler
preserves the original behavior. Without these tests, a constructor-signature
drift or an accidental attribute drop during the copy would silently break
schedule_task (REQ-008 + pr-test-analyzer finding).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from oneiric.mcp.scheduler import WorkflowTaskProcessor


class _FakeBridge:
    """Stand-in for WorkflowBridge that records calls and returns canned output."""

    def __init__(self, *, run_id: str = "run-xyz", results: dict[str, Any] | None = None):
        self.calls: list[dict[str, Any]] = []
        self._run_id = run_id
        self._results = results or {"ok": True}

    async def execute_dag(self, workflow_key: str, **kwargs) -> dict[str, Any]:
        self.calls.append({"workflow_key": workflow_key, **kwargs})
        return {"run_id": self._run_id, "results": self._results}


class TestWorkflowTaskProcessor:
    def test_constructor_accepts_workflow_bridge(self) -> None:
        bridge = _FakeBridge()
        proc = WorkflowTaskProcessor(workflow_bridge=bridge)  # type: ignore[arg-type]
        assert proc._workflow_bridge is bridge  # noqa: SLF001 — internal check

    async def test_process_returns_documented_shape(self) -> None:
        bridge = _FakeBridge(run_id="run-42", results={"step1": "ok"})
        proc = WorkflowTaskProcessor(workflow_bridge=bridge)  # type: ignore[arg-type]
        result = await proc.process({
            "workflow": "my-workflow",
            "context": {"k": "v"},
            "checkpoint": {"cp": 1},
            "metadata": {"trace_id": "t-1"},
            "run_id": "explicit-run-id",
            "workflow_provider": "test-provider",
        })
        assert result["workflow"] == "my-workflow"
        assert result["run_id"] == "run-42"  # bridge output wins over payload
        assert result["results"] == {"step1": "ok"}
        assert result["processed_at"]  # ISO timestamp
        assert result["metadata"] == {"trace_id": "t-1"}

    async def test_process_propagates_bridge_errors(self) -> None:
        """The processor must NOT swallow errors from WorkflowBridge.execute_dag."""
        class _FailingBridge:
            async def execute_dag(self, *args, **kwargs):
                raise RuntimeError("dag exploded")

        proc = WorkflowTaskProcessor(workflow_bridge=_FailingBridge())  # type: ignore[arg-type]
        with pytest.raises(RuntimeError, match="dag exploded"):
            await proc.process({"workflow": "my-workflow"})

    async def test_process_rejects_missing_workflow_key(self) -> None:
        bridge = _FakeBridge()
        proc = WorkflowTaskProcessor(workflow_bridge=bridge)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="workflow-key-missing"):
            await proc.process({})
