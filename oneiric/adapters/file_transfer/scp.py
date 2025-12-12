"""SCP file transfer adapter."""

from __future__ import annotations

import os
import posixpath
import shlex
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, SecretStr

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class SCPFileTransferSettings(BaseModel):
    """Configuration for SCP transfers."""

    host: str
    username: str
    password: SecretStr | None = None
    private_key: str | None = Field(
        default=None, description="PEM private key content or path"
    )
    port: int = 22
    known_hosts: str | None = None
    root_path: str = Field(default=".", description="Base directory for transfers")


class SCPFileTransferAdapter:
    """Upload/download files via SCP using asyncssh."""

    metadata = AdapterMetadata(
        category="file_transfer",
        provider="scp",
        factory="oneiric.adapters.file_transfer.scp:SCPFileTransferAdapter",
        capabilities=["upload", "download", "delete", "list"],
        stack_level=20,
        priority=320,
        source=CandidateSource.LOCAL_PKG,
        owner="Infra",
        requires_secrets=True,
        settings_model=SCPFileTransferSettings,
    )

    def __init__(
        self,
        settings: SCPFileTransferSettings,
        *,
        connection: Any | None = None,
        client_factory: Callable[[SCPFileTransferSettings], Awaitable[Any]]
        | None = None,
        asyncssh_module: Any | None = None,
    ) -> None:
        self._settings = settings
        self._conn = connection
        self._client_factory = client_factory
        self._asyncssh = asyncssh_module
        self._owns_conn = connection is None
        self._logger = get_logger("adapter.file_transfer.scp").bind(
            domain="adapter",
            key="file_transfer",
            provider="scp",
        )

    async def init(self) -> None:
        """Establish SSH connection for SCP operations."""

        if self._conn:
            self._logger.info("scp-adapter-init-reuse-connection")
            return

        if self._client_factory:
            self._conn = await self._client_factory(self._settings)
            self._owns_conn = True
            self._logger.info("scp-adapter-init-factory")
            return

        if self._asyncssh is None:
            try:
                import asyncssh  # type: ignore
            except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
                raise LifecycleError(
                    "asyncssh-required: install asyncssh to use SCPFileTransferAdapter"
                ) from exc

            self._asyncssh = asyncssh

        connect_kwargs: dict[str, Any] = {
            "host": self._settings.host,
            "username": self._settings.username,
            "port": self._settings.port,
            "known_hosts": self._settings.known_hosts,
        }
        if self._settings.password:
            connect_kwargs["password"] = self._settings.password.get_secret_value()
        if self._settings.private_key:
            connect_kwargs["client_keys"] = [self._settings.private_key]

        self._conn = await self._asyncssh.connect(**connect_kwargs)
        self._owns_conn = True
        self._logger.info("scp-adapter-init")

    async def cleanup(self) -> None:
        if self._conn and self._owns_conn:
            await self._conn.close(wait_closed=True)
        self._conn = None
        self._logger.info("scp-adapter-cleanup")

    async def health(self) -> bool:
        try:
            await self._run_command(
                f"ls -1 {shlex.quote(self._resolve_remote_path('.'))}"
            )
            return True
        except LifecycleError:
            return False

    async def upload(self, remote_path: str, data: bytes) -> None:
        conn = self._ensure_connection()
        asyncssh = self._ensure_asyncssh()
        target = self._resolve_remote_path(remote_path)
        tmp_path = self._write_temp_file(data)
        try:
            await asyncssh.scp(str(tmp_path), (conn, target))
        except Exception as exc:  # pragma: no cover - network path
            self._logger.error("scp-upload-failed", path=target, error=str(exc))
            raise LifecycleError("scp-upload-failed") from exc
        finally:
            self._unlink_quietly(tmp_path)

    async def download(self, remote_path: str) -> bytes:
        conn = self._ensure_connection()
        asyncssh = self._ensure_asyncssh()
        target = self._resolve_remote_path(remote_path)
        tmp_path = self._create_temp_path()
        try:
            await asyncssh.scp((conn, target), str(tmp_path))
            return tmp_path.read_bytes()
        except Exception as exc:  # pragma: no cover - network path
            self._logger.error("scp-download-failed", path=target, error=str(exc))
            raise LifecycleError("scp-download-failed") from exc
        finally:
            self._unlink_quietly(tmp_path)

    async def delete(self, remote_path: str) -> bool:
        target = self._resolve_remote_path(remote_path)
        if not await self._path_exists(target):
            return False
        await self._run_command(f"rm -f {shlex.quote(target)}")
        return True

    async def list(self, prefix: str | None = None) -> list[str]:
        base = prefix or self._settings.root_path or "."
        target = self._resolve_remote_path(base)
        output = await self._run_command(f"ls -1 {shlex.quote(target)}")
        return [line.strip() for line in output.splitlines() if line.strip()]

    async def _run_command(self, command: str) -> str:
        conn = self._ensure_connection()
        try:
            result = await conn.run(command, check=False)
        except Exception as exc:  # pragma: no cover - network path
            self._logger.error("scp-command-failed", command=command, error=str(exc))
            raise LifecycleError("scp-command-failed") from exc

        if getattr(result, "exit_status", 0) != 0:
            self._logger.error(
                "scp-command-nonzero",
                command=command,
                status=getattr(result, "exit_status", None),
                stderr=getattr(result, "stderr", ""),
            )
            raise LifecycleError("scp-command-failed")

        return getattr(result, "stdout", "")

    def _resolve_remote_path(self, remote_path: str) -> str:
        if remote_path.startswith("/"):
            return posixpath.normpath(remote_path)
        base = self._settings.root_path or "."
        return posixpath.normpath(posixpath.join(base, remote_path))

    def _ensure_connection(self) -> Any:
        if not self._conn:
            raise LifecycleError("scp-connection-not-initialized")
        return self._conn

    def _ensure_asyncssh(self) -> Any:
        if not self._asyncssh:
            raise LifecycleError("scp-asyncssh-not-available")
        return self._asyncssh

    @staticmethod
    def _write_temp_file(data: bytes) -> Path:
        fd, name = tempfile.mkstemp()
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        return Path(name)

    @staticmethod
    def _create_temp_path() -> Path:
        fd, name = tempfile.mkstemp()
        os.close(fd)
        return Path(name)

    @staticmethod
    def _unlink_quietly(path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    async def _path_exists(self, remote_path: str) -> bool:
        conn = self._ensure_connection()
        try:
            result = await conn.run(f"test -e {shlex.quote(remote_path)}", check=False)
        except Exception as exc:  # pragma: no cover - network path
            self._logger.error("scp-exists-failed", path=remote_path, error=str(exc))
            raise LifecycleError("scp-command-failed") from exc
        return getattr(result, "exit_status", 0) == 0
