"""Cross-system entity reference registry.

Provides centralized registration for entity references across
ecosystem systems (Akosha entities, Crackerjack tests,
Session-buddy sessions, Mahavishnu workflows) for time-based
correlation and complete traceability.

Replaces the legacy ULID-keyed registry in ``oneiric.core.ulid_resolution``.
The new shape keys on UUID7 ``entity_id`` strings instead of ULIDs,
and drops the ``reference_type`` field -- the per-system entity type
is now carried inside ``metadata``.

Public API:
    register(entity_id, system_id, metadata)
        -- store a cross-system reference.
    find_entity(entity_id)
        -- SystemReference | None; look up a single entity.
    find_entities_by_system(system_id)
        -- list[SystemReference]; all refs for a system.
    find_related_entities(entity_id, time_window_ms=60000)
        -- list[str]; entity_ids within ``time_window_ms`` of the target.
    export()
        -- dict; full registry snapshot for debugging/analysis.
    import_from(data)
        -- None; load a previously-exported registry.
    get_stats()
        -- dict; registration counts by system.
    clear()
        -- None; empty the registry. Test-fixture helper.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from oneiric.core.ids import (
    extract_timestamp_ms,
    is_uuid7,
)

logger = logging.getLogger(__name__)


class SystemReference:
    """Cross-system reference with metadata.

    Attributes:
        entity_id: UUID7 hex (e.g. ``"018f3e7a5b1c4d2e9f0a8b7c6d5e4f3a"``).
        system_id: Source system name (akosha, crackerjack, ...).
        metadata: Caller-supplied context dict (entity_type, status, etc.).
        timestamp_ms: Time of the underlying entity, extracted from the
            UUID7 high-48-bit timestamp.
        registered_at: When the reference was added to the registry.
    """

    __slots__ = (
        "_entity_id",
        "_metadata",
        "_registered_at",
        "_system_id",
        "_timestamp_ms",
    )

    def __init__(
        self,
        entity_id: str,
        system_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not is_uuid7(entity_id):
            raise ValueError(
                f"SystemReference requires a UUID7 entity_id; got {entity_id!r}"
            )
        self._entity_id = entity_id
        self._system_id = system_id
        self._metadata = dict(metadata) if metadata else {}
        self._timestamp_ms = extract_timestamp_ms(entity_id)
        self._registered_at = datetime.now(UTC)

    @property
    def entity_id(self) -> str:
        return self._entity_id

    @property
    def system_id(self) -> str:
        return self._system_id

    @property
    def metadata(self) -> dict[str, Any]:
        return dict(self._metadata)

    @property
    def timestamp_ms(self) -> int:
        return self._timestamp_ms

    @property
    def registered_at(self) -> datetime:
        return self._registered_at

    def __repr__(self) -> str:
        return f"SystemReference({self._system_id}:{self._entity_id})"


_registry: dict[str, SystemReference] = {}


def register(
    entity_id: str,
    system_id: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Register a UUID7 entity reference for a system.

    Args:
        entity_id: UUID7 hex string (32 lowercase hex characters).
        system_id: Source system name (akosha, crackerjack, mahavishnu, ...).
        metadata: Additional metadata (e.g. ``{"entity_type": "test"}``).
    """
    ref = SystemReference(entity_id, system_id, metadata)
    _registry[entity_id] = ref
    logger.debug(
        "registered system reference: %s -> %s",
        entity_id,
        system_id,
    )


def find_entity(entity_id: str) -> SystemReference | None:
    """Look up a registered reference by ``entity_id``."""
    return _registry.get(entity_id)


def find_entities_by_system(system_id: str) -> list[SystemReference]:
    """Return all references whose ``system_id`` matches."""
    return [r for r in _registry.values() if r.system_id == system_id]


def find_related_entities(
    entity_id: str,
    time_window_ms: int = 60000,
) -> list[str]:
    """Return entity_ids within ``time_window_ms`` of ``entity_id``.

    Default window is 60_000 ms (1 minute). Uses each reference's
    ``timestamp_ms`` (extracted from its UUID7 high-48 bits).

    Args:
        entity_id: Central entity_id; its presence in the registry is
            required (returns ``[]`` if not registered).
        time_window_ms: Symmetric time window for correlation.

    Returns:
        List of entity_id strings (not including the target itself).
    """
    target = _registry.get(entity_id)
    if target is None:
        logger.warning("entity not found in registry: %s", entity_id)
        return []

    related: list[str] = []
    for other_id, ref in _registry.items():
        if other_id == entity_id:
            continue
        if abs(ref.timestamp_ms - target.timestamp_ms) <= time_window_ms:
            related.append(other_id)
    return related


def export() -> dict[str, dict[str, Any]]:
    """Export the full registry as a JSON-serializable dict.

    Keys are UUID7 entity_id strings; values carry ``system_id``,
    ``timestamp_ms``, and ``metadata``.
    """
    return {
        entity_id: {
            "system_id": ref.system_id,
            "timestamp_ms": ref.timestamp_ms,
            "metadata": dict(ref.metadata),
        }
        for entity_id, ref in _registry.items()
    }


def import_from(data: dict[str, dict[str, Any]]) -> None:
    """Load a previously-exported registry. Replaces current contents.

    Each entry must carry a valid UUID7 ``entity_id`` as its dict key.
    The ``system_id`` field is required; ``timestamp_ms`` and
    ``metadata`` are recomputed from the UUID7 / payload respectively.
    """
    _registry.clear()
    for entity_id, payload in data.items():
        if not is_uuid7(entity_id):
            raise ValueError(f"import_from requires UUID7 entity_id; got {entity_id!r}")
        ref = SystemReference(
            entity_id=entity_id,
            system_id=payload["system_id"],
            metadata=payload.get("metadata"),
        )
        _registry[entity_id] = ref


def get_stats() -> dict[str, Any]:
    """Return registration counts by ``system_id``."""
    by_system: dict[str, int] = {}
    for ref in _registry.values():
        by_system[ref.system_id] = by_system.get(ref.system_id, 0) + 1
    return {
        "total_registrations": len(_registry),
        "by_system": by_system,
    }


def clear() -> None:
    """Empty the registry. Intended for test fixtures."""
    _registry.clear()


__all__ = [
    "SystemReference",
    "clear",
    "export",
    "find_entities_by_system",
    "find_entity",
    "find_related_entities",
    "get_stats",
    "import_from",
    "register",
]
