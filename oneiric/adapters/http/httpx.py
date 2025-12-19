"""HTTP adapter backed by httpx.Client (supports async shim when needed)."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

import httpx
from pydantic import Field

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.http_helpers import observed_http_request
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.observability import inject_trace_context
from oneiric.core.resolution import CandidateSource
from oneiric.core.settings_mixins import BaseURLSettings


class HTTPClientSettings(BaseURLSettings):
    timeout: float = Field(
        default=10.0,
        ge=0.1,
        description="Request timeout in seconds.",
    )
    verify: bool = Field(
        default=True,
        description="Whether to verify TLS certificates.",
    )
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="Default headers merged into each request.",
    )
    healthcheck_path: str = Field(
        default="/",
        description="Relative path to hit during health checks when base_url is configured.",
    )


class _AsyncClientShim:
    """Async-friendly wrapper for httpx.Client when AsyncClient is unavailable."""

    def __init__(
        self,
        *,
        base_url: str | None,
        timeout: float,
        verify: bool,
        headers: dict[str, str] | None,
        transport: Any,
    ) -> None:
        client_kwargs: dict[str, Any] = {}
        if base_url:
            client_kwargs["url"] = base_url
        if headers:
            client_kwargs["headers"] = headers
        if transport:
            client_kwargs["transport"] = transport

        self._client = httpx.Client(**client_kwargs)
        self._timeout = timeout
        self._verify = verify

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        return await asyncio.to_thread(self._client.request, method, url, **kwargs)

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await asyncio.to_thread(self._client.get, url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await asyncio.to_thread(self._client.post, url, **kwargs)

    async def aclose(self) -> None:
        await asyncio.to_thread(self._client.close)


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

    def __init__(
        self,
        settings: HTTPClientSettings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings or HTTPClientSettings()
        self._transport = transport
        self._client: Any | None = None
        self._logger = get_logger("adapter.http.httpx").bind(
            domain="adapter",
            key="http",
            provider="httpx",
        )

    async def init(self) -> None:
        """Initialise AsyncClient with optional base URL + defaults."""
        async_client_cls: type[Any] = (
            getattr(httpx, "AsyncClient", None) or _AsyncClientShim
        )
        client_kwargs: dict[str, Any] = {
            "timeout": self._settings.timeout,
            "verify": self._settings.verify,
        }
        if self._settings.base_url:
            client_kwargs["base_url"] = str(self._settings.base_url)
        if self._settings.headers:
            client_kwargs["headers"] = self._settings.headers
        if self._transport:
            client_kwargs["transport"] = self._transport

        self._client = async_client_cls(**client_kwargs)
        self._logger.info(
            "adapter-init",
            adapter="httpx",
            base_url=str(self._settings.base_url or ""),
        )

    async def health(self) -> bool:
        """Run a lightweight GET when base_url is configured."""
        if not self._client:
            return False
        if not self._settings.base_url:
            return True
        try:
            response = await self._client.get(self._settings.healthcheck_path)
            return response.status_code < 500
        except httpx.HTTPError as exc:
            self._logger.warning("adapter-health-failed", error=str(exc))
            return False

    async def cleanup(self) -> None:
        """Dispose AsyncClient (or mocked equivalent)."""
        if self._client is None:
            return
        close_method = getattr(self._client, "aclose", None)
        if callable(close_method):
            maybe_coro = close_method()
            if inspect.isawaitable(maybe_coro):
                await maybe_coro
        elif hasattr(self._client, "close"):
            close_callable = getattr(self._client, "close")
            if callable(close_callable):
                close_callable()
        self._client = None
        self._logger.info("adapter-cleanup-complete", adapter="httpx")

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        client = self._ensure_client()
        caller = getattr(client, "request", None)
        return await self._request(method, url, caller=caller, **kwargs)

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        client = self._ensure_client()
        get_fn = getattr(client, "get", None)
        caller = (
            (lambda _method, target, **opts: get_fn(target, **opts))
            if callable(get_fn)
            else None
        )
        return await self._request("GET", url, caller=caller, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        client = self._ensure_client()
        post_fn = getattr(client, "post", None)
        caller = (
            (lambda _method, target, **opts: post_fn(target, **opts))
            if callable(post_fn)
            else None
        )
        return await self._request("POST", url, caller=caller, **kwargs)

    def _ensure_client(self) -> Any:
        if not self._client:
            raise LifecycleError("httpx-client-not-initialized")
        return self._client

    async def _request(
        self,
        method: str,
        url: str,
        *,
        caller: Any | None,
        **kwargs: Any,
    ) -> httpx.Response:
        client = self._ensure_client()
        headers = dict(kwargs.pop("headers", {}) or {})
        inject_trace_context(headers)
        if headers:
            kwargs["headers"] = headers
        operation = method.upper()

        async def send() -> httpx.Response:
            if callable(caller):
                return await caller(method, url, **kwargs)
            return await client.request(method, url, **kwargs)

        return await observed_http_request(
            domain="adapter",
            key="http",
            adapter="http",
            provider="httpx",
            operation=operation,
            url=str(url),
            component="adapter.http",
            span_name="adapter.http.request",
            send=send,
        )
