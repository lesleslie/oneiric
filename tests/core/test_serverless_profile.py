"""Serverless profile regression tests."""

from __future__ import annotations

from oneiric.cli import _initialize_state
from oneiric.core.config import OneiricSettings, apply_runtime_profile


def test_serverless_profile_toggles_expected_settings() -> None:
    """Applying the serverless profile disables watchers + remote sync."""
    base = OneiricSettings()
    updated = apply_runtime_profile(base, "serverless")

    assert updated.profile.name == "serverless"
    assert updated.profile.watchers_enabled is False
    assert updated.profile.remote_enabled is False
    assert updated.profile.inline_manifest_only is True
    assert updated.profile.supervisor_enabled is True
    assert updated.remote.enabled is False
    assert updated.remote.refresh_interval is None


def test_serverless_profile_idempotent() -> None:
    """Re-applying the profile keeps the toggles without mutation."""
    base = OneiricSettings()
    first = apply_runtime_profile(base, "serverless")
    second = apply_runtime_profile(first, "serverless")

    assert second.profile.name == "serverless"
    assert second.profile.watchers_enabled is False
    assert second.profile.supervisor_enabled is True
    assert second.remote.enabled is False


def test_initialize_state_honors_env_profile(monkeypatch):
    """Setting ONEIRIC_PROFILE applies the profile even without CLI flag."""
    monkeypatch.setenv("ONEIRIC_PROFILE", "serverless")
    state = _initialize_state(config_path=None, imports=[], demo=False, profile=None)

    assert state.settings.profile.name == "serverless"
    assert state.settings.remote.enabled is False
