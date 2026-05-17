"""Tests for runtime telemetry helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from oneiric.runtime.events import HandlerResult
from oneiric.runtime.telemetry import (
    RuntimeObservabilitySnapshot,
    RuntimeTelemetryRecorder,
    load_runtime_telemetry,
    runtime_telemetry_path,
)


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


def test_runtime_telemetry_handles_invalid_and_non_mapping_content(tmp_path):
    target = tmp_path / "runtime_telemetry.json"
    target.write_text('"not-json"')
    snapshot = load_runtime_telemetry(target)
    assert snapshot == RuntimeObservabilitySnapshot()

    target.write_text('{"last_event": "oops", "last_workflow": 3}')
    snapshot = load_runtime_telemetry(target)
    assert snapshot.last_event is None
    assert snapshot.last_workflow is None


def test_runtime_telemetry_path_resolves_from_cache_dir(tmp_path):
    path = runtime_telemetry_path(Path(tmp_path))
    assert path.name == "runtime_telemetry.json"


def test_runtime_telemetry_handles_read_errors(tmp_path):
    target = tmp_path / "runtime_telemetry.json"
    target.write_text("{}")

    with patch.object(Path, "read_text", side_effect=OSError("boom")):
        snapshot = load_runtime_telemetry(target)

    assert snapshot == RuntimeObservabilitySnapshot()


def test_runtime_telemetry_skips_malformed_workflow_entries(tmp_path):
    target = tmp_path / "runtime_telemetry.json"
    recorder = RuntimeTelemetryRecorder(target)
    dag_spec = {
        "nodes": [
            "bad-entry",
            {"key": 123},
            {"id": "ok", "depends_on": "not-a-list"},
        ]
    }

    payload = recorder._workflow_payload("demo", dag_spec, {})

    assert payload["node_count"] == 1
    assert payload["entry_nodes"] == ["ok"]
    assert payload["nodes"][0]["depends_on"] == []
