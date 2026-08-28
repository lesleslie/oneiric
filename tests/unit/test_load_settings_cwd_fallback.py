"""Tests for oneiric.core.config.load_settings() CWD-relative fallback.

When ``project_root`` is inferred (default) and the inferred anchored path
does not contain the project-layer file, ``load_settings()`` falls back to
CWD-relative resolution and emits a ``DeprecationWarning`` so operators who
``cd ~/Projects/repo && ./bin/run`` keep working during the migration window.

When ``project_root`` is passed explicitly, no fallback occurs — the caller
is trusted.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from oneiric.core.config import load_settings


def _clear_oneiric_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "ONEIRIC_CONFIG",
        "ONEIRIC_ACTIVITY_STORE",
        "ONEIRIC_LOG_LEVEL",
        "ONEIRIC_RUNTIME_SUPERVISOR__ENABLED",
        "XDG_CONFIG_HOME",
    ):
        monkeypatch.delenv(key, raising=False)


class TestCWDFallback:
    def test_fallback_warns_and_loads_cwd_value(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When the inferred anchored path doesn't exist but CWD has
        settings/{name}.yaml, the loader falls back to CWD and emits a
        DeprecationWarning.
        """
        _clear_oneiric_env(monkeypatch)
        # CWD has a settings file
        cwd_settings = tmp_path / "settings"
        cwd_settings.mkdir()
        (cwd_settings / "fallback_test.yaml").write_text(
            "app:\n  name: cwd_fallback\n"
        )
        monkeypatch.chdir(tmp_path)
        # Let project_root be inferred (None). The inferred anchor is the
        # package install location, which has no settings/fallback_test.yaml,
        # so the CWD fallback fires.
        with pytest.warns(DeprecationWarning, match="CWD-relative"):
            s = load_settings(project_name="fallback_test")
        # CWD file must have been loaded
        assert s.app.name == "cwd_fallback"

    def test_no_warn_when_neither_anchored_nor_cwd_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No DeprecationWarning when neither anchored nor CWD has the file."""
        _clear_oneiric_env(monkeypatch)
        monkeypatch.chdir(tmp_path)
        empty_root = tmp_path / "empty_anchor"
        empty_root.mkdir()
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            s = load_settings(
                project_root=empty_root, project_name="no_settings_anywhere"
            )
        # Default app name still applies
        assert s.app.name == "oneiric"

    def test_local_yaml_fallback_warns(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CWD-relative settings/local.yaml also emits a DeprecationWarning
        when the anchored equivalent is missing.
        """
        _clear_oneiric_env(monkeypatch)
        (tmp_path / "settings").mkdir()
        (tmp_path / "settings" / "local.yaml").write_text(
            "logging:\n  level: WARNING\n"
        )
        monkeypatch.chdir(tmp_path)
        # Let project_root be inferred. The inferred anchor's local.yaml
        # doesn't exist (the package install location has no settings/local.yaml),
        # so the CWD fallback fires.
        with pytest.warns(DeprecationWarning, match="local.yaml"):
            s = load_settings(project_name="local_fallback_test")
        assert s.logging.level == "WARNING"

    def test_anchored_wins_silently_over_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When both anchored and CWD have a settings file, anchored wins
        and no DeprecationWarning fires.
        """
        _clear_oneiric_env(monkeypatch)
        anchored_root = tmp_path / "anchored"
        anchored_settings = anchored_root / "settings"
        anchored_settings.mkdir(parents=True)
        (anchored_settings / "wins_test.yaml").write_text(
            "app:\n  name: from_anchored\n"
        )
        cwd_settings = tmp_path / "settings"
        cwd_settings.mkdir()
        (cwd_settings / "wins_test.yaml").write_text(
            "app:\n  name: from_cwd\n"
        )
        monkeypatch.chdir(tmp_path)
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            s = load_settings(
                project_root=anchored_root, project_name="wins_test"
            )
        # Anchored value loaded; CWD ignored.
        assert s.app.name == "from_anchored"

    def test_explicit_root_with_missing_anchored_does_not_warn(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Explicit project_root short-circuits the fallback — no warning,
        no CWD read.
        """
        _clear_oneiric_env(monkeypatch)
        cwd_settings = tmp_path / "settings"
        cwd_settings.mkdir()
        (cwd_settings / "explicit_test.yaml").write_text(
            "app:\n  name: from_cwd\n"
        )
        monkeypatch.chdir(tmp_path)
        empty_root = tmp_path / "empty_anchor"
        empty_root.mkdir()
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            s = load_settings(
                project_root=empty_root, project_name="explicit_test"
            )
        # CWD must NOT have been read.
        assert s.app.name == "oneiric"  # default
