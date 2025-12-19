"""Environment-backed secrets adapter."""

from __future__ import annotations

import os

from pydantic import BaseModel, Field

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class EnvSecretSettings(BaseModel):
    prefix: str = Field(
        default="ONEIRIC_SECRET_",
        description="Prefix used when looking up environment variables for secrets.",
    )
    uppercase_keys: bool = Field(
        default=True,
        description="Whether to uppercase secret IDs before composing the env var name.",
    )
    required_keys: list[str] = Field(
        default_factory=list,
        description="Optional list of secret IDs that must exist; checked during health probes.",
    )


class EnvSecretAdapter:
    metadata = AdapterMetadata(
        category="secrets",
        provider="env",
        factory="oneiric.adapters.secrets.env:EnvSecretAdapter",
        capabilities=["read"],
        stack_level=10,
        priority=100,
        source=CandidateSource.LOCAL_PKG,
        owner="Platform Core",
        requires_secrets=False,
        settings_model=EnvSecretSettings,
    )

    def __init__(self, settings: EnvSecretSettings | None = None) -> None:
        self._settings = settings or EnvSecretSettings()
        self._logger = get_logger("adapter.secrets.env").bind(
            domain="adapter",
            key="secrets",
            provider="env",
        )

    async def init(self) -> None:
        self._logger.info("adapter-init", adapter="env-secrets")

    async def health(self) -> bool:
        missing = [
            key
            for key in self._settings.required_keys
            if await self.get_secret(key) is None
        ]
        if missing:
            self._logger.warning("secrets-missing-required", missing=missing)
            return False
        return True

    async def cleanup(self) -> None:
        self._logger.info("adapter-cleanup-complete", adapter="env-secrets")

    async def get_secret(self, secret_id: str) -> str | None:
        key = self._compose_env_key(secret_id)
        return os.getenv(key)

    def _compose_env_key(self, secret_id: str) -> str:
        token = secret_id.upper() if self._settings.uppercase_keys else secret_id
        return f"{self._settings.prefix}{token}"
