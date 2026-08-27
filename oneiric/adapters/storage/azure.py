from __future__ import annotations

import tempfile
from collections.abc import Callable, Iterator
from typing import Any

from pydantic import BaseModel, Field

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class AzureBlobStorageSettings(BaseModel):
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
    metadata = AdapterMetadata(
        category="storage",
        provider="azure-blob",
        factory="oneiric.adapters.storage.azure: AzureBlobStorageAdapter",
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
        except OSError as exc:  # pragma: no cover - network errors
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

    async def exists(self, key: str) -> bool:
        """Return True iff ``key`` exists in the container.

        Uses ``get_blob_properties`` (cheap HEAD) and translates
        ``ResourceNotFoundError`` into ``False``. Other exceptions
        propagate so transient Azure errors surface to the caller.
        """
        blob_client = self._ensure_container().get_blob_client(key)
        try:
            await blob_client.get_blob_properties()
        except Exception as exc:
            if self._is_not_found(exc):
                return False
            raise
        return True

    async def save_stream(
        self,
        key: str,
        chunk_reader: Callable[[], Iterator[bytes]],
        *,
        metadata: dict[str, str] | None = None,
    ) -> str:
        """Stream a chunked payload to Azure Blob Storage via a SpooledTemporaryFile.

        Per ADR 015 v4 Phase 3 spec: ``chunk_reader`` is a sync
        ``Callable[[], Iterator[bytes]]`` so callers can iterate the body
        from any source (tar pipe, file reader) without binding it to
        the event loop. Chunks are drained into a ``SpooledTemporaryFile``
        (rolls to disk past 64 MiB) and then uploaded in a single
        ``upload_blob`` call. ``length`` is supplied so the SDK can pick
        the optimal chunk strategy for the body size. Returns the
        storage ``key``.
        """
        try:
            from azure.storage.blob import ContentSettings
        except ModuleNotFoundError as exc:  # pragma: no cover - defensive
            raise LifecycleError("azure-storage-blob-missing") from exc

        bytes_written = 0
        with tempfile.SpooledTemporaryFile(max_size=64 * 1024 * 1024) as spool:
            for chunk in chunk_reader():
                if not chunk:
                    continue
                spool.write(chunk)
                bytes_written += len(chunk)
            spool.seek(0)
            upload_kwargs: dict[str, Any] = {
                "blob_type": "BlockBlob",
                "overwrite": True,
                "length": bytes_written,
                "content_settings": ContentSettings(
                    content_type=self._settings.default_content_type,
                ),
            }
            if metadata:
                upload_kwargs["metadata"] = dict(metadata)
            await (
                self._ensure_container()
                .get_blob_client(key)
                .upload_blob(spool, **upload_kwargs)
            )

        self._logger.info(
            "azure-stream-save",
            key=key,
            bytes=bytes_written,
            metadata_keys=len(metadata) if metadata else 0,
        )
        return key

    def load_stream(
        self,
        key: str,
        *,
        chunk_size: int = 65536,
    ) -> Callable[[], Iterator[bytes]]:
        """Return a callable yielding Azure blob body chunks.

        The ``azure.storage.blob.aio`` client used elsewhere in this
        adapter cannot yield a streaming body synchronously, so the
        streaming load path lazily builds a sync
        ``azure.storage.blob.BlobServiceClient`` (mirroring the S3
        adapter's ``_build_sync_client`` pattern) and the returned
        callable performs a fresh ``download_blob().readall()`` into a
        ``SpooledTemporaryFile`` on every invocation — that way each
        iteration of the body is independent and the file handle is
        closed deterministically when the iterator is exhausted.

        Raises ``LifecycleError`` if the blob is missing so callers see
        the same error shape as the local + S3 adapters.
        """
        sync_client = self._build_sync_client()
        container_name = self._settings.container
        blob_client = sync_client.get_container_client(container_name).get_blob_client(
            key
        )
        try:
            blob_client.get_blob_properties()
        except Exception as exc:
            if self._is_not_found(exc):
                raise LifecycleError("azure-storage-key-not-found") from exc
            raise

        def reader() -> Iterator[bytes]:
            with tempfile.SpooledTemporaryFile(max_size=64 * 1024 * 1024) as spool:
                downloader = blob_client.download_blob()
                spool.write(downloader.readall())
                spool.seek(0)
                while True:
                    chunk = spool.read(chunk_size)
                    if not chunk:
                        break
                    yield chunk

        return reader

    def _build_sync_client(self) -> Any:
        """Lazily build a sync ``azure.storage.blob.BlobServiceClient``.

        The async ``aio`` client cannot yield a streaming body
        synchronously, so the streaming load path needs a sync
        counterpart. We reuse the same connection settings
        (connection_string or account_url + credential) so callers see
        consistent auth config across both clients.
        """
        cached = getattr(self, "_sync_client", None)
        if cached is not None:
            return cached
        try:
            from azure.storage.blob import BlobServiceClient
        except ModuleNotFoundError as exc:  # pragma: no cover - defensive
            raise LifecycleError("azure-storage-blob-missing") from exc

        connection_string = self._settings.connection_string
        account_url = self._settings.account_url
        credential = self._settings.credential
        if connection_string:
            self._sync_client = BlobServiceClient.from_connection_string(
                connection_string
            )
        elif account_url:
            if not credential:
                raise LifecycleError("azure-storage-credential-required")
            self._sync_client = BlobServiceClient(
                account_url=account_url, credential=credential
            )
        else:
            raise LifecycleError("azure-storage-client-misconfigured")
        return self._sync_client

    async def list(self, prefix: str = "") -> list[str]:  # ty: ignore[invalid-type-form] — ty resolves `list` to the method in scope
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
        return bool(isinstance(message, str) and "404" in message)
