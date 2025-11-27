"""HTTP adapter backed by aiohttp.ClientSession."""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urljoin

import aiohttp
from aiohttp import ClientResponse

from .httpx import HTTPClientSettings
from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class AioHTTPAdapter:
    """Async HTTP adapter using aiohttp."""

    metadata = AdapterMetadata(
        category="http",
        provider="aiohttp",
        factory="oneiric.adapters.http.aiohttp:AioHTTPAdapter",
        capabilities=["http", "rest", "stream"],
        stack_level=12,
        priority=225,
        source=CandidateSource.LOCAL_PKG,
        owner="Platform Core",
        requires_secrets=False,
        settings_model=HTTPClientSettings,
    )

    def __init__(self, settings: HTTPClientSettings | None = None, *, session: Optional[aiohttp.ClientSession] = None) -> None:
        self._settings = settings or HTTPClientSettings()
        self._session: Optional[aiohttp.ClientSession] = session
        self._owns_session = session is None
        self._logger = get_logger("adapter.http.aiohttp").bind(
            domain="adapter",
            key="http",
            provider="aiohttp",
        )

    async def init(self) -> None:
        if not self._session:
            timeout = aiohttp.ClientTimeout(total=self._settings.timeout)
            base_url = str(self._settings.base_url) if self._settings.base_url else None
            self._session = aiohttp.ClientSession(
                base_url=base_url,
                timeout=timeout,
                headers=self._settings.headers or None,
            )
        else:
            self._session.headers.update(self._settings.headers)
        self._logger.info("adapter-init", adapter="aiohttp", base_url=str(self._settings.base_url or ""))

    async def health(self) -> bool:
        if not self._settings.base_url:
            return True
        try:
            response = await self.get(self._settings.healthcheck_path)
            return response.status < 500
        except Exception as exc:  # pragma: no cover - defensive log path
            self._logger.warning("adapter-health-failed", error=str(exc))
            return False

    async def cleanup(self) -> None:
        if self._session and self._owns_session:
            await self._session.close()
            self._session = None
        self._logger.info("adapter-cleanup-complete", adapter="aiohttp")

    async def request(self, method: str, url: str, **kwargs: Any) -> ClientResponse:
        session = self._ensure_session()
        target = self._resolve_url(url)
        if "timeout" not in kwargs:
            kwargs["timeout"] = aiohttp.ClientTimeout(total=self._settings.timeout)
        if "ssl" not in kwargs:
            kwargs["ssl"] = self._settings.verify
        return await session.request(method, target, **kwargs)

    async def get(self, url: str, **kwargs: Any) -> ClientResponse:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> ClientResponse:
        return await self.request("POST", url, **kwargs)

    def _ensure_session(self) -> aiohttp.ClientSession:
        if not self._session:
            raise LifecycleError("aiohttp-session-not-initialized")
        return self._session

    def _resolve_url(self, url: str) -> str:
        if self._settings.base_url and not url.lower().startswith(("http://", "https://")):
            return urljoin(str(self._settings.base_url), url)
        return url
