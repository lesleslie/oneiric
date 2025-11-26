"""Settings and secrets helpers."""

from __future__ import annotations

import inspect
import json
import os
import tomllib
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from pydantic import BaseModel, Field

from .logging import get_logger
from .lifecycle import LifecycleManager, LifecycleError
from oneiric.runtime.health import default_runtime_health_path
from .resolution import ResolverSettings

logger = get_logger("config")


class AppConfig(BaseModel):
    name: str = "oneiric"
    environment: str = "dev"
    debug: bool = False


class LayerSettings(BaseModel):
    selections: Dict[str, str] = Field(default_factory=dict, description="category -> provider mapping")
    provider_settings: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict,
        description="per-provider configuration payloads",
    )


class SecretsConfig(BaseModel):
    domain: str = "adapter"
    key: str = "secrets"
    provider: Optional[str] = None
    inline: Dict[str, str] = Field(default_factory=dict)


class RemoteAuthConfig(BaseModel):
    header_name: str = "Authorization"
    secret_id: Optional[str] = None
    token: Optional[str] = None


class RemoteSourceConfig(BaseModel):
    enabled: bool = False
    manifest_url: Optional[str] = None
    cache_dir: str = ".oneiric_cache"
    verify_tls: bool = True
    auth: RemoteAuthConfig = Field(default_factory=RemoteAuthConfig)
    refresh_interval: Optional[float] = Field(
        default=300.0,
        description="Optional interval (seconds) to re-sync remote manifests; disabled when null.",
    )


class OneiricSettings(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    adapters: LayerSettings = Field(default_factory=LayerSettings)
    services: LayerSettings = Field(default_factory=LayerSettings)
    tasks: LayerSettings = Field(default_factory=LayerSettings)
    events: LayerSettings = Field(default_factory=LayerSettings)
    workflows: LayerSettings = Field(default_factory=LayerSettings)
    secrets: SecretsConfig = Field(default_factory=SecretsConfig)
    remote: RemoteSourceConfig = Field(default_factory=RemoteSourceConfig)


def load_settings(path: Optional[str | Path] = None) -> OneiricSettings:
    """Load settings from TOML/JSON file and environment overrides."""

    data: Dict[str, Any] = {}
    config_path = path or os.getenv("ONEIRIC_CONFIG")
    if config_path:
        file = Path(config_path)
        if file.exists():
            data = _read_file(file)
        else:
            logger.warning("config-file-missing", path=str(file))

    merged = _deep_merge(data, _env_overrides())
    return OneiricSettings.model_validate(merged)


def resolver_settings_from_config(settings: OneiricSettings) -> ResolverSettings:
    selections = {}
    domain_map = {
        "adapter": settings.adapters.selections,
        "service": settings.services.selections,
        "task": settings.tasks.selections,
        "event": settings.events.selections,
        "workflow": settings.workflows.selections,
    }
    for domain, mapping in domain_map.items():
        if mapping:
            selections[domain] = mapping
    return ResolverSettings(selections=selections)


def lifecycle_snapshot_path(settings: OneiricSettings) -> Path:
    cache = Path(settings.remote.cache_dir)
    return cache / "lifecycle_status.json"


def runtime_health_path(settings: OneiricSettings) -> Path:
    return default_runtime_health_path(settings.remote.cache_dir)


def domain_activity_path(settings: OneiricSettings) -> Path:
    cache = Path(settings.remote.cache_dir)
    return cache / "domain_activity.json"


class SecretsHook:
    """Resolve secrets via configured adapter or inline map."""

    def __init__(self, lifecycle: LifecycleManager, config: SecretsConfig) -> None:
        self.lifecycle = lifecycle
        self.config = config
        self._logger = get_logger("secrets")

    async def get(self, secret_id: str) -> Optional[str]:
        if secret_id in self.config.inline:
            return self.config.inline[secret_id]
        provider = await self._ensure_provider()
        if provider is None:
            return None
        getter = getattr(provider, "get_secret", None)
        if not callable(getter):
            raise LifecycleError("Configured secrets adapter does not implement 'get_secret'")
        value = getter(secret_id)
        return await _maybe_await(value)

    async def _ensure_provider(self) -> Optional[Any]:
        instance = self.lifecycle.get_instance(self.config.domain, self.config.key)
        if instance:
            return instance
        provider_id = self.config.provider
        if not provider_id:
            self._logger.debug("no-secrets-provider-configured")
            return None
        instance = await self.lifecycle.activate(
            self.config.domain,
            self.config.key,
            provider=provider_id,
        )
        return instance


def _env_overrides(prefix: str = "ONEIRIC_") -> Dict[str, Any]:
    overrides: Dict[str, Any] = {}
    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        path = key[len(prefix) :].lower().split("__")
        cursor = overrides
        for part in path[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[path[-1]] = _coerce_env_value(value)
    return overrides


def _coerce_env_value(value: str) -> Any:
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    for caster in (int, float):
        try:
            return caster(value)
        except ValueError:
            continue
    if "," in value:
        return [item.strip() for item in value.split(",")]
    return value


def _read_file(path: Path) -> Dict[str, Any]:
    content = path.read_text()
    if path.suffix in {".toml", ".tml"}:
        return tomllib.loads(content)
    if path.suffix == ".json":
        return json.loads(content)
    if content.strip().startswith("{"):
        return json.loads(content)
    return tomllib.loads(content)


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = dict(base)
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], Mapping)
            and isinstance(value, Mapping)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value
