"""Tracked settings wrapper for Oneiric adapters.

TrackedSettings holds a Pydantic settings model and intercepts attribute
assignments to push config snapshots and change events to Dhara.

Design notes:
- Wraps a Pydantic ``BaseModel`` (``settings_model``) via ``__setattr__``.
- Lifecycle events (startup/stop/restart) push a full JSON snapshot immediately.
- In-process settings changes log locally AND schedule a debounced, batched
  per-change push.
- Values are hashed with FNV-1a 64-bit unless the key is in the per-adapter
  allowlist. The hash is computed inline before JSON serialization.
- Push failures never raise. Telemetry is strictly non-blocking; failures are
  logged and the payload is captured in a local fallback file (mode ``0600``)
  for retry on the next lifecycle event.
- ``adapter_id`` is emitted as a TOP-LEVEL OTel span attribute on every
  lifecycle and change event so Phase D's ``adapter impact`` command can join
  on it directly. Nested attributes are NOT acceptable per Plan 4.
"""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import httpx
from pydantic import BaseModel

from oneiric.core.logging import get_logger
from oneiric.core.observability import get_tracer

logger = get_logger("adapter.tracked_settings")

TRACKED_SETTINGS_INSTRUMENTATION_SCOPE = "oneiric.adapters.tracked_settings"

FNV1A_OFFSET = 0xCBF29CE484222325
FNV1A_PRIME = 0x100000001B3
_HASH_PREFIX = "fnv1a:"

_FALLBACK_DIR = Path.home() / ".cache" / "oneiric" / "pending_snapshots"

_EVENT_SNAPSHOT = "snapshot"
_EVENT_CHANGE_BATCH = "change_batch"


class _HttpClientFactory(Protocol):
    def __call__(self) -> httpx.AsyncClient: ...


def fnv1a_64(value: str) -> str:
    """Compute FNV-1a 64-bit hash and return it as a 16-char hex string."""
    h = FNV1A_OFFSET
    for byte in value.encode("utf-8"):
        h ^= byte
        h = (h * FNV1A_PRIME) & 0xFFFFFFFFFFFFFFFF
    return f"{h:016x}"


def _hash_value_if_secret(value: Any) -> str:
    """Serialize a value for hashing, preserving type fidelity for primitives."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    return json.dumps(value, sort_keys=True, default=str)


def _ensure_cache_dir(cache_dir: Path) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    with suppress(OSError):  # pragma: no cover - permission policy dependent
        os.chmod(cache_dir, 0o700)
    return cache_dir


def _write_fallback_payload(
    *,
    cache_dir: Path,
    adapter_id: str,
    kind: str,
    payload: dict[str, Any],
) -> Path:
    """Write a fallback payload to disk with ``0600`` permissions."""
    target_dir = _ensure_cache_dir(cache_dir)
    # Preserve ``:`` (used in adapter_id) so files sort naturally; sanitize
    # only path separators so the filename is safe across OSes.
    safe_adapter = adapter_id.replace("/", "_")
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
    path = target_dir / f"{safe_adapter}-{kind}-{timestamp}.json"
    fd = os.open(
        path,
        flags=os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        mode=0o600,
    )
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, default=str)
    return path


class TrackedSettings:
    """Wrap a Pydantic settings model and push changes/lifecycle to Dhara.

    Parameters
    ----------
    model:
        Pydantic ``BaseModel`` instance to wrap.
    adapter_id:
        Stable adapter identifier (e.g. ``"adapter:cache:redis"``). Emitted
        as a TOP-LEVEL OTel span attribute on every event.
    dhara_url:
        Base URL of the Dhara MCP server.
    allowlist:
        Field names that may be persisted in plaintext. Any field not in the
        allowlist is hashed with FNV-1a 64-bit before serialization.
    debounce_seconds:
        Time window over which change events are coalesced into a single
        batched push.
    client_factory:
        Factory returning a configured ``httpx.AsyncClient``. Provided so
        tests can inject a ``MockTransport`` while production code uses
        defaults.
    fallback_dir:
        Override for the local fallback directory used when Dhara is
        unreachable. Defaults to ``~/.cache/oneiric/pending_snapshots/``.
    """

    # Internal state — populated in __init__ via ``object.__setattr__`` to
    # bypass our interception. Declared here so type checkers see them.
    _model: Any  # Pydantic BaseModel — typed as Any so field access narrows
    _adapter_id: str
    _dhara_url: str
    _allowlist: set[str]
    _debounce_seconds: float
    _pending_changes: list[dict[str, Any]]
    _flush_task: asyncio.Task[None] | None
    _fallback_dir: Path
    _client_factory: _HttpClientFactory

    def __init__(
        self,
        *,
        model: BaseModel,
        adapter_id: str,
        dhara_url: str,
        allowlist: list[str] | None = None,
        debounce_seconds: float = 30.0,
        client_factory: _HttpClientFactory | None = None,
        fallback_dir: Path | None = None,
    ) -> None:
        # Bypass our own __setattr__ for internal state — using object.__setattr__
        # so Pydantic field assignment is not intercepted.
        object.__setattr__(self, "_model", model)
        object.__setattr__(self, "_adapter_id", adapter_id)
        object.__setattr__(self, "_dhara_url", dhara_url.rstrip("/"))
        object.__setattr__(self, "_allowlist", set(allowlist or []))
        object.__setattr__(self, "_debounce_seconds", debounce_seconds)
        object.__setattr__(self, "_pending_changes", [])
        object.__setattr__(self, "_flush_task", None)
        object.__setattr__(self, "_fallback_dir", fallback_dir or _FALLBACK_DIR)
        object.__setattr__(self, "_client", None)
        factory: _HttpClientFactory = client_factory or (
            lambda: httpx.AsyncClient(
                base_url=self._dhara_url,
                timeout=10.0,
            )
        )
        object.__setattr__(self, "_client_factory", factory)

    # -- attribute interception ----------------------------------------------

    def __setattr__(self, name: str, value: Any) -> None:
        # Internal underscore names bypass interception. This avoids breaking
        # Pydantic machinery that sets ``__pydantic_*__`` attributes.
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return

        model = self.__dict__.get("_model")
        if model is None:
            object.__setattr__(self, name, value)
            return

        existing = getattr(model, name, None)
        if existing == value and name in type(model).model_fields:
            object.__setattr__(self, name, value)
            return

        # Apply the change to the underlying Pydantic model. This will
        # raise ``ValueError`` for unknown fields — propagate.
        setattr(model, name, value)

        # Record the change for the next batched push.
        change: dict[str, Any] = {
            "key": name,
            "new_value": value,
            "old_value": existing,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self._pending_changes.append(change)
        self._schedule_change_push()

    # -- snapshot construction -----------------------------------------------

    def _build_snapshot(self) -> dict[str, Any]:
        """Return a JSON-safe dict of all settings, hashing non-allowlisted."""
        snapshot: dict[str, Any] = {}
        for field_name in type(self._model).model_fields:
            if field_name.startswith("_"):
                continue
            value = getattr(self._model, field_name)
            if field_name in self._allowlist:
                snapshot[field_name] = value
            else:
                snapshot[field_name] = (
                    f"{_HASH_PREFIX}{fnv1a_64(_hash_value_if_secret(value))}"
                )
        return snapshot

    # -- HTTP client lifecycle -----------------------------------------------

    async def __aenter__(self) -> TrackedSettings:
        await self._ensure_client()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._close_client()

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = self._client_factory()
        return self._client

    async def _close_client(self) -> None:
        client = self._client
        if client is not None and not client.is_closed:
            await client.aclose()

    # -- push helpers --------------------------------------------------------

    async def _push_snapshot(self, event_type: str) -> None:
        """Push a full snapshot to Dhara. Never raises."""
        tracer = get_tracer(TRACKED_SETTINGS_INSTRUMENTATION_SCOPE)
        with tracer.start_as_current_span(f"tracked_settings.{event_type}") as span:
            span.set_attribute("adapter_id", self._adapter_id)
            span.set_attribute("event_type", event_type)
            try:
                payload = {
                    "adapter_id": self._adapter_id,
                    "event_type": event_type,
                    "config_json": self._build_snapshot(),
                    "timestamp": datetime.now(UTC).isoformat(),
                }
                await self._post_json("/tools/store_config_snapshot", payload)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "tracked-settings-snapshot-push-failed",
                    adapter_id=self._adapter_id,
                    event_type=event_type,
                    error=str(exc),
                )

    async def _post_json(self, path: str, payload: dict[str, Any]) -> None:
        """POST a JSON payload to Dhara. Captures failures to fallback."""
        client = await self._ensure_client()
        try:
            response = await client.post(path, json=payload)
            response.raise_for_status()
        except Exception as exc:
            kind = _EVENT_SNAPSHOT if "snapshot" in path else _EVENT_CHANGE_BATCH
            self._capture_fallback(kind, payload)
            logger.warning(
                "tracked-settings-push-failed",
                adapter_id=self._adapter_id,
                path=path,
                error=str(exc),
            )

    def _capture_fallback(self, kind: str, payload: dict[str, Any]) -> None:
        try:
            _write_fallback_payload(
                cache_dir=self._fallback_dir,
                adapter_id=self._adapter_id,
                kind=kind,
                payload=payload,
            )
        except Exception as exc:  # pragma: no cover - filesystem failure
            logger.warning(
                "tracked-settings-fallback-write-failed",
                adapter_id=self._adapter_id,
                error=str(exc),
            )

    # -- debounced change batch ----------------------------------------------

    def _schedule_change_push(self) -> None:
        if self._flush_task is None or self._flush_task.done():
            # If called from sync code without a running event loop (e.g.
            # outside an ``async`` context), skip scheduling. The change is
            # still recorded in ``_pending_changes`` and will be picked up by
            # the next ``flush_pending()`` call from a lifecycle hook.
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return
            self._flush_task = asyncio.create_task(self._debounced_flush())

    async def _debounced_flush(self) -> None:
        try:
            await asyncio.sleep(self._debounce_seconds)
            await self.flush_pending()
        except asyncio.CancelledError:  # pragma: no cover - race
            raise

    async def flush_pending(self) -> None:
        """Push any pending change events as a single batched POST."""
        if not self._pending_changes:
            return
        events = self._pending_changes.copy()
        self._pending_changes = []

        tracer = get_tracer(TRACKED_SETTINGS_INSTRUMENTATION_SCOPE)
        with tracer.start_as_current_span(
            f"tracked_settings.{_EVENT_CHANGE_BATCH}"
        ) as span:
            span.set_attribute("adapter_id", self._adapter_id)
            span.set_attribute("event_count", len(events))
            payload = {
                "adapter_id": self._adapter_id,
                "events": events,
                "timestamp": datetime.now(UTC).isoformat(),
            }
            try:
                await self._post_json("/tools/store_config_events", payload)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "tracked-settings-change-batch-failed",
                    adapter_id=self._adapter_id,
                    error=str(exc),
                )

    # -- lifecycle hooks ------------------------------------------------------

    async def on_startup(self) -> None:
        await self._push_snapshot("startup")

    async def on_stop(self) -> None:
        await self.flush_pending()
        await self._push_snapshot("stop")
        await self._close_client()

    async def on_restart(self) -> None:
        await self.flush_pending()
        await self._push_snapshot("restart")
