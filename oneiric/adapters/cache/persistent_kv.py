"""File-backed persistent KV and time-series cache adapter.

Ported from :mod:`dhara.mcp.kv_timeseries` (which used ``PersistentDict``/
``PersistentList`` over a Dhara ``Connection``). Oneiric has no equivalent of
Dhara's persistent collections, so this adapter serializes the entire store
as JSON to a single file on disk. Whole-file writes are acceptable for
low-throughput metadata stores (component endpoints, OTel config caches,
fitness signal windows) — exactly the workloads Dhara's KV layer served.

Implements:
- put/get with optional TTL
- list_prefix scan over KV keys
- record_time_series / query_time_series (with retention cutoff)
- aggregate_patterns across all stored time-series entries

The storage format is::

    {
        "kv":          {"key": <value>, ...},
        "kv_ttl":      {"key": <expires_at_unix>, ...},
        "time_series": {"metric_type:entity_id": [{"ts": "iso", ...}, ...], ...}
    }

Atomicity: every mutation is serialized to a temp file in the same directory
and then ``os.replace``-d into place so a crash mid-write leaves the prior
snapshot intact.
"""

from __future__ import annotations

import asyncio
import json
import operator
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, Field

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class PersistentKVCacheSettings(BaseModel):
    storage_path: str = Field(
        default="~/.oneiric/persistent_kv",
        description="File path for the JSON-backed KV store. The file is created "
        "on init() if it does not exist; the parent directory is created with "
        "parents=True.",
    )
    retention_days: int = Field(
        default=60,
        ge=1,
        description="Retention window (days) applied to time-series queries and "
        "writes. Entries older than now - retention_days are dropped on insert.",
    )
    auto_commit: bool = Field(
        default=True,
        description="When True, every mutation immediately persists to disk via an "
        "atomic write. Set False to batch updates; callers must then invoke "
        "commit() explicitly.",
    )
    key_ttl_seconds: int | None = Field(
        default=None,
        ge=1,
        description="Optional default TTL (seconds) applied to every put() call "
        "when no per-call ttl is provided. Mirrors MemoryCacheSettings.default_ttl "
        "semantics; per-call ttl always wins.",
    )


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except TypeError, ValueError:
        return None


def _purge_ts_list(
    entries: list[dict[str, Any]], cutoff: datetime
) -> list[dict[str, Any]]:
    if not entries:
        return entries
    kept: list[dict[str, Any]] = []
    for item in entries:
        ts_raw = item.get("ts") if isinstance(item, dict) else None
        ts_dt = _parse_iso(ts_raw) if isinstance(ts_raw, str) else None
        if ts_dt is None or ts_dt >= cutoff:
            kept.append(item)
    return kept


class PersistentKVCacheAdapter:
    """File-backed KV + time-series store, ported from Dhara's persistent objects."""

    metadata = AdapterMetadata(
        category="cache",
        provider="persistent_kv",
        factory="oneiric.adapters.cache.persistent_kv:PersistentKVCacheAdapter",
        capabilities=["cache", "kv", "time_series"],
        stack_level=20,
        priority=300,
        source=CandidateSource.LOCAL_PKG,
        owner="Storage",
        requires_secrets=False,
        settings_model=PersistentKVCacheSettings,
    )

    _SCHEMA_VERSION = 1
    _KV_KEY = "kv"
    _TTL_KEY = "kv_ttl"
    _TS_KEY = "time_series"

    def __init__(self, settings: PersistentKVCacheSettings | None = None) -> None:
        self._settings = settings or PersistentKVCacheSettings()
        self._storage_path = Path(self._settings.storage_path).expanduser()
        self._kv: dict[str, Any] = {}
        self._kv_ttl: dict[str, int] = {}
        self._time_series: dict[str, list[dict[str, Any]]] = {}
        self._lock = asyncio.Lock()
        self._initialized = False
        self._logger = get_logger("adapter.cache.persistent_kv").bind(
            domain="adapter",
            key="cache",
            provider="persistent_kv",
        )

    @property
    def settings(self) -> PersistentKVCacheSettings:
        return self._settings

    @property
    def storage_path(self) -> Path:
        return self._storage_path

    async def init(self) -> None:
        async with self._lock:
            await self._init_locked()
        self._logger.info(
            "adapter-init",
            adapter="persistent-kv-cache",
            storage_path=str(self._storage_path),
        )

    async def _init_locked(self) -> None:
        if self._initialized:
            return
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        if self._storage_path.exists():
            await self._load_locked()
        else:
            self._kv = {}
            self._kv_ttl = {}
            self._time_series = {}
            await self._write_locked()
        self._initialized = True

    async def _load_locked(self) -> None:
        try:
            raw = self._storage_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            self._kv = {}
            self._kv_ttl = {}
            self._time_series = {}
            return
        except OSError as exc:
            self._logger.error(
                "persistent-kv-load-failed",
                path=str(self._storage_path),
                error=str(exc),
            )
            self._kv = {}
            self._kv_ttl = {}
            self._time_series = {}
            return
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            self._logger.error(
                "persistent-kv-corrupt",
                path=str(self._storage_path),
                error=str(exc),
            )
            self._kv = {}
            self._kv_ttl = {}
            self._time_series = {}
            return
        if not isinstance(payload, dict):
            self._kv = {}
            self._kv_ttl = {}
            self._time_series = {}
            return
        self._kv = dict(payload.get(self._KV_KEY) or {})
        self._kv_ttl = {
            str(k): int(v)
            for k, v in (payload.get(self._TTL_KEY) or {}).items()
            if isinstance(v, (int, float))
        }
        raw_ts = payload.get(self._TS_KEY) or {}
        if isinstance(raw_ts, dict):
            self._time_series = cast(
                dict[str, list[dict[str, Any]]],
                {
                    str(k): list(v) if isinstance(v, list) else []
                    for k, v in raw_ts.items()
                },
            )
        else:
            self._time_series = {}

    async def _write_locked(self) -> None:
        if not self._settings.auto_commit:
            return
        await self._flush_locked()

    async def _flush_locked(self) -> None:
        payload = {
            "schema_version": self._SCHEMA_VERSION,
            self._KV_KEY: self._kv,
            self._TTL_KEY: self._kv_ttl,
            self._TS_KEY: self._time_series,
        }
        tmp_path = self._storage_path.with_suffix(self._storage_path.suffix + ".tmp")
        data = json.dumps(payload, default=str, sort_keys=True)
        # Use a sync write under the asyncio lock — the file is small and the
        # I/O is bounded, so running it inline avoids adding executor indirection
        # for every commit. MemoryCacheAdapter uses the same inline-write pattern.
        tmp_path.write_text(data, encoding="utf-8")
        os.replace(tmp_path, self._storage_path)

    async def health(self) -> bool:
        async with self._lock:
            if not self._initialized:
                return False
            try:
                # Touch the directory to confirm writability without mutating state.
                parent = self._storage_path.parent
                parent.mkdir(parents=True, exist_ok=True)
                probe = parent / f".{self._storage_path.name}.health"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink(missing_ok=True)
            except OSError:
                return False
            return True

    async def close(self) -> None:
        async with self._lock:
            if self._initialized:
                await self._flush_locked()
            self._initialized = False
            self._kv = {}
            self._kv_ttl = {}
            self._time_series = {}
        self._logger.info("adapter-cleanup-complete", adapter="persistent-kv-cache")

    async def commit(self) -> None:
        """Force-flush the in-memory snapshot to disk. No-op when auto_commit is on."""
        async with self._lock:
            await self._flush_locked()

    def _effective_ttl(self, ttl: int | None) -> int | None:
        if ttl is not None:
            if ttl <= 0:
                raise ValueError("persistent-kv-negative-ttl")
            return int(ttl)
        default = self._settings.key_ttl_seconds
        return default

    def _is_expired(self, key: str) -> bool:
        expires_at = self._kv_ttl.get(key)
        if expires_at is None:
            return False
        return int(time.time()) >= int(expires_at)

    async def put(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
    ) -> dict[str, Any]:
        async with self._lock:
            await self._init_locked()
            self._kv[key] = value
            effective = self._effective_ttl(ttl)
            if effective is not None:
                self._kv_ttl[key] = int(time.time()) + effective
            elif key in self._kv_ttl:
                del self._kv_ttl[key]
            await self._write_locked()
        return {"ok": True, "key": key}

    async def get(self, key: str) -> dict[str, Any]:
        async with self._lock:
            await self._init_locked()
            if key not in self._kv:
                return {"ok": True, "key": key, "value": None}
            if self._is_expired(key):
                self._kv.pop(key, None)
                self._kv_ttl.pop(key, None)
                await self._write_locked()
                return {"ok": True, "key": key, "value": None, "expired": True}
            return {"ok": True, "key": key, "value": self._kv[key]}

    async def list_prefix(self, prefix: str) -> list[dict[str, Any]]:
        """Return every non-expired KV entry whose key starts with ``prefix``."""
        async with self._lock:
            await self._init_locked()
            now = int(time.time())
            results: list[dict[str, Any]] = []
            for key, value in self._kv.items():
                if not key.startswith(prefix):
                    continue
                expires_at = self._kv_ttl.get(key)
                if expires_at is not None and now >= int(expires_at):
                    continue
                results.append({"key": key, "value": value})
            return results

    async def delete(self, key: str) -> bool:
        async with self._lock:
            await self._init_locked()
            existed = key in self._kv
            self._kv.pop(key, None)
            self._kv_ttl.pop(key, None)
            if existed:
                await self._write_locked()
            return existed

    @staticmethod
    def _ts_key(metric_type: str, entity_id: str) -> str:
        return f"{metric_type}:{entity_id}"

    async def record_time_series(
        self,
        metric_type: str,
        entity_id: str,
        record: dict[str, Any] | None = None,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        async with self._lock:
            await self._init_locked()
            key = self._ts_key(metric_type, entity_id)
            ts = timestamp or _utcnow().isoformat()
            payload: dict[str, Any] = {"ts": ts}
            if record:
                payload.update(record)
            series = self._time_series.setdefault(key, [])
            series.append(payload)
            cutoff = _utcnow() - timedelta(days=self._settings.retention_days)
            self._time_series[key] = _purge_ts_list(series, cutoff)
            await self._write_locked()
        return {"ok": True, "metric_type": metric_type, "entity_id": entity_id}

    async def query_time_series(
        self,
        metric_type: str,
        entity_id: str,
        start_date: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        async with self._lock:
            await self._init_locked()
            cutoff = _utcnow() - timedelta(days=self._settings.retention_days)
            start_dt = _parse_iso(start_date) if start_date else None
            series = self._time_series.get(self._ts_key(metric_type, entity_id), [])
            results: list[dict[str, Any]] = []
            for item in series:
                if not isinstance(item, dict):
                    continue
                ts_raw = item.get("ts")
                ts_dt = _parse_iso(ts_raw) if isinstance(ts_raw, str) else None
                if ts_dt is None or ts_dt < cutoff:
                    continue
                if start_dt is not None and ts_dt is not None and ts_dt < start_dt:
                    continue
                results.append(item)
            if limit is not None and limit >= 0:
                results = results[-int(limit) :]
            return results

    async def aggregate_patterns(
        self,
        start_date: str,
        min_occurrences: int = 2,
    ) -> list[dict[str, Any]]:
        async with self._lock:
            await self._init_locked()
            cutoff = _utcnow() - timedelta(days=self._settings.retention_days)
            start_dt = _parse_iso(start_date) if start_date else None
            counts: dict[str, int] = {}
            for series in self._time_series.values():
                for item in series:
                    if not isinstance(item, dict):
                        continue
                    ts_raw = item.get("ts")
                    ts_dt = _parse_iso(ts_raw) if isinstance(ts_raw, str) else None
                    if ts_dt is None or ts_dt < cutoff:
                        continue
                    if start_dt is not None and ts_dt is not None and ts_dt < start_dt:
                        continue
                    pattern = (
                        item.get("pattern")
                        or item.get("issue_type")
                        or item.get("event")
                        or item.get("category")
                    )
                    if not pattern:
                        continue
                    counts[str(pattern)] = counts.get(str(pattern), 0) + 1
            results = [
                {"pattern": pattern, "count": count}
                for pattern, count in counts.items()
                if count >= min_occurrences
            ]
            results.sort(key=operator.itemgetter("count"), reverse=True)
            return results
