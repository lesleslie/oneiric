"""Infisical secrets adapter."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
from pydantic import BaseModel, Field

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class InfisicalSecretSettings(BaseModel):
    """Configuration for the Infisical adapter."""

    base_url: str = Field(
        default="https://app.infisical.com", description="Infisical API base URL."
    )
    token: str = Field(description="Machine identity token.")
    environment: str = Field(
        description="Infisical environment slug (e.g., dev, prod)."
    )
    secret_path: str = Field(default="/", description="Secret path/folder.")
    project_id: str | None = Field(
        default=None, description="Optional project identifier."
    )
    cache_ttl_seconds: int = Field(default=60, ge=5)
    http_timeout: float = Field(default=5.0, gt=0)


class InfisicalSecretAdapter:
    """Fetches secrets from Infisical with simple caching."""

    metadata = AdapterMetadata(
        category="secrets",
        provider="infisical",
        factory="oneiric.adapters.secrets.infisical:InfisicalSecretAdapter",
        capabilities=["remote", "http", "cache"],
        stack_level=40,
        priority=600,
        source=CandidateSource.LOCAL_PKG,
        owner="Security",
        requires_secrets=True,
        settings_model=InfisicalSecretSettings,
    )

    def __init__(
        self,
        settings: InfisicalSecretSettings,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._http_client = http_client
        self._owns_client = http_client is None
        self._cache: dict[str, tuple[str, float]] = {}
        self._cache_lock = asyncio.Lock()
        self._logger = get_logger("adapter.secrets.infisical").bind(
            domain="adapter",
            key="secrets",
            provider="infisical",
        )

    async def init(self) -> None:
        if not self._http_client and self._owns_client:
            self._http_client = httpx.AsyncClient(timeout=self._settings.http_timeout)
        self._logger.info("adapter-init", adapter="infisical-secrets")

    async def health(self) -> bool:
        try:
            await self.get_secret(
                "healthcheck-this-key-should-not-exist", allow_missing=True
            )
            return True
        except Exception as exc:  # pragma: no cover - network
            self._logger.warning("adapter-health-error", error=str(exc))
            return False

    async def cleanup(self) -> None:
        if self._http_client and self._owns_client:
            await self._http_client.aclose()
        self._http_client = None
        self._cache.clear()
        self._logger.info("adapter-cleanup-complete", adapter="infisical-secrets")

    async def invalidate_cache(self) -> None:
        async with self._cache_lock:
            self._cache.clear()
        self._logger.info("secrets-cache-invalidated", adapter="infisical-secrets")

    async def get_secret(self, key: str, *, allow_missing: bool = False) -> str | None:
        cached = await self._get_cached(key)
        if cached is not None:
            return cached
        client = self._ensure_client()
        url = self._settings.base_url.rstrip("/") + "/api/v3/secrets/raw"
        payload: dict[str, Any] = {
            "environment": self._settings.environment,
            "secretPath": self._settings.secret_path,
            "secretName": key,
        }
        if self._settings.project_id:
            payload["projectId"] = self._settings.project_id
        headers = {
            "Authorization": f"Bearer {self._settings.token}",
        }
        response = await client.post(url, json=payload, headers=headers)
        if response.status_code == 404 and allow_missing:
            return None
        response.raise_for_status()
        if (value := response.json().get("secretValue")) is None and not allow_missing:
            raise LifecycleError("secret-value-missing")
        if value is not None:
            await self._set_cached(key, value)
        return value

    async def _get_cached(self, key: str) -> str | None:
        async with self._cache_lock:
            cached = self._cache.get(key)
            if not cached:
                return None
            value, expires_at = cached
            if expires_at < time.monotonic():
                self._cache.pop(key, None)
                return None
            return value

    async def _set_cached(self, key: str, value: str) -> None:
        async with self._cache_lock:
            expires_at = time.monotonic() + self._settings.cache_ttl_seconds
            self._cache[key] = (value, expires_at)

    def _ensure_client(self) -> httpx.AsyncClient:
        if not self._http_client:
            raise LifecycleError("infisical-http-client-not-initialized")
        return self._http_client
