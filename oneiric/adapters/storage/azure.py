"""Azure Blob Storage adapter."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class AzureBlobStorageSettings(BaseModel):
    """Configuration for the Azure Blob adapter."""

    container: str = Field(description="Target Azure Blob container name.")
    connection_string: str | None = Field(
        default=None,
        description="Optional storage connection string used to build the client.",
    )
    account_url: str | None = Field(
        default=None,
        description="Account URL (https://<account>.blob.core.windows.net). Required when no connection string is provided.",
    )
    credential: str | None = Field(
        default=None,
        description="Account key or SAS token used with account_url instantiation.",
    )
    default_content_type: str = Field(
        default="application/octet-stream",
        description="Fallback content type for uploads when one is not provided.",
    )


class AzureBlobStorageAdapter:
    """Async Azure Blob Storage adapter powered by azure-storage-blob."""

    metadata = AdapterMetadata(
        category="storage",
        provider="azure-blob",
        factory="oneiric.adapters.storage.azure:AzureBlobStorageAdapter",
        capabilities=["blob", "stream", "delete", "container"],
        stack_level=28,
        priority=425,
        source=CandidateSource.LOCAL_PKG,
        owner="Data Platform",
        requires_secrets=True,
        settings_model=AzureBlobStorageSettings,
    )

    def __init__(
        self,
        settings: AzureBlobStorageSettings,
        *,
        client: Any | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._container_client: Any | None = None
        self._logger = get_logger("adapter.storage.azure").bind(
            domain="adapter",
            key="storage",
            provider="azure-blob",
            container=settings.container,
        )

    async def init(self) -> None:
        if self._client is None:
            connection_string = self._settings.connection_string
            account_url = self._settings.account_url
            credential = self._settings.credential
            try:
                from azure.storage.blob.aio import BlobServiceClient
            except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
                raise LifecycleError("azure-storage-blob-missing") from exc

            if connection_string:
                self._client = BlobServiceClient.from_connection_string(
                    connection_string
                )
            elif account_url:
                if not credential:
                    raise LifecycleError("azure-storage-credential-required")
                self._client = BlobServiceClient(
                    account_url=account_url, credential=credential
                )
            else:
                raise LifecycleError("azure-storage-client-misconfigured")

        self._container_client = self._client.get_container_client(
            self._settings.container
        )
        await self._container_client.exists()
        self._logger.info("adapter-init", adapter="azure-blob-storage")

    async def health(self) -> bool:
        container = self._ensure_container()
        try:
            return await container.exists()
        except Exception as exc:  # pragma: no cover - network errors
            self._logger.warning("adapter-health-error", error=str(exc))
            return False

    async def cleanup(self) -> None:
        if self._container_client and hasattr(self._container_client, "close"):
            await self._container_client.close()
        if self._client and hasattr(self._client, "close"):
            await self._client.close()
        self._container_client = None
        self._client = None
        self._logger.info("adapter-cleanup-complete", adapter="azure-blob-storage")

    async def upload(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
    ) -> None:
        blob = self._ensure_container().get_blob_client(key)
        await blob.upload_blob(
            data,
            overwrite=True,
            content_type=content_type or self._settings.default_content_type,
        )

    async def download(self, key: str) -> bytes | None:
        blob = self._ensure_container().get_blob_client(key)
        try:
            return await (await blob.download_blob()).readall()
        except Exception as exc:
            if self._is_not_found(exc):
                return None
            raise

    async def delete(self, key: str) -> None:
        try:
            await self._ensure_container().get_blob_client(key).delete_blob()
        except Exception as exc:
            if not self._is_not_found(exc):
                raise

    async def list(self, prefix: str = "") -> list[str]:
        container = self._ensure_container()
        items: list[str] = []
        async for blob in container.list_blobs(name_starts_with=prefix):
            name = getattr(blob, "name", None)
            if isinstance(name, str):
                items.append(name)
        return items

    def _ensure_container(self) -> Any:
        if not self._container_client:
            raise LifecycleError("azure-storage-container-not-initialized")
        return self._container_client

    def _is_not_found(self, exc: Exception) -> bool:
        code = getattr(exc, "status_code", None)
        if code == 404:
            return True
        error_code = getattr(exc, "error_code", None)
        if isinstance(error_code, str) and error_code.lower() == "blobnotfound":
            return True
        message = getattr(exc, "message", None)
        if isinstance(message, str) and "404" in message:
            return True
        return False
