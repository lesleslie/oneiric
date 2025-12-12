"""HTTPS upload adapter."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import httpx
from pydantic import AnyHttpUrl, BaseModel, Field, SecretStr

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class HTTPSUploadSettings(BaseModel):
    """Configuration for HTTPS uploads."""

    base_url: AnyHttpUrl | None = Field(
        default=None,
        description="Optional base URL prepended to relative upload paths.",
    )
    method: str = Field(
        default="PUT",
        description="HTTP method used for uploads (PUT or POST).",
    )
    timeout: float = Field(default=30.0, ge=1.0)
    verify_tls: bool = True
    default_headers: dict[str, str] = Field(default_factory=dict)
    auth_token: SecretStr | None = Field(
        default=None,
        description="Optional token injected into Authorization headers.",
    )
    auth_scheme: str = Field(
        default="Bearer",
        description="Prefix used for the Authorization header (e.g., Bearer).",
    )
    auth_header: str = Field(
        default="Authorization",
        description="Header used for auth tokens.",
    )


class HTTPSUploadAdapter:
    """Upload artifacts over HTTPS using httpx."""

    metadata = AdapterMetadata(
        category="file_transfer",
        provider="https-upload",
        factory="oneiric.adapters.file_transfer.http_upload:HTTPSUploadAdapter",
        capabilities=["upload"],
        stack_level=15,
        priority=360,
        source=CandidateSource.LOCAL_PKG,
        owner="Platform Core",
        requires_secrets=False,
        settings_model=HTTPSUploadSettings,
    )

    def __init__(
        self,
        settings: HTTPSUploadSettings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._owns_client = client is None
        self._logger = get_logger("adapter.file_transfer.https_upload").bind(
            domain="adapter",
            key="file_transfer",
            provider="https-upload",
        )

    async def init(self) -> None:
        if self._client is None:
            base_url = str(self._settings.base_url) if self._settings.base_url else None
            self._client = httpx.AsyncClient(
                timeout=self._settings.timeout,
                verify=self._settings.verify_tls,
                base_url=base_url,
            )
            self._owns_client = True
        self._logger.info("https-upload-init")

    async def cleanup(self) -> None:
        if self._client and self._owns_client:
            await self._client.aclose()
        self._client = None
        self._logger.info("https-upload-cleanup")

    async def health(self) -> bool:
        if self._settings.base_url is None:
            return True
        try:
            response = await self._ensure_client().get("", timeout=5.0)
            return response.status_code < 500
        except httpx.HTTPError:  # pragma: no cover - network path
            return False

    async def upload(
        self,
        path_or_url: str,
        data: bytes,
        *,
        content_type: str | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> str:
        client = self._ensure_client()
        headers = dict(self._settings.default_headers)
        if self._settings.auth_token:
            token = self._settings.auth_token.get_secret_value()
            scheme = (self._settings.auth_scheme or "").strip()
            prefix = f"{scheme} " if scheme else ""
            headers.setdefault(self._settings.auth_header, f"{prefix}{token}")
        if content_type:
            headers.setdefault("Content-Type", content_type)
        if extra_headers:
            headers.update(extra_headers)

        request_target = path_or_url
        if self._settings.base_url and not path_or_url.startswith("http"):
            request_target = path_or_url.lstrip("/")

        try:
            response = await client.request(
                self._settings.method.upper(),
                request_target,
                content=data,
                headers=headers,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            self._logger.error(
                "https-upload-failed", url=request_target, error=str(exc)
            )
            raise LifecycleError("https-upload-failed") from exc

        location = response.headers.get("Location") or str(response.request.url)
        return location

    async def upload_file(
        self,
        path_or_url: str,
        file_path: str | Path,
        *,
        content_type: str | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> str:
        data = Path(file_path).read_bytes()
        return await self.upload(
            path_or_url,
            data,
            content_type=content_type,
            extra_headers=extra_headers,
        )

    def _ensure_client(self) -> httpx.AsyncClient:
        if not self._client:
            raise LifecycleError("https-upload-client-not-initialized")
        return self._client
