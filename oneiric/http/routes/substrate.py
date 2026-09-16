"""HTTP routes exposing Oneiric's substrate state over HTTP.

Three read-only routes back the substrate layer Dhara used to manage
under its FastMCP server. Persistence is JSON files under
``~/.oneiric/substrate/`` (Oneiric's storage layer is blob-oriented and
does not yet have a substrate-state primitive):

- ``settings.json``     — current ``ActiveSettings`` + history
- ``context.json``      — current ``ContextVersion`` per tenant + history
- ``progress.json``     — progress snapshots per workflow + history

Each route registers a :class:`HealthFeedState` so the server-level
``/health`` endpoint can aggregate per-feed state. ``/health`` returns
``503`` if ANY route is degraded (errors_total > 0 or the store is
unreachable on the first call).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from aiohttp import web


# ---------------------------------------------------------------------------
# Health feed state
# ---------------------------------------------------------------------------


@dataclass
class HealthFeedState:
    """Per-route health state used by the aggregated /health endpoint."""

    name: str
    entities_count: int = 0
    last_updated_timestamp: str | None = None
    errors_total: int = 0
    cycles_total: int = 0

    def record_success(self, entities_count: int) -> None:
        """Mark a successful read; advance the cycle counters."""
        self.cycles_total += 1
        self.entities_count = entities_count
        self.last_updated_timestamp = datetime.now(UTC).isoformat()

    def record_error(self) -> None:
        """Mark a failed read; advance cycles + errors counters."""
        self.cycles_total += 1
        self.errors_total += 1

    def is_healthy(self) -> bool:
        """Degraded if any errors recorded AND we've had cycles."""
        if self.cycles_total == 0:
            return False
        return self.errors_total == 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "entities_count": self.entities_count,
            "last_updated_timestamp": self.last_updated_timestamp,
            "errors_total": self.errors_total,
            "cycles_total": self.cycles_total,
            "healthy": self.is_healthy(),
        }


# ---------------------------------------------------------------------------
# Pydantic payload models (POST schemas — used by write helpers)
# ---------------------------------------------------------------------------


class ActiveSettingsVersionIn(BaseModel):
    """Body for ``POST /substrate/settings``."""

    version: str = Field(..., min_length=1)
    source: str | None = None
    metadata: dict[str, Any] | None = None


class ContextVersionIn(BaseModel):
    """Body for ``POST /substrate/context``."""

    tenant_id: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)
    kind: str | None = None
    metadata: dict[str, Any] | None = None


class ProgressSnapshotIn(BaseModel):
    """Body for ``POST /substrate/progress``."""

    workflow_id: str = Field(..., min_length=1)
    stage: str = Field(..., min_length=1)
    percent: int = Field(..., ge=0, le=100)
    note: str | None = None
    metadata: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


DEFAULT_SUBSTRATE_DIR = Path.home() / ".oneiric" / "substrate"

_BUCKETS: tuple[str, ...] = ("settings", "context", "progress")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _ensure_bucket_paths(root: Path) -> dict[str, Path]:
    """Create the three bucket files (with empty payloads) under ``root``."""
    root.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for name in _BUCKETS:
        path = root / f"{name}.json"
        if not path.exists():
            path.write_text(json.dumps(_empty_bucket(name), indent=2))
        paths[name] = path
    return paths


def _empty_bucket(name: str) -> dict[str, Any]:
    if name == "settings":
        return {"current": None, "history": []}
    if name == "context":
        return {"tenants": {}}
    return {"workflows": {}}


@dataclass
class SubstrateStore:
    """JSON-file substrate store rooted at ``root`` (defaults to ``~/.oneiric/substrate/``).

    Bucket shape mirrors Dhara's substrate:

    - ``settings``: ``{"current": <record|None>, "history": [<record>...]}``
    - ``context``:  ``{"tenants": {<tenant_id>: {"current": <record|None>,
                              "history": [<record>...]}}}``
    - ``progress``: ``{"workflows": {<workflow_id>: {"snapshots": [<record>...]}}}``

    A record carries ``id``, ``created_at``, and a ``payload`` (the raw
    Pydantic ``model_dump()``). Atomic writes via ``tmp + replace`` so
    concurrent reads never see a half-written file.
    """

    root: Path = field(default_factory=lambda: DEFAULT_SUBSTRATE_DIR)
    _paths: dict[str, Path] = field(default_factory=dict, init=False)
    _locks: dict[str, asyncio.Lock] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self._paths = _ensure_bucket_paths(self.root)
        self._locks = {name: asyncio.Lock() for name in _BUCKETS}

    @property
    def paths(self) -> dict[str, Path]:
        return dict(self._paths)

    # ----- read -----

    def read_settings(self) -> dict[str, Any]:
        return _read_json(self._paths["settings"], _empty_bucket("settings"))

    def read_context(self) -> dict[str, Any]:
        return _read_json(self._paths["context"], _empty_bucket("context"))

    def read_progress(self) -> dict[str, Any]:
        return _read_json(self._paths["progress"], _empty_bucket("progress"))

    # ----- write -----

    def write_settings(self, payload: ActiveSettingsVersionIn) -> dict[str, Any]:
        record: dict[str, Any] = {
            "id": _uuid_hex(),
            "created_at": _now_iso(),
            "payload": payload.model_dump(),
        }
        with self._locks["settings"]:
            bucket = self.read_settings()
            bucket["history"] = list(bucket.get("history", [])) + [record]
            bucket["current"] = record
            _write_json_atomic(self._paths["settings"], bucket)
        return record

    def write_context(
        self, tenant_id: str, payload: ContextVersionIn
    ) -> dict[str, Any]:
        record: dict[str, Any] = {
            "id": _uuid_hex(),
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

    def write_progress(self, payload: ProgressSnapshotIn) -> dict[str, Any]:
        record: dict[str, Any] = {
            "id": _uuid_hex(),
            "workflow_id": payload.workflow_id,
            "created_at": _now_iso(),
            "payload": payload.model_dump(),
        }
        with self._locks["progress"]:
            bucket = self.read_progress()
            workflows = dict(bucket.get("workflows", {}))
            entry = dict(workflows.get(payload.workflow_id, {"snapshots": []}))
            entry["snapshots"] = list(entry.get("snapshots", [])) + [record]
            workflows[payload.workflow_id] = entry
            bucket["workflows"] = workflows
            _write_json_atomic(self._paths["progress"], bucket)
        return record


# ---------------------------------------------------------------------------
# Disk I/O
# ---------------------------------------------------------------------------


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
    """Write ``payload`` to ``path`` atomically via tmp+replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str))
    tmp.replace(path)


def _uuid_hex() -> str:
    from uuid import uuid4

    return uuid4().hex


def _web_json(payload: Any, *, status: int = 200) -> "web.Response":
    """Build a JSON aiohttp response (import aiohttp lazily for tests)."""
    from aiohttp import web

    return web.json_response(payload, status=status, dumps=_safe_dumps)


def _safe_dumps(payload: Any) -> str:
    return json.dumps(payload, default=str)


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_substrate_routes(
    app: "web.Application",
    *,
    store: SubstrateStore | None = None,
) -> dict[str, HealthFeedState]:
    """Register the three substrate read routes (plus three POST writers).

    Args:
        app: The aiohttp ``Application`` to register routes on.
        store: Optional pre-built :class:`SubstrateStore` (for tests that
            want a custom path). Defaults to ``~/.oneiric/substrate``.

    Returns:
        Dict of ``name -> HealthFeedState`` so callers can aggregate
        into a /health handler.
    """
    from aiohttp import web

    if store is None:
        store = SubstrateStore()

    feeds: dict[str, HealthFeedState] = {
        name: HealthFeedState(name=name) for name in _BUCKETS
    }

    async def _read_with_feed(
        name: str,
        loader: Callable[[], dict[str, Any]],
        renderer: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> web.Response:
        feed = feeds[name]
        try:
            raw = loader()
            payload = renderer(raw)
        except (OSError, ValueError, TypeError):
            feed.record_error()
            return _web_json(
                {"error": "substrate-read-failed", "route": name},
                status=503,
            )
        feed.record_success(entities_count=_count_entities(name, payload))
        return _web_json(payload)

    async def get_settings(_request: web.Request) -> web.Response:
        return await _read_with_feed(
            "settings", store.read_settings, _render_settings
        )

    async def get_context(_request: web.Request) -> web.Response:
        return await _read_with_feed(
            "context", store.read_context, _render_context
        )

    async def get_progress(_request: web.Request) -> web.Response:
        return await _read_with_feed(
            "progress", store.read_progress, _render_progress
        )

    async def post_settings(request: web.Request) -> web.Response:
        feed = feeds["settings"]
        try:
            data = await request.json()
            parsed = ActiveSettingsVersionIn.model_validate(data)
            record = await asyncio.to_thread(store.write_settings, parsed)
        except (ValueError, TypeError, OSError):
            feed.record_error()
            return _web_json(
                {"error": "validation failed", "details": "invalid settings body"},
                status=422,
            )
        feed.record_success(entities_count=1)
        return _web_json(
            {"record_id": record["id"], "version": parsed.version},
            status=200,
        )

    async def post_context(request: web.Request) -> web.Response:
        feed = feeds["context"]
        try:
            data = await request.json()
            parsed = ContextVersionIn.model_validate(data)
            record = await asyncio.to_thread(
                store.write_context, parsed.tenant_id, parsed
            )
        except (ValueError, TypeError, OSError):
            feed.record_error()
            return _web_json(
                {"error": "validation failed", "details": "invalid context body"},
                status=422,
            )
        feed.record_success(entities_count=1)
        return _web_json(
            {
                "record_id": record["id"],
                "tenant_id": parsed.tenant_id,
                "version": parsed.version,
            },
            status=200,
        )

    async def post_progress(request: web.Request) -> web.Response:
        feed = feeds["progress"]
        try:
            data = await request.json()
            parsed = ProgressSnapshotIn.model_validate(data)
            record = await asyncio.to_thread(store.write_progress, parsed)
        except (ValueError, TypeError, OSError):
            feed.record_error()
            return _web_json(
                {"error": "validation failed", "details": "invalid progress body"},
                status=422,
            )
        feed.record_success(entities_count=1)
        return _web_json(
            {
                "record_id": record["id"],
                "workflow_id": parsed.workflow_id,
                "stage": parsed.stage,
                "percent": parsed.percent,
            },
            status=200,
        )

    app.router.add_get("/substrate/settings", get_settings)
    app.router.add_get("/substrate/context", get_context)
    app.router.add_get("/substrate/progress", get_progress)
    app.router.add_post("/substrate/settings", post_settings)
    app.router.add_post("/substrate/context", post_context)
    app.router.add_post("/substrate/progress", post_progress)

    return feeds


# ---------------------------------------------------------------------------
# Render helpers (turn store buckets into non-empty HTTP payloads)
# ---------------------------------------------------------------------------


def _count_entities(name: str, payload: dict[str, Any]) -> int:
    if name == "settings":
        return 1 if payload.get("current") else 0
    if name == "context":
        tenants = payload.get("tenants", [])
        return sum(1 for t in tenants if t.get("current"))
    workflows = payload.get("workflows", [])
    return sum(int(entry.get("snapshot_total", 0)) for entry in workflows)


def _render_settings(raw: dict[str, Any]) -> dict[str, Any]:
    current = raw.get("current")
    history = list(raw.get("history", []))
    payload_version = current["payload"]["version"] if current else None
    return {
        "version": payload_version,
        "settings_version": payload_version,
        "current": current,
        "history": history,
        "history_total": len(history),
    }


def _render_context(raw: dict[str, Any]) -> dict[str, Any]:
    tenants_raw = raw.get("tenants", {}) or {}
    tenants: list[dict[str, Any]] = []
    for tenant_id, entry in tenants_raw.items():
        current = entry.get("current")
        history = list(entry.get("history", []))
        tenants.append(
            {
                "tenant_id": tenant_id,
                "current": current,
                "history": history,
                "history_total": len(history),
            }
        )
    return {"tenants": tenants, "tenant_total": len(tenants)}


def _render_progress(raw: dict[str, Any]) -> dict[str, Any]:
    workflows_raw = raw.get("workflows", {}) or {}
    workflows: list[dict[str, Any]] = []
    for workflow_id, entry in workflows_raw.items():
        snapshots = list(entry.get("snapshots", []))
        workflows.append(
            {
                "workflow_id": workflow_id,
                "snapshots": snapshots,
                "snapshot_total": len(snapshots),
            }
        )
    return {"workflows": workflows, "workflow_total": len(workflows)}


# ---------------------------------------------------------------------------
# Health aggregator
# ---------------------------------------------------------------------------


def aggregate_health(
    feeds: dict[str, HealthFeedState],
) -> tuple[int, dict[str, Any]]:
    """Aggregate per-route feeds into one health payload.

    Returns ``(status_code, body)``. ``status_code`` is ``200`` when every
    feed reports healthy; ``503`` when ANY feed is degraded.
    """
    healthy = all(feed.is_healthy() for feed in feeds.values())
    body: dict[str, Any] = {
        "component": "oneiric",
        "routes": {name: feed.as_dict() for name, feed in feeds.items()},
        "cycles_total": sum(feed.cycles_total for feed in feeds.values()),
        "errors_total": sum(feed.errors_total for feed in feeds.values()),
    }
    body["status"] = "healthy" if healthy else "degraded"
    return (200 if healthy else 503), body


# ---------------------------------------------------------------------------
# Lifecycle helpers (exposed for tests that need a teardown hook)
# ---------------------------------------------------------------------------


async def close_substrate(_feeds: dict[str, HealthFeedState]) -> None:
    """No-op async cleanup; kept for symmetry with future aiohttp resources."""
    return None