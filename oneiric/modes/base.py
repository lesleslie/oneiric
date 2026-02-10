"""Base operational mode interface for Oneiric.

Defines the abstract interface that all operational modes must implement.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ModeConfig:
    """Configuration for an operational mode.

    Attributes:
        name: Mode name (lite, standard, etc.)
        remote_enabled: Whether remote manifest resolution is enabled
        signature_required: Whether manifest signatures are required
        manifest_sync_enabled: Whether automatic manifest sync is enabled
        cloud_backup_enabled: Whether cloud backup is enabled
        watchers_enabled: Whether file watchers are enabled
        supervisor_enabled: Whether runtime supervisor is enabled
        inline_manifest_only: Whether only inline manifests are allowed
        setup_time_minutes: Estimated setup time in minutes
        external_dependencies: List of external service dependencies
        additional_settings: Additional mode-specific settings

    Example:
        >>> config = ModeConfig(
        ...     name="lite", remote_enabled=False, signature_required=False
        ... )
    """

    name: str
    remote_enabled: bool
    signature_required: bool
    manifest_sync_enabled: bool
    cloud_backup_enabled: bool
    watchers_enabled: bool
    supervisor_enabled: bool
    inline_manifest_only: bool
    setup_time_minutes: int
    external_dependencies: list[str] = field(default_factory=list)
    additional_settings: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert config to dictionary.

        Returns:
            Dictionary representation of the config
        """
        return {
            "mode": self.name,
            "remote_enabled": self.remote_enabled,
            "signature_required": self.signature_required,
            "manifest_sync_enabled": self.manifest_sync_enabled,
            "cloud_backup_enabled": self.cloud_backup_enabled,
            "watchers_enabled": self.watchers_enabled,
            "supervisor_enabled": self.supervisor_enabled,
            "inline_manifest_only": self.inline_manifest_only,
            "setup_time_minutes": self.setup_time_minutes,
            "external_dependencies": self.external_dependencies,
            **self.additional_settings,
        }


class OperationMode(ABC):
    """Abstract base class for operational modes.

    All operational modes must inherit from this class and implement
    the abstract methods.

    Example:
        >>> class LiteMode(OperationMode):
        ...     @property
        ...     def name(self) -> str:
        ...         return "lite"
        ...
        ...     def get_config(self) -> ModeConfig:
        ...         return ModeConfig(
        ...             name="lite", remote_enabled=False, signature_required=False
        ...         )
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Get mode name.

        Returns:
            Mode name (e.g., "lite", "standard")
        """
        ...

    @abstractmethod
    def get_config(self) -> ModeConfig:
        """Get mode configuration.

        Returns:
            ModeConfig instance with all mode-specific settings
        """
        ...

    def validate_environment(self) -> list[str]:
        """Validate that the environment supports this mode.

        Returns:
            List of validation errors (empty if valid)

        Example:
            >>> errors = mode.validate_environment()
            >>> if errors:
            ...     print(f"Validation errors: {errors}")
        """
        return []

    def get_startup_message(self) -> str:
        """Get startup message for this mode.

        Returns:
            Human-readable startup message

        Example:
            >>> message = mode.get_startup_message()
            >>> print(message)
            Starting Oneiric in lite mode...
        """
        return f"Starting Oneiric in {self.name} mode..."


# Mode registry
_MODE_REGISTRY: dict[str, type[OperationMode]] = {}


def register_mode(mode_class: type[OperationMode]) -> None:
    """Register a mode class.

    Args:
        mode_class: Mode class to register

    Example:
        >>> @register_mode
        ... class LiteMode(OperationMode):
        ...     pass
    """
    _MODE_REGISTRY[mode_class.__name__.lower()] = mode_class


def get_mode(mode_name: str | None = None) -> OperationMode:
    """Get mode instance by name.

    Args:
        mode_name: Mode name (lite, standard). If None, detects from environment.

    Returns:
        OperationMode instance

    Raises:
        ValueError: If mode name is invalid

    Example:
        >>> # Detect from environment
        >>> mode = get_mode()
        >>>
        >>> # Specify mode explicitly
        >>> mode = get_mode("lite")
    """
    if mode_name is None:
        # Detect from environment variable
        mode_name = os.getenv("ONEIRIC_MODE", "lite").lower()

    # Normalize mode name
    mode_name = mode_name.lower().replace("_", "").replace("-", "")

    # Import mode implementations
    from oneiric.modes.lite import LiteMode
    from oneiric.modes.standard import StandardMode

    # Map mode names to classes
    mode_classes: dict[str, type[OperationMode]] = {
        "lite": LiteMode,
        "standard": StandardMode,
    }

    mode_class = mode_classes.get(mode_name)
    if mode_class is None:
        available = ", ".join(mode_classes.keys())
        msg = f"Invalid mode '{mode_name}'. Available modes: {available}"
        raise ValueError(msg)

    return mode_class()
