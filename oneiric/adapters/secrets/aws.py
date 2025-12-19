"""AWS Secrets Manager adapter."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, Field

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class AWSSecretManagerSettings(BaseModel):
    """Settings for interacting with AWS Secrets Manager."""

    region: str = Field(description="AWS region where the secrets live.")
    endpoint_url: str | None = Field(
        default=None, description="Optional custom endpoint (e.g., LocalStack)."
    )
    profile_name: str | None = Field(
        default=None, description="AWS profile name for credential discovery."
    )
    access_key_id: str | None = Field(default=None)
    secret_access_key: str | None = Field(default=None)
    session_token: str | None = Field(default=None)
    cache_ttl_seconds: int = Field(default=60, ge=0)
    healthcheck_secret: str | None = Field(
        default=None, description="Optional secret name probed during health checks."
    )
    version_stage: str | None = Field(
        default=None, description="Optional version stage filter (e.g., AWSCURRENT)."
    )


class AWSSecretManagerAdapter:
    """Async adapter powered by aioboto3's Secrets Manager client."""

    metadata = AdapterMetadata(
        category="secrets",
        provider="aws-secret-manager",
        factory="oneiric.adapters.secrets.aws:AWSSecretManagerAdapter",
        capabilities=["remote", "cache"],
        stack_level=52,
        priority=560,
        source=CandidateSource.LOCAL_PKG,
        owner="Security",
        requires_secrets=True,
        settings_model=AWSSecretManagerSettings,
    )

    def __init__(
        self,
        settings: AWSSecretManagerSettings,
        *,
        client: Any | None = None,
        client_factory: Callable[[], Awaitable[Any]] | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._client_factory = client_factory
        self._client_cm: Any | None = None
        self._cache: dict[str, tuple[str, float]] = {}
        self._cache_lock = asyncio.Lock()
        self._logger = get_logger("adapter.secrets.aws").bind(
            domain="adapter",
            key="secrets",
            provider="aws-secret-manager",
            region=settings.region,
        )

    async def init(self) -> None:
        if self._client is not None:
            return
        if self._client_factory:
            self._client = await self._client_factory()
            return
        try:
            import aioboto3
        except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
            raise LifecycleError("aioboto3-missing") from exc

        session_kwargs: dict[str, Any] = {
            "region_name": self._settings.region,
        }
        if self._settings.profile_name:
            session_kwargs["profile_name"] = self._settings.profile_name
        session = aioboto3.Session(**session_kwargs)
        client_kwargs: dict[str, Any] = {
            "service_name": "secretsmanager",
            "endpoint_url": self._settings.endpoint_url,
            "aws_access_key_id": self._settings.access_key_id,
            "aws_secret_access_key": self._settings.secret_access_key,
            "aws_session_token": self._settings.session_token,
        }
        client_kwargs = {k: v for k, v in client_kwargs.items() if v is not None}
        self._client_cm = session.client(**client_kwargs)
        self._client = await self._client_cm.__aenter__()
        self._logger.info("adapter-init", adapter="aws-secret-manager")

    async def health(self) -> bool:
        probe = self._settings.healthcheck_secret
        if not probe:
            return True
        try:
            value = await self.get_secret(probe, allow_missing=True)
            return value is not None
        except Exception as exc:  # pragma: no cover - external failure path
            self._logger.warning("adapter-health-error", error=str(exc))
            return False

    async def cleanup(self) -> None:
        if self._client_cm:
            await self._client_cm.__aexit__(None, None, None)
        if self._client and hasattr(self._client, "close"):
            await self._client.close()
        self._client = None
        self._client_cm = None
        self._cache.clear()
        self._logger.info("adapter-cleanup-complete", adapter="aws-secret-manager")

    async def invalidate_cache(self) -> None:
        async with self._cache_lock:
            self._cache.clear()
        self._logger.info("secrets-cache-invalidated", adapter="aws-secret-manager")

    async def get_secret(
        self,
        name: str,
        *,
        version_stage: str | None = None,
        allow_missing: bool = False,
    ) -> str | None:
        cached = await self._get_cached(name, version_stage)
        if cached is not None:
            return cached
        client = self._ensure_client()
        request: dict[str, Any] = {"SecretId": name}
        stage = version_stage or self._settings.version_stage
        if stage:
            request["VersionStage"] = stage
        try:
            response = await client.get_secret_value(**request)
        except Exception as exc:
            if allow_missing and self._is_not_found(exc):
                return None
            raise
        value = self._extract_secret(response)
        await self._set_cached(name, version_stage, value)
        return value

    def _ensure_client(self) -> Any:
        if not self._client:
            raise LifecycleError("aws-secret-client-not-initialized")
        return self._client

    def _extract_secret(self, response: dict[str, Any]) -> str:
        if "SecretString" in response:
            return str(response["SecretString"])
        if "SecretBinary" in response:
            data = response["SecretBinary"]
            if isinstance(data, (bytes, bytearray)):
                return data.decode("utf-8")
        raise LifecycleError("aws-secret-invalid-response")

    def _is_not_found(self, exc: Exception) -> bool:
        code = getattr(exc, "response", {}).get("Error", {}).get("Code")
        if isinstance(code, str) and code in {"ResourceNotFoundException", "404"}:
            return True
        message = getattr(exc, "args", [None])[0]
        if isinstance(message, str):
            return "ResourceNotFound" in message or "404" in message
        return False

    async def _get_cached(self, name: str, version_stage: str | None) -> str | None:
        async with self._cache_lock:
            key = self._cache_key(name, version_stage)
            cached = self._cache.get(key)
            if not cached:
                return None
            value, expires_at = cached
            if expires_at < time.monotonic():
                self._cache.pop(key, None)
                return None
            return value

    async def _set_cached(
        self, name: str, version_stage: str | None, value: str
    ) -> None:
        if self._settings.cache_ttl_seconds == 0:
            return
        async with self._cache_lock:
            key = self._cache_key(name, version_stage)
            expires_at = time.monotonic() + self._settings.cache_ttl_seconds
            self._cache[key] = (value, expires_at)

    def _cache_key(self, name: str, version_stage: str | None) -> str:
        return f"{name}:{version_stage or self._settings.version_stage or 'default'}"
