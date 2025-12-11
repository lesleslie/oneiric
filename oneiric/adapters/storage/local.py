"""Filesystem-backed storage adapter."""

from __future__ import annotations

import asyncio
import builtins
from pathlib import Path

from pydantic import BaseModel, Field

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class LocalStorageSettings(BaseModel):
    """Settings for the local filesystem storage adapter."""

    base_path: Path = Field(
        default=Path("./.oneiric_storage"),
        description="Directory where blobs are persisted.",
    )
    create_parents: bool = Field(
        default=True,
        description="Whether to create parent directories automatically at init time.",
    )


class LocalStorageAdapter:
    """Simple filesystem-backed blob storage."""

    metadata = AdapterMetadata(
        category="storage",
        provider="local",
        factory="oneiric.adapters.storage.local:LocalStorageAdapter",
        capabilities=["blob", "stream", "delete"],
        stack_level=20,
        priority=200,
        source=CandidateSource.LOCAL_PKG,
        owner="Data Platform",
        requires_secrets=False,
        settings_model=LocalStorageSettings,
    )

    def __init__(self, settings: LocalStorageSettings | None = None) -> None:
        self._settings = settings or LocalStorageSettings()
        self._base_path = self._settings.base_path.expanduser().resolve()
        self._logger = get_logger("adapter.storage.local").bind(
            domain="adapter",
            key="storage",
            provider="local",
        )
        self._lock = asyncio.Lock()

    async def init(self) -> None:
        if self._settings.create_parents:
            self._base_path.mkdir(parents=True, exist_ok=True)
        elif not self._base_path.exists():
            raise LifecycleError("storage-base-path-missing")
        self._logger.info(
            "adapter-init", adapter="local-storage", base=str(self._base_path)
        )

    async def health(self) -> bool:
        return self._base_path.exists() and self._base_path.is_dir()

    async def cleanup(self) -> None:
        self._logger.info("adapter-cleanup-complete", adapter="local-storage")

    async def save(self, key: str, data: bytes) -> str:
        path = self._resolve_path(key)
        async with self._lock:
            await asyncio.to_thread(self._write_bytes, path, data)
        return str(path)

    async def read(self, key: str) -> bytes | None:
        path = self._resolve_path(key)
        if not path.exists():
            return None
        async with self._lock:
            return await asyncio.to_thread(path.read_bytes)

    async def delete(self, key: str) -> None:
        path = self._resolve_path(key)
        if not path.exists():
            return
        async with self._lock:
            await asyncio.to_thread(path.unlink)

    async def list(self, prefix: str | None = None) -> builtins.list[str]:
        async with self._lock:
            return await asyncio.to_thread(self._list_relative_paths, prefix or "")

    async def exists(self, key: str) -> bool:
        return self._resolve_path(key).exists()

    def _resolve_path(self, key: str) -> Path:
        normalized = key.strip("/")
        path = (self._base_path / normalized).resolve()
        if not str(path).startswith(str(self._base_path)):
            raise LifecycleError("path-traversal-detected")
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _write_bytes(self, path: Path, data: bytes) -> None:
        path.write_bytes(data)

    def _list_relative_paths(self, prefix: str) -> builtins.list[str]:
        results: list[str] = []
        base_str = str(self._base_path)
        for item in self._base_path.rglob("*"):
            if not item.is_file():
                continue
            rel = str(item)[len(base_str) + 1 :]
            if prefix and not rel.startswith(prefix):
                continue
            results.append(rel)
        return sorted(results)
