"""Custom pydantic-settings sources for Oneiric's substrate settings loader.

Provides custom sources wired into OneiricSettings'
``settings_customise_sources`` chain:

- ``_AliasOverridesEnvSource`` — translates the legacy single-underscore
  alias env vars (``ONEIRIC_ACTIVITY_STORE``, ``ONEIRIC_LOG_LEVEL``) to
  the nested target fields. The legacy hand-rolled loader did this via
  ``_env_overrides`` / ``_ALIAS_OVERRIDES``. Under pydantic-settings'
  standard ``EnvSettingsSource`` the AliasChoices pre-wired on the
  target fields does NOT route these env vars (the framework constructs
  env names from ``env_prefix`` + field path; AliasChoices only
  affects ``model_validate`` alias lookup, not env-var construction).
  This custom source is slotted at the highest priority (after
  ``init_settings``) so the alias wins over YAML layers, matching the
  legacy precedence.
- ``_AuthExcludingYamlSource`` — wraps ``YamlConfigSettingsSource`` and
  strips the ``auth:`` key. ``OneiricMCPAuthConfig`` is a stdlib
  ``@dataclass`` (not a Pydantic model); pydantic-settings cannot
  decorate it for env-var / YAML merge. The CLI applies the env-var
  overlay via ``OneiricMCPAuthConfig.from_env()`` at the call site.
- ``_AuthExcludingEnvSource`` — wraps ``EnvSettingsSource`` and applies
  the same ``auth:`` exclusion.
- ``BodaiManifestSource`` — reads adapter/pack manifests from the
  ``oneiric remote-sync`` cache. Returns an empty dict (no-op) when no
  manifest URL is configured.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic_settings import (
    EnvSettingsSource,
    PydanticBaseSettingsSource,
    YamlConfigSettingsSource,
)

_AUTH_KEY = "auth"

# Legacy single-underscore alias env vars → nested target field paths.
# The key is the env-var suffix (after the per-project prefix; e.g.,
# ``ACTIVITY_STORE`` for ``ONEIRIC_ACTIVITY_STORE``); the value is the
# nested target path inside the settings instance. This is the
# pydantic-settings equivalent of the legacy ``_ALIAS_OVERRIDES`` dict
# at oneiric/core/config.py:800-805.
#
# Phase 0 audit (_ALIAS_OVERRIDES section in the migration plan)
# confirmed exactly two aliases: ACTIVITY_STORE and LOG_LEVEL. The
# pre-wired AliasChoices on the target fields are dead config under
# pydantic-settings' standard EnvSettingsSource (which constructs env
# names from field path + prefix); this custom source is the active
# path. See Phase 4 task 4.7b for documentation refresh.
_LEGACY_ALIAS_OVERRIDES: dict[str, dict[str, Any]] = {
    "ACTIVITY_STORE": {"runtime_paths": {"domain_activity_path": ...}},  # sentinel
    "LOG_LEVEL": {"logging": {"level": ...}},  # sentinel
}


def strip_auth(data: dict[str, Any]) -> dict[str, Any]:
    """Return ``data`` with the ``auth`` key removed (if it's a dict)."""
    if _AUTH_KEY in data and isinstance(data[_AUTH_KEY], dict):
        data.pop(_AUTH_KEY, None)
    return data


class _AuthExcludingYamlSource(YamlConfigSettingsSource):
    """YamlConfigSettingsSource variant that drops the ``auth:`` key."""

    def __call__(self) -> dict[str, Any]:
        return strip_auth(super().__call__())


class _AuthExcludingEnvSource(EnvSettingsSource):
    """EnvSettingsSource variant that drops the ``auth:`` key."""

    def __call__(self) -> dict[str, Any]:
        return strip_auth(super().__call__())


class _AliasOverridesEnvSource(EnvSettingsSource):
    """Routes legacy single-underscore alias env vars to nested target fields.

    Matches the legacy ``_ALIAS_OVERRIDES`` precedence (after
    ``init_settings``, before YAML layers). The alias env vars are
    pre-wired on the target fields via ``AliasChoices`` so
    ``model_validate`` can also resolve them outside this override path;
    this source ensures they fire at construction time too.

    Unlike ``_AuthExcludingEnvSource``, this source returns ONLY the
    alias-derived data (not the full env-var payload). The full env
    source runs separately as part of pydantic-settings' normal
    chain.
    """

    def __init__(self, settings_cls: type, env_prefix: str = "") -> None:
        super().__init__(settings_cls, env_prefix=env_prefix)

    def __call__(self) -> dict[str, Any]:
        prefix = self.env_prefix
        result: dict[str, Any] = {}
        for alias_suffix, target_template in _LEGACY_ALIAS_OVERRIDES.items():
            for env_key, env_value in os.environ.items():
                if not env_key.startswith(prefix):
                    continue
                suffix = env_key[len(prefix) :]
                if suffix != alias_suffix:
                    continue
                # Place the value under the nested path.
                for section, fields in target_template.items():
                    section_dict = result.setdefault(section, {})
                    if isinstance(section_dict, dict):
                        for field in fields:
                            section_dict[field] = env_value
        return result


class BodaiManifestSource(PydanticBaseSettingsSource):
    """Read adapter/pack manifests from the ``oneiric remote-sync`` cache.

    Returns an empty dict when no manifest URL is configured. When a
    manifest URL is set, the source reads the cached manifest file
    under the project's cache directory and returns its parsed payload
    as a flat dict.

    The cache layout is owned by ``oneiric.runtime.remote_sync`` and
    follows the contract documented at
    ``docs/specs/2026-10-11-remote-sync-cache-layout.md`` (planned;
    the cache writer is the only producer).
    """

    def __init__(self, settings_cls: type, cache_dir: Path | None = None) -> None:
        super().__init__(settings_cls)
        self._cache_dir = cache_dir

    def get_field_value(
        self, field: Any, field_name: str
    ) -> tuple[Any, str, bool]:
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        cache_dir = self._cache_dir
        if cache_dir is None:
            return {}
        manifest_path = cache_dir / "manifest.yaml"
        if not manifest_path.exists():
            return {}
        try:
            import yaml

            payload = yaml.safe_load(manifest_path.read_text())
        except Exception:  # noqa: BLE001
            return {}
        if not isinstance(payload, dict):
            return {}
        return dict(payload)


def build_yaml_layers(
    settings_cls: type,
    project_root_path: Path,
    project_name: str,
) -> list[PydanticBaseSettingsSource]:
    """Construct the 5 YAML layer sources for ``settings_customise_sources``.

    Layers, in returned order (pydantic-settings will put them in the
    chain after higher-priority sources): XDG local → XDG config →
    project local → project yaml → project yml. Only existing files
    are wrapped; missing files are silently skipped (pydantic-settings
    ``YamlConfigSettingsSource`` defaults to a no-op on missing files).
    """
    xdg_dir = Path(
        os.environ.get("XDG_CONFIG_HOME", "~/.config")
    ).expanduser() / project_name
    candidates = (
        xdg_dir / "local.yaml",
        xdg_dir / "config.yaml",
        project_root_path / "settings" / "local.yaml",
        project_root_path / "settings" / f"{project_name}.yaml",
        project_root_path / "settings" / f"{project_name}.yml",
    )
    layers: list[PydanticBaseSettingsSource] = []
    for path in candidates:
        if path.exists():
            layers.append(
                _AuthExcludingYamlSource(settings_cls, yaml_file=path, deep_merge=True)
            )
    return layers


__all__ = [
    "BodaiManifestSource",
    "_AliasOverridesEnvSource",
    "_AuthExcludingYamlSource",
    "_AuthExcludingEnvSource",
    "build_yaml_layers",
    "strip_auth",
]