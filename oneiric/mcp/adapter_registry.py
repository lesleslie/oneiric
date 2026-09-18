"""Oneiric-native adapter registry (Phase 1 of Dhara MCP decomposition).

Mirrors the public interface of ``dhara.mcp.adapter_tools.AsyncAdapterRegistry``
(``store_adapter_async`` / ``get_adapter_async`` / ``list_adapters_async`` /
``list_adapter_versions_async`` / ``validate_adapter_async`` /
``check_adapter_health_async``) but persists to a local JSON file instead
of Dhara's PersistentDict shelve. This keeps Oneiric's MCP server
self-contained — adapters stored via these tools live in
``~/.oneiric/adapter_registry.json`` and do NOT require Dhara to be
running.

The Dhara ``Adapter`` model (version_history, health_status, env tag) is
preserved so existing callers ported from Dhara keep their shape
expectations.

Design follows the SubstrateStore pattern (oneiric/mcp/store.py):
- JSON-file persistence under a configurable root directory
- threading.Lock for concurrent-safe reads/writes
- dataclass-based state (no Pydantic — registry is internal-only)

The registry is intentionally simpler than Dhara's because Oneiric does
not need cross-process ACID transactions; the use case here is local
adapter discovery for the control plane. Phase 2 of the decomposition
will likely add a write-through to a shared substrate so other Bodai
components can read what Oneiric exposes.
"""

from __future__ import annotations

import importlib
import json
import logging
import operator
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _import_factory(factory_path: str) -> tuple[Any, Any]:
    """Import a factory path and return (module, class)."""
    module_path, class_name = factory_path.rsplit(".", 1)
    # nosem: python.lang.security.audit.non-literal-import.non-literal-import
    module = importlib.import_module(module_path)
    return module, getattr(module, class_name)


@dataclass
class AdapterRecord:
    """Persistent adapter record (mirrors Dhara Adapter schema)."""

    domain: str
    key: str
    provider: str
    version: str
    factory_path: str
    config: dict[str, Any] = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    env: str | None = None
    version_history: list[dict[str, Any]] = field(default_factory=list)
    health_status: str = "unknown"
    last_health_check: str | None = None
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    @property
    def adapter_id(self) -> str:
        return f"{self.domain}:{self.key}:{self.provider}"

    def update_version(
        self,
        *,
        new_version: str,
        changelog: str,
        factory_path: str,
        config: dict[str, Any],
        dependencies: list[str],
        capabilities: list[str],
        **metadata_updates: Any,
    ) -> None:
        """Append current state to history, then apply new version."""
        self.version_history.append(
            {
                "version": self.version,
                "updated_at": self.updated_at,
                "changelog": changelog,
                "state": {
                    "factory_path": self.factory_path,
                    "config": dict(self.config),
                    "capabilities": list(self.capabilities),
                    "dependencies": list(self.dependencies),
                },
            }
        )
        # Cap history at 10 entries (mirrors Dhara limit).
        if len(self.version_history) > 10:
            self.version_history.pop(0)
        self.version = new_version
        self.factory_path = factory_path
        self.config = dict(config)
        self.dependencies = list(dependencies)
        self.capabilities = list(capabilities)
        if metadata_updates:
            self.metadata = {**self.metadata, **metadata_updates}
        self.updated_at = _now_iso()

    def to_dict(self) -> dict[str, Any]:
        """Return the public dict shape (mirrors Dhara Adapter.to_dict)."""
        return {
            "schema_version": 1,
            "domain": self.domain,
            "key": self.key,
            "provider": self.provider,
            "version": self.version,
            "factory_path": self.factory_path,
            "config": self.config,
            "dependencies": self.dependencies,
            "capabilities": self.capabilities,
            "metadata": self.metadata,
            "env": self.env,
            "adapter_id": self.adapter_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "health_status": self.health_status,
            "last_health_check": self.last_health_check,
        }


class OneiricAdapterRegistry:
    """JSON-file backed adapter registry with the Dhara AsyncAdapterRegistry API.

    All async methods are coroutines (matching the Dhara interface so
    callers can swap implementations) but the underlying I/O is synchronous
    JSON. Because tool handlers run in async context, each public method
    releases the GIL via ``asyncio.to_thread`` so we don't block the event
    loop on a slow disk. The threading.Lock inside guarantees serialized
    reads/writes (same as SubstrateStore).
    """

    SCHEMA_VERSION = 1

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or (Path.home() / ".oneiric")
        self._path = self._root / "adapter_registry.json"
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._adapters: dict[str, AdapterRecord] = self._load()

    # ----- persistence -----

    def _load(self) -> dict[str, AdapterRecord]:
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        out: dict[str, AdapterRecord] = {}
        for adapter_id, entry in raw.items():
            if not isinstance(entry, dict):
                continue
            try:
                out[adapter_id] = AdapterRecord(
                    domain=entry["domain"],
                    key=entry["key"],
                    provider=entry["provider"],
                    version=entry.get("version", "1.0.0"),
                    factory_path=entry.get("factory_path", ""),
                    config=entry.get("config", {}),
                    dependencies=entry.get("dependencies", []),
                    capabilities=entry.get("capabilities", []),
                    metadata=entry.get("metadata", {}),
                    env=entry.get("env"),
                    version_history=entry.get("version_history", []),
                    health_status=entry.get("health_status", "unknown"),
                    last_health_check=entry.get("last_health_check"),
                    created_at=entry.get("created_at", _now_iso()),
                    updated_at=entry.get("updated_at", _now_iso()),
                )
            except KeyError:
                logger.warning(
                    "adapter_registry: skipping malformed entry %s", adapter_id
                )
        return out

    def _save(self) -> None:
        serialized = {
            aid: {
                "domain": rec.domain,
                "key": rec.key,
                "provider": rec.provider,
                "version": rec.version,
                "factory_path": rec.factory_path,
                "config": rec.config,
                "dependencies": rec.dependencies,
                "capabilities": rec.capabilities,
                "metadata": rec.metadata,
                "env": rec.env,
                "version_history": rec.version_history,
                "health_status": rec.health_status,
                "last_health_check": rec.last_health_check,
                "created_at": rec.created_at,
                "updated_at": rec.updated_at,
            }
            for aid, rec in self._adapters.items()
        }
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(serialized, indent=2, default=str))
        tmp.replace(self._path)

    # ----- async public API (mirrors Dhara AsyncAdapterRegistry) -----

    async def store_adapter_async(
        self,
        *,
        domain: str,
        key: str,
        provider: str,
        version: str,
        factory_path: str,
        config: dict[str, Any],
        dependencies: list[str],
        capabilities: list[str],
        metadata: dict[str, Any],
    ) -> str:
        """Store or update an adapter; returns adapter_id."""
        import asyncio

        def _do() -> str:
            with self._lock:
                adapter_id = f"{domain}:{key}:{provider}"
                existing = self._adapters.get(adapter_id)
                if existing is not None:
                    changelog = (
                        metadata.get("changelog", "Manual update")
                        if isinstance(metadata, dict)
                        else "Manual update"
                    )
                    extra_meta = (
                        {k: v for k, v in metadata.items() if k != "changelog"}
                        if isinstance(metadata, dict)
                        else {}
                    )
                    existing.update_version(
                        new_version=version,
                        changelog=changelog,
                        factory_path=factory_path,
                        config=config,
                        dependencies=dependencies,
                        capabilities=capabilities,
                        **extra_meta,
                    )
                else:
                    self._adapters[adapter_id] = AdapterRecord(
                        domain=domain,
                        key=key,
                        provider=provider,
                        version=version,
                        factory_path=factory_path,
                        config=dict(config),
                        dependencies=list(dependencies),
                        capabilities=list(capabilities),
                        metadata=dict(metadata) if metadata else {},
                    )
                self._save()
                return adapter_id

        return await asyncio.to_thread(_do)

    async def get_adapter_async(
        self,
        *,
        domain: str,
        key: str,
        provider: str | None = None,
        version: str | None = None,
    ) -> dict[str, Any] | None:
        """Retrieve an adapter (latest matching if no provider/version)."""
        import asyncio

        def _do() -> dict[str, Any] | None:
            with self._lock:
                if provider:
                    rec = self._adapters.get(f"{domain}:{key}:{provider}")
                    return rec.to_dict() if rec else None
                matches = [
                    rec.to_dict()
                    for aid, rec in self._adapters.items()
                    if aid.startswith(f"{domain}:{key}:")
                ]
                if not matches:
                    return None
                if version:
                    for match in matches:
                        if match["version"] == version:
                            return match
                    return None
                return matches[0]

        return await asyncio.to_thread(_do)

    async def list_adapters_async(
        self,
        *,
        domain: str | None = None,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        """List adapters with optional filters."""
        import asyncio

        def _do() -> list[dict[str, Any]]:
            with self._lock:
                results: list[dict[str, Any]] = []
                for rec in self._adapters.values():
                    payload = rec.to_dict()
                    if domain and payload["domain"] != domain:
                        continue
                    if category:
                        rec_category = (payload.get("metadata") or {}).get(
                            "category"
                        )
                        if rec_category != category:
                            continue
                    results.append(payload)
                return results

        return await asyncio.to_thread(_do)

    async def list_adapter_versions_async(
        self,
        *,
        domain: str,
        key: str,
        provider: str,
    ) -> list[dict[str, Any]]:
        """Return version history + current version for an adapter."""
        import asyncio

        def _do() -> list[dict[str, Any]]:
            with self._lock:
                rec = self._adapters.get(f"{domain}:{key}:{provider}")
                if rec is None:
                    return []
                history: list[dict[str, Any]] = [
                    {
                        "version": entry["version"],
                        "updated_at": entry["updated_at"],
                        "changelog": entry.get("changelog", ""),
                    }
                    for entry in rec.version_history
                ]
                history.append(
                    {
                        "version": rec.version,
                        "updated_at": rec.updated_at,
                        "changelog": "Current version",
                    }
                )
                history.sort(key=operator.itemgetter("updated_at"), reverse=True)
                return history

        return await asyncio.to_thread(_do)

    async def validate_adapter_async(
        self,
        *,
        domain: str,
        key: str,
        provider: str,
        version: str | None = None,
    ) -> dict[str, Any]:
        """Validate an adapter's factory import + deps + capabilities."""
        adapter = await self.get_adapter_async(
            domain=domain, key=key, provider=provider, version=version
        )
        if not adapter:
            return {
                "valid": False,
                "errors": [f"Adapter not found: {domain}:{key}:{provider}"],
                "warnings": [],
            }

        errors: list[str] = []
        warnings: list[str] = []

        try:
            _import_factory(adapter["factory_path"])
        except ImportError as exc:
            errors.append(f"Factory path not importable: {exc}")
        except AttributeError as exc:
            errors.append(f"Factory class not found: {exc}")
        except (OSError, TypeError, ValueError) as exc:
            errors.append(f"Factory validation error: {exc}")

        for dep in adapter.get("dependencies", []):
            parts = dep.split(":")[:2] if ":" in dep else (None, dep)
            dep_domain, dep_key = parts[0], parts[1]
            dep_adapter = await self.get_adapter_async(
                domain=dep_domain or domain,
                key=dep_key,
            )
            if not dep_adapter:
                warnings.append(f"Dependency not found: {dep}")

        if not adapter.get("capabilities"):
            warnings.append("No capabilities declared")

        return {"valid": not errors, "errors": errors, "warnings": warnings}

    async def check_adapter_health_async(
        self,
        *,
        domain: str,
        key: str,
        provider: str,
    ) -> dict[str, Any]:
        """Probe adapter health by importing its factory; records result."""
        import asyncio

        def _do() -> dict[str, Any]:
            with self._lock:
                rec = self._adapters.get(f"{domain}:{key}:{provider}")
                if rec is None:
                    return {
                        "healthy": False,
                        "error": "Adapter not found",
                        "last_check": None,
                    }
                rec.last_health_check = _now_iso()
                try:
                    _import_factory(rec.factory_path)
                    rec.health_status = "healthy"
                    healthy_payload: dict[str, Any] = {
                        "healthy": True,
                        "last_check": rec.last_health_check,
                        "status": rec.health_status,
                    }
                    self._save()
                    return healthy_payload
                except Exception as exc:  # noqa: BLE001
                    rec.health_status = "unhealthy"
                    unhealthy_payload: dict[str, Any] = {
                        "healthy": False,
                        "last_check": rec.last_health_check,
                        "status": rec.health_status,
                        "error": str(exc),
                    }
                    self._save()
                    return unhealthy_payload

        return await asyncio.to_thread(_do)

    async def count_async(self) -> int:
        """Return the number of stored adapters."""
        import asyncio

        def _do() -> int:
            with self._lock:
                return len(self._adapters)

        return await asyncio.to_thread(_do)


__all__ = ["AdapterRecord", "OneiricAdapterRegistry"]