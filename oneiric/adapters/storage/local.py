from __future__ import annotations

import asyncio
import builtins
import os
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path

from pydantic import BaseModel, Field

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class LocalStorageSettings(BaseModel):
    base_path: Path = Field(
        default=Path("./.oneiric_storage"),
        description="Directory where blobs are persisted.",
    )
    create_parents: bool = Field(
        default=True,
        description="Whether to create parent directories automatically at init time.",
    )


class LocalStorageAdapter:
    metadata = AdapterMetadata(
        category="storage",
        provider="local",
        factory="oneiric.adapters.storage.local: LocalStorageAdapter",
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
            try:
                self._base_path.mkdir(parents=True, exist_ok=True)
            except (PermissionError, OSError) as exc:
                # Serverless / read-only-filesystem deployments cannot
                # create a writable base. Surface a clear lifecycle
                # error with a fix hint. ADR 015 v4 §7.
                raise LifecycleError(
                    "local-storage-readonly-filesystem"
                ) from exc
        elif not self._base_path.exists():
            raise LifecycleError("storage-base-path-missing")

        # Defense in depth: even if mkdir() succeeded (e.g. directory
        # already existed), the filesystem may now be read-only. Check
        # writability before declaring init() successful.
        import os

        if not os.access(self._base_path, os.W_OK):
            raise LifecycleError(
                "local-storage-readonly-filesystem"
            )

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

    def save_stream(
        self,
        key: str,
        chunk_reader: Callable[[], Iterator[bytes]],
        *,
        metadata: dict[str, str] | None = None,
    ) -> int:
        """Stream chunks to a local file with atomic temp-file rename.

        Per ADR 015 v4 Phase 3 spec: ``chunk_reader`` is a zero-arg callable
        that returns a fresh ``Iterator[bytes]`` each call. The local path
        writes chunks to a sibling temp file, fsyncs, then ``os.replace``s
        into the final key. Failure mid-write leaves no partial target
        file — only the temp file, which is unlinked in the cleanup path.

        ``metadata`` is accepted for cross-adapter symmetry with S3/GCS
        but is not persisted on the local filesystem. Callers that need
        metadata should serialize it alongside the blob (e.g. a sibling
        ``.metadata.json`` sidecar).
        """
        path = self._resolve_path(key)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
        )
        bytes_written = 0
        try:
            with os.fdopen(fd, "wb") as tmp:
                for chunk in chunk_reader():
                    if chunk:
                        tmp.write(chunk)
                        bytes_written += len(chunk)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp_name, path)
            self._logger.info(
                "storage-stream-save",
                key=key,
                bytes=bytes_written,
                metadata_keys=len(metadata) if metadata else 0,
            )
        except BaseException:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass
            raise
        return bytes_written

    def load_stream(
        self,
        key: str,
        *,
        chunk_size: int = 65536,
    ) -> Callable[[], Iterator[bytes]]:
        """Return a callable that yields local file body chunks.

        The returned callable produces a fresh ``Iterator[bytes]`` on
        each invocation, so the caller can iterate the body multiple
        times. Raises ``LifecycleError`` if the key does not exist or
        resolves outside the base path.
        """
        path = self._resolve_path(key)
        if not path.exists():
            raise LifecycleError("local-storage-key-not-found")

        def reader() -> Iterator[bytes]:
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    yield chunk

        return reader

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
