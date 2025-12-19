"""HTTP convenience action kit."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal
from urllib.parse import urljoin

import httpx
from pydantic import Field

from oneiric.actions.metadata import ActionMetadata
from oneiric.actions.payloads import normalize_payload
from oneiric.core.http_helpers import observed_http_request
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.observability import inject_trace_context
from oneiric.core.resolution import CandidateSource
from oneiric.core.settings_mixins import BaseURLSettings


class HttpActionSettings(BaseURLSettings):
    """Settings for the HTTP fetch action."""

    default_method: Literal[
        "GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"
    ] = Field(
        default="GET",
        description="Default HTTP method when payload omits 'method'.",
    )
    timeout_seconds: float = Field(
        default=10.0,
        ge=0.1,
        description="Request timeout in seconds.",
    )
    verify_ssl: bool = Field(
        default=True,
        description="Verify TLS certificates for outbound requests.",
    )
    allow_redirects: bool = Field(
        default=True,
        description="Follow redirects by default.",
    )
    raise_for_status: bool = Field(
        default=False,
        description="Raise errors when status is >= 400 instead of returning the payload.",
    )
    default_headers: dict[str, str] = Field(
        default_factory=dict,
        description="Headers applied to every request (payload headers merge/override).",
    )


class HttpFetchAction:
    """Action kit that performs HTTP requests via httpx."""

    metadata = ActionMetadata(
        key="http.fetch",
        provider="builtin-http-fetch",
        factory="oneiric.actions.http:HttpFetchAction",
        description="Async HTTP convenience action for GET/POST requests with JSON parsing",
        domains=["service", "task", "workflow"],
        capabilities=["http", "json", "external-service"],
        stack_level=40,
        priority=405,
        source=CandidateSource.LOCAL_PKG,
        owner="Platform Core",
        requires_secrets=False,
        side_effect_free=False,
        settings_model=HttpActionSettings,
    )

    _ALLOWED_METHODS: tuple[str, ...] = (
        "GET",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "HEAD",
        "OPTIONS",
    )

    def __init__(
        self,
        settings: HttpActionSettings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or HttpActionSettings()
        self._client = client
        self._logger = get_logger("action.http.fetch")

    async def execute(self, payload: dict | None = None) -> dict:
        payload = normalize_payload(payload)
        method = (
            payload.get("method") or self._settings.default_method or "GET"
        ).upper()
        if method not in self._ALLOWED_METHODS:
            raise LifecycleError("http-action-invalid-method")
        url = self._build_url(payload)
        params = self._normalize_mapping(
            payload.get("params") or payload.get("query"), "params"
        )
        headers = self._merge_headers(payload.get("headers"))
        timeout = float(payload.get("timeout", self._settings.timeout_seconds))
        verify = bool(payload.get("verify", self._settings.verify_ssl))
        follow_redirects = bool(
            payload.get("allow_redirects", self._settings.allow_redirects)
        )
        raise_for_status = bool(
            payload.get("raise_for_status", self._settings.raise_for_status)
        )
        response = await observed_http_request(
            domain="action",
            key="http.fetch",
            adapter="http",
            provider="builtin-http-fetch",
            operation=method,
            url=url,
            component="action.http",
            span_name="action.http.request",
            send=lambda: self._send_request(
                method=method,
                url=url,
                params=params,
                headers=headers,
                timeout=timeout,
                verify=verify,
                follow_redirects=follow_redirects,
                json=payload.get("json"),
                data=payload.get("data"),
                content=payload.get("content"),
            ),
        )
        if raise_for_status and not response.is_success:
            raise LifecycleError(f"http-action-status-{response.status_code}")
        try:
            parsed_json = response.json()
            is_json = True
        except ValueError:
            parsed_json = None
            is_json = False
        elapsed_ms = await self._elapsed_ms(response)
        result = {
            "status": "success" if response.is_success else "error",
            "status_code": response.status_code,
            "ok": response.is_success,
            "method": method,
            "url": str(response.request.url),
            "headers": dict(response.headers),
            "elapsed_ms": elapsed_ms,
            "json": parsed_json,
            "text": None if is_json else response.text,
        }
        self._logger.info(
            "http-action-request",
            method=method,
            url=url,
            status_code=response.status_code,
            ok=response.is_success,
        )
        return result

    def _build_url(self, payload: dict) -> str:
        url = payload.get("url")
        path = payload.get("path")
        base_url = str(self._settings.base_url) if self._settings.base_url else None
        if url:
            return str(url)
        if path and base_url:
            return urljoin(f"{base_url.rstrip('/')}/", path.lstrip("/"))
        if base_url and not path:
            return base_url
        raise LifecycleError("http-action-url-required")

    def _merge_headers(self, overrides: Any) -> dict[str, str]:
        headers = self._settings.default_headers.copy()
        if overrides is None:
            return headers
        if isinstance(overrides, Mapping):
            headers.update({str(key): str(value) for key, value in overrides.items()})
            return headers
        raise LifecycleError("http-action-headers-invalid")

    def _normalize_mapping(self, value: Any, field: str) -> dict[str, Any] | None:
        if value is None:
            return None
        if isinstance(value, Mapping):
            return {str(k): v for k, v in value.items()}
        raise LifecycleError(f"http-action-{field}-invalid")

    async def _send_request(
        self,
        *,
        method: str,
        url: str,
        params: dict[str, Any] | None,
        headers: dict[str, str],
        timeout: float,
        verify: bool,
        follow_redirects: bool,
        json: Any,
        data: Any,
        content: Any,
    ) -> httpx.Response:
        request_headers = dict(headers)
        inject_trace_context(request_headers)
        request_kwargs = {
            "params": params,
            "headers": request_headers,
            "json": json,
            "data": data,
            "content": content,
        }
        if self._client:
            return await self._client.request(
                method,
                url,
                timeout=timeout,
                follow_redirects=follow_redirects,
                **request_kwargs,
            )
        async with httpx.AsyncClient(
            timeout=timeout,
            verify=verify,
            follow_redirects=follow_redirects,
        ) as client:
            return await client.request(method, url, **request_kwargs)

    async def _elapsed_ms(self, response: httpx.Response) -> float | None:
        try:
            elapsed = response.elapsed
        except RuntimeError:
            await response.aread()
            try:
                elapsed = response.elapsed
            except RuntimeError:
                return None
        if elapsed is None:
            return None
        return elapsed.total_seconds() * 1000
