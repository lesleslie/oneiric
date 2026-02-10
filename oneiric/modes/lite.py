"""Lite operational mode - zero-dependency, local-only mode.

Lite mode is designed for:
- Quick testing and development
- CI/CD pipelines
- Temporary sessions
- Performance testing
- Users new to Oneiric

Features:
- Local configuration only
- No remote manifest resolution
- Optional signature verification
- Manual manifest sync only
- No external dependencies
- No cloud backup
- Minimal setup time

Setup Time: < 2 minutes
"""

from __future__ import annotations

from oneiric.modes.base import ModeConfig, OperationMode


class LiteMode(OperationMode):
    """Lite operational mode with minimal dependencies and local-only operation.

    This mode provides the fastest startup time and zero external service
    dependencies, making it ideal for development, testing, and users who
    want to understand Oneiric before adopting remote features.

    Example:
        >>> from oneiric.modes import LiteMode
        >>>
        >>> mode = LiteMode()
        >>> config = mode.get_config()
        >>> print(config.remote_enabled)  # False
        >>> print(config.signature_required)  # False
    """

    @property
    def name(self) -> str:
        """Get mode name.

        Returns:
            Mode name
        """
        return "lite"

    def get_config(self) -> ModeConfig:
        """Get lite mode configuration.

        Returns:
            ModeConfig optimized for minimal dependencies and fast startup

        Example:
            >>> mode = LiteMode()
            >>> config = mode.get_config()
            >>> print(config.remote_enabled)  # False
            >>> print(config.signature_required)  # False
            >>> print(config.manifest_sync_enabled)  # False
            >>> print(config.setup_time_minutes)  # 2
        """
        return ModeConfig(
            name="lite",
            # Disable remote features
            remote_enabled=False,
            signature_required=False,  # Optional in lite mode
            manifest_sync_enabled=False,  # Manual sync only
            cloud_backup_enabled=False,
            # Enable basic local features
            watchers_enabled=True,  # File watchers for config changes
            supervisor_enabled=False,  # No runtime supervisor needed
            inline_manifest_only=True,  # Local manifests only
            # Metadata
            setup_time_minutes=2,
            external_dependencies=[],  # Zero external dependencies
            additional_settings={
                "description": "Local-only mode with minimal dependencies",
                "use_case": "Development, testing, CI/CD",
                "remote_resolution": "Disabled - local manifests only",
                "signature_verification": "Optional - security warning if disabled",
                "manifest_sync": "Manual - use 'oneiric remote-sync' command",
            },
        )

    def validate_environment(self) -> list[str]:
        """Validate that the environment supports lite mode.

        Lite mode has minimal requirements, so validation always passes.
        All dependencies are local and included with Oneiric.

        Returns:
            Empty list (no errors)

        Example:
            >>> mode = LiteMode()
            >>> errors = mode.validate_environment()
            >>> assert len(errors) == 0
        """
        return []

    def get_startup_message(self) -> str:
        """Get startup message for lite mode.

        Returns:
            Human-readable startup message with mode characteristics

        Example:
            >>> mode = LiteMode()
            >>> message = mode.get_startup_message()
            >>> print(message)
            Starting Oneiric in lite mode...
            Configuration: Local only
            Setup time: < 2 minutes
            Remote resolution: Disabled
        """
        return """Starting Oneiric in lite mode...

Configuration:
  - Source: Local files only
  - Remote resolution: Disabled
  - Signature verification: Optional
  - Manifest sync: Manual only
  - Cloud backup: Disabled

Features:
  - File watchers: Enabled
  - Runtime supervisor: Disabled
  - External dependencies: Zero

Setup time: < 2 minutes

To load remote manifests manually:
  oneiric remote-sync --manifest <path> --no-watch

To upgrade to standard mode:
  oneiric start --mode=standard --manifest-url <url>
"""

    def to_dict(self) -> dict[str, bool | str | int | list[str]]:
        """Get lite mode configuration as dictionary.

        Returns:
            Dictionary with mode settings

        Example:
            >>> mode = LiteMode()
            >>> config_dict = mode.to_dict()
            >>> print(config_dict["mode"])  # lite
            >>> print(config_dict["remote_enabled"])  # False
        """
        config = self.get_config()
        return config.to_dict()
