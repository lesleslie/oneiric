"""Runtime observability telemetry helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from oneiric.core.logging import get_logger

RUNTIME_TELEMETRY_FILENAME = "runtime_telemetry.json"
telemetry_logger = get_logger("runtime.telemetry")


@dataclass
class RuntimeObservabilitySnapshot:
    """Combined event + workflow telemetry payload."""

    last_event: dict[str, Any] | None = None
    last_workflow: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if data.get("last_event") is None:
            data["last_event"] = {}
        if data.get("last_workflow") is None:
            data["last_workflow"] = {}
        return data


def load_runtime_telemetry(path: str | Path) -> RuntimeObservabilitySnapshot:
    """Load runtime telemetry snapshot from disk."""

    file = Path(path)
    if not file.exists():
        return RuntimeObservabilitySnapshot()
    try:
        data = json.loads(file.read_text())
    except Exception:
        return RuntimeObservabilitySnapshot()
    snapshot = RuntimeObservabilitySnapshot()
    if isinstance(data, Mapping):
        last_event = data.get("last_event")
        if isinstance(last_event, Mapping):
            snapshot.last_event = dict(last_event)
        last_workflow = data.get("last_workflow")
        if isinstance(last_workflow, Mapping):
            snapshot.last_workflow = dict(last_workflow)
    return snapshot


class RuntimeTelemetryRecorder:
    """Persist workflow + event telemetry for CLI inspectors and dashboards."""

    def __init__(self, target_path: str | Path) -> None:
        self._path = Path(target_path)
        self._logger = telemetry_logger

    def record_event_dispatch(self, topic: str, results: Sequence[Any]) -> None:
        snapshot = load_runtime_telemetry(self._path)
        snapshot.last_event = self._event_payload(topic, results)
        self._write(snapshot)
        payload = snapshot.last_event or {}
        self._logger.info(
            "runtime-event-telemetry",
            topic=payload.get("topic"),
            matched=payload.get("matched_handlers", 0),
            failures=payload.get("failures", 0),
        )

    def record_workflow_execution(
        self, workflow_key: str, dag_spec: Mapping[str, Any], results: Mapping[str, Any]
    ) -> None:
        snapshot = load_runtime_telemetry(self._path)
        snapshot.last_workflow = self._workflow_payload(workflow_key, dag_spec, results)
        self._write(snapshot)
        payload = snapshot.last_workflow or {}
        self._logger.info(
            "runtime-workflow-telemetry",
            workflow=payload.get("workflow"),
            node_count=payload.get("node_count", 0),
            total_duration_ms=payload.get("total_duration_ms", 0.0),
        )

    # internal -----------------------------------------------------------------

    def _event_payload(self, topic: str, results: Sequence[Any]) -> dict[str, Any]:
        handlers: list[dict[str, Any]] = []
        failures = 0
        total_duration = 0.0
        for result in results:
            duration_ms = float(getattr(result, "duration", 0.0)) * 1000.0
            total_duration += duration_ms
            success = bool(getattr(result, "success", False))
            if not success:
                failures += 1
            handlers.append(
                {
                    "handler": getattr(result, "handler", "unknown"),
                    "success": success,
                    "duration_ms": duration_ms,
                    "attempts": int(getattr(result, "attempts", 0) or 0),
                    "error": getattr(result, "error", None),
                }
            )
        return {
            "topic": topic,
            "matched_handlers": len(results),
            "failures": failures,
            "total_duration_ms": total_duration,
            "handlers": handlers,
            "recorded_at": _timestamp(),
        }

    def _workflow_payload(
        self,
        workflow_key: str,
        dag_spec: Mapping[str, Any],
        results: Mapping[str, Any],
    ) -> dict[str, Any]:
        nodes_raw = dag_spec.get("nodes") or dag_spec.get("tasks") or []
        nodes: list[dict[str, Any]] = []
        total_duration = 0.0
        for entry in nodes_raw if isinstance(nodes_raw, Sequence) else []:
            if not isinstance(entry, Mapping):
                continue
            node_id = entry.get("id") or entry.get("key")
            if not isinstance(node_id, str):
                continue
            depends = entry.get("depends_on") or []
            if not isinstance(depends, Sequence) or isinstance(depends, (str, bytes)):
                depends = []
            duration = float(results.get(f"{node_id}__duration") or 0.0)
            duration_ms = duration * 1000.0
            total_duration += duration_ms
            nodes.append(
                {
                    "node": node_id,
                    "task": entry.get("task"),
                    "depends_on": list(depends),
                    "duration_ms": duration_ms,
                    "attempts": int(results.get(f"{node_id}__attempts") or 0),
                    "retry_policy": entry.get("retry_policy") or None,
                }
            )
        entry_nodes = [node["node"] for node in nodes if not node["depends_on"]]
        return {
            "workflow": workflow_key,
            "node_count": len(nodes),
            "entry_nodes": entry_nodes,
            "nodes": nodes,
            "total_duration_ms": total_duration,
            "recorded_at": _timestamp(),
        }

    def _write(self, snapshot: RuntimeObservabilitySnapshot) -> None:
        path = self._path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(snapshot.as_dict()))
        tmp.replace(path)


def runtime_telemetry_path(cache_dir: str | Path) -> Path:
    """Return the default path used for runtime telemetry payloads."""

    return Path(cache_dir) / RUNTIME_TELEMETRY_FILENAME


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()
