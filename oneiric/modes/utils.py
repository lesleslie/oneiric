"""Utility functions for integrating operational modes with Oneiric configuration.

This module provides helper functions to apply mode configurations to
OneiricSettings and handle mode-specific overrides.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from oneiric.core.config import OneiricSettings
from oneiric.modes.base import OperationMode


def apply_mode_to_settings(
    settings: OneiricSettings, mode: OperationMode
) -> OneiricSettings:
    """Apply operational mode configuration to OneiricSettings.

    This function updates the settings instance with mode-specific
    configuration while preserving existing values where appropriate.

    Args:
        settings: Base OneiricSettings instance
        mode: OperationMode instance to apply

    Returns:
        Updated OneiricSettings with mode configuration applied

    Example:
        >>> from oneiric.modes import create_mode
        >>> from oneiric.modes.utils import apply_mode_to_settings
        >>>
        >>> mode = create_mode("lite")
        >>> updated_settings = apply_mode_to_settings(settings, mode)
    """
    config = mode.get_config()

    # Create a deep copy to avoid mutating the original
    updated = settings.model_copy(deep=True)

    # Apply remote configuration based on mode
    updated.remote.enabled = config.remote_enabled
    updated.remote.signature_required = config.signature_required

    # Apply manifest sync settings
    if not config.manifest_sync_enabled:
        updated.remote.refresh_interval = None

    # Apply runtime profile based on mode
    updated.profile.name = config.name
    updated.profile.remote_enabled = config.remote_enabled
    updated.profile.inline_manifest_only = config.inline_manifest_only
    updated.profile.watchers_enabled = config.watchers_enabled
    updated.profile.supervisor_enabled = config.supervisor_enabled

    # Apply runtime paths
    if not config.supervisor_enabled:
        # Disable checkpoints if supervisor is disabled
        updated.runtime_paths.workflow_checkpoints_enabled = False

    # Apply runtime supervisor settings
    updated.runtime_supervisor.enabled = config.supervisor_enabled

    return updated


def load_mode_config_file(mode_name: str) -> Path | None:
    """Load mode-specific configuration file path.

    Args:
        mode_name: Name of the mode (lite, standard)

    Returns:
        Path to mode config file, or None if not found

    Example:
        >>> from oneiric.modes.utils import load_mode_config_file
        >>>
        >>> config_path = load_mode_config_file("lite")
        >>> print(config_path)  # PosixPath('config/lite.yaml')
    """
    # Check for config directory in current directory
    config_dir = Path("config")
    if config_dir.exists():
        config_file = config_dir / f"{mode_name}.yaml"
        if config_file.exists():
            return config_file

    # Check for config directory in package root
    # This is useful when running from installed package
    import oneiric

    package_root = Path(oneiric.__file__).parent.parent
    config_dir = package_root / "config"
    if config_dir.exists():
        config_file = config_dir / f"{mode_name}.yaml"
        if config_file.exists():
            return config_file

    return None


def get_mode_from_environment() -> str:
    """Get operational mode from environment variable.

    Checks the ONEIRIC_MODE environment variable. Defaults to "lite"
    if not set.

    Returns:
        Mode name (lite, standard)

    Example:
        >>> import os
        >>> os.environ["ONEIRIC_MODE"] = "standard"
        >>> from oneiric.modes.utils import get_mode_from_environment
        >>> mode = get_mode_from_environment()
        >>> print(mode)  # standard
    """
    return os.getenv("ONEIRIC_MODE", "lite").lower()


def validate_mode_requirements(
    mode: OperationMode, settings: OneiricSettings
) -> list[str]:
    """Validate that settings meet mode requirements.

    Args:
        mode: OperationMode instance
        settings: OneiricSettings to validate

    Returns:
        List of validation errors (empty if valid)

    Example:
        >>> from oneiric.modes import create_mode
        >>> from oneiric.modes.utils import validate_mode_requirements
        >>>
        >>> mode = create_mode("standard")
        >>> errors = validate_mode_requirements(mode, settings)
        >>> if errors:
        ...     print(f"Validation errors: {errors}")
    """
    errors = []
    config = mode.get_config()

    # Validate remote settings for standard mode
    if config.remote_enabled and config.signature_required:
        if not settings.remote.manifest_url:
            # Only warn if remote is enabled but no URL is provided
            # This is not necessarily an error, as manifest can be provided via CLI
            pass

    # Validate cache directory
    cache_dir = Path(settings.remote.cache_dir)
    if not cache_dir.exists():
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            errors.append(f"Cannot create cache directory {cache_dir}: {e}")

    return errors


def get_mode_startup_info(mode: OperationMode) -> dict[str, Any]:
    """Get comprehensive startup information for a mode.

    Args:
        mode: OperationMode instance

    Returns:
        Dictionary with mode information

    Example:
        >>> from oneiric.modes import create_mode
        >>> from oneiric.modes.utils import get_mode_startup_info
        >>>
        >>> mode = create_mode("lite")
        >>> info = get_mode_startup_info(mode)
        >>> print(info["name"])  # lite
        >>> print(info["setup_time_minutes"])  # 2
    """
    config = mode.get_config()

    return {
        "name": config.name,
        "remote_enabled": config.remote_enabled,
        "signature_required": config.signature_required,
        "manifest_sync_enabled": config.manifest_sync_enabled,
        "cloud_backup_enabled": config.cloud_backup_enabled,
        "watchers_enabled": config.watchers_enabled,
        "supervisor_enabled": config.supervisor_enabled,
        "inline_manifest_only": config.inline_manifest_only,
        "setup_time_minutes": config.setup_time_minutes,
        "external_dependencies": config.external_dependencies,
        "startup_message": mode.get_startup_message(),
        **config.additional_settings,
    }


def print_mode_startup_info(mode: OperationMode) -> None:
    """Print mode startup information to console.

    Args:
        mode: OperationMode instance

    Example:
        >>> from oneiric.modes import create_mode
        >>> from oneiric.modes.utils import print_mode_startup_info
        >>>
        >>> mode = create_mode("standard")
        >>> print_mode_startup_info(mode)
    """
    info = get_mode_startup_info(mode)
    print("\n" + "=" * 60)
    print(f"Oneiric Operational Mode: {info['name'].upper()}")
    print("=" * 60)
    print(info.get("startup_message", mode.get_startup_message()))
    print("=" * 60 + "\n")
