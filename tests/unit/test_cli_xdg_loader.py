"""Tests for the Oneiric CLI XDG-loader migration (REQ-CLI-XDG-001..004).

Covers the contract between ``OneiricSettings.auth`` (typed in Phase 2)
and ``oneiric.cli.mcp._load_auth_from_settings`` (rewritten in Phase 3):
  - XDG ``auth:`` block (typed) round-trips through ``load_settings``.
  - Env vars ``ONEIRIC_AUTH_*`` still overlay at the call site via
    ``OneiricMCPAuthConfig.from_env``.
  - The renamed dataclass field ``providers`` binds the YAML ``providers:``
    block (Phase 2 follow-on rename).

Pre-existing ``tests/unit/test_load_settings_xdg.py`` covers the generic
XDG layering mechanism. This file focuses on the CLI/auth contract that
the migration exposed.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from oneiric.cli.mcp import _load_auth_from_settings
from oneiric.core.config import load_settings
from oneiric.mcp.config import OneiricMCPAuthConfig


def _clear_oneiric_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip every ONEIRIC_* env var that could leak into the test."""
    for key in (
        "ONEIRIC_CONFIG",
        "ONEIRIC_ACTIVITY_STORE",
        "ONEIRIC_LOG_LEVEL",
        "ONEIRIC_RUNTIME_SUPERVISOR__ENABLED",
        "ONEIRIC_AUTH_ENABLED",
        "ONEIRIC_AUTH_DEFAULT_PROVIDER",
        "ONEIRIC_AUTH_TRUSTED_ISSUERS",
    ):
        monkeypatch.delenv(key, raising=False)


class TestSettingsAuthTyped:
    """Phase 2: ``OneiricSettings.auth`` is ``OneiricMCPAuthConfig``."""

    def test_auth_is_typed_when_xdg_has_no_auth_block(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No ``auth:`` in any layer -> defaults via typed field, NOT dict."""
        _clear_oneiric_env(monkeypatch)
        xdg_dir = tmp_path / "xdg" / "oneiric"
        xdg_dir.mkdir(parents=True)
        (xdg_dir / "local.yaml").write_text("logging:\n  level: INFO\n")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        s = load_settings(project_root=tmp_path, project_name="oneiric")
        assert isinstance(s.auth, OneiricMCPAuthConfig)
        assert s.auth.enabled is False
        assert s.auth.default_provider is None
        assert s.auth.trusted_issuers == []
        assert s.auth.providers == {}

    def test_xdg_auth_block_flows_through(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """XDG layer ``auth:`` overrides typed defaults."""
        _clear_oneiric_env(monkeypatch)
        xdg_dir = tmp_path / "xdg" / "oneiric"
        xdg_dir.mkdir(parents=True)
        (xdg_dir / "local.yaml").write_text(
            "auth:\n"
            "  enabled: true\n"
            "  default_provider: jwt\n"
            "  trusted_issuers:\n"
            '    - "issuer-a"\n'
            '    - "issuer-b"\n'
            "  providers:\n"
            "    jwt:\n"
            "      secret: foo\n"
            "      audience: bar\n"
        )
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        s = load_settings(project_root=tmp_path, project_name="oneiric")
        assert isinstance(s.auth, OneiricMCPAuthConfig)
        assert s.auth.enabled is True
        assert s.auth.default_provider == "jwt"
        assert s.auth.trusted_issuers == ["issuer-a", "issuer-b"]
        # Phase 2 follow-on rename: YAML key 'providers' binds to the
        # dataclass field named 'providers' (not 'provider_configs').
        assert s.auth.providers == {
            "jwt": {"secret": "foo", "audience": "bar"},
        }

    def test_provider_configs_key_is_no_longer_recognised(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression guard: the pre-migration dataclass field name
        ``provider_configs`` is gone. Any operator still using the old
        name in their YAML (improbable — it was only ever read via
        ``from_env()``, never via Pydantic binding) gets an empty dict
        so they know to rename.
        """
        _clear_oneiric_env(monkeypatch)
        xdg_dir = tmp_path / "xdg" / "oneiric"
        xdg_dir.mkdir(parents=True)
        (xdg_dir / "local.yaml").write_text(
            "auth:\n"
            "  enabled: true\n"
            "  provider_configs:\n"
            "    jwt:\n"
            "      secret: foo\n"
        )
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        s = load_settings(project_root=tmp_path, project_name="oneiric")
        assert s.auth.providers == {}  # old name silently dropped

    def test_no_pydantic_extra_for_auth(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``auth`` is no longer in ``__pydantic_extra__`` after Phase 2.

        The pre-migration setup used ``extra='allow'`` so the live
        YAML key showed up in extras as an unvalidated dict. With the
        typed field, Pydantic binds the keys and stores nothing
        under extras for ``auth``.
        """
        _clear_oneiric_env(monkeypatch)
        xdg_dir = tmp_path / "xdg" / "oneiric"
        xdg_dir.mkdir(parents=True)
        (xdg_dir / "local.yaml").write_text(
            "auth:\n  enabled: true\n"
        )
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        s = load_settings(project_root=tmp_path, project_name="oneiric")
        extras = getattr(s, "__pydantic_extra__", {}) or {}
        assert "auth" not in extras


class TestCliLoadAuthFromSettings:
    """Phase 3: ``_load_auth_from_settings()`` reads via ``load_settings()``.

    These tests exercise the public contract that the FastMCP server
    boot path relies on. ``_load_auth_from_settings`` is called with no
    args; the function internally calls
    ``load_settings(project_name="oneiric", project_root=<oneiric/core>)``.
    """

    def test_returns_typed_auth_when_no_layers_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No XDG layer, no env vars -> trusted-network defaults."""
        _clear_oneiric_env(monkeypatch)
        # Empty HOME so no ~/.config/oneiric/local.yaml exists.
        import tempfile

        with tempfile.TemporaryDirectory() as empty_home:
            monkeypatch.setenv("HOME", empty_home)
            # Also clear XDG_CONFIG_HOME so /etc/xdg or default doesn't leak.
            monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
            cfg = _load_auth_from_settings()
            assert isinstance(cfg, OneiricMCPAuthConfig)
            assert cfg.enabled is False
            assert cfg.default_provider is None
            assert cfg.trusted_issuers == []
            assert cfg.providers == {}

    def test_env_var_overrides_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``ONEIRIC_AUTH_ENABLED=true`` wins over the YAML ``auth.enabled: false``.

        Env-var overlay is applied at the CLI call site via
        ``OneiricMCPAuthConfig.from_env(vars(settings.auth))`` per
        REQ-006. The YAML value flows through ``settings.auth.enabled``,
        then ``from_env`` checks the env var and wins.
        """
        _clear_oneiric_env(monkeypatch)
        xdg_dir = tmp_path / "xdg" / "oneiric"
        xdg_dir.mkdir(parents=True)
        (xdg_dir / "local.yaml").write_text(
            "auth:\n  enabled: false\n  default_provider: yaml-provider\n"
        )
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.setenv("ONEIRIC_AUTH_ENABLED", "true")
        monkeypatch.setenv("ONEIRIC_AUTH_DEFAULT_PROVIDER", "env-provider")
        cfg = _load_auth_from_settings()
        assert cfg.enabled is True
        assert cfg.default_provider == "env-provider"

    def test_trusted_issuers_csv_parses(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``ONEIRIC_AUTH_TRUSTED_ISSUERS=a,b,c`` -> list[str]."""
        _clear_oneiric_env(monkeypatch)
        xdg_dir = tmp_path / "xdg" / "oneiric"
        xdg_dir.mkdir(parents=True)
        (xdg_dir / "local.yaml").write_text("auth:\n  enabled: false\n")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.setenv("ONEIRIC_AUTH_TRUSTED_ISSUERS", "alpha,beta,gamma")
        cfg = _load_auth_from_settings()
        assert cfg.trusted_issuers == ["alpha", "beta", "gamma"]

    def test_yaml_provider_configs_round_trip(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``auth.providers.<name>: <config>`` flows through end-to-end.

        The Phase 2 follow-on rename aligns the YAML key with the
        dataclass field name (``providers``). This test pins the
        end-to-end behaviour so a future refactor that reverts the
        rename trips this test.
        """
        _clear_oneiric_env(monkeypatch)
        xdg_dir = tmp_path / "xdg" / "oneiric"
        xdg_dir.mkdir(parents=True)
        (xdg_dir / "local.yaml").write_text(
            "auth:\n"
            "  enabled: true\n"
            "  providers:\n"
            "    jwt:\n"
            "      secret: x\n"
            "    oidc:\n"
            "      issuer: y\n"
        )
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        cfg = _load_auth_from_settings()
        assert cfg.providers == {
            "jwt": {"secret": "x"},
            "oidc": {"issuer": "y"},
        }


class TestNoLegacyPath:
    """Phase 3+4: legacy ``~/.oneiric/settings.yaml`` is no longer read."""

    def test_legacy_path_ignored_when_xdg_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Even if ``~/.oneiric/settings.yaml`` exists, the CLI ignores it.

        Regression guard for the Phase 3 cutover — the operator must
        migrate by hand (``cp ~/.oneiric/settings.yaml
        ~/.config/oneiric/local.yaml``). Pre-1.0 software per
        ``feedback-no-backwards-compat-pre-1.0.md``.
        """
        _clear_oneiric_env(monkeypatch)
        # Plant a legacy file with values that WOULD have set enabled=True.
        legacy_dir = tmp_path / ".oneiric"
        legacy_dir.mkdir()
        (legacy_dir / "settings.yaml").write_text(
            "auth:\n  enabled: true\n"
        )
        # And an empty XDG dir (no auth block).
        xdg_dir = tmp_path / "xdg" / "oneiric"
        xdg_dir.mkdir(parents=True)
        (xdg_dir / "local.yaml").write_text("")
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        cfg = _load_auth_from_settings()
        # If the legacy reader were still active, this would be True.
        assert cfg.enabled is False
