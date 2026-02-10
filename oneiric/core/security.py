from __future__ import annotations

import hmac
import os
import re
from typing import Any

FACTORY_PATTERN = re.compile(
    r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)*:[a-zA-Z_][a-zA-Z0-9_]*$"
)


DEFAULT_ALLOWED_PREFIXES = [
    "oneiric.",
]


BLOCKED_MODULES = [
    "os",
    "subprocess",
    "sys",
    "importlib",
    "__builtin__",
    "builtins",
    "shutil",
    "pathlib",
    "tempfile",
]


def validate_factory_string(
    factory: str,
    allowed_prefixes: list[str] | None = None,
) -> tuple[bool, str | None]:
    if not FACTORY_PATTERN.match(factory):
        return (
            False,
            f"Invalid factory format: {factory}. Expected 'module.path: function'",
        )

    module_path, _, attr = factory.partition(":")

    for blocked in BLOCKED_MODULES:
        if module_path == blocked or module_path.startswith(f"{blocked}."):
            return (
                False,
                f"Factory module '{module_path}' is blocked for security reasons",
            )

    prefixes = (
        allowed_prefixes if allowed_prefixes is not None else DEFAULT_ALLOWED_PREFIXES
    )

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
    env_value = os.getenv("ONEIRIC_FACTORY_ALLOWLIST")
    if env_value is not None:
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
    if not key:
        return False, "Key cannot be empty"

    if ".." in key or key.startswith("/") or "\\" in key:
        return False, f"Key contains path traversal: {key}"

    if allow_dots:
        pattern = r"^[a-zA-Z0-9_\-\.]+$"
    else:
        pattern = r"^[a-zA-Z0-9_\-]+$"

    if not re.match(pattern, key):
        allowed = "alphanumeric with -_." if allow_dots else "alphanumeric with -_"
        return False, f"Key contains invalid characters (must be {allowed}): {key}"

    return True, None


def validate_priority_bounds(priority: Any) -> tuple[bool, str | None]:
    MIN_PRIORITY = -1000
    MAX_PRIORITY = 1000

    if not isinstance(priority, int):
        return False, f"Priority must be integer, got {type(priority).__name__}"

    if priority < MIN_PRIORITY or priority > MAX_PRIORITY:
        return (
            False,
            f"Priority {priority} out of bounds [{MIN_PRIORITY}, {MAX_PRIORITY}]",
        )

    return True, None


def validate_stack_level_bounds(stack_level: Any) -> tuple[bool, str | None]:
    MIN_STACK_LEVEL = -100
    MAX_STACK_LEVEL = 100

    if not isinstance(stack_level, int):
        return False, f"Stack level must be integer, got {type(stack_level).__name__}"

    if stack_level < MIN_STACK_LEVEL or stack_level > MAX_STACK_LEVEL:
        return (
            False,
            f"Stack level {stack_level} out of bounds [{MIN_STACK_LEVEL}, {MAX_STACK_LEVEL}]",
        )

    return True, None


def constant_time_compare(a: str, b: str) -> bool:
    if not isinstance(a, str) or not isinstance(b, str):
        raise TypeError(
            f"constant_time_compare requires str arguments, got {type(a).__name__} and {type(b).__name__}"
        )

    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def timing_safe_compare(a: str | bytes, b: str | bytes) -> bool:

    if isinstance(a, str) and isinstance(b, str):
        return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))

    if isinstance(a, bytes) and isinstance(b, bytes):
        return hmac.compare_digest(a, b)

    raise TypeError(
        f"timing_safe_compare requires both arguments to be str or both to be bytes, "
        f"got {type(a).__name__} and {type(b).__name__}"
    )


def constant_time_bytes_compare(a: bytes, b: bytes) -> bool:
    if not isinstance(a, bytes) or not isinstance(b, bytes):
        raise TypeError(
            f"constant_time_bytes_compare requires bytes arguments, got {type(a).__name__} and {type(b).__name__}"
        )

    return hmac.compare_digest(a, b)
