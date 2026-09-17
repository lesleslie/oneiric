"""Tests for oneiric.mcp.config — OneiricMCPAuthConfig + loaders (REQ-006)."""
from __future__ import annotations

import pytest

from oneiric.mcp.config import (
    OneiricMCPAuthConfig,
    load_auth_config,
    load_yaml_auth_section,
)


def test_default_config_is_disabled() -> None:
    cfg = OneiricMCPAuthConfig()
    assert cfg.enabled is False
    assert cfg.default_provider is None
    assert cfg.trusted_issuers == []


def test_load_auth_config_when_disabled() -> None:
    """When auth is disabled, no providers are needed; config is minimal."""
    cfg = OneiricMCPAuthConfig(enabled=False)
    auth_config, providers = load_auth_config(cfg)
    assert auth_config.enabled is False
    assert providers == {}


def test_load_auth_config_when_enabled_but_no_provider_raises(monkeypatch) -> None:
    """Security-critical path: enabled=True with no provider_factories must fail loud.

    The operator-facing error is a RuntimeError from the production loader,
    not a downstream TypeError. This guards the REQ-006 contract that
    operators get a clear, actionable message when they enable auth but
    forget to wire provider factories in the production settings loader.
    """
    cfg = OneiricMCPAuthConfig(
        enabled=True,
        default_provider="missing",
        trusted_issuers=["acme"],
    )
    with pytest.raises(RuntimeError, match="provider_factories"):
        load_auth_config(cfg)


def test_load_auth_config_reads_env_var_enabled(monkeypatch) -> None:
    """Env-var override flips enabled=True when ONEIRIC_AUTH_ENABLED=true."""
    monkeypatch.setenv("ONEIRIC_AUTH_ENABLED", "true")
    cfg = OneiricMCPAuthConfig.from_env({})
    assert cfg.enabled is True


def test_load_auth_config_reads_env_var_trusted_issuers(monkeypatch) -> None:
    monkeypatch.setenv("ONEIRIC_AUTH_ENABLED", "true")
    monkeypatch.setenv("ONEIRIC_AUTH_TRUSTED_ISSUERS", "acme,other")
    cfg = OneiricMCPAuthConfig.from_env({})
    assert cfg.trusted_issuers == ["acme", "other"]


# --- pr-test-analyzer env-var-vs-YAML precedence tests (REQ-006) ---


def test_env_var_overrides_yaml_setting(monkeypatch) -> None:
    """Env vars beat YAML (operator precedence)."""
    monkeypatch.setenv("ONEIRIC_AUTH_ENABLED", "true")
    # YAML has no `default_provider` key — so the env var (also absent)
    # leaves it at the dataclass default of None. Proves env wins and
    # YAML is fall-through for unset fields.
    raw_yaml = {"enabled": False}
    cfg = OneiricMCPAuthConfig.from_env(raw_yaml)
    assert cfg.enabled is True  # env win
    assert cfg.default_provider is None  # no YAML key, no env var


def test_yaml_setting_wins_when_env_var_absent(monkeypatch) -> None:
    """YAML is the source of truth when no env var overrides it."""
    monkeypatch.delenv("ONEIRIC_AUTH_ENABLED", raising=False)
    raw_yaml = {"enabled": True, "default_provider": "from-yaml", "trusted_issuers": ["acme"]}
    cfg = OneiricMCPAuthConfig.from_env(raw_yaml)
    assert cfg.enabled is True
    assert cfg.default_provider == "from-yaml"
    assert cfg.trusted_issuers == ["acme"]


def test_yaml_loaded_from_settings_file(tmp_path, monkeypatch) -> None:
    """The CLI loader must read settings/oneiric.yaml — not silently ignore it.

    silent-failure-hunter finding #2 (critical): the spec promises YAML
    config but no task actually loaded it. This test pins the contract.
    """
    import yaml as _yaml
    settings_dir = tmp_path
    settings_file = settings_dir / "oneiric.yaml"
    settings_file.write_text(_yaml.safe_dump({
        "auth": {
            "enabled": True,
            "default_provider": "from-yaml",
            "trusted_issuers": ["acme"],
        }
    }))
    monkeypatch.delenv("ONEIRIC_AUTH_ENABLED", raising=False)
    raw = load_yaml_auth_section(settings_file)
    cfg = OneiricMCPAuthConfig.from_env(raw)
    assert cfg.enabled is True
    assert cfg.default_provider == "from-yaml"
    assert cfg.trusted_issuers == ["acme"]


def test_yaml_missing_file_returns_empty_dict(tmp_path) -> None:
    """When settings/oneiric.yaml doesn't exist, loader returns {} (not error).

    The error path is "settings file exists but is malformed" → fail loud.
    The "no settings file" path is the trusted-network default → silent.
    """
    missing = tmp_path / "does-not-exist.yaml"
    raw = load_yaml_auth_section(missing)
    assert raw == {}


# --- load_yaml_auth_section error-contract tests (REQ-006) ---


def test_yaml_parse_error_raises(tmp_path) -> None:
    """Malformed YAML must fail loud with a clear 'Failed to parse' message.

    Guards silent-failure-hunter finding #2: a syntactically broken settings
    file should never silently degrade to 'auth disabled' — operators must
    see the parse error so they fix it.
    """
    settings_file = tmp_path / "bad.yaml"
    settings_file.write_text("enabled: [unclosed\n")
    with pytest.raises(RuntimeError, match="(?i)Failed to parse|YAML"):
        load_yaml_auth_section(settings_file)


def test_yaml_non_dict_top_level_raises(tmp_path) -> None:
    """Top-level YAML must be a mapping; a list (or scalar) must fail loud.

    Operators regularly mistake `oneiric.yaml` for a flat list of settings;
    catching that shape here gives them a one-line fix instead of a silent
    'auth disabled' boot.
    """
    settings_file = tmp_path / "list.yaml"
    settings_file.write_text("- list\n- not\n- dict\n")
    with pytest.raises(RuntimeError, match="YAML mapping"):
        load_yaml_auth_section(settings_file)


def test_yaml_auth_section_non_dict_raises(tmp_path) -> None:
    """The 'auth:' section must itself be a mapping; a scalar must fail loud.

    An operator who writes `auth: "jwt"` (intending a string provider name)
    would otherwise get a confusing downstream ProviderConfig error. The
    shape check here turns that into a one-line YAML fix.
    """
    settings_file = tmp_path / "scalar_auth.yaml"
    settings_file.write_text("auth: not a dict\n")
    with pytest.raises(RuntimeError, match="auth:"):
        load_yaml_auth_section(settings_file)
