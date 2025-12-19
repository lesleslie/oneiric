"""Settings and secrets helpers."""

from __future__ import annotations

import inspect
import json
import os
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, Field

from oneiric.runtime.health import default_runtime_health_path

from .lifecycle import LifecycleError, LifecycleManager
from .logging import LoggingConfig, get_logger
from .protocols import SecretsCacheProtocol, SecretsProviderProtocol
from .resolution import ResolverSettings
from .secrets_cache import SecretValueCache

logger = get_logger("config")


class AppConfig(BaseModel):
    name: str = "oneiric"
    environment: str = "dev"
    debug: bool = False


class LayerSettings(BaseModel):
    selections: dict[str, str] = Field(
        default_factory=dict, description="category -> provider mapping"
    )
    provider_settings: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="per-provider configuration payloads",
    )
    options: dict[str, Any] = Field(
        default_factory=dict,
        description="Domain-specific configuration knobs (e.g., workflow queue defaults).",
    )


class SecretsConfig(BaseModel):
    domain: str = "adapter"
    key: str = "secrets"
    provider: str | None = None
    inline: dict[str, str] = Field(default_factory=dict)
    cache_ttl_seconds: float = Field(
        default=600.0,
        ge=0.0,
        description="Number of seconds to cache resolved secrets (0 disables cache).",
    )
    refresh_interval: float | None = Field(
        default=None,
        ge=1.0,
        description="Seconds between secrets cache invalidations (None disables).",
    )


class RemoteAuthConfig(BaseModel):
    header_name: str = "Authorization"
    secret_id: str | None = None
    token: str | None = None


class RemoteSourceConfig(BaseModel):
    enabled: bool = False
    manifest_url: str | None = None
    cache_dir: str = ".oneiric_cache"
    verify_tls: bool = True
    auth: RemoteAuthConfig = Field(default_factory=RemoteAuthConfig)
    signature_required: bool = Field(
        default=False,
        description="Reject unsigned manifests when True.",
    )
    signature_threshold: int = Field(
        default=1,
        ge=1,
        description="Number of valid signatures required to accept a manifest.",
    )
    signature_max_age_seconds: float | None = Field(
        default=None,
        ge=0.0,
        description="Optional maximum age (seconds) for signed manifests.",
    )
    signature_require_expiry: bool = Field(
        default=False,
        description="Require expires_at on signed manifests when True.",
    )
    refresh_interval: float | None = Field(
        default=300.0,
        description="Optional interval (seconds) to re-sync remote manifests; disabled when null.",
    )
    max_retries: int = Field(
        default=3, description="Number of retry attempts for remote fetches."
    )
    retry_base_delay: float = Field(
        default=1.0, description="Base delay (seconds) for retry backoff."
    )
    retry_max_delay: float = Field(
        default=30.0, description="Maximum delay (seconds) between retries."
    )
    retry_jitter: float = Field(
        default=0.25, description="Jitter factor added to retry sleep."
    )
    circuit_breaker_threshold: int = Field(
        default=5,
        description="Consecutive failures before opening the remote circuit breaker.",
    )
    circuit_breaker_reset: float = Field(
        default=60.0,
        description="Seconds before allowing attempts after circuit breaker opens.",
    )
    allow_file_uris: bool = Field(
        default=False,
        description="Allow file:// URIs and local manifest paths when True.",
    )
    allowed_file_uri_roots: list[str] = Field(
        default_factory=list,
        description="Optional allowlist of roots for file:// URIs and local paths.",
    )
    latency_budget_ms: float = Field(
        default=5000.0,
        description="Warn threshold (milliseconds) for remote sync latency.",
    )


class LifecycleConfig(BaseModel):
    activation_timeout: float = Field(
        default=30.0,
        description="Seconds before lifecycle activation times out.",
    )
    health_timeout: float = Field(
        default=5.0,
        description="Seconds before lifecycle health checks time out.",
    )
    cleanup_timeout: float = Field(
        default=10.0,
        description="Seconds before cleanup hooks time out.",
    )
    hook_timeout: float = Field(
        default=5.0,
        description="Seconds before pre/post-swap hooks time out.",
    )
    shield_tasks: bool = Field(
        default=True,
        description="Shield lifecycle awaitables from cancellation.",
    )


class PluginsConfig(BaseModel):
    auto_load: bool = Field(
        default=False,
        description="Load built-in Oneiric entry-point groups (oneiric.*).",
    )
    entry_points: list[str] = Field(
        default_factory=list,
        description="Additional entry-point groups to load during bootstrap.",
    )


class RuntimeProfileConfig(BaseModel):
    name: str = "default"
    watchers_enabled: bool = True
    remote_enabled: bool = True
    inline_manifest_only: bool = False
    supervisor_enabled: bool = True


class RuntimePathsConfig(BaseModel):
    """Filesystem locations + toggles for runtime persistence helpers."""

    workflow_checkpoints_enabled: bool = True
    workflow_checkpoints_path: str | None = Field(
        default=None,
        description="Override path for workflow checkpoint SQLite store.",
    )


class RuntimeSupervisorConfig(BaseModel):
    """Supervisor loop feature flag + tuning knobs."""

    enabled: bool = True
    poll_interval: float = Field(
        default=2.0,
        ge=0.1,
        description="Seconds between supervisor poll iterations.",
    )


class OneiricSettings(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    adapters: LayerSettings = Field(default_factory=LayerSettings)
    services: LayerSettings = Field(default_factory=LayerSettings)
    tasks: LayerSettings = Field(default_factory=LayerSettings)
    events: LayerSettings = Field(default_factory=LayerSettings)
    workflows: LayerSettings = Field(default_factory=LayerSettings)
    actions: LayerSettings = Field(default_factory=LayerSettings)
    secrets: SecretsConfig = Field(default_factory=SecretsConfig)
    remote: RemoteSourceConfig = Field(default_factory=RemoteSourceConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    lifecycle: LifecycleConfig = Field(default_factory=LifecycleConfig)
    plugins: PluginsConfig = Field(default_factory=PluginsConfig)
    profile: RuntimeProfileConfig = Field(default_factory=RuntimeProfileConfig)
    runtime_paths: RuntimePathsConfig = Field(default_factory=RuntimePathsConfig)
    runtime_supervisor: RuntimeSupervisorConfig = Field(
        default_factory=RuntimeSupervisorConfig
    )


def load_settings(path: str | Path | None = None) -> OneiricSettings:
    """Load settings from TOML/JSON file and environment overrides."""

    data: dict[str, Any] = {}
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
        "action": settings.actions.selections,
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
    return cache / "domain_activity.sqlite"


def runtime_observability_path(settings: OneiricSettings) -> Path:
    cache = Path(settings.remote.cache_dir)
    return cache / "runtime_telemetry.json"


def workflow_checkpoint_path(settings: OneiricSettings) -> Path | None:
    """Resolve workflow checkpoint path (or None when disabled)."""

    if not settings.runtime_paths.workflow_checkpoints_enabled:
        return None
    override = settings.runtime_paths.workflow_checkpoints_path
    if override:
        return Path(override)
    cache = Path(settings.remote.cache_dir)
    return cache / "workflow_checkpoints.sqlite"


def apply_runtime_profile(
    settings: OneiricSettings, profile_name: str | None
) -> OneiricSettings:
    """Return a copy of settings with the requested runtime profile applied."""

    target = (profile_name or settings.profile.name or "default").lower()
    updated = settings.model_copy(deep=True)
    if target in ("", "default"):
        updated.profile = RuntimeProfileConfig()
        if profile_name:
            logger.info("runtime-profile-applied", profile="default")
        return updated
    if target == "serverless":
        updated.profile = RuntimeProfileConfig(
            name="serverless",
            watchers_enabled=False,
            remote_enabled=False,
            inline_manifest_only=True,
            supervisor_enabled=True,
        )
        updated.remote.enabled = False
        updated.remote.refresh_interval = None
        updated.runtime_supervisor.enabled = True
        logger.info("runtime-profile-applied", profile="serverless")
        return updated
    raise ValueError(f"Unknown runtime profile: {profile_name}")


def apply_profile_with_fallback(
    settings: OneiricSettings, profile_name: str | None
) -> OneiricSettings:
    """Apply an explicit or configured runtime profile if necessary."""

    explicit = profile_name or ""
    if explicit:
        return apply_runtime_profile(settings, explicit)

    configured = settings.profile.name or "default"
    if configured.lower() != "default":
        return apply_runtime_profile(settings, configured)
    return settings


class SecretsHook:
    """Resolve secrets via configured adapter or inline map."""

    def __init__(self, lifecycle: LifecycleManager, config: SecretsConfig) -> None:
        self.lifecycle = lifecycle
        self.config = config
        self._logger = get_logger("secrets")
        self._cache = SecretValueCache(config.cache_ttl_seconds)
        self._default_cache_key = config.provider or f"{config.domain}:{config.key}"
        self._prefetched = False

    async def get(self, secret_id: str) -> str | None:
        if secret_id in self.config.inline:
            return self.config.inline[secret_id]
        cache_key = self._cache_key()
        hit, cached_value = self._cache.get(cache_key, secret_id)
        if hit:
            self._logger.debug(
                "secret-cache-hit", secret_id=secret_id, provider=cache_key
            )
            return cached_value
        provider = await self._ensure_provider()
        if provider is None:
            return None
        getter = getattr(provider, "get_secret", None)
        if not callable(getter):
            raise LifecycleError(
                "Configured secrets adapter does not implement 'get_secret'"
            )
        value = getter(secret_id)
        resolved = await _maybe_await(value)
        self._cache.set(cache_key, secret_id, resolved)
        return resolved

    async def prefetch(self) -> bool:
        """Ensure the configured provider is activated before first use."""

        provider = await self._ensure_provider()
        ready = provider is not None
        if ready:
            self._logger.debug(
                "secrets-prefetched",
                provider=self.config.provider or self._default_cache_key,
            )
        return ready

    async def rotate(
        self,
        keys: Sequence[str] | None = None,
        *,
        provider: str | None = None,
        include_provider_cache: bool = True,
    ) -> int:
        """Invalidate cached secrets and optionally refresh provider caches."""
        removed = self.invalidate(keys=keys, provider=provider)
        if include_provider_cache:
            await self._invalidate_provider_cache()
        return removed

    @property
    def prefetched(self) -> bool:
        """Return True when the secrets provider has been activated."""

        return self._prefetched

    async def _ensure_provider(self) -> SecretsProviderProtocol | None:
        instance = self.lifecycle.get_instance(self.config.domain, self.config.key)
        if instance:
            self._prefetched = True
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
        if instance is not None:
            self._prefetched = True
        return instance

    def invalidate(
        self,
        keys: Sequence[str] | None = None,
        provider: str | None = None,
    ) -> int:
        """Invalidate cached secret values. Returns number of entries removed."""
        provider_key = self._cache_key(provider) if provider else None
        removed = self._cache.invalidate(keys, provider_key)
        self._logger.info(
            "secrets-cache-invalidated",
            removed=removed,
            provider=provider_key or "*",
            keys="*" if keys is None else list(keys),
        )
        return removed

    async def _invalidate_provider_cache(self) -> None:
        provider = await self._ensure_provider()
        if provider is None:
            return
        cache_provider = cast(SecretsCacheProtocol, provider)
        for method_name in ("invalidate_cache", "clear_cache", "refresh"):
            handler = getattr(cache_provider, method_name, None)
            if callable(handler):
                await _maybe_await(handler())
                self._logger.info(
                    "secrets-provider-cache-invalidated",
                    method=method_name,
                )
                return

    def _cache_key(self, override: str | None = None) -> str:
        return (override or self._default_cache_key or "default").lower()


def _env_overrides(prefix: str = "ONEIRIC_") -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        path = key[len(prefix) :].lower().split("__")
        coerced = _coerce_env_value(value)
        if len(path) == 1 and path[0] == "profile":
            profile_section = overrides.setdefault("profile", {})
            if isinstance(profile_section, dict):
                profile_section["name"] = coerced
            else:
                overrides["profile"] = {"name": coerced}
            continue
        cursor = overrides
        for part in path[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[path[-1]] = coerced
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


def _read_file(path: Path) -> dict[str, Any]:
    content = path.read_text()
    if path.suffix in {".toml", ".tml"}:
        return tomllib.loads(content)
    if path.suffix == ".json":
        return json.loads(content)
    if content.strip().startswith("{"):
        return json.loads(content)
    return tomllib.loads(content)


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = dict(base)
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
