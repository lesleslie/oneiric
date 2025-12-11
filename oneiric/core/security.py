"""Security validation helpers for Oneiric.

This module provides security controls for factory resolution, input validation,
and other security-critical operations.
"""

from __future__ import annotations

import os
import re
from typing import Any

# Factory string format: module.path:function_name
FACTORY_PATTERN = re.compile(
    r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)*:[a-zA-Z_][a-zA-Z0-9_]*$"
)

# Default safe prefixes (allow only oneiric and explicitly approved packages)
DEFAULT_ALLOWED_PREFIXES = [
    "oneiric.",
    # Users can extend via ONEIRIC_FACTORY_ALLOWLIST environment variable
]

# Modules that are always blocked (security risk)
BLOCKED_MODULES = [
    "os",
    "subprocess",
    "sys",
    "importlib",
    "__builtin__",
    "builtins",
    "shutil",
    "pathlib",  # Can be used for path manipulation
    "tempfile",  # Can write to filesystem
]


def validate_factory_string(
    factory: str,
    allowed_prefixes: list[str] | None = None,
) -> tuple[bool, str | None]:
    """Validate factory string format and module path.

    Args:
        factory: Factory string in format "module.path:function"
        allowed_prefixes: List of allowed module prefixes (defaults to DEFAULT_ALLOWED_PREFIXES)

    Returns:
        Tuple of (is_valid, error_message). error_message is None if valid.

    Examples:
        >>> validate_factory_string("oneiric.demo:DemoAdapter")
        (True, None)

        >>> validate_factory_string("os:system")
        (False, "Factory module 'os' is blocked for security reasons")

        >>> validate_factory_string("invalid")
        (False, "Invalid factory format: invalid. Expected 'module.path:function'")
    """
    # Format validation
    if not FACTORY_PATTERN.match(factory):
        return (
            False,
            f"Invalid factory format: {factory}. Expected 'module.path:function'",
        )

    module_path, _, attr = factory.partition(":")

    # Check against blocked modules first (highest priority)
    for blocked in BLOCKED_MODULES:
        if module_path == blocked or module_path.startswith(f"{blocked}."):
            return (
                False,
                f"Factory module '{module_path}' is blocked for security reasons",
            )

    # Check against allowlist
    prefixes = (
        allowed_prefixes if allowed_prefixes is not None else DEFAULT_ALLOWED_PREFIXES
    )

    # If allowlist is empty, reject all
    if not prefixes:
        return (
            False,
            f"Factory module '{module_path}' not in allowlist (allowlist is empty)",
        )

    if not any(module_path.startswith(prefix) for prefix in prefixes):
        return (
            False,
            f"Factory module '{module_path}' not in allowlist. Allowed prefixes: {prefixes}",
        )

    return True, None


def load_factory_allowlist() -> list[str]:
    """Load factory allowlist from environment or config.

    Reads from ONEIRIC_FACTORY_ALLOWLIST environment variable.
    Format: comma-separated list of module prefixes.

    Returns:
        List of allowed module prefixes

    Examples:
        # With env: ONEIRIC_FACTORY_ALLOWLIST="oneiric.,myapp.,vendor."
        >>> load_factory_allowlist()
        ['oneiric.', 'myapp.', 'vendor.']

        # Without env (defaults)
        >>> load_factory_allowlist()
        ['oneiric.']
    """
    env_value = os.getenv("ONEIRIC_FACTORY_ALLOWLIST")
    if env_value is not None:
        # Environment variable is set (even if empty)
        # Parse comma-separated list and ensure trailing dots
        prefixes = []
        for prefix in env_value.split(","):
            prefix = prefix.strip()
            if prefix and not prefix.endswith("."):
                prefix += "."
            if prefix:
                prefixes.append(prefix)
        return prefixes
    return DEFAULT_ALLOWED_PREFIXES.copy()


def validate_key_format(key: str, allow_dots: bool = True) -> tuple[bool, str | None]:
    """Validate component key format (prevent path traversal).

    Args:
        key: Component key to validate
        allow_dots: Whether to allow dots in keys (default: True)

    Returns:
        Tuple of (is_valid, error_message)

    Examples:
        >>> validate_key_format("my-component")
        (True, None)

        >>> validate_key_format("../../evil")
        (False, "Key contains path traversal: ../../evil")
    """
    if not key:
        return False, "Key cannot be empty"

    # Check for path traversal attempts
    if ".." in key or key.startswith("/") or "\\" in key:
        return False, f"Key contains path traversal: {key}"

    # Validate character set (alphanumeric, dash, underscore, optionally dot)
    if allow_dots:
        pattern = r"^[a-zA-Z0-9_\-\.]+$"
    else:
        pattern = r"^[a-zA-Z0-9_\-]+$"

    if not re.match(pattern, key):
        allowed = "alphanumeric with -_." if allow_dots else "alphanumeric with -_"
        return False, f"Key contains invalid characters (must be {allowed}): {key}"

    return True, None


def validate_priority_bounds(priority: Any) -> tuple[bool, str | None]:
    """Validate priority is within acceptable bounds.

    Args:
        priority: Priority value to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    MIN_PRIORITY = -1000
    MAX_PRIORITY = 1000

    if not isinstance(priority, int):
        return False, f"Priority must be integer, got {type(priority).__name__}"

    # Type guard satisfied - priority is int
    if priority < MIN_PRIORITY or priority > MAX_PRIORITY:
        return (
            False,
            f"Priority {priority} out of bounds [{MIN_PRIORITY}, {MAX_PRIORITY}]",
        )

    return True, None


def validate_stack_level_bounds(stack_level: Any) -> tuple[bool, str | None]:
    """Validate stack_level is within acceptable bounds.

    Args:
        stack_level: Stack level value to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    MIN_STACK_LEVEL = -100
    MAX_STACK_LEVEL = 100

    if not isinstance(stack_level, int):
        return False, f"Stack level must be integer, got {type(stack_level).__name__}"

    # Type guard satisfied - stack_level is int
    if stack_level < MIN_STACK_LEVEL or stack_level > MAX_STACK_LEVEL:
        return (
            False,
            f"Stack level {stack_level} out of bounds [{MIN_STACK_LEVEL}, {MAX_STACK_LEVEL}]",
        )

    return True, None
