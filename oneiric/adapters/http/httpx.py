"""HTTP adapter backed by httpx.AsyncClient."""

from __future__ import annotations

from typing import Any, Dict, Optional

import httpx
from pydantic import AnyHttpUrl, BaseModel, Field

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class HTTPClientSettings(BaseModel):
    base_url: Optional[AnyHttpUrl] = Field(
        default=None,
        description="Optional base URL used for relative requests and health checks.",
    )
    timeout: float = Field(
        default=10.0,
        ge=0.1,
        description="Request timeout in seconds.",
    )
    verify: bool = Field(
        default=True,
        description="Whether to verify TLS certificates.",
    )
    headers: Dict[str, str] = Field(
        default_factory=dict,
        description="Default headers merged into each request.",
    )
    healthcheck_path: str = Field(
        default="/",
        description="Relative path to hit during health checks when base_url is configured.",
    )


class HTTPClientAdapter:
    metadata = AdapterMetadata(
        category="http",
        provider="httpx",
        factory="oneiric.adapters.http.httpx:HTTPClientAdapter",
        capabilities=["http", "rest", "otlp"],
        stack_level=10,
        priority=200,
        source=CandidateSource.LOCAL_PKG,
        owner="Platform Core",
        requires_secrets=False,
        settings_model=HTTPClientSettings,
    )

    def __init__(self, settings: HTTPClientSettings | None = None, *, transport: Optional[httpx.AsyncBaseTransport] = None) -> None:
        self._settings = settings or HTTPClientSettings()
        self._transport = transport
        self._client: Optional[httpx.AsyncClient] = None
        self._logger = get_logger("adapter.http.httpx").bind(
            domain="adapter",
            key="http",
            provider="httpx",
        )

    async def init(self) -> None:
        timeout = httpx.Timeout(self._settings.timeout)
        base_url = str(self._settings.base_url) if self._settings.base_url else ""
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            verify=self._settings.verify,
            headers=self._settings.headers,
            transport=self._transport,
        )
        self._logger.info("adapter-init", adapter="httpx", base_url=str(self._settings.base_url or ""))

    async def health(self) -> bool:
        if not self._client or not self._settings.base_url:
            return True
        try:
            response = await self._client.get(self._settings.healthcheck_path, timeout=self._settings.timeout)
            return response.status_code < 500
        except httpx.HTTPError as exc:
            self._logger.warning("adapter-health-failed", error=str(exc))
            return False

    async def cleanup(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
        self._logger.info("adapter-cleanup-complete", adapter="httpx")

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        client = self._ensure_client()
        return await client.request(method, url, **kwargs)

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        client = self._ensure_client()
        return await client.get(url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        client = self._ensure_client()
        return await client.post(url, **kwargs)

    def _ensure_client(self) -> httpx.AsyncClient:
        if not self._client:
            raise LifecycleError("httpx-client-not-initialized")
        return self._client
