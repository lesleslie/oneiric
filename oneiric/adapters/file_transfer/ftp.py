"""FTP file transfer adapter."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field, SecretStr

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class FTPFileTransferSettings(BaseModel):
    """Configuration for FTP/SFTP connections."""

    host: str
    username: str
    password: SecretStr
    port: int = 21
    ssl: bool = False
    root_path: str = "/"
    timeout: float = Field(default=10.0, ge=0.5)


class FTPFileTransferAdapter:
    """Upload/download files via FTP (aioftp)."""

    metadata = AdapterMetadata(
        category="file_transfer",
        provider="ftp",
        factory="oneiric.adapters.file_transfer.ftp:FTPFileTransferAdapter",
        capabilities=["upload", "download", "delete", "list"],
        stack_level=20,
        priority=340,
        source=CandidateSource.LOCAL_PKG,
        owner="Infra",
        requires_secrets=True,
        settings_model=FTPFileTransferSettings,
    )

    def __init__(
        self,
        settings: FTPFileTransferSettings,
        *,
        client: Any | None = None,
        client_factory: Callable[[FTPFileTransferSettings], Any] | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._client_factory = client_factory
        self._owns_client = client is None
        self._logger = get_logger("adapter.file_transfer.ftp").bind(
            domain="adapter",
            key="file_transfer",
            provider="ftp",
        )

    async def init(self) -> None:
        """Connect to FTP server."""
        if self._client:
            self._logger.info("ftp-adapter-init-reuse-client")
            return
        if self._client_factory:
            self._client = self._client_factory(self._settings)
            self._owns_client = True
            self._logger.info("ftp-adapter-init-factory")
            return
        try:
            import aioftp  # type: ignore
        except ModuleNotFoundError as exc:  # pragma: no cover - optional path
            raise LifecycleError(
                "aioftp-required: install aioftp to use FTPFileTransferAdapter"
            ) from exc

        self._client = aioftp.ClientSession(
            self._settings.host,
            self._settings.port,
            user=self._settings.username,
            password=self._settings.password.get_secret_value(),
            ssl=self._settings.ssl,
            socket_timeout=self._settings.timeout,
        )
        await self._client.connect()
        await self._client.login()
        if self._settings.root_path:
            await self._client.change_directory(self._settings.root_path)
        self._logger.info("ftp-adapter-init")

    async def cleanup(self) -> None:
        """Close connection."""
        if self._client and self._owns_client:
            try:
                await self._client.quit()
            except Exception:  # pragma: no cover - network cleanup path
                pass
        self._client = None
        self._logger.info("ftp-adapter-cleanup")

    async def health(self) -> bool:
        client = self._ensure_client()
        try:
            await client.list(self._settings.root_path or ".")
            return True
        except Exception as exc:  # pragma: no cover - network path
            self._logger.warning("ftp-health-failed", error=str(exc))
            return False

    async def upload(self, remote_path: str, data: bytes) -> None:
        client = self._ensure_client()
        try:
            async with client.upload_stream(remote_path) as stream:
                await stream.write(data)
        except Exception as exc:
            self._logger.error("ftp-upload-failed", path=remote_path, error=str(exc))
            raise LifecycleError("ftp-upload-failed") from exc

    async def download(self, remote_path: str) -> bytes:
        client = self._ensure_client()
        try:
            chunks: list[bytes] = []
            async with client.download_stream(remote_path) as stream:
                async for chunk in stream.iter_by_block():
                    chunks.append(chunk)
            return b"".join(chunks)
        except Exception as exc:
            self._logger.error("ftp-download-failed", path=remote_path, error=str(exc))
            raise LifecycleError("ftp-download-failed") from exc

    async def delete(self, remote_path: str) -> bool:
        client = self._ensure_client()
        try:
            await client.remove_file(remote_path)
            return True
        except FileNotFoundError:
            return False
        except Exception as exc:
            self._logger.error("ftp-delete-failed", path=remote_path, error=str(exc))
            raise LifecycleError("ftp-delete-failed") from exc

    async def list(self, prefix: str | None = None) -> list[str]:
        client = self._ensure_client()
        try:
            entries: list[str] = []
            base = prefix or self._settings.root_path or "."
            async for path, _ in client.list(base):
                entries.append(str(path))
            return entries
        except Exception as exc:
            self._logger.error("ftp-list-failed", prefix=prefix, error=str(exc))
            raise LifecycleError("ftp-list-failed") from exc

    def _ensure_client(self) -> Any:
        if not self._client:
            raise LifecycleError("ftp-client-not-initialized")
        return self._client
