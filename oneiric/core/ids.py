"""UUID7 identifier substrate for Oneiric.

Replaces the legacy ULID substrate (``oneiric.core.ulid*``) with
RFC 9562 UUID7 hex. The new generator emits 32 lowercase hex
characters whose ``UUID.version`` nibble is 7. Legacy 26-char
Crockford Base32 ULIDs remain readable for the duration of the
lazy dual-write migration window (REQ-012) but are no longer
produced.

Public API:
    generate_id(value)            -- fresh UUID7 hex string.
    is_uuid7(value)               -- strict UUID7 hex check.
    is_valid_id(value)            -- accepts UUID7 hex OR legacy ULID
                                     (read-time acceptance only).
    extract_timestamp_ms(value)   -- ms-since-epoch from UUID7 or ULID.
    extract_timestamp_seconds(value) -- seconds since epoch.
    ConfigTraceability            -- config-change correlation record,
                                     keyed on UUID7 entity_id instead
                                     of ULID config_id.

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

# Legacy 26-char Crockford Base32 ULID alphabet. Kept only for
# read-time acceptance of pre-migration storage rows; never used
# to generate.
_CROCKFORD_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"
_ULID_ALPHABET_INDEX = {c: i for i, c in enumerate(_CROCKFORD_ALPHABET)}
_ULID_ALPHABET_SET = frozenset(_CROCKFORD_ALPHABET)
_ULID_STRING_LENGTH = 26
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
        >>> is_uuid7("01ARZ3NDEKTS6PQRYF")  # legacy ULID
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


def _is_legacy_ulid(value: str) -> bool:
    """Read-time check that ``value`` is a 26-char Crockford Base32 ULID."""
    if not isinstance(value, str):
        return False
    if len(value) != _ULID_STRING_LENGTH:
        return False
    return all(c in _ULID_ALPHABET_SET for c in value.lower())


def is_valid_id(value: Any) -> bool:
    """Read-time acceptance: True for UUID7 hex OR legacy 26-char ULID.

    Used to validate identifiers that may be encountered in pre-migration
    storage rows (e.g. Akosha's warm.db carries ULID PKs from before
    the UUID7 migration; reads accept both shapes until the lazy
    dual-write backfill finishes).

    This function never accepts ULIDs as new identifiers -- generation
    always emits UUID7. It only validates pre-existing data.

    Example:
        >>> is_valid_id(generate_id())
        True
        >>> is_valid_id("01ARZ3NDEKTS6PQRYF")
        True
        >>> is_valid_id("not-an-id")
        False
    """
    return is_uuid7(value) or _is_legacy_ulid(value)


def _ulid_to_int(value: str) -> int:
    """Decode a 26-char ULID into its 128-bit integer form."""
    n = 0
    for c in value.lower():
        n = (n << 5) | _ULID_ALPHABET_INDEX[c]
    return n


def extract_timestamp_ms(value: str) -> int:
    """Extract ms-since-epoch from a UUID7 hex string or legacy ULID.

    Both shapes place a 48-bit Unix-ms timestamp in the high 48 bits
    of the 128-bit value, so the extraction is the same shift. Raises
    ValueError for unparsable input.

    Example:
        >>> extract_timestamp_ms(generate_id()) > 0
        True
    """
    if is_uuid7(value):
        return UUID(value).int >> _UUID7_TIMESTAMP_SHIFT
    if _is_legacy_ulid(value):
        return _ulid_to_int(value) >> _UUID7_TIMESTAMP_SHIFT
    raise ValueError(f"Cannot extract timestamp from invalid id: {value!r}")


def extract_timestamp_seconds(value: str) -> float:
    """Extract seconds-since-epoch from a UUID7 hex string or legacy ULID.

    Convenience wrapper over :func:`extract_timestamp_ms`. Raises
    ValueError for unparsable input.
    """
    return extract_timestamp_ms(value) / 1000.0


class ConfigTraceability:
    """Configuration change tracking keyed on UUID7 entity_id.

    Provides traceability for configuration changes across systems,
    enabling cross-system correlation and time-ordered history.

    Replaces the ULID-keyed ``ConfigTraceability`` from the legacy
    ``oneiric.core.ulid`` module. The slot ``entity_id`` replaces
    ``config_id``; the timestamp source shifts from Crockford ULID
    decode to UUID7 (RFC 9562 sec 5.7) high-48-bit extraction.

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
        """Timestamp in seconds."""
        return self._timestamp_ms / 1000.0

    @property
    def metadata(self) -> dict[str, Any]:
        """Additional metadata (returns a copy)."""
        return dict(self._metadata)

    def correlates_with(self, other_id: str) -> bool:
        """True if this trace correlates with ``other_id`` within 1 second.

        Useful for cross-system correlation when tracking related
        changes. Accepts both UUID7 hex and legacy ULID (read-time
        acceptance per REQ-012).
        """
        if not is_valid_id(other_id):
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
