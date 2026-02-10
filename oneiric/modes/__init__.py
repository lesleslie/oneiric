"""Oneiric operational modes.

This module provides different operational modes for Oneiric:
- Lite mode: Zero-dependency, local-only mode (< 2 min setup)
- Standard mode: Full-featured production mode (~ 5 min setup)

Example:
    >>> from oneiric.modes import create_mode, get_mode
    >>>
    >>> # Create mode explicitly
    >>> mode = create_mode("lite")
    >>> config = mode.get_config()
    >>>
    >>> # Or detect from environment
    >>> mode = get_mode()  # Reads ONEIRIC_MODE env var
    >>>
    >>> # Get mode info
    >>> print(mode.get_startup_message())
"""

from oneiric.modes.base import OperationMode, get_mode, register_mode
from oneiric.modes.lite import LiteMode
from oneiric.modes.standard import StandardMode
from oneiric.modes.utils import (
    apply_mode_to_settings,
    get_mode_from_environment,
    get_mode_startup_info,
    load_mode_config_file,
    print_mode_startup_info,
    validate_mode_requirements,
)

__all__ = [
    "OperationMode",
    "LiteMode",
    "StandardMode",
    "create_mode",
    "get_mode",
    "register_mode",
    "apply_mode_to_settings",
    "get_mode_from_environment",
    "get_mode_startup_info",
    "load_mode_config_file",
    "print_mode_startup_info",
    "validate_mode_requirements",
]


def create_mode(mode_name: str) -> OperationMode:
    """Create a mode instance by name.

    Args:
        mode_name: Mode name (lite, standard)

    Returns:
        OperationMode instance

    Raises:
        ValueError: If mode_name is unknown

    Example:
        >>> from oneiric.modes import create_mode
        >>>
        >>> mode = create_mode("lite")
        >>> print(mode.name)  # lite
        >>>
        >>> mode = create_mode("standard")
        >>> print(mode.name)  # standard
    """
    mode_classes = {
        "lite": LiteMode,
        "standard": StandardMode,
    }

    # Normalize mode name
    mode_name = mode_name.lower().replace("_", "").replace("-", "")

    mode_class = mode_classes.get(mode_name)
    if not mode_class:
        available = ", ".join(mode_classes.keys())
        raise ValueError(f"Unknown mode: {mode_name}. Available modes: {available}")

    return mode_class()


# List available modes
AVAILABLE_MODES = ["lite", "standard"]


def get_available_modes() -> list[str]:
    """Get list of available operational modes.

    Returns:
        List of mode names

    Example:
        >>> from oneiric.modes import get_available_modes
        >>> modes = get_available_modes()
        >>> print(modes)  # ['lite', 'standard']
    """
    return AVAILABLE_MODES.copy()
