from __future__ import annotations

from oneiric.core.config import (
    OneiricSettings,
    RuntimeProfileConfig,
    apply_profile_with_fallback,
    apply_runtime_profile,
)


def test_apply_runtime_profile_default() -> None:
    settings = OneiricSettings()
    updated = apply_runtime_profile(settings, None)
    assert updated.profile.name == "default"
    assert updated.profile.watchers_enabled
    assert updated.profile.remote_enabled
    assert updated.profile.supervisor_enabled


def test_apply_runtime_profile_serverless() -> None:
    settings = OneiricSettings()
    updated = apply_runtime_profile(settings, "serverless")
    assert updated.profile.name == "serverless"
    assert not updated.profile.watchers_enabled
    assert not updated.profile.remote_enabled
    assert updated.profile.inline_manifest_only
    assert updated.profile.supervisor_enabled
    assert not updated.remote.enabled
    assert updated.remote.refresh_interval is None


def test_apply_profile_with_fallback_uses_configured_profile() -> None:
    settings = OneiricSettings(profile=RuntimeProfileConfig(name="serverless"))
    updated = apply_profile_with_fallback(settings, None)
    assert updated.profile.name == "serverless"
    assert not updated.remote.enabled


def test_apply_profile_with_fallback_prioritizes_override() -> None:
    settings = OneiricSettings()
    updated = apply_profile_with_fallback(settings, "serverless")
    assert updated.profile.name == "serverless"
