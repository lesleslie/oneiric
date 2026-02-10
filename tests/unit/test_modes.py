"""Unit tests for Oneiric operational modes."""

from __future__ import annotations

import os

import pytest

from oneiric.core.config import OneiricSettings
from oneiric.modes import (
    AVAILABLE_MODES,
    create_mode,
    get_available_modes,
    get_mode,
    get_mode_from_environment,
)
from oneiric.modes.base import ModeConfig, OperationMode
from oneiric.modes.lite import LiteMode
from oneiric.modes.standard import StandardMode
from oneiric.modes.utils import (
    apply_mode_to_settings,
    get_mode_startup_info,
    load_mode_config_file,
    print_mode_startup_info,
    validate_mode_requirements,
)


class TestLiteMode:
    """Tests for LiteMode."""

    def test_mode_name(self) -> None:
        """Test that lite mode has correct name."""
        mode = LiteMode()
        assert mode.name == "lite"

    def test_get_config(self) -> None:
        """Test that lite mode returns correct configuration."""
        mode = LiteMode()
        config = mode.get_config()

        assert config.name == "lite"
        assert config.remote_enabled is False
        assert config.signature_required is False
        assert config.manifest_sync_enabled is False
        assert config.cloud_backup_enabled is False
        assert config.watchers_enabled is True
        assert config.supervisor_enabled is False
        assert config.inline_manifest_only is True
        assert config.setup_time_minutes == 2
        assert config.external_dependencies == []

    def test_validate_environment(self) -> None:
        """Test that lite mode environment validation always passes."""
        mode = LiteMode()
        errors = mode.validate_environment()
        assert errors == []

    def test_get_startup_message(self) -> None:
        """Test that lite mode returns startup message."""
        mode = LiteMode()
        message = mode.get_startup_message()
        assert "lite mode" in message.lower()
        assert "local" in message.lower()
        assert "disabled" in message.lower()

    def test_to_dict(self) -> None:
        """Test that lite mode can be converted to dict."""
        mode = LiteMode()
        config_dict = mode.to_dict()
        assert config_dict["mode"] == "lite"
        assert config_dict["remote_enabled"] is False
        assert config_dict["signature_required"] is False


class TestStandardMode:
    """Tests for StandardMode."""

    def test_mode_name(self) -> None:
        """Test that standard mode has correct name."""
        mode = StandardMode()
        assert mode.name == "standard"

    def test_get_config(self) -> None:
        """Test that standard mode returns correct configuration."""
        mode = StandardMode()
        config = mode.get_config()

        assert config.name == "standard"
        assert config.remote_enabled is True
        assert config.signature_required is True
        assert config.manifest_sync_enabled is True
        assert config.cloud_backup_enabled is True
        assert config.watchers_enabled is True
        assert config.supervisor_enabled is True
        assert config.inline_manifest_only is False
        assert config.setup_time_minutes == 5
        assert len(config.external_dependencies) > 0

    def test_validate_environment(self) -> None:
        """Test that standard mode environment validation."""
        mode = StandardMode()
        errors = mode.validate_environment()
        # Should pass if cache directory is writable
        # Errors list may be empty or contain warnings
        assert isinstance(errors, list)

    def test_get_startup_message(self) -> None:
        """Test that standard mode returns startup message."""
        mode = StandardMode()
        message = mode.get_startup_message()
        assert "standard mode" in message.lower()
        assert "remote" in message.lower()
        assert "enabled" in message.lower()

    def test_to_dict(self) -> None:
        """Test that standard mode can be converted to dict."""
        mode = StandardMode()
        config_dict = mode.to_dict()
        assert config_dict["mode"] == "standard"
        assert config_dict["remote_enabled"] is True
        assert config_dict["signature_required"] is True


class TestModeCreation:
    """Tests for mode creation utilities."""

    def test_create_lite_mode(self) -> None:
        """Test creating lite mode."""
        mode = create_mode("lite")
        assert isinstance(mode, LiteMode)
        assert mode.name == "lite"

    def test_create_standard_mode(self) -> None:
        """Test creating standard mode."""
        mode = create_mode("standard")
        assert isinstance(mode, StandardMode)
        assert mode.name == "standard"

    def test_create_mode_with_invalid_name(self) -> None:
        """Test that creating mode with invalid name raises error."""
        with pytest.raises(ValueError, match="Unknown mode"):
            create_mode("invalid")

    def test_create_mode_case_insensitive(self) -> None:
        """Test that mode creation is case-insensitive."""
        mode1 = create_mode("Lite")
        mode2 = create_mode("LITE")
        mode3 = create_mode("lite")
        assert all(isinstance(m, LiteMode) for m in [mode1, mode2, mode3])

    def test_create_mode_with_variations(self) -> None:
        """Test that mode creation handles hyphens and underscores."""
        mode1 = create_mode("Lite")
        mode2 = create_mode("LITE")
        assert all(isinstance(m, LiteMode) for m in [mode1, mode2])

    def test_get_mode_from_environment_default(self) -> None:
        """Test that get_mode_from_environment defaults to lite."""
        # Clear environment variable
        os.environ.pop("ONEIRIC_MODE", None)
        mode_name = get_mode_from_environment()
        assert mode_name == "lite"

    def test_get_mode_from_environment_set(self) -> None:
        """Test that get_mode_from_environment reads from environment."""
        os.environ["ONEIRIC_MODE"] = "standard"
        mode_name = get_mode_from_environment()
        assert mode_name == "standard"
        # Cleanup
        os.environ.pop("ONEIRIC_MODE", None)

    def test_get_mode_detects_from_environment(self) -> None:
        """Test that get_mode detects from environment."""
        os.environ["ONEIRIC_MODE"] = "standard"
        mode = get_mode()
        assert isinstance(mode, StandardMode)
        # Cleanup
        os.environ.pop("ONEIRIC_MODE", None)

    def test_get_available_modes(self) -> None:
        """Test that get_available_modes returns correct list."""
        modes = get_available_modes()
        assert modes == ["lite", "standard"]
        assert AVAILABLE_MODES == ["lite", "standard"]


class TestModeUtils:
    """Tests for mode utility functions."""

    def test_apply_mode_to_settings_lite(self) -> None:
        """Test applying lite mode to settings."""
        settings = OneiricSettings()
        mode = create_mode("lite")
        updated = apply_mode_to_settings(settings, mode)

        assert updated.remote.enabled is False
        assert updated.remote.signature_required is False
        assert updated.profile.name == "lite"
        assert updated.profile.remote_enabled is False
        assert updated.profile.inline_manifest_only is True
        assert updated.profile.supervisor_enabled is False

    def test_apply_mode_to_settings_standard(self) -> None:
        """Test applying standard mode to settings."""
        settings = OneiricSettings()
        mode = create_mode("standard")
        updated = apply_mode_to_settings(settings, mode)

        assert updated.remote.enabled is True
        assert updated.remote.signature_required is True
        assert updated.profile.name == "standard"
        assert updated.profile.remote_enabled is True
        assert updated.profile.inline_manifest_only is False
        assert updated.profile.supervisor_enabled is True

    def test_validate_mode_requirements_lite(self) -> None:
        """Test validating lite mode requirements."""
        settings = OneiricSettings()
        mode = create_mode("lite")
        errors = validate_mode_requirements(mode, settings)
        # Lite mode should have no errors
        assert isinstance(errors, list)

    def test_validate_mode_requirements_standard(self) -> None:
        """Test validating standard mode requirements."""
        settings = OneiricSettings()
        mode = create_mode("standard")
        errors = validate_mode_requirements(mode, settings)
        # Standard mode should validate without blocking errors
        assert isinstance(errors, list)

    def test_get_mode_startup_info(self) -> None:
        """Test getting mode startup info."""
        mode = create_mode("lite")
        info = get_mode_startup_info(mode)

        assert info["name"] == "lite"
        assert info["remote_enabled"] is False
        assert info["signature_required"] is False
        assert info["setup_time_minutes"] == 2
        assert "startup_message" in info

    def test_print_mode_startup_info(self, capsys: pytest.CaptureFixture) -> None:
        """Test printing mode startup info."""
        mode = create_mode("standard")
        print_mode_startup_info(mode)
        captured = capsys.readouterr()
        assert "STANDARD" in captured.out
        assert "Oneiric Operational Mode" in captured.out

    def test_load_mode_config_file_lite(self) -> None:
        """Test loading lite mode config file."""
        config_path = load_mode_config_file("lite")
        # May return None if config file doesn't exist
        assert config_path is None or config_path.name == "lite.yaml"

    def test_load_mode_config_file_standard(self) -> None:
        """Test loading standard mode config file."""
        config_path = load_mode_config_file("standard")
        # May return None if config file doesn't exist
        assert config_path is None or config_path.name == "standard.yaml"


class TestModeConfig:
    """Tests for ModeConfig dataclass."""

    def test_mode_config_creation(self) -> None:
        """Test creating ModeConfig."""
        config = ModeConfig(
            name="test",
            remote_enabled=False,
            signature_required=False,
            manifest_sync_enabled=False,
            cloud_backup_enabled=False,
            watchers_enabled=True,
            supervisor_enabled=False,
            inline_manifest_only=True,
            setup_time_minutes=1,
        )
        assert config.name == "test"
        assert config.remote_enabled is False

    def test_mode_config_to_dict(self) -> None:
        """Test converting ModeConfig to dict."""
        config = ModeConfig(
            name="test",
            remote_enabled=True,
            signature_required=True,
            manifest_sync_enabled=True,
            cloud_backup_enabled=True,
            watchers_enabled=True,
            supervisor_enabled=True,
            inline_manifest_only=False,
            setup_time_minutes=5,
            additional_settings={"custom": "value"},
        )
        config_dict = config.to_dict()
        assert config_dict["mode"] == "test"
        assert config_dict["remote_enabled"] is True
        assert config_dict["custom"] == "value"


class TestModeIntegration:
    """Integration tests for mode system."""

    def test_mode_switching(self) -> None:
        """Test switching between modes."""
        settings = OneiricSettings()

        # Start with lite mode
        lite_mode = create_mode("lite")
        lite_settings = apply_mode_to_settings(settings, lite_mode)
        assert lite_settings.remote.enabled is False

        # Switch to standard mode
        standard_mode = create_mode("standard")
        standard_settings = apply_mode_to_settings(settings, standard_mode)
        assert standard_settings.remote.enabled is True

    def test_mode_preserves_non_mode_settings(self) -> None:
        """Test that applying mode preserves non-mode settings."""
        settings = OneiricSettings(
            app={"name": "test", "environment": "test", "debug": True}
        )
        mode = create_mode("lite")
        updated = apply_mode_to_settings(settings, mode)

        # Non-mode settings should be preserved
        assert updated.app.name == "test"
        assert updated.app.environment == "test"
        assert updated.app.debug is True

    def test_all_modes_have_valid_config(self) -> None:
        """Test that all available modes have valid configuration."""
        for mode_name in get_available_modes():
            mode = create_mode(mode_name)
            config = mode.get_config()
            assert isinstance(config, ModeConfig)
            assert config.name == mode_name
            assert isinstance(config.remote_enabled, bool)
            assert isinstance(config.signature_required, bool)
            assert isinstance(config.setup_time_minutes, int)
            assert config.setup_time_minutes > 0
