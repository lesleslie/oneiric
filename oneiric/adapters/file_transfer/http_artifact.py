"""HTTP artifact transfer adapter."""

from __future__ import annotations

import hashlib
from typing import Any

import httpx
from pydantic import AnyHttpUrl, BaseModel, Field

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class HTTPArtifactSettings(BaseModel):
    """Configuration for HTTP artifact downloads."""

    base_url: AnyHttpUrl | None = Field(
        default=None, description="Optional base URL prepended to artifact paths."
    )
    timeout: float = Field(default=30.0, ge=1.0)
    verify_tls: bool = True


class HTTPArtifactAdapter:
    """Download artifacts via HTTP(S) with optional checksum validation."""

    metadata = AdapterMetadata(
        category="file_transfer",
        provider="http",
        factory="oneiric.adapters.file_transfer.http_artifact:HTTPArtifactAdapter",
        capabilities=["download"],
        stack_level=15,
        priority=350,
        source=CandidateSource.LOCAL_PKG,
        owner="Platform Core",
        requires_secrets=False,
        settings_model=HTTPArtifactSettings,
    )

    def __init__(
        self,
        settings: HTTPArtifactSettings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._owns_client = client is None
        self._logger = get_logger("adapter.file_transfer.http").bind(
            domain="adapter",
            key="file_transfer",
            provider="http",
        )

    async def init(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._settings.timeout,
                verify=self._settings.verify_tls,
                base_url=str(self._settings.base_url)
                if self._settings.base_url
                else None,
            )
            self._owns_client = True
        self._logger.info("http-artifact-init")

    async def cleanup(self) -> None:
        if self._client and self._owns_client:
            await self._client.aclose()
        self._client = None
        self._logger.info("http-artifact-cleanup")

    async def health(self) -> bool:
        if self._settings.base_url is None:
            return True
        try:
            response = await self._ensure_client().get("", timeout=5)
            return response.status_code < 500
        except httpx.HTTPError:  # pragma: no cover - network path
            return False

    async def download(self, path_or_url: str, *, sha256: str | None = None) -> bytes:
        """Download artifact bytes."""
        client = self._ensure_client()
        url = path_or_url
        if self._settings.base_url and not path_or_url.startswith("http"):
            url = path_or_url.lstrip("/")
        try:
            response = await client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            self._logger.error("http-artifact-download-failed", url=url, error=str(exc))
            raise LifecycleError("http-artifact-download-failed") from exc
        content = response.content
        if sha256:
            digest = hashlib.sha256(content).hexdigest()
            if digest.lower() != sha256.lower():
                raise LifecycleError("http-artifact-checksum-mismatch")
        return content

    async def download_to_file(
        self, path_or_url: str, destination: Any, *, sha256: str | None = None
    ) -> None:
        data = await self.download(path_or_url, sha256=sha256)
        with open(destination, "wb") as handle:
            handle.write(data)

    def _ensure_client(self) -> httpx.AsyncClient:
        if not self._client:
            raise LifecycleError("http-artifact-client-not-initialized")
        return self._client
