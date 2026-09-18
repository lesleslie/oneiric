"""JSON-file substrate store.

Migrated from oneiric/http/routes/substrate.py (REQ-009). The legacy
implementation used ``asyncio.Lock`` and was called via
``asyncio.to_thread`` from aiohttp handlers — which does NOT serialize
across worker threads. This version uses ``threading.Lock`` because
the FastMCP tool handlers run in async context but the actual disk
write can be invoked from any thread (depending on the FastMCP
transport's threading model).

The on-disk JSON shape is preserved verbatim so existing
``~/.oneiric/substrate/{settings,context,progress}.json`` files from
legacy oneiric installations continue to load unchanged.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4


class _PayloadLike(Protocol):
    """Any payload with .model_dump(); T3 will refine to the concrete types."""

    def model_dump(self) -> dict[str, Any]: ...


_BUCKETS: tuple[str, ...] = ("settings", "context", "progress")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _empty_bucket(name: str) -> dict[str, Any]:
    if name == "settings":
        return {"current": None, "history": []}
    if name == "context":
        return {"tenants": {}}
    return {"workflows": {}}


def _ensure_bucket_paths(root: Path) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for name in _BUCKETS:
        path = root / f"{name}.json"
        if not path.exists():
            path.write_text(json.dumps(_empty_bucket(name), indent=2))
        paths[name] = path
    return paths


def _read_json(path: Path, empty: dict[str, Any]) -> dict[str, Any]:
    try:
        text = path.read_text()
    except FileNotFoundError:
        return empty
    try:
        data = json.loads(text) if text.strip() else empty
    except json.JSONDecodeError:
        return empty
    return data if isinstance(data, dict) else empty


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str))
    tmp.replace(path)


@dataclass
class SubstrateStore:
    """JSON-file substrate store rooted at ``root``.

    Concurrent-safe via ``threading.Lock`` per bucket (REQ-009).
    """

    root: Path = field(default_factory=lambda: Path.home() / ".oneiric" / "substrate")
    _paths: dict[str, Path] = field(default_factory=dict, init=False)
    _locks: dict[str, threading.Lock] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self._paths = _ensure_bucket_paths(self.root)
        self._locks = {name: threading.Lock() for name in _BUCKETS}

    @property
    def paths(self) -> dict[str, Path]:
        return self._paths.copy()

    # ----- read -----

    def read_settings(self) -> dict[str, Any]:
        return _read_json(self._paths["settings"], _empty_bucket("settings"))

    def read_context(self) -> dict[str, Any]:
        return _read_json(self._paths["context"], _empty_bucket("context"))

    def read_progress(self) -> dict[str, Any]:
        return _read_json(self._paths["progress"], _empty_bucket("progress"))

    # ----- write -----

    def write_settings(self, payload: _PayloadLike) -> dict[str, Any]:
        record: dict[str, Any] = {
            "id": uuid4().hex,
            "created_at": _now_iso(),
            "payload": payload.model_dump(),
        }
        with self._locks["settings"]:
            bucket = self.read_settings()
            bucket["history"] = list(bucket.get("history", [])) + [record]
            bucket["current"] = record
            _write_json_atomic(self._paths["settings"], bucket)
        return record

    def write_context(self, tenant_id: str, payload: _PayloadLike) -> dict[str, Any]:
        record: dict[str, Any] = {
            "id": uuid4().hex,
            "tenant_id": tenant_id,
            "created_at": _now_iso(),
            "payload": payload.model_dump(),
        }
        with self._locks["context"]:
            bucket = self.read_context()
            tenants = dict(bucket.get("tenants", {}))
            entry = dict(tenants.get(tenant_id, {"current": None, "history": []}))
            entry["history"] = list(entry.get("history", [])) + [record]
            entry["current"] = record
            tenants[tenant_id] = entry
            bucket["tenants"] = tenants
            _write_json_atomic(self._paths["context"], bucket)
        return record

    def write_progress(self, payload: _PayloadLike) -> dict[str, Any]:
        record: dict[str, Any] = {
            "id": uuid4().hex,
            "workflow_id": payload.model_dump().get("workflow_id", ""),
            "created_at": _now_iso(),
            "payload": payload.model_dump(),
        }
        with self._locks["progress"]:
            bucket = self.read_progress()
            workflows = dict(bucket.get("workflows", {}))
            wf_id = payload.model_dump().get("workflow_id", "")
            entry = dict(workflows.get(wf_id, {"snapshots": []}))
            entry["snapshots"] = list(entry.get("snapshots", [])) + [record]
            workflows[wf_id] = entry
            bucket["workflows"] = workflows
            _write_json_atomic(self._paths["progress"], bucket)
        return record


__all__ = ["SubstrateStore"]
