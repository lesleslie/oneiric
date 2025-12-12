"""Tests for runtime telemetry helpers."""

from __future__ import annotations

import pytest

from oneiric.runtime.events import HandlerResult
from oneiric.runtime.telemetry import RuntimeTelemetryRecorder, load_runtime_telemetry


def test_runtime_telemetry_records_event(tmp_path):
    """Event dispatch telemetry is persisted with handler summaries."""
    target = tmp_path / "runtime_telemetry.json"
    recorder = RuntimeTelemetryRecorder(target)
    recorder.record_event_dispatch(
        "demo.topic",
        [
            HandlerResult(
                handler="demo-handler",
                success=True,
                duration=0.01,
                value={"ok": True},
                attempts=1,
            ),
            HandlerResult(
                handler="demo-handler-b",
                success=False,
                duration=0.02,
                error="boom",
                attempts=2,
            ),
        ],
    )
    snapshot = load_runtime_telemetry(target)
    event_payload = snapshot.last_event
    assert event_payload["topic"] == "demo.topic"
    assert event_payload["matched_handlers"] == 2
    assert event_payload["failures"] == 1
    assert len(event_payload["handlers"]) == 2
    assert event_payload["handlers"][1]["error"] == "boom"


def test_runtime_telemetry_records_workflow(tmp_path):
    """Workflow execution telemetry summarizes DAG nodes."""
    target = tmp_path / "runtime_telemetry.json"
    recorder = RuntimeTelemetryRecorder(target)
    dag_spec = {
        "nodes": [
            {"id": "start", "task": "tasks.start"},
            {
                "id": "next",
                "task": "tasks.next",
                "depends_on": ["start"],
                "retry_policy": {"attempts": 2},
            },
        ]
    }
    results = {
        "start": {"ok": True},
        "start__duration": 0.01,
        "start__attempts": 1,
        "next": {"ok": True},
        "next__duration": 0.02,
        "next__attempts": 2,
    }
    recorder.record_workflow_execution("demo-workflow", dag_spec, results)
    snapshot = load_runtime_telemetry(target)
    workflow_payload = snapshot.last_workflow
    assert workflow_payload["workflow"] == "demo-workflow"
    assert workflow_payload["node_count"] == 2
    assert workflow_payload["total_duration_ms"] == pytest.approx(30.0)
    assert workflow_payload["nodes"][1]["retry_policy"] == {"attempts": 2}
