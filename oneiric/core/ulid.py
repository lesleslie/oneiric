"""ULID integration for Oneiric configuration management.

This module provides ULID (Universally Unique Lexicographically Sortable Identifier)
support for Oneiric, enabling:
- Time-ordered configuration traceability
- Cross-system correlation with dhruva OIDs
- Globally unique configuration IDs
- Time-based config history queries

Example:
    >>> from oneiric.core.ulid import generate_config_id, is_config_ulid, extract_timestamp
    >>> config_id = generate_config_id()
    >>> print(config_id)  # e.g., 01ARZ3NDEKTS6PQRYF
    >>> is_ulid = is_config_ulid(config_id)
    >>> timestamp_ms = extract_timestamp(config_id)
"""

from __future__ import annotations

import time
from typing import Any

# Try to import from dhruva, fallback to local implementation
try:
    from dhruva import ULID, generate, get_timestamp, is_ulid
    DHURUVA_AVAILABLE = True
except ImportError:
    DHURUVA_AVAILABLE = False
    # Fallback implementation if dhruva is not available
    import os
    import secrets

    BASE32_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"
    ULID_BINARY_SIZE = 16
    ULID_STRING_LENGTH = 26

    class ULID:
        """Fallback ULID implementation."""

        __slots__ = ("_bytes", "_str")

        def __init__(self, value: str | bytes | None = None):
            if value is None:
                self._bytes = self._generate()
                self._str = self._encode(self._bytes)
            elif isinstance(value, str):
                if len(value) != ULID_STRING_LENGTH:
                    raise ValueError(f"Invalid ULID string: {value!r}")
                self._str = value
                self._bytes = self._decode(value)
            elif isinstance(value, bytes):
                if len(value) != ULID_BINARY_SIZE:
                    raise ValueError(f"ULID bytes must be {ULID_BINARY_SIZE} bytes")
                self._bytes = value
                self._str = self._encode(value)

        def _generate(self) -> bytes:
            timestamp_ms = int(time.time() * 1000)
            timestamp_bytes = timestamp_ms.to_bytes(6, byteorder="big")
            random_bytes = secrets.token_bytes(10)
            return timestamp_bytes + random_bytes

        @staticmethod
        def _encode(data: bytes) -> str:
            if len(data) != ULID_BINARY_SIZE:
                raise ValueError(f"Data must be {ULID_BINARY_SIZE} bytes")
            value = int.from_bytes(data, byteorder="big")
            result = []
            for _ in range(ULID_STRING_LENGTH):
                index = value & 0x1F
                result.append(BASE32_ALPHABET[index])
                value >>= 5
            return "".join(reversed(result))

        @staticmethod
        def _decode(value: str) -> bytes:
            if len(value) != ULID_STRING_LENGTH:
                raise ValueError(f"Invalid ULID string: {value!r}")
            alphabet_index = {char: idx for idx, char in enumerate(BASE32_ALPHABET)}
            value_int = 0
            for char in value:
                value_int = (value_int << 5) | alphabet_index[char]
            return value_int.to_bytes(ULID_BINARY_SIZE, byteorder="big")

        @property
        def timestamp(self) -> int:
            timestamp_bytes = self._bytes[:6]
            return int.from_bytes(timestamp_bytes, byteorder="big")

        def __str__(self) -> str:
            return self._str

        def __repr__(self) -> str:
            return f"ULID({self._str!r})"

        def __eq__(self, other: object) -> bool:
            if isinstance(other, ULID):
                return self._bytes == other._bytes
            elif isinstance(other, str):
                return self._str == other
            return False

        def __hash__(self) -> int:
            return hash(self._bytes)

    def generate() -> str:
        """Generate a new ULID string."""
        return str(ULID())

    def get_timestamp(value: str | ULID) -> int:
        """Extract timestamp from ULID."""
        if isinstance(value, ULID):
            return value.timestamp
        ulid = ULID(value)
        return ulid.timestamp

    def is_ulid(value: str) -> bool:
        """Check if string is a valid ULID."""
        if not isinstance(value, str):
            return False
        if len(value) != ULID_STRING_LENGTH:
            return False
        return all(char in BASE32_ALPHABET for char in value.lower())


__all__ = [
    "generate_config_id",
    "is_config_ulid",
    "extract_timestamp",
    "parse_config_ulid",
    "ConfigTraceability",
    "generate_with_retry",  # NEW
    "CollisionError",  # NEW
    "get_collision_stats",  # NEW
    "register_reference",  # NEW from ulid_resolution
    "resolve_ulid",  # NEW from ulid_resolution
    "find_references_by_system",  # NEW from ulid_resolution
    "find_related_ulids",  # NEW from ulid_resolution
    "get_cross_system_trace",  # NEW from ulid_resolution
    "export_registry",  # NEW from ulid_resolution
    "get_registry_stats",  # NEW from ulid_resolution
    "SystemReference",  # NEW from ulid_resolution
]


def generate_config_id() -> str:
    """Generate a new ULID for configuration tracking.

    Returns:
        26-character ULID string

    Example:
        >>> config_id = generate_config_id()
        >>> print(len(config_id))
        26
    """
    return generate()


def is_config_ulid(value: str) -> bool:
    """Check if a string is a valid configuration ULID.

    Args:
        value: String to check

    Returns:
        True if valid ULID

    Example:
        >>> config_id = generate_config_id()
        >>> is_config_ulid(config_id)
        True
        >>> is_config_ulid("not-a-ulid")
        False
    """
    return is_ulid(value)


def extract_timestamp(value: str) -> int:
    """Extract timestamp from configuration ULID.

    Args:
        value: ULID string

    Returns:
        Unix timestamp in milliseconds

    Example:
        >>> config_id = generate_config_id()
        >>> ts = extract_timestamp(config_id)
        >>> print(ts > 0)
        True
    """
    return get_timestamp(value)


def parse_config_ulid(value: str) -> ULID:
    """Parse a configuration ULID string.

    Args:
        value: ULID string

    Returns:
        ULID instance

    Example:
        >>> config_id = generate_config_id()
        >>> ulid = parse_config_ulid(config_id)
        >>> print(ulid.timestamp)
    """
    if isinstance(value, ULID):
        return value
    return ULID(value)


class ConfigTraceability:
    """Configuration change tracking with ULID support.

    Provides traceability for configuration changes across systems,
    enabling cross-system correlation and time-ordered history.

    Example:
        >>> trace = ConfigTraceability(
        ...     config_id=generate_config_id(),
        ...     source="oneiric",
        ...     change_type="update"
        ... )
        >>> print(trace.config_id)
        >>> print(trace.timestamp_ms)
    """

    __slots__ = (
        "_config_id",
        "_source",
        "_change_type",
        "_timestamp_ms",
        "_metadata",
    )

    def __init__(
        self,
        config_id: str | None = None,
        source: str = "oneiric",
        change_type: str = "unknown",
        metadata: dict[str, Any] | None = None,
    ):
        """Initialize configuration traceability record.

        Args:
            config_id: ULID configuration ID (generated if None)
            source: Source system (oneiric, mahavishnu, akosha, etc.)
            change_type: Type of change (create, update, delete, etc.)
            metadata: Additional metadata
        """
        if config_id is None:
            config_id = generate_config_id()

        if not is_config_ulid(config_id):
            raise ValueError(f"Invalid config ULID: {config_id}")

        self._config_id = config_id
        self._source = source
        self._change_type = change_type
        self._metadata = metadata or {}
        self._timestamp_ms = extract_timestamp(config_id)

    @property
    def config_id(self) -> str:
        """Configuration ULID."""
        return self._config_id

    @property
    def source(self) -> str:
        """Source system."""
        return self._source

    @property
    def change_type(self) -> str:
        """Change type."""
        return self._change_type

    @property
    def timestamp_ms(self) -> int:
        """Timestamp in milliseconds (extracted from ULID)."""
        return self._timestamp_ms

    @property
    def timestamp_seconds(self) -> float:
        """Timestamp in seconds."""
        return self._timestamp_ms / 1000.0

    @property
    def metadata(self) -> dict[str, Any]:
        """Additional metadata."""
        return self._metadata.copy()

    def correlates_with(self, other_ulid: str) -> bool:
        """Check if this trace correlates with another ULID.

        Useful for cross-system correlation when tracking related changes.

        Args:
            other_ulid: Another ULID to compare against

        Returns:
            True if correlated (similar timestamp)
        """
        if not is_config_ulid(other_ulid):
            return False

        other_ts = extract_timestamp(other_ulid)
        # Consider correlated if within 1 second (1000ms)
        return abs(self._timestamp_ms - other_ts) < 1000

    def __repr__(self) -> str:
        return (
            f"ConfigTraceability(config_id={self._config_id!r}, "
            f"source={self._source!r}, change_type={self._change_type!r})"
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "config_id": self._config_id,
            "source": self._source,
            "change_type": self._change_type,
            "timestamp_ms": self._timestamp_ms,
            "timestamp_seconds": self.timestamp_seconds,
            "metadata": self._metadata,
        }


def detect_ulid_in_config(value: Any) -> list[str]:
    """Detect ULID strings in configuration values.

    Recursively scans configuration dictionaries and lists for ULID strings.

    Args:
        value: Configuration value to scan

    Returns:
        List of detected ULID strings

    Example:
        >>> config = {"ref": "01ARZ3NDEKTS6PQRYF", "nested": {"id": "01XKD6RF5Y2K1VQH9"}}
        >>> ulids = detect_ulid_in_config(config)
        >>> print(len(ulids))
        2
    """
    ulids: list[str] = []

    if isinstance(value, str):
        if is_config_ulid(value):
            ulids.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            ulids.extend(detect_ulid_in_config(v))
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            ulids.extend(detect_ulid_in_config(item))

    return ulids
