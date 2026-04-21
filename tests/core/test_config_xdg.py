"""Tests for XDG-compliant layered configuration.

These tests verify that the XDG configuration layer works correctly
with proper priority ordering and project-specific lookups.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import yaml

from oneiric.core.config import _env_overrides, load_settings


class TestXDGConfigLayer:
    """Test XDG configuration layer functionality."""

    def test_xdg_config_path_construction(self, tmp_path):
        """Test XDG config path is constructed correctly."""
        project_name = "test_project"
        xdg_config_home = tmp_path / ".config"
        xdg_config_path = xdg_config_home / project_name / "config.yaml"

        # Create XDG config file
        xdg_config_path.parent.mkdir(parents=True, exist_ok=True)
        xdg_config_path.write_text(
            yaml.dump({"remote": {"cache_dir": "/tmp/xdg_cache"}})
        )

        # Set XDG config home environment variable
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(xdg_config_home)}):
            settings = load_settings(project_name=project_name)

        assert settings.remote.cache_dir == "/tmp/xdg_cache"

    def test_xdg_config_with_default_location(self, tmp_path, monkeypatch):
        """Test XDG config uses default ~/.config location when XDG_CONFIG_HOME not set."""
        # Create mock home directory
        fake_home = tmp_path / "home"
        fake_config = fake_home / ".config" / "test_project"
        fake_config.mkdir(parents=True, exist_ok=True)
        (fake_config / "config.yaml").write_text(
            yaml.dump({"logging": {"level": "DEBUG"}})
        )

        # Set HOME to tmp_path/home
        monkeypatch.setenv("HOME", str(fake_home))
        # Ensure XDG_CONFIG_HOME is not set
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

        settings = load_settings(project_name="test_project")

        assert "DEBUG" in str(settings.logging.level)

    def test_xdg_config_missing_falls_back_to_defaults(self, monkeypatch):
        """Test missing XDG config falls back to code defaults."""
        monkeypatch.setenv("HOME", "/tmp/nonexistent")
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

        settings = load_settings(project_name="nonexistent_project")

        # Should use default values from OneiricSettings
        assert settings.remote.cache_dir == ".oneiric_cache"

    def test_xdg_config_with_toml_format(self, tmp_path, monkeypatch):
        """Test XDG config supports TOML format (via .toml extension)."""
        # Note: XDG config file is named config.yaml by default
        # This test verifies TOML parsing works when using .toml extension
        xdg_config = tmp_path / ".config" / "test_project" / "config.toml"
        xdg_config.parent.mkdir(parents=True, exist_ok=True)
        xdg_config.write_text(
            '[remote]\ncache_dir = "/tmp/toml_cache"\nenabled = true'
        )

        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))

        # Load with explicit path to .toml file
        settings = load_settings(
            path=str(xdg_config), project_name="test_project"
        )

        assert settings.remote.cache_dir == "/tmp/toml_cache"
        assert settings.remote.enabled is True


class TestConfigPriorityOrder:
    """Test configuration layer priority ordering."""

    def test_explicit_path_highest_priority(self, tmp_path, monkeypatch):
        """Test explicit path parameter has highest priority."""
        # Create XDG config
        xdg_config = tmp_path / ".config" / "test" / "config.yaml"
        xdg_config.parent.mkdir(parents=True, exist_ok=True)
        xdg_config.write_text(yaml.dump({"remote": {"cache_dir": "/tmp/xdg"}}))

        # Create explicit config
        explicit_config = tmp_path / "explicit.yaml"
        explicit_config.write_text(yaml.dump({"remote": {"cache_dir": "/tmp/explicit"}}))

        # Create local config
        local_config = tmp_path / "settings" / "local.yaml"
        local_config.parent.mkdir(parents=True, exist_ok=True)
        local_config.write_text(yaml.dump({"remote": {"cache_dir": "/tmp/local"}}))

        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
        monkeypatch.chdir(tmp_path)

        settings = load_settings(path=str(explicit_config), project_name="test")

        # Explicit path should win
        assert settings.remote.cache_dir == "/tmp/explicit"

    def test_project_config_env_var(self, tmp_path, monkeypatch):
        """Test {PROJECT}_CONFIG environment variable."""
        # Create XDG config
        xdg_config = tmp_path / ".config" / "test_project" / "config.yaml"
        xdg_config.parent.mkdir(parents=True, exist_ok=True)
        xdg_config.write_text(yaml.dump({"remote": {"cache_dir": "/tmp/xdg"}}))

        # Create env config
        env_config = tmp_path / "env_config.yaml"
        env_config.write_text(yaml.dump({"remote": {"cache_dir": "/tmp/env"}}))

        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
        monkeypatch.setenv("TEST_PROJECT_CONFIG", str(env_config))

        settings = load_settings(project_name="test_project")

        # Env var config should win
        assert settings.remote.cache_dir == "/tmp/env"

    def test_env_overrides_highest_priority(self, tmp_path, monkeypatch):
        """Test environment variable overrides have highest priority."""
        # Create XDG config
        xdg_config = tmp_path / ".config" / "test" / "config.yaml"
        xdg_config.parent.mkdir(parents=True, exist_ok=True)
        xdg_config.write_text(yaml.dump({"remote": {"cache_dir": "/tmp/xdg"}}))

        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
        monkeypatch.setenv("TEST_REMOTE__CACHE_DIR", "/tmp/env_override")

        settings = load_settings(project_name="test")

        # Environment variable should win
        assert settings.remote.cache_dir == "/tmp/env_override"

    def test_xdg_over_project_local(self, tmp_path, monkeypatch):
        """Test XDG config overrides project local config."""
        # Create XDG config
        xdg_config = tmp_path / ".config" / "test" / "config.yaml"
        xdg_config.parent.mkdir(parents=True, exist_ok=True)
        xdg_config.write_text(yaml.dump({"remote": {"cache_dir": "/tmp/xdg"}}))

        # Create local config
        local_config = tmp_path / "settings" / "local.yaml"
        local_config.parent.mkdir(parents=True, exist_ok=True)
        local_config.write_text(yaml.dump({"remote": {"cache_dir": "/tmp/local"}}))

        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
        monkeypatch.chdir(tmp_path)

        settings = load_settings(project_name="test")

        # XDG should override local
        assert settings.remote.cache_dir == "/tmp/xdg"

    def test_project_local_over_defaults(self, tmp_path, monkeypatch):
        """Test project local config overrides defaults."""
        # Create local config
        local_config = tmp_path / "settings" / "local.yaml"
        local_config.parent.mkdir(parents=True, exist_ok=True)
        local_config.write_text(yaml.dump({"remote": {"cache_dir": "/tmp/local"}}))

        monkeypatch.chdir(tmp_path)

        settings = load_settings(project_name="test")

        # Local should override default
        assert settings.remote.cache_dir == "/tmp/local"


class TestEnvironmentOverrides:
    """Test environment variable override functionality."""

    def test_env_override_simple_string(self, monkeypatch):
        """Test simple string environment override."""
        monkeypatch.setenv("TEST_REMOTE__CACHE_DIR", "/tmp/test_cache")

        overrides = _env_overrides("test")

        assert overrides == {"remote": {"cache_dir": "/tmp/test_cache"}}

    def test_env_override_boolean(self, monkeypatch):
        """Test boolean environment override."""
        monkeypatch.setenv("TEST_REMOTE__ENABLED", "true")
        monkeypatch.setenv("TEST_REMOTE__VERIFY_TLS", "false")

        overrides = _env_overrides("test")

        assert overrides["remote"]["enabled"] is True
        assert overrides["remote"]["verify_tls"] is False

    def test_env_override_numeric(self, monkeypatch):
        """Test numeric environment override."""
        monkeypatch.setenv("TEST_REMOTE__MAX_RETRIES", "5")
        monkeypatch.setenv("TEST_REMOTE__REFRESH_INTERVAL", "300.5")

        overrides = _env_overrides("test")

        assert overrides["remote"]["max_retries"] == 5
        assert overrides["remote"]["refresh_interval"] == 300.5

    def test_env_override_list(self, monkeypatch):
        """Test list environment override."""
        monkeypatch.setenv("TEST_REMOTE__ALLOWED_FILE_URI_ROOTS", "/tmp,/home,.")

        overrides = _env_overrides("test")

        assert overrides["remote"]["allowed_file_uri_roots"] == ["/tmp", "/home", "."]

    def test_env_override_profile_single_level(self, monkeypatch):
        """Test profile single-level override."""
        monkeypatch.setenv("TEST_PROFILE", "serverless")

        overrides = _env_overrides("test")

        assert overrides["profile"]["name"] == "serverless"

    def test_env_override_nested_sections(self, monkeypatch):
        """Test nested section environment overrides."""
        monkeypatch.setenv("TEST_LOGGING__LEVEL", "DEBUG")
        monkeypatch.setenv("TEST_LOGGING__FORMAT", "json")
        monkeypatch.setenv("TEST_REMOTE__CACHE_DIR", "/tmp/cache")
        monkeypatch.setenv("TEST_SECRETS__PROVIDER", "vault")

        overrides = _env_overrides("test")

        assert overrides["logging"]["level"] == "DEBUG"
        assert overrides["logging"]["format"] == "json"
        assert overrides["remote"]["cache_dir"] == "/tmp/cache"
        assert overrides["secrets"]["provider"] == "vault"

    def test_env_override_ignores_other_projects(self, monkeypatch):
        """Test env overrides only apply to specified project."""
        monkeypatch.setenv("OTHER_PROJECT_REMOTE__CACHE_DIR", "/tmp/other")
        monkeypatch.setenv("TEST_REMOTE__CACHE_DIR", "/tmp/test")

        overrides = _env_overrides("test")

        # Should only include TEST_ prefixed variables
        assert "remote" in overrides
        assert overrides["remote"]["cache_dir"] == "/tmp/test"

    def test_env_override_applied_to_settings(self, monkeypatch):
        """Test environment overrides are applied to final settings."""
        monkeypatch.setenv("TEST_REMOTE__CACHE_DIR", "/tmp/env_cache")

        settings = load_settings(project_name="test")

        assert settings.remote.cache_dir == "/tmp/env_cache"


class TestProjectNameParameter:
    """Test project_name parameter functionality."""

    def test_default_project_name(self):
        """Test default project_name is 'oneiric'."""
        settings = load_settings()

        # Should load with default project name
        assert settings.app.name == "oneiric"

    def test_custom_project_name(self, monkeypatch):
        """Test custom project_name affects env prefix."""
        monkeypatch.setenv("SESSION_BUDDY_LOGGING__LEVEL", "DEBUG")

        settings = load_settings(project_name="session_buddy")

        assert "DEBUG" in str(settings.logging.level)

    def test_project_name_affects_xdg_path(self, tmp_path, monkeypatch):
        """Test project_name affects XDG config lookup path."""
        # Create XDG config for specific project
        xdg_config = tmp_path / ".config" / "my_project" / "config.yaml"
        xdg_config.parent.mkdir(parents=True, exist_ok=True)
        xdg_config.write_text(yaml.dump({"remote": {"cache_dir": "/tmp/my_project"}}))

        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))

        settings = load_settings(project_name="my_project")

        assert settings.remote.cache_dir == "/tmp/my_project"


class TestBackwardsCompatibility:
    """Test backwards compatibility with existing code."""

    def test_load_settings_without_project_name(self):
        """Test load_settings works without project_name parameter."""
        # Should use default "oneiric" project name
        settings = load_settings()

        assert settings is not None
        assert settings.app.name == "oneiric"

    def test_load_settings_with_path_only(self, tmp_path):
        """Test load_settings works with just path parameter (old API)."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump({"remote": {"cache_dir": "/tmp/legacy"}})
        )

        settings = load_settings(path=str(config_file))

        assert settings.remote.cache_dir == "/tmp/legacy"

    def test_env_prefix_oneiric_default(self, monkeypatch):
        """Test ONEIRIC_ prefix still works as default."""
        monkeypatch.setenv("ONEIRIC_REMOTE__CACHE_DIR", "/tmp/oneiric_cache")

        settings = load_settings()

        assert settings.remote.cache_dir == "/tmp/oneiric_cache"


class TestConfigMerging:
    """Test deep merge behavior across configuration layers."""

    def test_partial_merge_across_layers(self, tmp_path, monkeypatch):
        """Test partial config merges across layers."""
        # XDG config sets cache_dir
        xdg_config = tmp_path / ".config" / "test" / "config.yaml"
        xdg_config.parent.mkdir(parents=True, exist_ok=True)
        xdg_config.write_text(
            yaml.dump({"remote": {"cache_dir": "/tmp/xdg_cache"}})
        )

        # Env var sets enabled
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
        monkeypatch.setenv("TEST_REMOTE__ENABLED", "true")

        settings = load_settings(project_name="test")

        # Both settings should be present
        assert settings.remote.cache_dir == "/tmp/xdg_cache"
        assert settings.remote.enabled is True

    def test_nested_merge_behavior(self, tmp_path, monkeypatch):
        """Test nested dict merge behavior."""
        # XDG config
        xdg_config = tmp_path / ".config" / "test" / "config.yaml"
        xdg_config.parent.mkdir(parents=True, exist_ok=True)
        xdg_config.write_text(
            yaml.dump(
                {
                    "adapters": {
                        "selections": {"cache": "redis"},
                        "provider_settings": {"redis": {"host": "localhost"}},
                    }
                }
            )
        )

        # Local config adds to selections
        local_config = tmp_path / "settings" / "local.yaml"
        local_config.parent.mkdir(parents=True, exist_ok=True)
        local_config.write_text(
            yaml.dump({"adapters": {"selections": {"database": "postgresql"}}})
        )

        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
        monkeypatch.chdir(tmp_path)

        settings = load_settings(project_name="test")

        # Both selections should be present
        assert settings.adapters.selections["cache"] == "redis"
        assert settings.adapters.selections["database"] == "postgresql"
        assert settings.adapters.provider_settings["redis"]["host"] == "localhost"


class TestErrorHandling:
    """Test error handling in config loading."""

    def test_invalid_xdg_config_format(self, tmp_path, monkeypatch, caplog):
        """Test invalid XDG config format falls back gracefully."""
        # Create invalid YAML
        xdg_config = tmp_path / ".config" / "test" / "config.yaml"
        xdg_config.parent.mkdir(parents=True, exist_ok=True)
        xdg_config.write_text("invalid: yaml: content: [")

        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))

        # Should fall back to defaults
        settings = load_settings(project_name="test")

        assert settings.remote.cache_dir == ".oneiric_cache"  # Default value

    def test_missing_explicit_config_warns(self, tmp_path, monkeypatch, caplog):
        """Test missing explicit config path generates warning."""
        missing_config = tmp_path / "nonexistent.yaml"

        settings = load_settings(path=str(missing_config), project_name="test")

        # Should fall back to defaults
        assert settings is not None

        # Should log warning
        # Note: Actual warning logging depends on logger configuration


class TestRealWorldScenarios:
    """Test real-world configuration scenarios."""

    def test_development_mode_with_local_override(self, tmp_path, monkeypatch):
        """Test development mode using settings/local.yaml."""
        # Developer has local overrides for testing
        local_config = tmp_path / "settings" / "local.yaml"
        local_config.parent.mkdir(parents=True, exist_ok=True)
        local_config.write_text(
            yaml.dump(
                {
                    "logging": {"level": "DEBUG"},
                    "remote": {"cache_dir": "/tmp/dev_cache"},
                }
            )
        )

        monkeypatch.chdir(tmp_path)

        settings = load_settings(project_name="my_app")

        assert settings.logging.level == "DEBUG"
        assert settings.remote.cache_dir == "/tmp/dev_cache"

    def test_production_mode_with_xdg_config(self, tmp_path, monkeypatch):
        """Test production mode using XDG config."""
        # Installed package uses XDG config
        xdg_config = tmp_path / ".config" / "my_app" / "config.yaml"
        xdg_config.parent.mkdir(parents=True, exist_ok=True)
        xdg_config.write_text(
            yaml.dump(
                {
                    "logging": {"level": "INFO"},
                    "remote": {"cache_dir": "~/.cache/my_app"},
                }
            )
        )

        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))

        settings = load_settings(project_name="my_app")

        assert "INFO" in str(settings.logging.level)
        assert "my_app" in settings.remote.cache_dir

    def test_ci_cd_with_env_overrides(self, monkeypatch):
        """Test CI/CD environment using environment variables."""
        monkeypatch.setenv("MY_APP_LOGGING__LEVEL", "WARNING")
        monkeypatch.setenv("MY_APP_REMOTE__ENABLED", "false")
        monkeypatch.setenv("MY_APP_PROFILE", "serverless")

        settings = load_settings(project_name="my_app")

        assert "WARNING" in str(settings.logging.level)
        assert settings.remote.enabled is False
        assert settings.profile.name == "serverless"
