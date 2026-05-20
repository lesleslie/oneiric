from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from oneiric.core.config import (
    OneiricSettings,
    SecretsConfig,
    SecretsHook,
    _read_file,
    apply_profile_with_fallback,
    apply_runtime_profile,
    load_settings,
    resolve_cache_dir_path,
)
from oneiric.core.lifecycle import LifecycleError


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


def test_read_file_falls_back_to_toml_for_unknown_extension(tmp_path) -> None:
    toml_file = tmp_path / "config.cfg"
    toml_file.write_text('[app]\nname = "toml-fallback"\n')

    result = _read_file(toml_file)

    assert result["app"]["name"] == "toml-fallback"


class TestSecretsHookGetBranches:
    def _make_hook(self, inline: dict | None = None) -> SecretsHook:
        config = SecretsConfig(inline=inline or {})
        lifecycle = MagicMock()
        lifecycle.get_instance.return_value = None
        return SecretsHook(lifecycle=lifecycle, config=config)

    @pytest.mark.asyncio
    async def test_inline_secret_returned_directly(self) -> None:
        hook = self._make_hook(inline={"api-key": "secret-value"})

        result = await hook.get("api-key")

        assert result == "secret-value"

    @pytest.mark.asyncio
    async def test_returns_none_when_provider_unavailable(self) -> None:
        hook = self._make_hook()
        with patch.object(hook, "_ensure_provider", new=AsyncMock(return_value=None)):
            result = await hook.get("missing-key")

        assert result is None

    @pytest.mark.asyncio
    async def test_raises_when_provider_lacks_get_secret(self) -> None:
        hook = self._make_hook()
        bad_provider = object()  # has no get_secret attribute
        with patch.object(
            hook, "_ensure_provider", new=AsyncMock(return_value=bad_provider)
        ):
            with pytest.raises(LifecycleError, match="get_secret"):
                await hook.get("some-key")
