"""Google Cloud Secret Manager adapter."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class GCPSecretManagerSettings(BaseModel):
    """Settings for accessing Google Cloud Secret Manager."""

    project_id: str = Field(description="Target GCP project for secrets.")
    credentials_file: Path | None = Field(
        default=None,
        description="Optional service account JSON file.",
    )
    default_version: str = Field(
        default="latest",
        description="Default version requested when callers omit a version.",
    )
    cache_ttl_seconds: int = Field(default=60, ge=0)
    healthcheck_secret: str | None = Field(
        default=None,
        description="Optional secret to probe during health checks.",
    )


class GCPSecretManagerAdapter:
    """Async adapter that fetches secrets from Google Cloud Secret Manager."""

    metadata = AdapterMetadata(
        category="secrets",
        provider="gcp-secret-manager",
        factory="oneiric.adapters.secrets.gcp:GCPSecretManagerAdapter",
        capabilities=["remote", "cache"],
        stack_level=50,
        priority=550,
        source=CandidateSource.LOCAL_PKG,
        owner="Security",
        requires_secrets=True,
        settings_model=GCPSecretManagerSettings,
    )

    def __init__(
        self,
        settings: GCPSecretManagerSettings,
        *,
        client: Any | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._cache: dict[str, tuple[str, float]] = {}
        self._cache_lock = asyncio.Lock()
        self._logger = get_logger("adapter.secrets.gcp").bind(
            domain="adapter",
            key="secrets",
            provider="gcp-secret-manager",
        )

    async def init(self) -> None:
        if self._client is not None:
            return
        try:
            from google.cloud import secretmanager_v1
        except ModuleNotFoundError as exc:  # pragma: no cover - defensive
            raise LifecycleError("google-secret-manager-missing") from exc
        if self._settings.credentials_file:
            self._client = secretmanager_v1.SecretManagerServiceAsyncClient.from_service_account_file(
                str(self._settings.credentials_file)
            )
        else:
            self._client = secretmanager_v1.SecretManagerServiceAsyncClient()
        self._logger.info("adapter-init", adapter="gcp-secret-manager")

    async def health(self) -> bool:
        try:
            await self.get_secret(
                self._settings.healthcheck_secret or "__oneiric_health__",
                allow_missing=True,
            )
            return True
        except Exception as exc:  # pragma: no cover - network path
            self._logger.warning("adapter-health-error", error=str(exc))
            return False

    async def cleanup(self) -> None:
        client = self._client
        self._client = None
        self._cache.clear()
        if client and hasattr(client, "close"):
            await client.close()
        self._logger.info("adapter-cleanup-complete", adapter="gcp-secret-manager")

    async def invalidate_cache(self) -> None:
        async with self._cache_lock:
            self._cache.clear()
        self._logger.info("secrets-cache-invalidated", adapter="gcp-secret-manager")

    async def get_secret(
        self,
        name: str,
        *,
        version: str | None = None,
        allow_missing: bool = False,
    ) -> str | None:
        cached = await self._get_cached(name, version)
        if cached is not None:
            return cached
        client = self._ensure_client()
        secret_name = self._format_secret_name(name, version)
        try:
            response = await client.access_secret_version(request={"name": secret_name})
        except Exception as exc:
            if allow_missing and self._is_not_found(exc):
                return None
            raise
        payload = response.payload.data.decode("utf-8")
        await self._set_cached(name, version, payload)
        return payload

    def _format_secret_name(self, secret_name: str, version: str | None) -> str:
        resolved_version = version or self._settings.default_version
        return f"projects/{self._settings.project_id}/secrets/{secret_name}/versions/{resolved_version}"

    def _ensure_client(self) -> Any:
        if not self._client:
            raise LifecycleError("gcp-secret-client-not-initialized")
        return self._client

    def _is_not_found(self, exc: Exception) -> bool:
        status = getattr(exc, "code", None)
        if status is not None and getattr(status, "name", None) == "NOT_FOUND":
            return True
        message = getattr(exc, "args", [None])[0]
        if isinstance(message, str):
            return "NOT_FOUND" in message or "404" in message
        return False

    async def _get_cached(self, name: str, version: str | None) -> str | None:
        async with self._cache_lock:
            key = self._cache_key(name, version)
            cached = self._cache.get(key)
            if not cached:
                return None
            value, expires_at = cached
            if expires_at < time.monotonic():
                self._cache.pop(key, None)
                return None
            return value

    async def _set_cached(self, name: str, version: str | None, value: str) -> None:
        async with self._cache_lock:
            key = self._cache_key(name, version)
            expires_at = time.monotonic() + self._settings.cache_ttl_seconds
            self._cache[key] = (value, expires_at)

    def _cache_key(self, name: str, version: str | None) -> str:
        return f"{name}:{version or self._settings.default_version}"
