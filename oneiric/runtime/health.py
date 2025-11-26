"""Runtime orchestrator health snapshot helpers."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


RUNTIME_HEALTH_FILENAME = "runtime_health.json"


@dataclass
class RuntimeHealthSnapshot:
    watchers_running: bool = False
    remote_enabled: bool = False
    last_remote_sync_at: Optional[str] = None
    last_remote_error: Optional[str] = None
    orchestrator_pid: Optional[int] = None
    updated_at: Optional[str] = None
    last_remote_registered: Optional[int] = None
    last_remote_per_domain: Dict[str, int] = None  # type: ignore[assignment]
    last_remote_skipped: Optional[int] = None
    activity_state: Dict[str, Dict[str, Any]] = None  # type: ignore[assignment]

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if data.get("last_remote_per_domain") is None:
            data["last_remote_per_domain"] = {}
        if data.get("activity_state") is None:
            data["activity_state"] = {}
        return data


def load_runtime_health(path: str | Path) -> RuntimeHealthSnapshot:
    file = Path(path)
    if not file.exists():
        return RuntimeHealthSnapshot()
    try:
        data = json.loads(file.read_text())
    except Exception:
        return RuntimeHealthSnapshot()
    if not isinstance(data, dict):
        return RuntimeHealthSnapshot()
    snapshot = RuntimeHealthSnapshot()
    snapshot.watchers_running = bool(data.get("watchers_running", snapshot.watchers_running))
    snapshot.remote_enabled = bool(data.get("remote_enabled", snapshot.remote_enabled))
    snapshot.last_remote_sync_at = data.get("last_remote_sync_at")
    snapshot.last_remote_error = data.get("last_remote_error")
    snapshot.orchestrator_pid = data.get("orchestrator_pid")
    snapshot.updated_at = data.get("updated_at")
    snapshot.last_remote_registered = data.get("last_remote_registered")
    snapshot.last_remote_per_domain = data.get("last_remote_per_domain") or {}
    snapshot.last_remote_skipped = data.get("last_remote_skipped")
    snapshot.activity_state = data.get("activity_state") or {}
    return snapshot


def write_runtime_health(path: str | Path, snapshot: RuntimeHealthSnapshot) -> None:
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    snapshot.updated_at = _timestamp()
    tmp = file.with_suffix(".tmp")
    tmp.write_text(json.dumps(snapshot.as_dict()))
    tmp.replace(file)


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_runtime_health_path(cache_dir: str | Path) -> Path:
    return Path(cache_dir) / RUNTIME_HEALTH_FILENAME
