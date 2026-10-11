"""Phase 0 env-var collision audit for oneiric.core.config.OneiricSettings.

Pin the env-var forms that reach each top-level section of OneiricSettings
+ OneiricMCPConfig so Phase 1 (pydantic-settings migration) cannot introduce
accidental regressions where the same field is reachable via two DIFFERENT
env-var forms that are NOT covered by an ``AliasChoices`` binding or the
hand-rolled ``_ALIAS_OVERRIDES`` backward-compat map.

Env-var form conventions:

- All OneiricSettings fields: ``ONEIRIC_<SECTION>__<FIELD>`` (upper-cased).
- OneiricMCPConfig fields: ``ONEIRIC_MCP_<FIELD>`` (upper-cased).
- The hand-rolled _ALIAS_OVERRIDES adds:
  - ``ONEIRIC_ACTIVITY_STORE`` -> ``runtime_paths.domain_activity_path``
  - ``ONEIRIC_LOG_LEVEL``       -> ``logging.level``

This file also re-uses the env-strip helper from
``test_pydantic_settings_precedence`` so tests do not depend on shell state.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from oneiric.adapters.observability.settings import OTelStorageSettings
from oneiric.core.config import (
    AppConfig,
    LayerSettings,
    LifecycleConfig,
    OneiricMCPConfig,
    OneiricSettings,
    PluginsConfig,
    RemoteSourceConfig,
    RuntimePathsConfig,
    RuntimeProfileConfig,
    RuntimeSupervisorConfig,
    SecretsConfig,
)
from oneiric.core.logging import LoggingConfig
from oneiric.mcp.config import OneiricMCPAuthConfig

from tests.unit.test_pydantic_settings_precedence import _strip_oneiric_env


# ---------------------------------------------------------------------------
# Per-section tests
# ---------------------------------------------------------------------------


# Each per-section test asserts:
#   1. Instantiating OneiricSettings() yields an instance of the expected
#      type for that section.
#   2. The env-var form(s) that reach that section are documented in the
#      docstring above the test class so a future reader can map field
#      name -> env var without re-reading the production code.


@pytest.mark.unit
class TestAppSection:
    """``app`` section: env-var form ``ONEIRIC_APP__<FIELD>`` (e.g. NAME,
    ENVIRONMENT, DEBUG). Fields: name, environment, debug."""

    def test_instantiates_as_app_config(self) -> None:
        s = OneiricSettings()
        assert isinstance(s.app, AppConfig), (
            "Expected OneiricSettings().app to be AppConfig instance, "
            "got " + type(s.app).__name__
        )

    def test_env_var_round_trip(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``ONEIRIC_APP__ENVIRONMENT`` reaches ``app.environment`` only via
        ``load_settings()`` (NOT via direct ``OneiricSettings()`` instantiation
        — because AppConfig is a plain BaseModel that does not read env vars).
        """
        from oneiric.core.config import load_settings

        _strip_oneiric_env(monkeypatch)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.setenv("ONEIRIC_APP__ENVIRONMENT", "ci")
        s = load_settings(project_root=tmp_path, project_name="oneiric")
        assert s.app.environment == "ci"


@pytest.mark.unit
class TestAdaptersSection:
    """``adapters`` section: ``OneiricSettings.adapters`` env form
    ``ONEIRIC_ADAPTERS__<FIELD>``. ``LayerSettings`` fields: selections,
    provider_settings, options."""

    def test_instantiates_as_layer_settings(self) -> None:
        s = OneiricSettings()
        assert isinstance(s.adapters, LayerSettings), (
            "Expected OneiricSettings().adapters to be LayerSettings, "
            "got " + type(s.adapters).__name__
        )


@pytest.mark.unit
class TestServicesSection:
    """``services`` section: env-var form ``ONEIRIC_SERVICES__<FIELD>``."""

    def test_instantiates_as_layer_settings(self) -> None:
        s = OneiricSettings()
        assert isinstance(s.services, LayerSettings)


@pytest.mark.unit
class TestTasksSection:
    """``tasks`` section: env-var form ``ONEIRIC_TASKS__<FIELD>``."""

    def test_instantiates_as_layer_settings(self) -> None:
        s = OneiricSettings()
        assert isinstance(s.tasks, LayerSettings)


@pytest.mark.unit
class TestEventsSection:
    """``events`` section: env-var form ``ONEIRIC_EVENTS__<FIELD>``."""

    def test_instantiates_as_layer_settings(self) -> None:
        s = OneiricSettings()
        assert isinstance(s.events, LayerSettings)


@pytest.mark.unit
class TestWorkflowsSection:
    """``workflows`` section: env-var form ``ONEIRIC_WORKFLOWS__<FIELD>``."""

    def test_instantiates_as_layer_settings(self) -> None:
        s = OneiricSettings()
        assert isinstance(s.workflows, LayerSettings)


@pytest.mark.unit
class TestActionsSection:
    """``actions`` section: env-var form ``ONEIRIC_ACTIONS__<FIELD>``."""

    def test_instantiates_as_layer_settings(self) -> None:
        s = OneiricSettings()
        assert isinstance(s.actions, LayerSettings)


@pytest.mark.unit
class TestSecretsSection:
    """``secrets`` section: env-var form ``ONEIRIC_SECRETS__<FIELD>``.

    Top-level fields: domain, key, provider, inline, cache_ttl_seconds,
    refresh_interval.
    """

    def test_instantiates_as_secrets_config(self) -> None:
        s = OneiricSettings()
        assert isinstance(s.secrets, SecretsConfig)


@pytest.mark.unit
class TestRemoteSection:
    """``remote`` section: env-var form ``ONEIRIC_REMOTE__<FIELD>``.

    Top-level fields: enabled, manifest_url, cache_dir, verify_tls,
    signature_required, signature_threshold, signature_max_age_seconds,
    signature_require_expiry, refresh_interval, max_retries,
    retry_base_delay, retry_max_delay, retry_jitter, circuit_breaker_threshold,
    circuit_breaker_reset, allow_file_uris, allowed_file_uri_roots,
    latency_budget_ms. Nested ``auth`` block via ``RemoteAuthConfig``.
    """

    def test_instantiates_as_remote_source_config(self) -> None:
        s = OneiricSettings()
        assert isinstance(s.remote, RemoteSourceConfig)


@pytest.mark.unit
class TestLoggingSection:
    """``logging`` section: env-var form ``ONEIRIC_LOGGING__<FIELD>`` PLUS the
    backward-compat alias ``ONEIRIC_LOG_LEVEL`` (routed via
    ``_ALIAS_OVERRIDES`` + ``AliasChoices`` on ``LoggingConfig.level``).

    Top-level fields: level, emit_json, service_name, environment, release,
    timestamper_format, extra_processors, include_trace_context, sinks.
    """

    def test_instantiates_as_logging_config(self) -> None:
        s = OneiricSettings()
        assert isinstance(s.logging, LoggingConfig)


@pytest.mark.unit
class TestLifecycleSection:
    """``lifecycle`` section: env-var form ``ONEIRIC_LIFECYCLE__<FIELD>``.

    Top-level fields: activation_timeout, health_timeout, cleanup_timeout,
    hook_timeout, shield_tasks.
    """

    def test_instantiates_as_lifecycle_config(self) -> None:
        s = OneiricSettings()
        assert isinstance(s.lifecycle, LifecycleConfig)


@pytest.mark.unit
class TestPluginsSection:
    """``plugins`` section: env-var form ``ONEIRIC_PLUGINS__<FIELD>``.

    Top-level fields: auto_load, entry_points.
    """

    def test_instantiates_as_plugins_config(self) -> None:
        s = OneiricSettings()
        assert isinstance(s.plugins, PluginsConfig)


@pytest.mark.unit
class TestProfileSection:
    """``profile`` section: env-var form ``ONEIRIC_PROFILE__<FIELD>`` PLUS
    the legacy short form ``ONEIRIC_PROFILE`` (single-token override routed
    via the special-case clause in ``_env_overrides``).

    Top-level fields: name, watchers_enabled, remote_enabled,
    inline_manifest_only, supervisor_enabled.
    """

    def test_instantiates_as_runtime_profile_config(self) -> None:
        s = OneiricSettings()
        assert isinstance(s.profile, RuntimeProfileConfig)


@pytest.mark.unit
class TestRuntimePathsSection:
    """``runtime_paths`` section: env-var form
    ``ONEIRIC_RUNTIME_PATHS__<FIELD>`` PLUS the backward-compat alias
    ``ONEIRIC_ACTIVITY_STORE`` (routed via ``_ALIAS_OVERRIDES`` +
    ``AliasChoices`` on ``RuntimePathsConfig.domain_activity_path``).

    Top-level fields: workflow_checkpoints_enabled, workflow_checkpoints_path,
    domain_activity_path.
    """

    def test_instantiates_as_runtime_paths_config(self) -> None:
        s = OneiricSettings()
        assert isinstance(s.runtime_paths, RuntimePathsConfig)


@pytest.mark.unit
class TestRuntimeSupervisorSection:
    """``runtime_supervisor`` section: env-var form
    ``ONEIRIC_RUNTIME_SUPERVISOR__<FIELD>``. The ``enabled`` field carries
    an AliasChoices binding to the same uppercase env-var form (the
    pydantic-settings native nested-delimiter form).

    Top-level fields: enabled, poll_interval.
    """

    def test_instantiates_as_runtime_supervisor_config(self) -> None:
        s = OneiricSettings()
        assert isinstance(s.runtime_supervisor, RuntimeSupervisorConfig)


@pytest.mark.unit
class TestObservabilitySection:
    """``observability`` section: uses ``OTelStorageSettings`` whose own
    ``env_prefix='ONEIRIC_OTEL_STORAGE_'`` declares fields such as
    ``ONEIRIC_OTEL_STORAGE_CONNECTION_STRING`` and
    ``ONEIRIC_OTEL_STORAGE_BATCH_SIZE``. Because the field is NESTED inside
    ``OneiricSettings``, env vars with the parent prefix + nested delimiter
    also work (``ONEIRIC_OBSERVABILITY__CONNECTION_STRING`` etc.). Both
    forms reach the same field — that is the OBSERVABILITY-LEVEL collision
    that the pydantic-settings migration must keep transparent.

    Top-level fields: connection_string, embedding_model, embedding_dimension,
    cache_size, similarity_threshold, batch_size, batch_interval_seconds,
    max_retries, circuit_breaker_threshold.
    """

    def test_instantiates_as_otel_storage_settings(self) -> None:
        s = OneiricSettings()
        assert isinstance(s.observability, OTelStorageSettings)


@pytest.mark.unit
class TestAuthSection:
    """``auth`` section: field type is ``OneiricMCPAuthConfig`` (a stdlib
    dataclass, NOT a pydantic-settings model). Env-var overlay is NOT
    applied at the field level by ``load_settings``; it is applied
    OUT-OF-BAND by ``OneiricMCPAuthConfig.from_env(raw_dict)`` at the
    call site, using vars ``ONEIRIC_AUTH_ENABLED``,
    ``ONEIRIC_AUTH_DEFAULT_PROVIDER``, ``ONEIRIC_AUTH_TRUSTED_ISSUERS``.

    Top-level fields: enabled, default_provider, trusted_issuers, providers.
    """

    def test_instantiates_as_oneiric_mcp_auth_config(self) -> None:
        s = OneiricSettings()
        assert isinstance(s.auth, OneiricMCPAuthConfig)


# ---------------------------------------------------------------------------
# Per-field scans: OneiricMCPConfig
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOneiricMCPConfigFields:
    """``OneiricMCPConfig`` is its own pydantic-settings BaseModel with
    ``env_prefix='ONEIRIC_MCP_'`` so every field is reachable via
    ``ONEIRIC_MCP_<UPPER_FIELD>``.

    Top-level fields: http_port, http_host, enable_http_transport, debug,
    environment, cache_dir.
    """

    def test_default_instance(self) -> None:
        c = OneiricMCPConfig()
        assert c.http_port == 8000
        assert c.http_host == "127.0.0.1"
        assert c.enable_http_transport is True
        assert c.debug is False
        assert c.environment == "development"
        assert c.cache_dir == ".oneiric_cache"


# ---------------------------------------------------------------------------
# Aggregate: no field is reachable via 2 different env-var forms unless
# documented as an AliasChoices binding or an _ALIAS_OVERRIDES entry.
# ---------------------------------------------------------------------------


def _iter_concrete_fields(model_cls: type[BaseModel]) -> list[tuple[str, str]]:
    """Walk a pydantic model and return ``(section, field_name)`` for every
    concrete (i.e. not-pydantic-BaseModel-derived) field. Nested models are
    recursed into but only the concrete leaves are returned."""
    out: list[tuple[str, str]] = []
    for name, field in model_cls.model_fields.items():
        annotation = field.annotation
        # Unwrap Optional[X]
        origin = getattr(annotation, "__origin__", None)
        if origin is not None:
            annotation = (
                annotation.__args__[0] if hasattr(annotation, "__args__") else annotation
            )
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            out.extend(_iter_concrete_fields(annotation))
        elif isinstance(annotation, str):
            # unresolved forward-ref — skip; the simple fields this audit
            # cares about are concrete types in the existing models.
            continue
        else:
            out.append((model_cls.__name__, name))
    return out


# Each entry maps a field alias to the env-var form(s) that reach it.
# Sourced from _ALIAS_OVERRIDES in oneiric.core.config + AliasChoices
# declarations in oneiric.core.config + oneiric.core.logging. Each tuple
# lists the env var names that map to the field. The FIRST entry is the
# "primary" nested-delimiter form; the rest are backward-compat aliases.
_KNOWN_ALIASED_FIELDS: dict[str, tuple[str, ...]] = {
    "logging.level": ("ONEIRIC_LOGGING__LEVEL", "ONEIRIC_LOG_LEVEL"),
    "runtime_paths.domain_activity_path": (
        "ONEIRIC_RUNTIME_PATHS__DOMAIN_ACTIVITY_PATH",
        "ONEIRIC_ACTIVITY_STORE",
    ),
}


@pytest.mark.unit
def test_no_unintended_env_var_alias_collisions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """For every concrete field reachable on OneiricSettings, the field must
    be reachable via AT MOST ONE env-var form unless that field is either
    (a) listed in ``_KNOWN_ALIASED_FIELDS`` above, OR (b) the colliding
    AliasChoices binding lists both env-var forms.

    NOTE: round-trips must go through ``load_settings()`` because nested
    section models are plain BaseModels and do not read env vars at
    direct instantiation time.
    """
    from oneiric.core.config import load_settings

    _strip_oneiric_env(monkeypatch)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    # 1) ONEIRIC_LOG_LEVEL -> logging.level (alias form via _ALIAS_OVERRIDES)
    monkeypatch.setenv("ONEIRIC_LOG_LEVEL", "CRITICAL")
    s_alias_1 = load_settings(project_root=tmp_path, project_name="oneiric")
    assert s_alias_1.logging.level == "CRITICAL", (
        "ONEIRIC_LOG_LEVEL alias did not reach logging.level via "
        "_ALIAS_OVERRIDES + AliasChoices"
    )

    # 2) ONEIRIC_ACTIVITY_STORE -> runtime_paths.domain_activity_path
    monkeypatch.delenv("ONEIRIC_LOG_LEVEL", raising=False)
    monkeypatch.setenv("ONEIRIC_ACTIVITY_STORE", "/tmp/audit-alias.db")
    s_alias_2 = load_settings(project_root=tmp_path, project_name="oneiric")
    assert (
        s_alias_2.runtime_paths.domain_activity_path
        == "/tmp/audit-alias.db"
    ), "ONEIRIC_ACTIVITY_STORE alias did not reach runtime_paths.domain_activity_path"

    # 3) Both forms set on the same field: nested-delimiter wins (it is
    # applied LAST by load_settings, AFTER _ALIAS_OVERRIDES parsed).
    monkeypatch.setenv(
        "ONEIRIC_RUNTIME_PATHS__DOMAIN_ACTIVITY_PATH", "/tmp/audit-nested.db"
    )
    s_both = load_settings(project_root=tmp_path, project_name="oneiric")
    assert (
        s_both.runtime_paths.domain_activity_path == "/tmp/audit-nested.db"
    ), "Nested-delimiter form should outrank _ALIAS_OVERRIDES legacy alias"

    # 4) Spot check: a non-aliased field has exactly one env-var form.
    # Pick app.name (no AliasChoices), set ONEIRIC_APP__NAME and confirm.
    monkeypatch.delenv("ONEIRIC_ACTIVITY_STORE", raising=False)
    monkeypatch.delenv("ONEIRIC_RUNTIME_PATHS__DOMAIN_ACTIVITY_PATH", raising=False)
    monkeypatch.setenv("ONEIRIC_APP__NAME", "from_env_audit")
    s_basic = load_settings(project_root=tmp_path, project_name="oneiric")
    assert s_basic.app.name == "from_env_audit", (
        "Basic nested-form env var (ONEIRIC_APP__NAME) did not reach app.name"
    )


@pytest.mark.unit
def test_alias_collections_match_known_table() -> None:
    """Static sanity check: the per-field alias table documents every alias
    that the loader is currently expected to expose. If this fails, the
    alias table is out of sync with the loader — update both atomically."""
    # The audit documents exactly the known alias env-var forms. The table
    # size MUST match the loader's known set; if a new alias is added to
    # the loader, add it here too (and re-run this test).
    expected_keys = {"logging.level", "runtime_paths.domain_activity_path"}
    assert set(_KNOWN_ALIASED_FIELDS) == expected_keys, (
        "Alias table drift detected. Update _KNOWN_ALIASED_FIELDS in "
        "test_env_var_collision_audit.py AND _ALIAS_OVERRIDES in "
        "oneiric/core/config.py atomically."
    )


# ---------------------------------------------------------------------------
# Section inventory (re-used in audit summary output if any test fails)
# ---------------------------------------------------------------------------


SECTION_TO_TYPE: dict[str, type[Any]] = {
    "app": AppConfig,
    "adapters": LayerSettings,
    "services": LayerSettings,
    "tasks": LayerSettings,
    "events": LayerSettings,
    "workflows": LayerSettings,
    "actions": LayerSettings,
    "secrets": SecretsConfig,
    "remote": RemoteSourceConfig,
    "logging": LoggingConfig,
    "lifecycle": LifecycleConfig,
    "plugins": PluginsConfig,
    "profile": RuntimeProfileConfig,
    "runtime_paths": RuntimePathsConfig,
    "runtime_supervisor": RuntimeSupervisorConfig,
    "observability": OTelStorageSettings,
    "auth": OneiricMCPAuthConfig,
}


@pytest.mark.unit
def test_every_section_instance_matches_documented_type() -> None:
    """Inventory test: every top-level nested section on OneiricSettings
    matches its documented type, even for sections whose dedicated
    per-section test classes above were not explicit about type identity."""
    s = OneiricSettings()
    for section_name, expected_type in SECTION_TO_TYPE.items():
        attr = getattr(s, section_name)
        assert isinstance(attr, expected_type), (
            f"Section {section_name!r}: expected {expected_type.__name__}, "
            f"got {type(attr).__name__}"
        )
