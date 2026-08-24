from __future__ import annotations

import asyncio
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.adapters.storage.error_detection import is_not_found_error
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class GCSStorageSettings(BaseModel):
    bucket: str = Field(description="Name of the target GCS bucket.")
    project: str | None = Field(default=None, description="GCP project ID.")
    credentials_file: Path | None = Field(
        default=None,
        description="Optional path to a service account JSON file.",
    )
    default_content_type: str | None = Field(
        default="application/octet-stream",
        description="Fallback content type used when uploads omit content_type.",
    )


class GCSStorageAdapter:
    metadata = AdapterMetadata(
        category="storage",
        provider="gcs",
        factory="oneiric.adapters.storage.gcs: GCSStorageAdapter",
        capabilities=["blob", "stream", "delete", "bucket"],
        stack_level=30,
        priority=450,
        source=CandidateSource.LOCAL_PKG,
        owner="Data Platform",
        requires_secrets=True,
        settings_model=GCSStorageSettings,
    )

    def __init__(
        self, settings: GCSStorageSettings, *, client: Any | None = None
    ) -> None:
        self._settings = settings
        self._client = client
        self._bucket: Any | None = None
        self._logger = get_logger("adapter.storage.gcs").bind(
            domain="adapter",
            key="storage",
            provider="gcs",
            bucket=settings.bucket,
        )

    async def init(self) -> None:
        if self._client is None:
            try:
                from google.cloud import storage  # type: ignore[attr-defined]
                from google.oauth2 import service_account
            except ModuleNotFoundError as exc:  # pragma: no cover - defensive
                raise LifecycleError("google-cloud-storage-missing") from exc
            client_kwargs: dict[str, Any] = {}
            if self._settings.credentials_file:
                credentials: Any = (
                    service_account.Credentials.from_service_account_file(
                        str(self._settings.credentials_file)
                    )
                )
                client_kwargs["credentials"] = credentials
            if self._settings.project:
                client_kwargs["project"] = self._settings.project
            self._client = storage.Client(**client_kwargs)
        self._bucket = self._client.bucket(self._settings.bucket)
        self._logger.info("adapter-init", adapter="gcs-storage")

    async def health(self) -> bool:
        bucket = self._ensure_bucket()
        try:
            await asyncio.to_thread(bucket.exists)
            return True
        except OSError as exc:  # pragma: no cover - network errors
            self._logger.warning("adapter-health-error", error=str(exc))
            return False

    async def cleanup(self) -> None:
        self._client = None
        self._bucket = None
        self._logger.info("adapter-cleanup-complete", adapter="gcs-storage")

    async def upload(
        self, key: str, data: bytes, *, content_type: str | None = None
    ) -> None:
        blob = self._ensure_bucket().blob(key)
        await asyncio.to_thread(
            blob.upload_from_string,
            data,
            content_type=content_type or self._settings.default_content_type,
        )

    async def download(self, key: str) -> bytes | None:
        blob = self._ensure_bucket().blob(key)
        try:
            return await asyncio.to_thread(blob.download_as_bytes)
        except Exception as exc:
            if is_not_found_error(exc, codes={404}, messages=("404", "Not Found")):
                return None
            raise

    async def delete(self, key: str) -> None:
        try:
            await asyncio.to_thread(self._ensure_bucket().blob(key).delete)
        except Exception as exc:
            if not is_not_found_error(exc, codes={404}, messages=("404", "Not Found")):
                raise

    async def exists(self, key: str) -> bool:
        """Return True iff ``key`` exists in the bucket.

        Uses the GCS client's ``Blob.exists()`` (cheap HEAD against the
        object). Translates ``NotFound`` into ``False``.
        """
        blob = self._ensure_bucket().blob(key)
        try:
            return bool(await asyncio.to_thread(blob.exists))
        except Exception as exc:
            if is_not_found_error(exc, codes={404}, messages=("404", "Not Found")):
                return False
            raise

    async def save_stream(
        self,
        key: str,
        chunk_reader: Callable[[], Iterator[bytes]],
        *,
        metadata: dict[str, str] | None = None,
    ) -> str:
        """Stream a chunked payload to GCS via a SpooledTemporaryFile.

        Per ADR 015 v4 Phase 3 spec: ``chunk_reader`` is a sync
        ``Callable[[], Iterator[bytes]]`` so callers can iterate the body
        from any source (tar pipe, file reader) without binding it to
        the event loop. Chunks are drained into a ``SpooledTemporaryFile``
        (rolls to disk past 64 MiB) and then uploaded in one
        ``upload_from_file`` call. Metadata, if provided, is attached to
        the ``Blob`` before the upload so it lands in the object's
        custom-metadata map on the GCS side. Returns the storage ``key``.
        """
        blob = self._ensure_bucket().blob(key)
        if metadata:
            blob.metadata = dict(metadata)

        bytes_written = 0
        with tempfile.SpooledTemporaryFile(max_size=64 * 1024 * 1024) as spool:
            for chunk in chunk_reader():
                if not chunk:
                    continue
                spool.write(chunk)
                bytes_written += len(chunk)
            spool.seek(0)
            await asyncio.to_thread(
                blob.upload_from_file,
                spool,
                rewind=True,
                content_type=self._settings.default_content_type,
            )

        self._logger.info(
            "gcs-stream-save",
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
        """Return a callable yielding GCS object body chunks.

        The Google Cloud Storage SDK is fully synchronous, so the load
        path does not need a separate async/sync bridge. We probe
        existence up-front (mirroring the ``LifecycleError`` contract
        used by the local + S3 adapters) and the returned callable
        performs a fresh ``download_to_file`` into a
        ``SpooledTemporaryFile`` on every invocation — that way each
        iteration of the body is independent and the file handle is
        closed deterministically when the iterator is exhausted.
        """
        blob = self._ensure_bucket().blob(key)
        try:
            exists = bool(blob.exists())
        except Exception as exc:
            if is_not_found_error(exc, codes={404}, messages=("404", "Not Found")):
                raise LifecycleError("gcs-storage-key-not-found") from exc
            raise
        if not exists:
            raise LifecycleError("gcs-storage-key-not-found")

        def reader() -> Iterator[bytes]:
            with tempfile.SpooledTemporaryFile(max_size=64 * 1024 * 1024) as spool:
                blob.download_to_file(spool)
                spool.seek(0)
                while True:
                    chunk = spool.read(chunk_size)
                    if not chunk:
                        break
                    yield chunk

        return reader

    async def list(self, prefix: str = "") -> list[str]:  # ty: ignore[invalid-type-form] — ty resolves `list` to the method in scope
        bucket = self._ensure_bucket()
        return await asyncio.to_thread(self._list_names, bucket, prefix)

    def _ensure_bucket(self) -> Any:
        if not self._bucket:
            raise LifecycleError("gcs-bucket-not-initialized")
        return self._bucket

    def _list_names(self, bucket: Any, prefix: str) -> list[str]:  # ty: ignore[invalid-type-form]
        blobs: Any = bucket.list_blobs(prefix=prefix)
        result: list[str] = [blob.name for blob in blobs]
        return result
