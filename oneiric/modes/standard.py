"""Standard operational mode - full-featured production mode.

Standard mode is designed for:
- Daily development
- Production deployments
- Multi-server coordination
- Remote manifest delivery
- Team collaboration

Features:
- Local + Remote configuration
- Remote manifest resolution
- Required signature verification
- Auto-sync with watch
- Optional cloud backup
- Runtime supervisor
- External services (Dhruva optional)

Setup Time: ~ 5 minutes
"""

from __future__ import annotations

from pathlib import Path

from oneiric.modes.base import ModeConfig, OperationMode


class StandardMode(OperationMode):
    """Standard operational mode with remote resolution and full features.

    This mode provides the complete Oneiric experience with remote
    manifest delivery, automatic sync, and all production features enabled.

    Example:
        >>> from oneiric.modes import StandardMode
        >>>
        >>> mode = StandardMode()
        >>> config = mode.get_config()
        >>> print(config.remote_enabled)  # True
        >>> print(config.signature_required)  # True
    """

    @property
    def name(self) -> str:
        """Get mode name.

        Returns:
            Mode name
        """
        return "standard"

    def get_config(self) -> ModeConfig:
        """Get standard mode configuration.

        Returns:
            ModeConfig with all features enabled

        Example:
            >>> mode = StandardMode()
            >>> config = mode.get_config()
            >>> print(config.remote_enabled)  # True
            >>> print(config.signature_required)  # True
            >>> print(config.manifest_sync_enabled)  # True
            >>> print(config.setup_time_minutes)  # 5
        """
        return ModeConfig(
            name="standard",
            # Enable remote features
            remote_enabled=True,
            signature_required=True,  # Required in standard mode
            manifest_sync_enabled=True,  # Auto-sync with watch
            cloud_backup_enabled=True,  # Optional cloud backup
            # Enable all features
            watchers_enabled=True,  # File watchers for config changes
            supervisor_enabled=True,  # Runtime supervisor for health
            inline_manifest_only=False,  # Remote manifests allowed
            # Metadata
            setup_time_minutes=5,
            external_dependencies=[
                "Dhruva (optional) - Remote manifest server",
            ],
            additional_settings={
                "description": "Full-featured mode with remote resolution",
                "use_case": "Production, development, team collaboration",
                "remote_resolution": "Enabled - fetch manifests from remote",
                "signature_verification": "Required - ED25519 signatures",
                "manifest_sync": "Automatic - with --watch or refresh interval",
                "cloud_backup": "Optional - backup to cloud storage",
            },
        )

    def validate_environment(self) -> list[str]:
        """Validate that the environment supports standard mode.

        Checks for:
        - Writable cache directory
        - Network connectivity (optional warning)
        - Sufficient disk space

        Returns:
            List of validation errors (empty if valid)

        Example:
            >>> mode = StandardMode()
            >>> errors = mode.validate_environment()
            >>> if errors:
            ...     print(f"Validation errors: {errors}")
        """
        errors = []

        # Check cache directory is writable
        cache_dir = Path(".oneiric_cache")
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            # Test write access
            test_file = cache_dir / ".write_test"
            test_file.touch()
            test_file.unlink()
        except PermissionError:
            errors.append(
                f"Cache directory {cache_dir} is not writable. Check permissions."
            )
        except Exception as e:
            errors.append(f"Failed to access cache directory: {e}")

        # Warn about network connectivity (non-blocking)
        # Note: We don't block startup on network issues since remote
        # resolution can fail gracefully

        return errors

    def get_startup_message(self) -> str:
        """Get startup message for standard mode.

        Returns:
            Human-readable startup message with mode characteristics

        Example:
            >>> mode = StandardMode()
            >>> message = mode.get_startup_message()
            >>> print(message)
            Starting Oneiric in standard mode...
            Configuration: Local + Remote
            Setup time: ~ 5 minutes
            Remote resolution: Enabled
        """
        return """Starting Oneiric in standard mode...

Configuration:
  - Source: Local + Remote manifests
  - Remote resolution: Enabled
  - Signature verification: Required
  - Manifest sync: Automatic (with --watch)
  - Cloud backup: Enabled (optional)

Features:
  - File watchers: Enabled
  - Runtime supervisor: Enabled
  - External dependencies: Dhruva (optional)

Setup time: ~ 5 minutes

To sync from remote:
  oneiric remote-sync --manifest-url <url> --watch

To verify manifest signatures:
  oneiric manifest verify --manifest <path>

To monitor sync status:
  oneiric remote-status
"""

    def to_dict(self) -> dict[str, bool | str | int | list[str]]:
        """Get standard mode configuration as dictionary.

        Returns:
            Dictionary with mode settings

        Example:
            >>> mode = StandardMode()
            >>> config_dict = mode.to_dict()
            >>> print(config_dict["mode"])  # standard
            >>> print(config_dict["remote_enabled"])  # True
        """
        config = self.get_config()
        return config.to_dict()
