from __future__ import annotations

import json
from pathlib import Path

import pytest

from oneiric.core.config import (
    OneiricSettings,
    _read_file,
    apply_profile_with_fallback,
    apply_runtime_profile,
    load_settings,
    resolve_cache_dir_path,
)


def test_resolve_cache_dir_path_falls_back_on_oserror(monkeypatch) -> None:
    original_mkdir = Path.mkdir

    def patched_mkdir(self, *args, **kwargs):
        if str(self).endswith("/nested/cache"):
            raise OSError("simulated mkdir failure")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", patched_mkdir)

    resolved = resolve_cache_dir_path("nested/cache")

    assert resolved.name == "cache"
    assert resolved.exists()


def test_load_settings_applies_env_and_explicit_override(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ONEIRIC_REMOTE__CACHE_DIR", str(tmp_path / "env-cache"))

    explicit = tmp_path / "settings.toml"
    explicit.write_text(
        """
[app]
name = "explicit"
"""
    )

    settings = load_settings(explicit)

    assert settings.app.name == "explicit"
    assert settings.remote.cache_dir == str(tmp_path / "env-cache")


def test_apply_runtime_profile_default_and_unknown() -> None:
    base = OneiricSettings()

    updated = apply_runtime_profile(base, "default")
    assert updated.profile.name == "default"

    with pytest.raises(ValueError, match="Unknown runtime profile"):
        apply_runtime_profile(base, "mystery")


def test_apply_profile_with_fallback_uses_configured_profile() -> None:
    settings = OneiricSettings(profile={"name": "serverless"})

    updated = apply_profile_with_fallback(settings, None)

    assert updated.profile.name == "serverless"


def test_read_file_supports_json_suffix_and_content_detection(tmp_path) -> None:
    json_file = tmp_path / "config.json"
    json_file.write_text(json.dumps({"app": {"name": "json"}}))

    detected_file = tmp_path / "config.cfg"
    detected_file.write_text(json.dumps({"app": {"environment": "staging"}}))

    assert _read_file(json_file)["app"]["name"] == "json"
    assert _read_file(detected_file)["app"]["environment"] == "staging"
