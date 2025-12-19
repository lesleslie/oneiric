"""Cloudflare DNS adapter."""

from __future__ import annotations

from typing import Any, Literal

import httpx
from pydantic import AnyHttpUrl, Field, SecretStr

from oneiric.adapters.httpx_base import HTTPXClientMixin
from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource
from oneiric.core.settings_mixins import TimeoutSettings


class CloudflareDNSSettings(TimeoutSettings):
    """Configuration for Cloudflare DNS."""

    zone_id: str = Field(description="Cloudflare zone identifier")
    api_token: SecretStr = Field(description="Cloudflare API token with DNS edit scope")
    base_url: AnyHttpUrl = Field(
        default="https://api.cloudflare.com/client/v4",
        description="Cloudflare API base URL",
    )


class CloudflareDNSAdapter(HTTPXClientMixin):
    """Manage DNS records via the Cloudflare API."""

    metadata = AdapterMetadata(
        category="dns",
        provider="cloudflare",
        factory="oneiric.adapters.dns.cloudflare:CloudflareDNSAdapter",
        capabilities=["record.manage", "record.list"],
        stack_level=30,
        priority=320,
        source=CandidateSource.LOCAL_PKG,
        owner="Platform Core",
        requires_secrets=True,
        settings_model=CloudflareDNSSettings,
    )

    def __init__(
        self,
        settings: CloudflareDNSSettings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(client=client)
        self._settings = settings
        self._logger = get_logger("adapter.dns.cloudflare").bind(
            domain="adapter",
            key="dns",
            provider="cloudflare",
        )

    async def init(self) -> None:
        """Initialize HTTP client."""
        if self._client is None:
            headers = {
                "Authorization": f"Bearer {self._settings.api_token.get_secret_value()}",
                "Content-Type": "application/json",
            }
            self._init_client(
                lambda: httpx.AsyncClient(
                    base_url=str(self._settings.base_url),
                    timeout=self._settings.timeout,
                    headers=headers,
                )
            )
        else:
            self._client.headers.update(
                {
                    "Authorization": f"Bearer {self._settings.api_token.get_secret_value()}",
                }
            )
        self._logger.info("cloudflare-dns-init")

    async def cleanup(self) -> None:
        """Dispose HTTP client."""
        await self._cleanup_client()
        self._logger.info("cloudflare-dns-cleanup")

    async def health(self) -> bool:
        """Lightweight zone read."""
        client = self._ensure_client("cloudflare-dns-client-not-initialized")
        try:
            response = await client.get(f"/zones/{self._settings.zone_id}")
            data = response.json()
            return response.status_code < 400 and data.get("success", False)
        except httpx.HTTPError as exc:  # pragma: no cover - network failure path
            self._logger.warning("cloudflare-dns-health-failed", error=str(exc))
            return False

    async def list_records(
        self, *, record_type: str | None = None, name: str | None = None
    ) -> list[dict[str, Any]]:
        """List DNS records in the zone."""
        params: dict[str, Any] = {}
        if record_type:
            params["type"] = record_type
        if name:
            params["name"] = name
        resp = await self._request(
            "GET",
            f"/zones/{self._settings.zone_id}/dns_records",
            params=params or None,
        )
        return resp.get("result", [])

    async def create_record(
        self,
        *,
        name: str,
        record_type: Literal["A", "AAAA", "CNAME", "TXT", "SRV", "MX", "NS"] = "A",
        content: str,
        ttl: int = 120,
        proxied: bool | None = None,
        priority: int | None = None,
    ) -> dict[str, Any]:
        """Create a DNS record."""
        payload: dict[str, Any] = {
            "type": record_type,
            "name": name,
            "content": content,
            "ttl": ttl,
        }
        if proxied is not None:
            payload["proxied"] = proxied
        if priority is not None:
            payload["priority"] = priority
        resp = await self._request(
            "POST",
            f"/zones/{self._settings.zone_id}/dns_records",
            json=payload,
        )
        return resp.get("result", {})

    async def update_record(
        self,
        record_id: str,
        *,
        name: str | None = None,
        content: str | None = None,
        ttl: int | None = None,
        proxied: bool | None = None,
        priority: int | None = None,
    ) -> dict[str, Any]:
        """Update an existing DNS record."""
        payload: dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if content is not None:
            payload["content"] = content
        if ttl is not None:
            payload["ttl"] = ttl
        if proxied is not None:
            payload["proxied"] = proxied
        if priority is not None:
            payload["priority"] = priority
        resp = await self._request(
            "PATCH",
            f"/zones/{self._settings.zone_id}/dns_records/{record_id}",
            json=payload,
        )
        return resp.get("result", {})

    async def delete_record(self, record_id: str) -> bool:
        """Delete a DNS record."""
        resp = await self._request(
            "DELETE",
            f"/zones/{self._settings.zone_id}/dns_records/{record_id}",
        )
        return bool(resp.get("success", False))

    async def _request(
        self,
        method: Literal["GET", "POST", "PATCH", "DELETE"],
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        client = self._ensure_client("cloudflare-dns-client-not-initialized")
        try:
            response = await client.request(
                method,
                path,
                params=params,
                json=json,
            )
        except httpx.HTTPError as exc:  # pragma: no cover - network failure path
            self._logger.error(
                "cloudflare-dns-request-error",
                method=method,
                path=path,
                error=str(exc),
            )
            raise LifecycleError("cloudflare-dns-request-error") from exc
        data = response.json()
        if not data.get("success", False):
            errors = data.get("errors") or []
            message = "; ".join(err.get("message", "unknown-error") for err in errors)
            self._logger.error(
                "cloudflare-dns-request-failed",
                method=method,
                path=path,
                status=response.status_code,
                error=message or response.text,
            )
            raise LifecycleError(f"cloudflare-dns-request-failed: {message or 'error'}")
        return data
