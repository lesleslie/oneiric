"""Cross-system ULID resolution service.

Provides centralized resolution for ULID references across ecosystem
systems (Akosha entities, Crackerjack tests, Session-buddy
sessions, Mahavishnu workflows) for time-based correlation
and complete traceability.
"""

import logging
from datetime import datetime, UTC
from typing import Dict, List, Optional

# Oneiric imports
try:
    from oneiric.core.ulid import get_timestamp
except ImportError:
    # Fallback if Oneiric is not available
    def get_timestamp(ulid: str):
        return 0

    def extract_timestamp(ulid: str) -> int:
        return 0


logger = logging.getLogger(__name__)


# Global registry of ULID → system mappings
_ulid_registry: Dict[str, "SystemReference"] = {}


class SystemReference:
    """Cross-system reference with metadata."""

    def __init__(
        self,
        ulid: str,
        system: str,  # "akosha", "crackerjack", "session_buddy", "mahavishnu"
        reference_type: str,  # "entity", "test", "session", "workflow", "pool_execution"
        metadata: Optional[Dict] = None,
    ):
        self.ulid = ulid
        self.system = system
        self.reference_type = reference_type
        self.metadata = metadata or {}

        # Extract timestamp from ULID for time-based queries
        try:
            self.timestamp = get_timestamp(ulid)
        except Exception:
            logger.warning(f"Failed to parse ULID timestamp: {ulid}")
            self.timestamp = 0

        self.registered_at = datetime.now(UTC)

    def __repr__(self) -> str:
        return f"SystemReference({self.system}:{self.reference_type}:{self.ulid})"


def register_reference(
    ulid: str,
    system: str,
    reference_type: str,
    metadata: Optional[Dict] = None,
) -> None:
    """Register ULID cross-system reference.

    Args:
        ulid: ULID identifier
        system: Source system name
        reference_type: Type of reference (entity, test, session, workflow)
        metadata: Additional metadata
    """
    ref = SystemReference(ulid, system, reference_type, metadata)
    _ulid_registry[ulid] = ref
    logger.debug(f"Registered ULID reference: {ulid} → {system}:{reference_type}")


def resolve_ulid(ulid: str) -> Optional[SystemReference]:
    """Resolve ULID to system reference.

    Args:
        ulid: ULID to resolve

    Returns:
        SystemReference if found, None otherwise
    """
    return _ulid_registry.get(ulid)


def find_references_by_system(system: str) -> List["SystemReference"]:
    """Find all references from a specific system.

    Args:
        system: System name to filter by

    Returns:
        List of SystemReferences from system
    """
    return [ref for ref in _ulid_registry.values() if ref.system == system]


def find_related_ulids(
    ulid: str,
    time_window_ms: int = 60000,  # 1 minute default
) -> List[str]:
    """Find ULIDs related by time proximity.

    Args:
        ulid: Central ULID
        time_window_ms: Time window for correlation (default: 1 minute)

    Returns:
        List of related ULIDs within time window
    """
    target_ref = _ulid_registry.get(ulid)

    if not target_ref:
        logger.warning(f"ULID not found in registry: {ulid}")
        return []

    target_timestamp = target_ref.timestamp

    related = []
    for other_ulid, ref in _ulid_registry.items():
        if abs(ref.timestamp - target_timestamp) <= time_window_ms:
            related.append(other_ulid)

    return related


def get_cross_system_trace(ulid: str) -> Dict[str, any]:
    """Get complete cross-system trace for ULID.

    Args:
        ulid: ULID to trace

    Returns:
        Dictionary with complete trace information
    """
    ref = resolve_ulid(ulid)

    if not ref:
        return {
            "error": "ULID not found in registry",
            "ulid": ulid,
        }

    related = find_related_ulids(ulid)

    return {
        "ulid": ulid,
        "source_system": ref.system,
        "reference_type": ref.reference_type,
        "timestamp_ms": ref.timestamp,
        "registered_at": ref.registered_at.isoformat(),
        "metadata": ref.metadata,
        "related_ulids": related,
        "related_count": len(related),
    }


def export_registry() -> Dict[str, Dict]:
    """Export complete registry for debugging/analysis.

    Returns:
        Dictionary of all ULID registrations
    """
    return {
        ulid: {
            "system": ref.system,
            "reference_type": ref.reference_type,
            "timestamp_ms": ref.timestamp,
            "metadata": ref.metadata,
        }
        for ulid, ref in _ulid_registry.items()
    }


def get_registry_stats() -> Dict[str, int]:
    """Get registry statistics for monitoring.

    Returns:
        Dictionary with registration metrics
    """
    system_counts: Dict[str, int] = {}
    type_counts: Dict[str, int] = {}

    for ref in _ulid_registry.values():
        system_counts[ref.system] = system_counts.get(ref.system, 0) + 1
        type_counts[ref.reference_type] = type_counts.get(ref.reference_type, 0) + 1

    return {
        "total_registrations": len(_ulid_registry),
        "by_system": system_counts,
        "by_reference_type": type_counts,
    }


# Export public API
__all__ = [
    "SystemReference",
    "register_reference",
    "resolve_ulid",
    "find_references_by_system",
    "find_related_ulids",
    "get_cross_system_trace",
    "export_registry",
    "get_registry_stats",
]
