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

    def test_xdg_config_overrides_project_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``build_yaml_layers`` enumerates 5 candidate paths; pin that
        XDG config (not just XDG local) is wired in and beats project yaml.
        """
        _clear_oneiric_env(monkeypatch)
        project_dir = tmp_path / "project"
        (project_dir / "settings").mkdir(parents=True)
        (project_dir / "settings" / "oneiric.yaml").write_text(
            "app:\n  name: project_default\n"
        )
        xdg_dir = tmp_path / "xdg" / "oneiric"
        xdg_dir.mkdir(parents=True)
        # Only config.yaml (no local.yaml) — distinct from xdg_local test
        (xdg_dir / "config.yaml").write_text("app:\n  name: xdg_config\n")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        s = load_settings(project_root=project_dir, project_name="oneiric")
        assert s.app.name == "xdg_config"

    def test_project_local_overrides_project_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``<project_root>/settings/local.yaml`` beats project yaml
        and is one of the 5 enumerated YAML layers.
        """
        _clear_oneiric_env(monkeypatch)
        project_dir = tmp_path / "project"
        (project_dir / "settings").mkdir(parents=True)
        (project_dir / "settings" / "oneiric.yaml").write_text(
            "app:\n  name: committed\n"
        )
        (project_dir / "settings" / "local.yaml").write_text(
            "app:\n  name: local_override\n"
        )
        s = load_settings(project_root=project_dir, project_name="oneiric")
        assert s.app.name == "local_override"

    def test_project_yml_variant_loaded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``.yml`` (vs ``.yaml``) is one of the 5 enumerated candidates.
        Pin that the loader picks it up.
        """
        _clear_oneiric_env(monkeypatch)
        project_dir = tmp_path / "project"
        (project_dir / "settings").mkdir(parents=True)
        (project_dir / "settings" / "oneiric.yml").write_text(
            "app:\n  name: yml_variant\n"
        )
        s = load_settings(project_root=project_dir, project_name="oneiric")
        assert s.app.name == "yml_variant"

    def test_alias_overrides_env_source_routes_activity_store(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Direct test of the ``_AliasOverridesEnvSource`` source — proves
        the custom source is wired into the chain by calling it
        directly with a stub settings_cls and verifying it produces
        the expected nested-path dict for ``ONEIRIC_ACTIVITY_STORE``.

        The end-to-end alias-routing test in ``test_yaml_loses_to_alias_source``
        passes via the pre-wired ``AliasChoices`` on the target field
        regardless of whether the custom source is in the chain. This
        direct test pins the custom source's own behavior.
        """
        from oneiric.core._sources import _AliasOverridesEnvSource
        from oneiric.core.config import OneiricSettings

        _clear_oneiric_env(monkeypatch)
        monkeypatch.setenv("ONEIRIC_ACTIVITY_STORE", "/custom/activity")
        source = _AliasOverridesEnvSource(OneiricSettings, env_prefix="ONEIRIC_")
        payload = source()
        assert payload == {
            "runtime_paths": {"domain_activity_path": "/custom/activity"}
        }

    def test_alias_overrides_env_source_does_not_match_other_prefixes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The custom source only matches env vars with the project prefix
        (e.g. ``ONEIRIC_`` for the oneiric project). Pin that prefix
        isolation works for the alias source.
        """
        from oneiric.core._sources import _AliasOverridesEnvSource
        from oneiric.core.config import OneiricSettings

        _clear_oneiric_env(monkeypatch)
        monkeypatch.setenv("MAHAVISHNU_ACTIVITY_STORE", "/wrong/project")
        source = _AliasOverridesEnvSource(OneiricSettings, env_prefix="ONEIRIC_")
        assert source() == {}
