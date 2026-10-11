"""Anchored ``project_root`` precedence tests (CWD fallback removed in Phase 1).

Phase 1 task 1.4 removed the CWD-relative fallback that this file
originally covered. Tests that pinned the legacy
``DeprecationWarning``-on-CWD contract were deleted; the surviving
tests verify the explicit ``project_root=`` path that replaced it.
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


class TestExplicitRootNoFallback:
    """Phase 1 amendment: explicit ``project_root=`` never reads CWD."""

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
