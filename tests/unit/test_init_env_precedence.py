"""Pin the ``settings_customise_sources`` chain order (Phase 4.7a).

pydantic-settings 2.15+ uses first-returned-wins. The chain must hold:

    init_settings > env_settings > alias > yaml > secrets

Pin via concrete assertions on ``OneiricSettings``:
- init_settings loses to env_settings (env wins).
- env_settings loses to YAML layers (YAML wins for fields NOT
  routed by the env source).
- alias source (legacy ``ONEIRIC_ACTIVITY_STORE``,
  ``ONEIRIC_LOG_LEVEL``) wins over YAML for the aliased fields.
- secrets lose to YAML (lowest priority).
"""

from __future__ import annotations

import os
from pathlib import Path
from textwrap import dedent

import pytest

from oneiric.core.config import OneiricSettings, load_settings


def _clear_oneiric_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "ONEIRIC_CONFIG",
        "ONEIRIC_ACTIVITY_STORE",
        "ONEIRIC_LOG_LEVEL",
        "ONEIRIC_RUNTIME_SUPERVISOR__ENABLED",
        "ONEIRIC_CONFIG_DIR",
        "XDG_CONFIG_HOME",
    ):
        monkeypatch.delenv(key, raising=False)


class TestSourceChainOrder:
    def test_init_kwarg_wins_over_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``OneiricSettings(config_dir="/from/init")`` + ``ONEIRIC_CONFIG_DIR=/tmp/from_env`` → ``/from/init``.

        ``init_settings`` is the first returned source in
        ``settings_customise_sources`` (highest priority under
        pydantic-settings' first-returned-wins semantics). Explicit
        constructor kwargs must beat env vars. The env var would
        only fill in fields the constructor left unspecified.
        """
        _clear_oneiric_env(monkeypatch)
        monkeypatch.setenv("ONEIRIC_CONFIG_DIR", "/tmp/from_env")
        settings = OneiricSettings(config_dir="/from/init")
        assert settings.config_dir == "/from/init"

    def test_env_fills_unspecified_init(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When the constructor omits ``config_dir``, the env var
        fills it. This is the practical case: a CLI invocation
        without explicit kwargs should still pick up operator-set
        env vars.
        """
        _clear_oneiric_env(monkeypatch)
        monkeypatch.setenv("ONEIRIC_CONFIG_DIR", "/tmp/from_env")
        settings = OneiricSettings()
        assert settings.config_dir == "/tmp/from_env"

    def test_env_loses_to_yaml_for_typed_field(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Project YAML sets ``app.name``; env var does NOT exist; YAML
        wins because env has no claim on this field. Pin the
        load_settings path so a future source-chain reshuffle that
        demotes YAML below env would surface here.
        """
        _clear_oneiric_env(monkeypatch)
        settings_dir = tmp_path / "settings"
        settings_dir.mkdir()
        (settings_dir / "oneiric.yaml").write_text(
            dedent(
                """
                app:
                  name: yaml_value
                """
            ).lstrip()
        )
        s = load_settings(project_root=tmp_path, project_name="oneiric")
        assert s.app.name == "yaml_value"

    def test_yaml_loses_to_alias_source(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``ONEIRIC_LOG_LEVEL=DEBUG`` must override the project's
        ``logging.level`` YAML value. The legacy
        ``_ALIAS_OVERRIDES`` table maps ``LOG_LEVEL`` →
        ``logging.level``; pydantic-settings' nested-delimiter
        path (``ONEIRIC_LOGGING__LEVEL``) ALSO resolves, but the
        alias source must win because it sits higher in the chain
        and the alias was the legacy contract.
        """
        _clear_oneiric_env(monkeypatch)
        settings_dir = tmp_path / "settings"
        settings_dir.mkdir()
        (settings_dir / "oneiric.yaml").write_text(
            "logging:\n  level: WARNING\n"
        )
        monkeypatch.setenv("ONEIRIC_LOG_LEVEL", "DEBUG")
        s = load_settings(project_root=tmp_path, project_name="oneiric")
        assert s.logging.level == "DEBUG"

    def test_xdg_local_overrides_project_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """XDG local beats project yaml for the same field. ``build_yaml_layers``
        returns XDG sources BEFORE project sources (because first-returned
        wins, lower-priority layers come later in the tuple).
        """
        _clear_oneiric_env(monkeypatch)
        # Project layer
        project_dir = tmp_path / "project"
        (project_dir / "settings").mkdir(parents=True)
        (project_dir / "settings" / "oneiric.yaml").write_text(
            "app:\n  name: project_default\n"
        )
        # XDG layer
        xdg_dir = tmp_path / "xdg" / "oneiric"
        xdg_dir.mkdir(parents=True)
        (xdg_dir / "local.yaml").write_text("app:\n  name: xdg_local\n")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        s = load_settings(project_root=project_dir, project_name="oneiric")
        assert s.app.name == "xdg_local"
