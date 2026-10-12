"""UUID7 identifier substrate for Oneiric.

UUID7-only substrate (RFC 9562). Generation emits 32 lowercase hex
characters whose ``UUID.version`` nibble is 7. Validation is strict:
legacy 26-char Crockford Base32 ULIDs are rejected.

The legacy 26-char ULID substrate was removed in
``docs/plans/2026-10-11-uuid7-only-migration.md`` Phase 5/6 (see the
``feedback-no-backwards-compat-pre-1.0`` rule). Any code that
previously accepted ULIDs must re-encode them to UUID7 before passing
them to this module.

Public API:
    generate_id()              -- fresh UUID7 hex string.
    is_uuid7(value)             -- strict UUID7 hex check.
    is_valid_id(value)          -- alias for is_uuid7 (UUID7-only).
    extract_timestamp_ms(value) -- ms-since-epoch from UUID7 high 48 bits.
    extract_timestamp_seconds(value) -- seconds since epoch.
    ConfigTraceability          -- config-change correlation record,
                                   keyed on UUID7 entity_id.

UUID7 (RFC 9562 sec 5.7) bit layout::

     0                   1                   2                   3
     0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
    +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    |                           unix_ts_ms                          |
    +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    |          unix_ts_ms           |  ver  |       rand_a          |
    +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    |var|                        rand_b                             |
    +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    |                            rand_b                             |
    +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+

``uuid.uuid7()`` is part of the Python 3.14 stdlib and emits the
canonical layout. This module never hand-rolls the bytes.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID, uuid7

logger = logging.getLogger(__name__)

_UUID7_HEX_LENGTH = 32
_UUID7_HEX_ALPHABET = frozenset("0123456789abcdef")
_UUID7_TIMESTAMP_SHIFT = 80  # 128 - 48 (high 48 bits hold unix_ts_ms)


def generate_id() -> str:
    """Return a freshly-generated UUID7 hex string.

    Returns:
        32 lowercase hex characters; ``uuid.UUID(result).version == 7``.

    Example:
        >>> result = generate_id()
        >>> len(result) == 32
        True
        >>> UUID(result).version == 7
        True
    """
    return uuid7().hex


def is_uuid7(value: Any) -> bool:
    """Strict check that ``value`` is a canonical UUID7 hex string.

    Returns True only when the value is exactly 32 lowercase hex
    characters AND parses to a UUID whose version nibble is 7
    (i.e. the standard generator output, not a hand-rolled UUIDv4
    mislabeled as v7).

    Example:
        >>> is_uuid7(generate_id())
        True
        >>> is_uuid7("01ARZ3NDEKTS6PQRYF")  # legacy 26-char ULID
        False
        >>> is_uuid7(
        ...     "bcfbf3f2-076c-4a35-96cc-340e3995ce74"
        ... )  # 36-char UUID with hyphens
        False
        >>> is_uuid7("not-an-id")
        False
    """
    if not isinstance(value, str):
        return False
    if len(value) != _UUID7_HEX_LENGTH:
        return False
    if not all(c in _UUID7_HEX_ALPHABET for c in value):
        return False
    try:
        return UUID(value).version == 7
    except ValueError, AttributeError:
        return False


# is_valid_id is an alias preserved for callers that use the more
# descriptive name. UUID7-only — legacy ULIDs return False.
is_valid_id = is_uuid7


def extract_timestamp_ms(value: str) -> int:
    """Extract ms-since-epoch from a UUID7 hex string.

    The high 48 bits of a UUID7 encode Unix-ms timestamp per
    RFC 9562 §5.7, so a single right-shift extracts it. Raises
    ``ValueError`` for unparsable input.

    Example:
        >>> extract_timestamp_ms(generate_id()) > 0
        True
        >>> extract_timestamp_ms("not-a-uuid7")
        Traceback (most recent call last):
            ...
        ValueError: Cannot extract timestamp from invalid id: 'not-a-uuid7'
    """
    if not is_uuid7(value):
        raise ValueError(f"Cannot extract timestamp from invalid id: {value!r}")
    return UUID(value).int >> _UUID7_TIMESTAMP_SHIFT


def extract_timestamp_seconds(value: str) -> float:
    """Extract seconds-since-epoch from a UUID7 hex string.

    Convenience wrapper over :func:`extract_timestamp_ms`. Raises
    ``ValueError`` for unparsable input.
    """
    return extract_timestamp_ms(value) / 1000.0


class ConfigTraceability:
    """Configuration change tracking keyed on UUID7 entity_id.

    Provides traceability for configuration changes across systems,
    enabling cross-system correlation and time-ordered history.

    Example:
        >>> trace = ConfigTraceability(source="oneiric", change_type="update")
        >>> UUID(trace.entity_id).version == 7
        True
    """

    __slots__ = (
        "_change_type",
        "_entity_id",
        "_metadata",
        "_source",
        "_timestamp_ms",
    )

    def __init__(
        self,
        entity_id: str | None = None,
        source: str = "oneiric",
        change_type: str = "unknown",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if entity_id is None:
            entity_id = generate_id()

        if not is_uuid7(entity_id):
            raise ValueError(
                f"ConfigTraceability requires a UUID7 entity_id; got {entity_id!r}"
            )

        self._entity_id = entity_id
        self._source = source
        self._change_type = change_type
        self._metadata = dict(metadata) if metadata else {}
        self._timestamp_ms = extract_timestamp_ms(entity_id)

    @property
    def entity_id(self) -> str:
        """UUID7 entity identifier."""
        return self._entity_id

    @property
    def source(self) -> str:
        """Source system."""
        return self._source

    @property
    def change_type(self) -> str:
        """Type of change (create, update, delete, etc.)."""
        return self._change_type

    @property
    def timestamp_ms(self) -> int:
        """Timestamp in milliseconds (extracted from UUID7)."""
        return self._timestamp_ms

    @property
    def timestamp_seconds(self) -> float:
        """Timestamp in seconds (extracted from UUID7)."""
        return self._timestamp_ms / 1000.0

    @property
    def metadata(self) -> dict[str, Any]:
        """Application metadata (returns a copy)."""
        return dict(self._metadata)

    def correlates_with(self, other_id: str) -> bool:
        """True if this trace correlates with ``other_id`` within 1 second.

        Useful for cross-system correlation when tracking related
        changes. ``other_id`` must be a UUID7 hex string; non-UUID7
        inputs return False (no exception).
        """
        if not is_uuid7(other_id):
            return False
        other_ts = extract_timestamp_ms(other_id)
        return abs(self._timestamp_ms - other_ts) < 1000

    def __repr__(self) -> str:
        return (
            f"ConfigTraceability(entity_id={self._entity_id!r}, "
            f"source={self._source!r}, change_type={self._change_type!r})"
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "entity_id": self._entity_id,
            "source": self._source,
            "change_type": self._change_type,
            "timestamp_ms": self._timestamp_ms,
            "timestamp_seconds": self.timestamp_seconds,
            "metadata": dict(self._metadata),
        }


__all__ = [
    "ConfigTraceability",
    "extract_timestamp_ms",
    "extract_timestamp_seconds",
    "generate_id",
    "is_uuid7",
    "is_valid_id",
]
