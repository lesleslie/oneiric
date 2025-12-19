"""Google Cloud Storage adapter."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.adapters.storage.utils import is_not_found_error
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class GCSStorageSettings(BaseModel):
    """Configuration for the GCS adapter."""

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
    """Google Cloud Storage adapter with async-friendly wrappers."""

    metadata = AdapterMetadata(
        category="storage",
        provider="gcs",
        factory="oneiric.adapters.storage.gcs:GCSStorageAdapter",
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
                from google.cloud import storage
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
        except Exception as exc:  # pragma: no cover - network errors
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

    async def list(self, prefix: str = "") -> list[str]:
        bucket = self._ensure_bucket()
        return await asyncio.to_thread(self._list_names, bucket, prefix)

    def _ensure_bucket(self) -> Any:
        if not self._bucket:
            raise LifecycleError("gcs-bucket-not-initialized")
        return self._bucket

    def _list_names(self, bucket: Any, prefix: str) -> list[str]:  # type: ignore[valid-type]
        """List blob names from bucket with the given prefix."""
        blobs: Any = bucket.list_blobs(prefix=prefix)
        result: list[str] = [blob.name for blob in blobs]
        return result
