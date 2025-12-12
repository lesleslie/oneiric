"""SFTP file transfer adapter."""

from __future__ import annotations

import io
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field, SecretStr

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class SFTPFileTransferSettings(BaseModel):
    """Configuration for SFTP connections."""

    host: str
    username: str
    password: SecretStr | None = None
    private_key: str | None = Field(
        default=None, description="PEM private key content or path"
    )
    port: int = 22
    known_hosts: str | None = None
    root_path: str = "."


class SFTPFileTransferAdapter:
    """Upload/download files via SFTP (asyncssh)."""

    metadata = AdapterMetadata(
        category="file_transfer",
        provider="sftp",
        factory="oneiric.adapters.file_transfer.sftp:SFTPFileTransferAdapter",
        capabilities=["upload", "download", "delete", "list"],
        stack_level=20,
        priority=330,
        source=CandidateSource.LOCAL_PKG,
        owner="Infra",
        requires_secrets=True,
        settings_model=SFTPFileTransferSettings,
    )

    def __init__(
        self,
        settings: SFTPFileTransferSettings,
        *,
        client_factory: Callable[[SFTPFileTransferSettings], Any] | None = None,
        connection: Any | None = None,
        sftp_client: Any | None = None,
    ) -> None:
        self._settings = settings
        self._client_factory = client_factory
        self._conn = connection
        self._sftp = sftp_client
        self._owns_conn = connection is None
        self._logger = get_logger("adapter.file_transfer.sftp").bind(
            domain="adapter",
            key="file_transfer",
            provider="sftp",
        )

    async def init(self) -> None:
        """Establish SFTP connection."""
        if self._sftp:
            self._logger.info("sftp-adapter-init-reuse-client")
            return

        if self._client_factory:
            self._conn, self._sftp = await self._client_factory(self._settings)
            self._owns_conn = True
            self._logger.info("sftp-adapter-init-factory")
            return

        try:
            import asyncssh  # type: ignore
        except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
            raise LifecycleError(
                "asyncssh-required: install asyncssh to use SFTPFileTransferAdapter"
            ) from exc

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

        self._conn = await asyncssh.connect(**connect_kwargs)
        self._sftp = await self._conn.start_sftp_client()
        if self._settings.root_path:
            await self._sftp.chdir(self._settings.root_path)
        self._owns_conn = True
        self._logger.info("sftp-adapter-init")

    async def cleanup(self) -> None:
        """Close connection."""
        if self._owns_conn and self._sftp:
            await self._sftp.exit()
        if self._owns_conn and self._conn:
            await self._conn.close(wait_closed=True)
        self._conn = None
        self._sftp = None
        self._logger.info("sftp-adapter-cleanup")

    async def health(self) -> bool:
        client = self._ensure_client()
        try:
            await client.listdir(".")
            return True
        except Exception as exc:  # pragma: no cover - network path
            self._logger.warning("sftp-health-failed", error=str(exc))
            return False

    async def upload(self, remote_path: str, data: bytes) -> None:
        client = self._ensure_client()
        try:
            buf = io.BytesIO(data)
            await client.put(buf, remote_path)
        except Exception as exc:
            self._logger.error("sftp-upload-failed", path=remote_path, error=str(exc))
            raise LifecycleError("sftp-upload-failed") from exc

    async def download(self, remote_path: str) -> bytes:
        client = self._ensure_client()
        try:
            buf = io.BytesIO()
            await client.get(remote_path, buf)
            return buf.getvalue()
        except Exception as exc:
            self._logger.error("sftp-download-failed", path=remote_path, error=str(exc))
            raise LifecycleError("sftp-download-failed") from exc

    async def delete(self, remote_path: str) -> bool:
        client = self._ensure_client()
        try:
            await client.remove(remote_path)
            return True
        except FileNotFoundError:
            return False
        except Exception as exc:
            self._logger.error("sftp-delete-failed", path=remote_path, error=str(exc))
            raise LifecycleError("sftp-delete-failed") from exc

    async def list(self, prefix: str | None = None) -> list[str]:
        client = self._ensure_client()
        base = prefix or "."
        try:
            entries = await client.listdir(base)
            return [str(entry.filename) for entry in entries]
        except Exception as exc:
            self._logger.error("sftp-list-failed", prefix=base, error=str(exc))
            raise LifecycleError("sftp-list-failed") from exc

    def _ensure_client(self) -> Any:
        if not self._sftp:
            raise LifecycleError("sftp-client-not-initialized")
        return self._sftp
