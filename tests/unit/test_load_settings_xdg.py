"""Tests for oneiric.core.config.load_settings() XDG user-config layering.

Verifies the XDG path resolution (``~/.config/{project_name}/``) and the
precedence: project < XDG config < XDG local.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from oneiric.core.config import load_settings


def _clear_oneiric_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "ONEIRIC_CONFIG",
        "ONEIRIC_ACTIVITY_STORE",
        "ONEIRIC_LOG_LEVEL",
        "ONEIRIC_RUNTIME_SUPERVISOR__ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)


class TestXDGOverrides:
    def test_xdg_config_overrides_project(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_oneiric_env(monkeypatch)
        # Project layer sets a baseline value
        settings_dir = tmp_path / "settings"
        settings_dir.mkdir()
        (settings_dir / "oneiric.yaml").write_text(
            "app:\n  name: project_default\n"
        )
        # XDG layer overrides
        xdg_dir = tmp_path / "xdg" / "oneiric"
        xdg_dir.mkdir(parents=True)
        (xdg_dir / "config.yaml").write_text("app:\n  name: xdg_override\n")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        s = load_settings(project_root=tmp_path, project_name="oneiric")
        assert s.app.name == "xdg_override"

    def test_xdg_local_overrides_xdg_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_oneiric_env(monkeypatch)
        xdg_dir = tmp_path / "xdg" / "oneiric"
        xdg_dir.mkdir(parents=True)
        (xdg_dir / "config.yaml").write_text("app:\n  name: xdg_config\n")
        (xdg_dir / "local.yaml").write_text("app:\n  name: xdg_local\n")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        s = load_settings(project_root=tmp_path, project_name="oneiric")
        assert s.app.name == "xdg_local"

    def test_xdg_only_local(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Local-only override (no config.yaml) still applies."""
        _clear_oneiric_env(monkeypatch)
        xdg_dir = tmp_path / "xdg" / "oneiric"
        xdg_dir.mkdir(parents=True)
        (xdg_dir / "local.yaml").write_text("logging:\n  level: WARNING\n")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        s = load_settings(project_root=tmp_path, project_name="oneiric")
        assert s.logging.level == "WARNING"

    def test_xdg_with_unknown_project_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An XDG override on a different project_name does not leak
        into a different project's settings.
        """
        _clear_oneiric_env(monkeypatch)
        xdg_dir = tmp_path / "xdg" / "oneiric"
        xdg_dir.mkdir(parents=True)
        (xdg_dir / "config.yaml").write_text("app:\n  name: xdg_value\n")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        s = load_settings(
            project_root=tmp_path, project_name="other_project"
        )
        # The other project's XDG dir doesn't exist; nothing should leak.
        assert s.app.name == "oneiric"  # default
