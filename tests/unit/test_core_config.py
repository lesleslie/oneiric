"""Tests for oneiric.core.config models and pure functions."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from oneiric.core.config import (
    OneiricSettings,
    RemoteAuthConfig,
    RemoteSourceConfig,
    SecretsConfig,
    domain_activity_path,
    lifecycle_snapshot_path,
    resolver_settings_from_config,
    runtime_health_path,
    runtime_observability_path,
    workflow_checkpoint_path,
)

# ---------------------------------------------------------------------------
# OneiricSettings defaults
# ---------------------------------------------------------------------------

class TestOneiricSettingsDefaults:
    def test_default_instance(self) -> None:
        s = OneiricSettings()
        assert s.app.name == "oneiric"
        assert s.remote.enabled is False
        assert s.lifecycle.activation_timeout == 30.0

    def test_domain_layers_exist(self) -> None:
        s = OneiricSettings()
        for domain in ("adapters", "services", "tasks", "events", "workflows", "actions"):
            assert hasattr(s, domain)


# ---------------------------------------------------------------------------
# RemoteSourceConfig
# ---------------------------------------------------------------------------

class TestRemoteSourceConfig:
    def test_defaults(self) -> None:
        c = RemoteSourceConfig()
        assert c.enabled is False
        assert c.manifest_url is None
        assert c.verify_tls is True
        assert c.signature_required is False
        assert c.signature_threshold == 1
        assert c.refresh_interval == 300.0
        assert c.max_retries == 3
        assert c.latency_budget_ms == 5000.0
        assert c.allow_file_uris is False

    def test_custom_values(self) -> None:
        c = RemoteSourceConfig(
            enabled=True,
            manifest_url="https://example.com/manifest.json",
            signature_required=True,
            signature_threshold=2,
        )
        assert c.enabled is True
        assert c.manifest_url == "https://example.com/manifest.json"
        assert c.signature_threshold == 2

    def test_signature_threshold_minimum(self) -> None:
        with pytest.raises(ValidationError):
            RemoteSourceConfig(signature_threshold=0)

    def test_signature_max_age_rejects_negative(self) -> None:
        with pytest.raises(ValidationError):
            RemoteSourceConfig(signature_max_age_seconds=-1.0)


# ---------------------------------------------------------------------------
# RemoteAuthConfig
# ---------------------------------------------------------------------------

class TestRemoteAuthConfig:
    def test_defaults(self) -> None:
        a = RemoteAuthConfig()
        assert a.header_name == "Authorization"
        assert a.secret_id is None
        assert a.token is None

    def test_custom(self) -> None:
        a = RemoteAuthConfig(header_name="X-Custom", token="abc")
        assert a.header_name == "X-Custom"
        assert a.token == "abc"


# ---------------------------------------------------------------------------
# SecretsConfig
# ---------------------------------------------------------------------------

class TestSecretsConfig:
    def test_defaults(self) -> None:
        s = SecretsConfig()
        assert s.domain == "adapter"
        assert s.key == "secrets"
        assert s.provider is None
        assert s.inline == {}
        assert s.cache_ttl_seconds == 600.0
        assert s.refresh_interval is None

    def test_negative_ttl_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SecretsConfig(cache_ttl_seconds=-1.0)

    def test_negative_refresh_interval_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SecretsConfig(refresh_interval=0.0)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

class TestPathHelpers:
    def _make_settings(self, **overrides) -> OneiricSettings:
        return OneiricSettings(**overrides)

    def test_lifecycle_snapshot_path(self) -> None:
        s = self._make_settings()
        p = lifecycle_snapshot_path(s)
        assert p.name == "lifecycle_status.json"

    def test_runtime_health_path(self) -> None:
        s = self._make_settings()
        p = runtime_health_path(s)
        assert p.name == "runtime_health.json"

    def test_domain_activity_path(self) -> None:
        s = self._make_settings()
        p = domain_activity_path(s)
        assert p.name == "domain_activity.sqlite"

    def test_runtime_observability_path(self) -> None:
        s = self._make_settings()
        p = runtime_observability_path(s)
        assert p.name == "runtime_telemetry.json"

    def test_workflow_checkpoint_path(self) -> None:
        s = self._make_settings()
        p = workflow_checkpoint_path(s)
        assert p is not None
        assert p.name == "workflow_checkpoints.sqlite"

    def test_workflow_checkpoint_disabled(self) -> None:
        s = OneiricSettings(
            runtime_paths={"workflow_checkpoints_enabled": False},
        )
        assert workflow_checkpoint_path(s) is None

    def test_workflow_checkpoint_custom_path(self) -> None:
        s = OneiricSettings(
            runtime_paths={
                "workflow_checkpoints_enabled": True,
                "workflow_checkpoints_path": "/tmp/my.db",
            },
        )
        p = workflow_checkpoint_path(s)
        assert p == Path("/tmp/my.db")


# ---------------------------------------------------------------------------
# resolver_settings_from_config
# ---------------------------------------------------------------------------

class TestResolverSettingsFromConfig:
    def test_returns_settings(self) -> None:
        s = OneiricSettings()
        rs = resolver_settings_from_config(s)
        assert rs is not None
        assert rs.default_priority == 0
        assert rs.selections == {}

    def test_selections_from_settings(self) -> None:
        s = OneiricSettings()
        s.adapters.selections = {"cache": "redis"}
        rs = resolver_settings_from_config(s)
        assert rs.selections.get("adapter") == {"cache": "redis"}
