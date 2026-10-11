from __future__ import annotations

import hashlib
import inspect
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import yaml
from pydantic import AliasChoices, BaseModel, Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from ._sources import (
    BodaiManifestSource,
    _AliasOverridesEnvSource,
    _AuthExcludingEnvSource,
    build_yaml_layers,
)

from oneiric.runtime.health import default_runtime_health_path

if TYPE_CHECKING:
    # Used as a string forward-ref on ``OneiricSettings.observability`` to
    # break the eager import cycle (see the docstring on
    # ``_default_otel_storage_settings`` below).
    from oneiric.adapters.observability.settings import OTelStorageSettings

    # 2026-10-05: same lazy-forward pattern for ``OneiricSettings.auth`` —
    # eager import of oneiric.mcp.config pulls in oneiric.mcp.__init__, which
    # transitively imports mcp_common → oneiric.runtime.cache → this module
    # (circular). Verified 2026-10-05 via ``uv pip install -e .`` followed
    # by ``python -c "from oneiric.core.config import load_settings"`` —
    # ImportError unless the factory defers the import. See
    # docs/plans/2026-10-05-oneiric-cli-loader-xdg-migration.md (Phase 2).
    from oneiric.mcp.config import OneiricMCPAuthConfig


def _default_otel_storage_settings() -> OTelStorageSettings:
    """Lazy factory for ``OneiricSettings.observability``.

    Defers the import of ``OTelStorageSettings`` until the field is first
    materialised (i.e. when an actual ``OneiricSettings`` instance is
    built). The eager import path would create a cycle:

        oneiric.core.config
          -> oneiric.adapters.observability.settings
          -> oneiric.adapters.__init__
          -> oneiric.adapters.bridge
          -> oneiric.core.config.LayerSettings   (still loading)

    The deferred import breaks the cycle because by the time
    ``default_factory`` runs, ``oneiric.core.config`` is fully loaded.
    """
    from oneiric.adapters.observability.settings import OTelStorageSettings

    return OTelStorageSettings()


def _default_auth_config() -> OneiricMCPAuthConfig:
    """Lazy factory for ``OneiricSettings.auth``.

    Defers the import of ``OneiricMCPAuthConfig`` (a stdlib ``@dataclass``
    defined in ``oneiric.mcp.config``) until the field is first accessed.
    The eager import path would create a cycle:

        oneiric.core.config
          -> oneiric.mcp.config             (OneiricMCPAuthConfig lives here)
          -> oneiric.mcp.__init__           (re-exports the package surface)
          -> oneiric.mcp.server             (FastMCP server module)
          -> mcp_common.server.runtime
          -> oneiric.runtime.cache
          -> oneiric.core.config.resolve_cache_dir_path   (still loading)

    The deferred import breaks the cycle because by the time
    ``default_factory`` runs, ``oneiric.core.config`` is fully loaded.
    Without this factory, the CLI bootstrap fails with
    ``ImportError: cannot import name 'resolve_cache_dir_path' from
    partially initialized module 'oneiric.core.config'`` — verified
    2026-10-05 in a fresh ``uv pip install -e .`` venv.
    REQ-CLI-XDG-002.
    """
    from oneiric.mcp.config import OneiricMCPAuthConfig

    return OneiricMCPAuthConfig()


from .lifecycle import LifecycleError, LifecycleManager
from .logging import LoggingConfig, get_logger
from .protocols import SecretsCacheProtocol, SecretsProviderProtocol
from .resolution import ResolverSettings
from .secrets_cache import SecretValueCache

logger = get_logger("config")


def resolve_cache_dir_path(cache_dir: str | Path) -> Path:
    path = Path(cache_dir).expanduser()
    cache_seed = os.environ.get("PYTEST_CURRENT_TEST") or str(Path.cwd())
    cwd_hash = hashlib.sha256(cache_seed.encode("utf-8")).hexdigest()[:12]
    if not path.is_absolute():
        path = Path(tempfile.gettempdir()) / "oneiric-cache" / cwd_hash / path
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_test"
        probe.touch(exist_ok=True)
        probe.unlink(missing_ok=True)
        return path
    except OSError:
        path = Path(tempfile.gettempdir()) / "oneiric-cache" / cwd_hash / path.name
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_test"
        probe.touch(exist_ok=True)
        probe.unlink(missing_ok=True)
        return path


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
    workflow_checkpoints_enabled: bool = True
    workflow_checkpoints_path: str | None = Field(
        default=None,
        description="Override path for workflow checkpoint SQLite store.",
    )
    domain_activity_path: str | None = Field(
        default=None,
        validation_alias=AliasChoices("domain_activity_path", "ONEIRIC_ACTIVITY_STORE"),
        description=(
            "Override path for the domain activity SQLite store. Bound from "
            "the ONEIRIC_ACTIVITY_STORE environment variable; if unset, the "
            "store lives under <cache_dir>/domain_activity.sqlite."
        ),
    )


class RuntimeSupervisorConfig(BaseModel):
    enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("enabled", "ONEIRIC_RUNTIME_SUPERVISOR__ENABLED"),
        description=(
            "Enable the service supervisor loop. Bound from "
            "ONEIRIC_RUNTIME_SUPERVISOR__ENABLED via pydantic-settings' "
            "nested-delimiter path (the __ delimiter maps to "
            "runtime_supervisor.enabled). The AliasChoices form is "
            "redundant-but-harmless insurance."
        ),
    )
    poll_interval: float = Field(
        default=2.0,
        ge=0.1,
        description="Seconds between supervisor poll iterations.",
    )


class OneiricMCPConfig(BaseSettings):
    http_port: int = 8000
    http_host: str = "127.0.0.1"
    enable_http_transport: bool = True
    debug: bool = False
    environment: str = "development"
    cache_dir: str = ".oneiric_cache"

    # Intentionally no ``env_file``: the legacy BaseModel loader never
    # did CWD-relative .env-file lookup; preserving that requires
    # omitting the key (it would activate silently under BaseSettings).
    model_config = SettingsConfigDict(
        env_prefix="ONEIRIC_MCP_",
        extra="allow",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Customise pydantic-settings source chain for ``OneiricMCPConfig``.

        Phase 1 Option A: env > init precedence. Mirrors
        ``OneiricSettings.settings_customise_sources`` but without the
        YAML layers (``OneiricMCPConfig`` does not load YAML files; the
        ``ONEIRIC_MCP_`` ``env_prefix`` is the only configured source).

        Chain order (first returned wins; pydantic-settings semantics):

        1. ``_AuthExcludingEnvSource`` — defensive (OneiricMCPConfig has
           no ``auth`` field, but the wrapper is harmless and keeps the
           custom-source surface consistent with ``OneiricSettings``).
        2. ``env_settings`` — ``ONEIRIC_MCP_`` env-var source (wins over
           ``init_settings`` because returned later in the chain).
        3. ``init_settings`` — constructor kwargs.

        Verified by plan gate D5: ``ONEIRIC_MCP_HTTP_PORT=9999
        OneiricMCPConfig(http_port=8888).http_port`` returns 9999.
        """
        return (
            _AuthExcludingEnvSource(settings_cls),
            env_settings,
            init_settings,
        )


class OneiricSettings(BaseSettings):
    # 2026-10-11: migrate from ``BaseModel`` to ``BaseSettings`` (pydantic-
    # settings 2.15+). Activates env-var loading for every nested field via
    # ``env_prefix`` + ``env_nested_delimiter``. The ``arbitrary_types_allowed``
    # flag is required because ``auth: OneiricMCPAuthConfig`` is a stdlib
    # ``@dataclass`` (not a Pydantic model); without it, ``model_validate``
    # raises ``TypeError`` on the auth field. Env-var merging for the
    # ``auth`` field is suppressed via the custom ``_AuthExcludingEnvSource`` /
    # ``_AuthExcludingYamlSource`` wrappers in ``oneiric.core._sources``;
    # the CLI's existing ``OneiricMCPAuthConfig.from_env()`` call site
    # (oneiric/cli/mcp.py:_load_auth_from_settings) remains the sole
    # channel for ``ONEIRIC_AUTH_*`` env vars. REQ-PYDANTIC-MIGRATION-001.
    model_config = SettingsConfigDict(
        env_prefix="ONEIRIC_",
        env_nested_delimiter="__",
        extra="allow",
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )
    config_dir: str | None = None
    cache_dir: str | None = None
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
        default_factory=RuntimeSupervisorConfig,
        description="Enable the service supervisor loop. Bound from "
        "ONEIRIC_RUNTIME_SUPERVISOR__ENABLED via the pydantic-settings "
        "nested-delimiter path. The AliasChoices on ``enabled`` also "
        "recognises the modern ``__`` nested-key form.",
    )
    # 2026-09-29: nested OTelStorageSettings so XDG/env-var overrides on
    # ``observability.<field>`` (e.g. ``observability.connection_string``)
    # route directly to the OTel storage adapter. Without this field the
    # OneiricSettings model would silently drop those overrides via
    # ``extra="allow"`` storage in ``__pydantic_extra__``, leaving consumers
    # to fall back to ``OTelStorageSettings()`` defaults. The sub-model
    # already declares ``env_prefix="ONEIRIC_OTEL_STORAGE_"`` on its own
    # model_config, but those env vars only fire when ``OTelStorageSettings``
    # is constructed standalone; nesting it here lets ``ONEIRIC_OBSERVABILITY__
    # CONNECTION_STRING=...`` work via pydantic-settings' nested-delimiter.
    observability: OTelStorageSettings = Field(
        default_factory=_default_otel_storage_settings,
        description="OpenTelemetry storage settings (pgvector-backed).",
    )
    # 2026-10-05: typed ``auth:`` block so XDG/project layer overrides on
    # ``auth.<field>`` (e.g. ``auth.enabled``, ``auth.providers``) flow through
    # pydantic-settings validation instead of being silently swallowed by
    # ``extra="allow"`` and stored in ``__pydantic_extra__``. The CLI's
    # previous reader (oneiric/cli/mcp.py:_load_auth_from_settings) called
    # ``load_yaml_auth_section()`` to fetch this same dict; the migration
    # makes ``settings.auth`` (this field) the canonical source. Env-var
    # overlay (``ONEIRIC_AUTH_*``) is still applied via
    # ``OneiricMCPAuthConfig.from_env()`` at the CLI call site, preserving
    # the existing REQ-006 contract. REQ-CLI-XDG-002 in
    # docs/plans/2026-10-05-oneiric-cli-loader-xdg-migration.md.
    auth: OneiricMCPAuthConfig = Field(  # type: ignore[valid-type]
        default_factory=_default_auth_config,
        description=(
            "Auth section consumed by the oneiric FastMCP server. "
            "Env-var overlay applied at call time via "
            "OneiricMCPAuthConfig.from_env()."
        ),
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Customise the pydantic-settings source chain.

        Order = "first returned wins" (pydantic-settings). Precedence
        (highest → lowest):

        1. ``init_settings`` (constructor kwargs)
        2. Env source (``{PREFIX}_{SECTION}__{FIELD}`` nested form)
        3. ``_AliasOverridesEnvSource`` — legacy single-underscore aliases
        4. ``BodaiManifestSource`` (no-op when no manifest URL configured)
        5-9. YAML layers (XDG local, XDG config, project local, project yaml, project yml)
        10. ``dotenv_settings`` (deactivated by the loader — never declared)
        11. ``file_secret_settings``

        The ``_AuthExcludingEnvSource`` wrapper drops the ``auth:`` key
        so the stdlib ``OneiricMCPAuthConfig`` dataclass never sees
        env-source merge (pydantic-settings cannot decorate dataclasses).
        """
        project_root_path: Path = getattr(
            settings_cls,
            "oneiric_project_root",
            Path(__file__).resolve().parent.parent.parent,
        )
        project_name: str = getattr(settings_cls, "oneiric_project_name", "oneiric")
        return (
            init_settings,
            _AuthExcludingEnvSource(settings_cls),
            _AliasOverridesEnvSource(
                settings_cls, env_prefix=f"{project_name.upper()}_"
            ),
            BodaiManifestSource(settings_cls),
            *build_yaml_layers(settings_cls, project_root_path, project_name),
            dotenv_settings,
            file_secret_settings,
        )


def load_settings(
    path: str | Path | None = None,
    project_name: str = "oneiric",
    project_root: str | Path | None = None,
) -> OneiricSettings:
    """Load Oneiric settings with XDG-compliant layered configuration.

    Configuration priority (highest to lowest):
    1. Explicit ``path`` argument (post-construction override)
    2. ``{PROJECT_NAME}_CONFIG`` environment variable (post-construction override)
    3. Bare-env-var source (``{PREFIX}_{FIELD}``) — via pydantic-settings
    4. XDG user-local override: ``~/.config/{project_name}/local.yaml``
    5. XDG user config: ``~/.config/{project_name}/config.yaml``
    6. Project local override: ``<project_root>/settings/local.yaml``
    7. Project committed config: ``<project_root>/settings/{project_name}.yaml``
    8. Code defaults

    Project-layer paths are anchored at the package install location (the
    directory containing this package, e.g. ``<repo>/oneiric/``) so they
    resolve correctly under any process spawn context (launchd, nohup,
    containers, worktrees). The CWD-relative fallback that previously
    emitted a DeprecationWarning was removed in the Phase 0 amendment;
    callers that need a non-package anchor must pass ``project_root=``.

    The custom source chain is wired in
    ``OneiricSettings.settings_customise_sources``; this function only
    handles the explicit path / ``{PROJECT}_CONFIG`` overrides (which
    pydantic-settings cannot natively model as "final override slots")
    and the per-project env_prefix via the ``build_oneiric_settings``
    factory.

    Args:
        path: Optional explicit config file path (highest priority).
        project_name: Project identifier for XDG/environment variable lookup
            (e.g., "oneiric", "session_buddy", "crackerjack").
        project_root: Optional explicit project root directory. When ``None``
            (default), inferred from this module's package install location
            (``Path(__file__).resolve().parent.parent.parent``). Pass
            explicitly when calling from a different package or test that
            needs to anchor at a specific checkout. NOTE: the post-
            migration loader no longer falls back to CWD when ``project_root``
            is omitted; tests must pass ``project_root=tmp_path`` explicitly
            to anchor at an empty directory.

    Returns:
        Validated ``_Project`` instance with all layers applied.

    Examples:
        >>> # Load with defaults (anchored at package install location)
        >>> settings = load_settings()

        >>> # Load for specific project (uses XDG config)
        >>> settings = load_settings(project_name="session_buddy")

        >>> # Load with explicit config override
        >>> settings = load_settings(path="/path/to/config.yaml")

        >>> # Anchor at an explicit checkout (e.g., for tests)
        >>> settings = load_settings(project_root="/path/to/repo")
    """
    # Lazy import to avoid the circular: build_settings imports OneiricSettings,
    # which is defined in this module.
    from .build_settings import build_oneiric_settings

    settings_cls = build_oneiric_settings(project_name, project_root=project_root)
    project_root_path = getattr(
        settings_cls, "oneiric_project_root", Path(__file__).resolve().parent.parent.parent
    )
    logger.debug(
        "load-settings-source-chain",
        project=project_name,
        project_root=str(project_root_path),
        settings_class=settings_cls.__name__,
    )

    config_path = path or os.getenv(f"{project_name.upper()}_CONFIG")
    explicit_overlay: dict[str, Any] | None = None
    if config_path:
        file = Path(config_path)
        if file.exists():
            explicit_overlay = _read_yaml_file(file)
            logger.info(
                "explicit-config-loaded",
                path=str(file),
                layer="explicit",
            )
        else:
            logger.warning(
                "config-file-missing",
                path=str(file),
                layer="explicit",
            )

    # Construct via ``__init__()`` so pydantic-settings runs the full
    # source chain (env vars + YAML layers + manifest). For explicit
    # path overrides, model_validate the base instance with the parsed
    # overlay AFTER construction so the path wins over everything else.
    settings_obj = settings_cls()
    if explicit_overlay is not None:
        settings_obj = settings_obj.model_validate(explicit_overlay)
        logger.info(
            "explicit-config-applied",
            layer="explicit-final",
        )
    return settings_obj


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
    cache = resolve_cache_dir_path(settings.cache_dir or settings.remote.cache_dir)
    return cache / "lifecycle_status.json"


def runtime_health_path(settings: OneiricSettings) -> Path:
    return default_runtime_health_path(
        resolve_cache_dir_path(settings.cache_dir or settings.remote.cache_dir)
    )


def domain_activity_path(settings: OneiricSettings) -> Path:
    override = getattr(settings.runtime_paths, "domain_activity_path", None)
    if override:
        path = Path(override).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    cache = resolve_cache_dir_path(settings.cache_dir or settings.remote.cache_dir)
    return cache / "domain_activity.sqlite"


def runtime_observability_path(settings: OneiricSettings) -> Path:
    cache = resolve_cache_dir_path(settings.cache_dir or settings.remote.cache_dir)
    return cache / "runtime_telemetry.json"


def workflow_checkpoint_path(settings: OneiricSettings) -> Path | None:
    if not settings.runtime_paths.workflow_checkpoints_enabled:
        return None
    override = settings.runtime_paths.workflow_checkpoints_path
    if override:
        return Path(override)
    cache = resolve_cache_dir_path(settings.cache_dir or settings.remote.cache_dir)
    return cache / "workflow_checkpoints.sqlite"


def apply_runtime_profile(
    settings: OneiricSettings, profile_name: str | None
) -> OneiricSettings:
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
    explicit = profile_name or ""
    if explicit:
        return apply_runtime_profile(settings, explicit)

    configured = settings.profile.name or "default"
    if configured.lower() != "default":
        return apply_runtime_profile(settings, configured)
    return settings


class SecretsHook:
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
        removed = self.invalidate(keys=keys, provider=provider)
        if include_provider_cache:
            await self._invalidate_provider_cache()
        return removed

    @property
    def prefetched(self) -> bool:
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


def _read_yaml_file(path: Path) -> dict[str, Any]:
    """Read the explicit ``path=`` override YAML and return the parsed dict.

    Phase 1 task 1.6: explicit-path override is the only remaining
    YAML parser inside ``load_settings`` — the layered YAML sources
    are handled by pydantic-settings'
    ``YamlConfigSettingsSource``. The explicit path is always YAML
    (TOML/JSON were never documented as supported by ``path=``).
    """
    content = path.read_text()
    try:
        return yaml.safe_load(content) or {}
    except yaml.YAMLError as e:
        logger.error("explicit-yaml-parse-error", path=str(path), error=str(e))
        raise


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


# Rebuild OneiricSettings so the ``observability: "OTelStorageSettings"``
# string forward-ref resolves to the real class. The eager import would
# cycle (see ``_default_otel_storage_settings`` docstring); the lazy
# ``default_factory`` lets the class definition succeed, but Pydantic
# needs ``model_rebuild`` to link the string annotation to the type.
# Importing ``OTelStorageSettings`` here is safe — by the time module
# load reaches this line, ``oneiric.core.config`` is fully resolved and
# the only thing preventing the eager import was the *eager evaluation
# during class body definition*. The eager evaluation at module-bottom
# runs after the class body completes, so the cycle doesn't fire.
from oneiric.adapters.observability.settings import OTelStorageSettings

# 2026-10-05: same trick for ``OneiricSettings.auth``. Importing
# ``OneiricMCPAuthConfig`` here is safe for the same reason: by module
# bottom, ``oneiric.core.config`` is fully resolved and the only thing
# that would cycle (oneiric.mcp.config → oneiric.mcp → oneiric.mcp.server
# → mcp_common → oneiric.runtime.cache → oneiric.core.config) runs AFTER
# ``oneiric.core.config`` is loaded. REQ-CLI-XDG-002.
from oneiric.mcp.config import OneiricMCPAuthConfig

OneiricSettings.model_rebuild()
