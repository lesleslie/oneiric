"""File-backed secrets adapter."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class FileSecretSettings(BaseModel):
    path: Path = Field(
        ..., description="Path to JSON/TOML file containing key/value secrets."
    )
    format: str = Field(
        default="json",
        description="File format: currently supports 'json'.",
    )
    reload_on_access: bool = Field(
        default=False,
        description="Reload the file on every get() call instead of caching.",
    )


class FileSecretAdapter:
    metadata = AdapterMetadata(
        category="secrets",
        provider="file",
        factory="oneiric.adapters.secrets.file:FileSecretAdapter",
        capabilities=["read"],
        stack_level=20,
        priority=150,
        source=CandidateSource.LOCAL_PKG,
        owner="Platform Core",
        requires_secrets=True,
        settings_model=FileSecretSettings,
    )

    def __init__(self, settings: FileSecretSettings) -> None:
        self._settings = settings
        self._cache: dict[str, str] | None = None
        self._logger = get_logger("adapter.secrets.file").bind(
            domain="adapter",
            key="secrets",
            provider="file",
        )

    async def init(self) -> None:
        self._logger.info(
            "adapter-init", adapter="file-secrets", path=str(self._settings.path)
        )
        if not self._settings.path.exists():
            raise LifecycleError("secrets-file-missing")
        self._load()

    async def health(self) -> bool:
        try:
            self._load(force=True)
            return True
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("secrets-file-health-failed", error=str(exc))
            return False

    async def cleanup(self) -> None:
        self._logger.info("adapter-cleanup-complete", adapter="file-secrets")

    async def invalidate_cache(self) -> None:
        self._cache = None
        self._logger.info("secrets-cache-invalidated", adapter="file-secrets")

    async def get_secret(self, secret_id: str) -> str | None:
        if self._settings.reload_on_access or self._cache is None:
            self._load(force=True)
        assert self._cache is not None
        return self._cache.get(secret_id)

    def _load(self, *, force: bool = False) -> None:
        if self._cache is not None and not force:
            return
        if self._settings.format != "json":
            raise LifecycleError("unsupported-secrets-file-format")
        try:
            data = json.loads(self._settings.path.read_text())
        except Exception as exc:  # noqa: BLE001
            raise LifecycleError("invalid-secrets-file") from exc
        if not isinstance(data, dict):
            raise LifecycleError("secrets-file-must-be-object")
        self._cache = {str(key): str(value) for key, value in data.items()}
