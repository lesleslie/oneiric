"""Extended configuration tests.

Tests for configuration loading, merging, and validation.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from oneiric.core.config import (
    AppConfig,
    LayerSettings,
    LifecycleConfig,
    OneiricSettings,
    RemoteAuthConfig,
    RemoteSourceConfig,
    SecretsConfig,
    _coerce_env_value,
    _deep_merge,
    load_settings,
)


class TestConfigModels:
    """Test Pydantic configuration models."""

    def test_app_config_defaults(self):
        """AppConfig has correct defaults."""
        config = AppConfig()
        assert config.name == "oneiric"
        assert config.environment == "dev"
        assert config.debug is False

    def test_app_config_custom_values(self):
        """AppConfig accepts custom values."""
        config = AppConfig(name="custom", environment="prod", debug=True)
        assert config.name == "custom"
        assert config.environment == "prod"
        assert config.debug is True

    def test_layer_settings_defaults(self):
        """LayerSettings has correct defaults."""
        config = LayerSettings()
        assert config.selections == {}
        assert config.provider_settings == {}
        assert config.options == {}

    def test_layer_settings_with_data(self):
        """LayerSettings accepts configuration data."""
        config = LayerSettings(
            selections={"adapter": "redis"},
            provider_settings={"redis": {"host": "localhost"}},
            options={"timeout": 30},
        )
        assert config.selections == {"adapter": "redis"}
        assert config.provider_settings["redis"]["host"] == "localhost"
        assert config.options["timeout"] == 30

    def test_secrets_config_defaults(self):
        """SecretsConfig has correct defaults."""
        config = SecretsConfig()
        assert config.domain == "adapter"
        assert config.key == "secrets"
        assert config.provider is None
        assert config.inline == {}
        assert config.cache_ttl_seconds == 600.0

    def test_secrets_config_validation(self):
        """SecretsConfig validates cache_ttl_seconds is non-negative."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            SecretsConfig(cache_ttl_seconds=-1.0)

    def test_remote_auth_config_defaults(self):
        """RemoteAuthConfig has correct defaults."""
        config = RemoteAuthConfig()
        assert config.header_name == "Authorization"
        assert config.secret_id is None
        assert config.token is None

    def test_remote_source_config_defaults(self):
        """RemoteSourceConfig has extensive defaults."""
        config = RemoteSourceConfig()
        assert config.enabled is False
        assert config.manifest_url is None
        assert config.cache_dir == ".oneiric_cache"
        assert config.verify_tls is True

    def test_remote_source_config_validation(self):
        """RemoteSourceConfig validates signature_threshold >= 1."""
        with pytest.raises(ValueError):
            RemoteSourceConfig(signature_threshold=0)

    def test_lifecycle_config_defaults(self):
        """LifecycleConfig has correct defaults."""
        config = LifecycleConfig()
        assert config.activation_timeout == 30.0
        assert config.health_timeout == 5.0
        assert config.cleanup_timeout == 10.0
        assert config.hook_timeout == 5.0
        assert config.shield_tasks is True

    def test_lifecycle_config_custom_values(self):
        """LifecycleConfig accepts custom values."""
        config = LifecycleConfig(
            activation_timeout=60.0,
            health_timeout=10.0,
            cleanup_timeout=20.0,
            hook_timeout=15.0,
            shield_tasks=False,
        )
        assert config.activation_timeout == 60.0
        assert config.health_timeout == 10.0


class TestDeepMerge:
    """Test deep merge functionality."""

    def test_deep_merge_simple_dicts(self):
        """Deep merge combines simple dictionaries."""
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        result = _deep_merge(base, override)

        assert result["a"] == 1
        assert result["b"] == 3  # Overridden
        assert result["c"] == 4

    def test_deep_merge_nested_dicts(self):
        """Deep merge handles nested dictionaries."""
        base = {"outer": {"inner": "value", "keep": "base"}}
        override = {"outer": {"inner": "overridden"}}
        result = _deep_merge(base, override)

        assert result["outer"]["inner"] == "overridden"
        assert result["outer"]["keep"] == "base"  # Preserved

    def test_deep_merge_with_lists(self):
        """Deep merge replaces lists (doesn't merge them)."""
        base = {"items": ["a", "b", "c"]}
        override = {"items": ["d", "e"]}
        result = _deep_merge(base, override)

        assert result["items"] == ["d", "e"]

    def test_deep_merge_empty_override(self):
        """Deep merge with empty override returns base."""
        base = {"key": "value"}
        override = {}
        result = _deep_merge(base, override)

        assert result == base

    def test_deep_merge_empty_base(self):
        """Deep merge with empty base returns override."""
        base = {}
        override = {"key": "value"}
        result = _deep_merge(base, override)

        assert result == override


class TestEnvCoercion:
    """Test environment variable value coercion."""

    def test_coerce_string(self):
        """String values remain strings."""
        assert _coerce_env_value("hello") == "hello"

    def test_coerce_integer(self):
        """Numeric strings are coerced to integers."""
        assert _coerce_env_value("42") == 42
        assert isinstance(_coerce_env_value("42"), int)

    def test_coerce_float(self):
        """Decimal strings are coerced to floats."""
        assert _coerce_env_value("3.14") == 3.14
        assert isinstance(_coerce_env_value("3.14"), float)

    def test_coerce_boolean_true(self):
        """Boolean strings are coerced to bool."""
        assert _coerce_env_value("true") is True
        assert _coerce_env_value("True") is True
        assert _coerce_env_value("TRUE") is True
        # Note: "1" coerces to int 1, not bool True
        assert _coerce_env_value("1") == 1
        assert isinstance(_coerce_env_value("1"), int)

    def test_coerce_boolean_false(self):
        """False boolean strings are coerced to bool."""
        assert _coerce_env_value("false") is False
        assert _coerce_env_value("False") is False
        assert _coerce_env_value("FALSE") is False
        # Note: "0" coerces to int 0, not bool False
        assert _coerce_env_value("0") == 0
        assert isinstance(_coerce_env_value("0"), int)

    def test_coerce_json_list(self):
        """Comma-separated strings are coerced to lists."""
        # Note: JSON parsing is not implemented - comma-separated values are split
        result = _coerce_env_value('a,b,c')
        assert result == ["a", "b", "c"]
        assert isinstance(result, list)

    def test_coerce_json_dict(self):
        """Strings without commas remain strings (no JSON parsing)."""
        result = _coerce_env_value('{"key": "value"}')
        assert result == '{"key": "value"}'
        assert isinstance(result, str)

    def test_coerce_invalid_json(self):
        """Strings without special formatting remain strings."""
        result = _coerce_env_value("{invalid}")
        assert result == "{invalid}"
        assert isinstance(result, str)


class TestLoadSettings:
    """Test settings loading."""

    def test_load_settings_nonexistent(self, tmp_path: Path):
        """Loading nonexistent file returns default settings."""
        settings = load_settings(tmp_path / "nonexistent.yaml")
        assert isinstance(settings, OneiricSettings)

    def test_load_settings_with_yaml(self, tmp_path: Path):
        """Load settings from TOML file (YAML not supported)."""
        config_file = tmp_path / "settings.toml"
        config_content = """
[app]
name = "test-app"
environment = "production"

[secrets]
cache_ttl_seconds = 300.0
"""

        with open(config_file, "w") as f:
            f.write(config_content)

        settings = load_settings(config_file)
        assert settings.app.name == "test-app"
        assert settings.app.environment == "production"
        assert settings.secrets.cache_ttl_seconds == 300.0

    def test_load_settings_defaults(self, tmp_path: Path):
        """Loading without file uses default settings."""
        settings = load_settings(None)
        assert settings.app.name == "oneiric"
        assert settings.app.environment == "dev"


class TestConfigEdgeCases:
    """Test configuration edge cases."""

    def test_model_serialization(self):
        """Config models can be serialized."""
        config = AppConfig(name="test", environment="prod")
        data = config.model_dump()

        assert data["name"] == "test"
        assert data["environment"] == "prod"
        assert data["debug"] is False

    def test_model_json_serialization(self):
        """Config models can be serialized to JSON."""
        config = SecretsConfig(provider="vault", inline={"key": "value"})
        json_str = config.model_dump_json()

        assert "vault" in json_str
        assert "key" in json_str

    def test_nested_config_options(self):
        """LayerSettings handles complex option structures."""
        config = LayerSettings(
            options={
                "timeouts": {"connect": 5, "read": 30},
                "retries": {"max": 3, "backoff": "exponential"},
            }
        )

        assert config.options["timeouts"]["connect"] == 5
        assert config.options["retries"]["backoff"] == "exponential"

    def test_remote_source_config_all_fields(self):
        """RemoteSourceConfig accepts all optional fields."""
        config = RemoteSourceConfig(
            enabled=True,
            manifest_url="https://example.com/manifest.json",
            cache_dir="/tmp/cache",
            verify_tls=False,
            auth=RemoteAuthConfig(
                header_name="X-Auth",
                secret_id="my-secret",
                token="my-token",
            ),
            signature_required=True,
            signature_threshold=2,
            signature_max_age_seconds=3600.0,
            signature_require_expiry=True,
            refresh_interval=600.0,
            max_retries=5,
            retry_base_delay=2.0,
            retry_max_delay=60.0,
            retry_jitter=0.5,
            circuit_breaker_threshold=10,
            circuit_breaker_reset=120.0,
            allow_file_uris=True,
            allowed_file_uri_roots=["/etc/oneiric"],
            latency_budget_ms=10000.0,
        )

        assert config.enabled is True
        assert config.manifest_url == "https://example.com/manifest.json"
        assert config.signature_threshold == 2
        assert config.allowed_file_uri_roots == ["/etc/oneiric"]

    def test_deep_merge_preserves_types(self):
        """Deep merge preserves original value types."""
        base = {
            "string": "value",
            "int": 42,
            "float": 3.14,
            "bool": True,
            "list": [1, 2, 3],
            "dict": {"nested": "value"},
        }
        override = {}

        result = _deep_merge(base, override)

        assert isinstance(result["string"], str)
        assert isinstance(result["int"], int)
        assert isinstance(result["float"], float)
        assert isinstance(result["bool"], bool)
        assert isinstance(result["list"], list)
        assert isinstance(result["dict"], dict)

    def test_deep_merge_with_none_values(self):
        """Deep merge handles None values in override."""
        base = {"app": {"name": "test", "value": "keep"}}
        override = {"app": {"name": None}}

        result = _deep_merge(base, override)

        # None should override the value
        assert result["app"]["name"] is None
        assert result["app"]["value"] == "keep"
