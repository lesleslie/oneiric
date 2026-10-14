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
- ``OneiricManifestSource`` — reads adapter/pack manifests from the
  ``oneiric remote-sync`` cache. Returns an empty dict (no-op) when no
  manifest URL is configured.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
    YamlConfigSettingsSource,
)

# Top-level field names whose values are consumed out-of-band (via
# ``os.getenv`` at the CLI call site) rather than via pydantic-settings'
# env/YAML source chain. The EnvSettingsSource iteration in
# pydantic_settings.sources.base.__call__ calls ``_get_resolved_field_value``
# for every field and tries to JSON-decode complex values; an env var like
# ``ONEIRIC_PROFILE=serverless`` would raise ``SettingsError`` because
# ``"serverless"`` is not valid JSON. We intercept at ``get_field_value``
# so the env source returns ``None`` for these fields and the parent's
# ``if field_value is not None`` filter drops them from the merged data.
# The CLI then reads the env var via ``os.getenv`` and applies it via
# ``apply_profile_with_fallback``.
_AUTH_KEY = "auth"
_OUT_OF_BAND_ENV_FIELDS: frozenset[str] = frozenset({"auth", "profile"})

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
    """Return ``data`` with out-of-band-managed keys removed.

    Strips two top-level fields the CLI consumes via ``os.getenv``
    rather than via the pydantic-settings source chain:

    - ``auth`` — typed ``OneiricMCPAuthConfig`` dataclass (pydantic-
      settings cannot decorate a stdlib dataclass for env/YAML merge).
      The CLI applies ``ONEIRIC_AUTH_*`` overlay via
      ``OneiricMCPAuthConfig.from_env()`` at the call site.
    - ``profile`` — typed ``RuntimeProfileConfig``. ``ONEIRIC_PROFILE``
      is read directly via ``os.getenv`` in ``_initialize_state`` and
      applied via ``apply_profile_with_fallback``. Letting the env
      source attempt JSON-decode a plain string here raises
      ``SettingsError`` ("serverless" is not valid JSON), so we strip
      ``profile`` from env-source entirely. Phase 1 amendment.
    """
    for key in (_AUTH_KEY, "profile"):
        if key in data and isinstance(data[key], dict):
            data.pop(key, None)
    return data


class _AuthExcludingYamlSource(YamlConfigSettingsSource):
    """YamlConfigSettingsSource variant that drops out-of-band-managed keys.

    Strips ``auth:`` and ``profile:`` from the YAML payload so the
    typed (and/or dataclass-backed) fields aren't subjected to
    pydantic-settings' per-field env-var handling. See
    :func:`strip_auth` for the rationale; the prefix ``_Auth`` is
    historic — the function strips more than just ``auth``.
    """

    def __call__(self) -> dict[str, Any]:
        return strip_auth(super().__call__())


class _AuthExcludingEnvSource(EnvSettingsSource):
    """EnvSettingsSource variant that drops out-of-band-managed keys.

    Same rationale as :class:`_AuthExcludingYamlSource`. Class name
    is historic (kept for grep-ability vs. the legacy
    ``settings_customise_sources`` reference).

    The ``get_field_value`` override returns ``(None, field_name, False)``
    for fields in :data:`_OUT_OF_BAND_ENV_FIELDS` so the parent loop in
    :meth:`PydanticBaseSettingsSource.__call__` skips them via its
    ``if field_value is not None`` filter (base.py:614). Doing the
    strip in ``__call__`` post-hoc is too late — ``super().__call__``
    raises ``SettingsError`` during ``prepare_field_value`` when env
    vars like ``ONEIRIC_PROFILE=serverless`` fail JSON decoding for a
    complex (BaseModel-typed) field.
    """

    def get_field_value(  # type: ignore[override]
        self, field: Any, field_name: str
    ) -> tuple[Any, str, bool]:
        if field_name in _OUT_OF_BAND_ENV_FIELDS:
            return None, field_name, False
        return super().get_field_value(field, field_name)

    def __call__(self) -> dict[str, Any]:
        """Post-process the env-source payload to strip nested paths.

        ``get_field_value`` returning ``None`` only blocks the top-level
        ``auth`` / ``profile`` field. pydantic-settings' nested-delimiter
        resolution still walks the auth dataclass for subkeys
        (``ONEIRIC_AUTH__ENABLED`` → ``{"auth": {"enabled": "true"}}``),
        so we strip the keys post-hoc. See plan §Phase 1 task 1.10
        ("auth env vars handled at from_env()") — the post-hoc strip
        is what makes that contract observable.
        """
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

    def __init__(self, settings_cls: type[BaseSettings], env_prefix: str = "") -> None:
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


# 2026-10-12 (Phase E1, Plan 2): canonical prefix for substrate env vars.
# The substrate spec §5.3 declares double-underscore field names
# (``cache__max_entries``, ``warm__pg_url``, etc.). pydantic-settings
# nested-delimiter resolution cannot natively route
# ``ONEIRIC__SUBSTRATE__CACHE__MAX_ENTRIES=5`` to the leaf field
# ``cache__max_entries`` because the parent's ``env_nested_delimiter='__'``
# splits the suffix during ``EnvSettingsSource.explode_env_vars`` and
# the resulting ``cache`` / ``max_entries`` tokens do not match any
# single field name in ``SubstrateSettings``. The custom source below
# is the explicit Phase E1 fix — it short-circuits the broken nested
# walk by scanning the same env vars and mapping them straight into
# ``{"substrate": {<field>: <value>}}``. This is purely additive; the
# pydantic-settings chain still runs (so non-substrate env vars behave
# as before) and the canonical field-with-double-underscore surface
# stays intact.
_SUBSTRATE_ENV_PREFIX: str = "ONEIRIC__SUBSTRATE__"


class _SubstrateEnvSource(PydanticBaseSettingsSource):
    """Routes ``ONEIRIC__SUBSTRATE__<field>`` env vars to ``SubstrateSettings``.

    Pure-additive Phase E1 (Plan 2) source. Bypasses pydantic-settings'
    nested-delimiter walk because the ``__`` delimiter would otherwise
    re-split field names that themselves contain ``__`` (e.g.
    ``cache__max_entries`` resolves to two path tokens ``cache`` and
    ``max_entries``, neither of which matches the literal field). See
    the comment on :data:`_SUBSTRATE_ENV_PREFIX` for the full rationale.

    Precedence: slotted into the chain AFTER the parent's EnvSettingsSource
    (so non-substrate vars still route through the normal walk) but
    BEFORE the YAML layers (so explicit env vars still win over the
    substrate YAML section, matching the legacy ``_env_overrides``
    ordering).

    Field-name mapping: env suffix (lowercased) maps 1:1 to the
    double-underscore field name on ``SubstrateSettings``. Unknown
    env suffixes are silently ignored (caller's responsibility to
    detect them via pydantic validation on construction).
    """

    def __init__(self, settings_cls: type[BaseSettings]) -> None:
        super().__init__(settings_cls)

    def get_field_value(  # type: ignore[override]
        self, field: Any, field_name: str
    ) -> tuple[Any, str, bool]:
        # We override ``__call__`` to do bulk collection, so
        # ``get_field_value`` is a no-op for the per-field iteration
        # in the base class.
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        prefix = _SUBSTRATE_ENV_PREFIX
        result: dict[str, Any] = {}
        for env_key, env_value in os.environ.items():
            if not env_key.startswith(prefix):
                continue
            suffix = env_key[len(prefix) :].lower()
            if not suffix:
                continue
            substrate_section = result.setdefault("substrate", {})
            if isinstance(substrate_section, dict):
                substrate_section[suffix] = env_value
        return result


class OneiricManifestSource(PydanticBaseSettingsSource):
    """Read adapter/pack manifests from the ``oneiric remote-sync`` cache.

    Returns an empty dict when no cache_dir is configured. When a
    cache_dir is set (via the per-project ``oneiric_cache_dir`` class
    attribute populated by ``build_oneiric_settings._Project``), the
    source reads the cached manifest file at
    ``{cache_dir}/manifest.yaml`` and returns its parsed payload as a
    flat dict.

    The cache layout is owned by ``oneiric.runtime.remote_sync`` and
    follows the contract documented at
    ``docs/specs/2026-10-11-remote-sync-cache-layout.md`` (planned;
    the cache writer is the only producer).

    When ``cache_dir`` is ``None`` (the default until a project opts
    in by setting ``oneiric_cache_dir`` on its subclass), the source
    is a no-op and returns ``{}`` — so the chain slot is reserved but
    inert. This avoids the substrate-compat shim rot pattern (see
    ``feedback-substrate-compat-shim-rot.md``): the source is
    deliberately wired but explicitly opt-in.
    """

    def __init__(
        self, settings_cls: type[BaseSettings], cache_dir: Path | None = None
    ) -> None:
        super().__init__(settings_cls)
        # If no explicit cache_dir was passed, fall back to a
        # per-subclass ``oneiric_cache_dir`` ClassVar (set by
        # ``build_oneiric_settings._Project`` or a downstream caller).
        if cache_dir is None:
            cache_dir = getattr(settings_cls, "oneiric_cache_dir", None)
        self._cache_dir = cache_dir

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        cache_dir = self._cache_dir
        if cache_dir is None:
            return {}
        manifest_path = Path(cache_dir) / "manifest.yaml"
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
    settings_cls: type[BaseSettings],
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
    xdg_dir = (
        Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser() / project_name
    )
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


class _AuthExcludingDotEnvSource(DotEnvSettingsSource):
    """DotEnvSettingsSource variant that drops out-of-band-managed keys.

    Parity with :class:`_AuthExcludingYamlSource` and
    :class:`_AuthExcludingEnvSource`. Currently a no-op because
    ``OneiricSettings.model_config`` does not declare ``env_file``;
    defensive in case a future change re-enables ``.env`` loading —
    without this wrapper, the ``auth:`` block in a project ``.env``
    would re-enter the merge path.
    """

    def __call__(self) -> dict[str, Any]:
        return strip_auth(super().__call__())


__all__ = [
    "OneiricManifestSource",
    "_AliasOverridesEnvSource",
    "_AuthExcludingDotEnvSource",
    "_AuthExcludingEnvSource",
    "_AuthExcludingYamlSource",
    "_SubstrateEnvSource",
    "build_yaml_layers",
    "strip_auth",
]
