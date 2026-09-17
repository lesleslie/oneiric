"""Tests for oneiric.mcp.config — OneiricMCPAuthConfig + loaders (REQ-006)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from oneiric.mcp.config import OneiricMCPAuthConfig, load_auth_config


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
    """validate_auth_config should reject enabled=True with no providers."""
    cfg = OneiricMCPAuthConfig(
        enabled=True,
        default_provider="missing",
        trusted_issuers=["acme"],
    )
    # validate_auth_config raises when enabled=True but no provider instances are available
    with pytest.raises(Exception):  # noqa: PT011 - exact exception type is mcp-common's contract
        load_auth_config(cfg, provider_factories={"acme": lambda: None})


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
    from oneiric.mcp.config import load_yaml_auth_section
    raw = load_yaml_auth_section(settings_file)
    cfg = OneiricMCPAuthConfig.from_env(raw)
    assert cfg.enabled is True
    assert cfg.default_provider == "from-yaml"
    assert cfg.trusted_issuers == ["acme"]


def test_yaml_missing_file_returns_empty_dict(tmp_path, monkeypatch) -> None:
    """When settings/oneiric.yaml doesn't exist, loader returns {} (not error).

    The error path is "settings file exists but is malformed" → fail loud.
    The "no settings file" path is the trusted-network default → silent.
    """
    from oneiric.mcp.config import load_yaml_auth_section
    missing = tmp_path / "does-not-exist.yaml"
    raw = load_yaml_auth_section(missing)
    assert raw == {}
