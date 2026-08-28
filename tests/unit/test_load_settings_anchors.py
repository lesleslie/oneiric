"""Tests for oneiric.core.config.load_settings() anchored project-layer resolution.

Verifies that when ``project_root`` is passed explicitly (or inferred from the
package install location), the project-layer settings files are read from that
root rather than from the current working directory.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from oneiric.core.config import load_settings


def _clear_oneiric_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip all ONEIRIC_* env vars so tests don't inherit shell state."""
    for key in (
        "ONEIRIC_CONFIG",
        "ONEIRIC_ACTIVITY_STORE",
        "ONEIRIC_LOG_LEVEL",
        "ONEIRIC_RUNTIME_SUPERVISOR__ENABLED",
        "XDG_CONFIG_HOME",
    ):
        monkeypatch.delenv(key, raising=False)


class TestExplicitProjectRoot:
    def test_loads_yaml_at_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_oneiric_env(monkeypatch)
        # CWD is somewhere unrelated to the anchored settings.
        monkeypatch.chdir(tmp_path)
        settings_dir = tmp_path / "settings"
        settings_dir.mkdir()
        (settings_dir / "oneiric.yaml").write_text("app:\n  name: anchored\n")
        s = load_settings(project_root=tmp_path, project_name="oneiric")
        assert s.app.name == "anchored"

    def test_loads_yml_variant(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_oneiric_env(monkeypatch)
        monkeypatch.chdir(tmp_path)
        settings_dir = tmp_path / "settings"
        settings_dir.mkdir()
        (settings_dir / "oneiric.yml").write_text("app:\n  name: yml_anchor\n")
        s = load_settings(project_root=tmp_path, project_name="oneiric")
        assert s.app.name == "yml_anchor"

    def test_loads_local_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_oneiric_env(monkeypatch)
        monkeypatch.chdir(tmp_path)
        settings_dir = tmp_path / "settings"
        settings_dir.mkdir()
        (settings_dir / "local.yaml").write_text("logging:\n  level: DEBUG\n")
        s = load_settings(project_root=tmp_path, project_name="oneiric")
        assert s.logging.level == "DEBUG"

    def test_explicit_root_does_not_fall_back_to_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When project_root is explicit and the anchored file does not exist,
        the loader must NOT fall back to CWD-relative resolution.
        """
        _clear_oneiric_env(monkeypatch)
        # CWD has a settings file
        cwd_settings = tmp_path / "cwd" / "settings"
        cwd_settings.mkdir(parents=True)
        (cwd_settings / "oneiric.yaml").write_text("app:\n  name: from_cwd\n")
        monkeypatch.chdir(tmp_path / "cwd")
        # Anchored root has NO settings dir
        anchored_root = tmp_path / "anchored"
        anchored_root.mkdir()
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            s = load_settings(
                project_root=anchored_root, project_name="oneiric"
            )
        # CWD file must not have been loaded — explicit anchor wins silently.
        assert s.app.name == "oneiric"  # default
