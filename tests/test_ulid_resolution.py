"""Tests for ULID resolution service."""

import pytest
from oneiric.core.ulid_resolution import (
    SystemReference,
    register_reference,
    resolve_ulid,
    find_references_by_system,
    find_related_ulids,
    get_cross_system_trace,
    export_registry,
    get_registry_stats,
)


def test_register_akosha_entity():
    """Should register Akosha entity reference."""
    register_reference(
        ulid="01ARZ3NDEKTS6PQRYF",
        system="akosha",
        reference_type="entity",
        metadata={"entity_type": "test", "name": "test_entity"},
    )

    ref = resolve_ulid("01ARZ3NDEKTS6PQRYF")
    assert ref is not None
    assert ref.ulid == "01ARZ3NDEKTS6PQRYF"
    assert ref.system == "akosha"
    assert ref.reference_type == "entity"
    assert ref.metadata is not None
    assert ref.metadata.get("entity_type") == "test_entity"


def test_register_crackerjack_test():
    """Should register Crackerjack test execution reference."""
    register_reference(
        ulid="01KH85B0X6000A9VB7CGN42ED8",
        system="crackerjack",
        reference_type="test",
        metadata={"test_file": "test_api.py", "status": "passed"},
    )

    ref = resolve_ulid("01KH85B0X6000A9VB7CGN42ED8")
    assert ref is not None
    assert ref.system == "crackerjack"
    assert ref.reference_type == "test"


def test_register_mahavishnu_workflow():
    """Should register Mahavishnu workflow execution reference."""
    register_reference(
        ulid="01XKD6RF5Y2K1VQH9",
        system="mahavishnu",
        reference_type="workflow",
        metadata={"workflow_name": "test_workflow", "status": "running"},
    )

    ref = resolve_ulid("01XKD6RF5Y2K1VQH9")
    assert ref is not None
    assert ref.system == "mahavishnu"


def test_register_session_buddy_session():
    """Should register Session-Buddy session reference."""
    register_reference(
        ulid="01ARZ3NDEKTS6PQRYF",
        system="session-buddy",
        reference_type="session",
        metadata={"project": "test_project", "duration_minutes": 45},
    )

    ref = resolve_ulid("01ARZ3NDEKTS6PQRYF")
    assert ref is not None
    assert ref.system == "session-buddy"


def test_resolve_nonexistent_ulid():
    """Should return None for non-existent ULID."""
    ref = resolve_ulid("01ARZ3NDEKTSVPQ9G7")  # Non-existent ULID
    assert ref is None


def test_find_by_system_akosha():
    """Should find all Akosha entity references."""
    # Register some Akosha entities
    register_reference(
        ulid="01ARZ3NDEKTS6PQRYF",
        system="akosha",
        reference_type="entity",
    )
    register_reference(
        ulid="01XKD6RF5Y2K1VQH9",
        system="akosha",
        reference_type="entity",
    )

    refs = find_references_by_system("akosha")
    assert len(refs) == 2
    assert all(ref.system == "akosha" for ref in refs)


def test_find_by_system_crackerjack():
    """Should find all Crackerjack test references."""
    register_reference(
        ulid="01KH85B0X6000A9VB7CGN42ED8",
        system="crackerjack",
        reference_type="test",
    )

    refs = find_references_by_system("crackerjack")
    assert len(refs) == 1
    assert refs[0].system == "crackerjack"


def test_find_related_ulids_time_window():
    """Should find ULIDs within time window."""
    # Register ULIDs with different timestamps
    # Timestamp 1: 2026-02-11 12:00:00 (in milliseconds)
    register_reference(
        ulid="01ARZ3NDEKTS6PQRYF",  # Earlier timestamp
        system="test",
        reference_type="test",
    )

    # Timestamp 2: Same timestamp + 30 seconds (within 1 minute window)
    register_reference(
        ulid="01ARZ3NDEKTSVPQ8G3",  # 30 seconds later
        system="test",
        reference_type="test",
    )

    related = find_related_ulids("01ARZ3NDEKTS6PQRYF", time_window_ms=60000)
    assert len(related) == 2  # Both ULIDs should be found


def test_find_related_ulids_no_matches():
    """Should return empty list when no ULIDs within time window."""
    register_reference(
        ulid="01ARZ3NDEKTS6PQRYF",
        system="test",
        reference_type="test",
    )

    # Use very small time window (1 second)
    related = find_related_ulids("01ARZ3NDEKTS6PQRYF", time_window_ms=1000)
    assert len(related) == 1  # Only the target ULID itself


def test_get_cross_system_trace():
    """Should get complete trace for ULID."""
    register_reference(
        ulid="01ARZ3NDEKTS6PQRYF",
        system="akosha",
        reference_type="entity",
        metadata={"entity_type": "test_entity"},
    )

    trace = get_cross_system_trace("01ARZ3NDEKTS6PQRYF")

    assert trace["ulid"] == "01ARZ3NDEKTS6PQRYF"
    assert trace["source_system"] == "akosha"
    assert trace["reference_type"] == "entity"
    assert "timestamp_ms" in trace
    assert "registered_at" in trace
    assert "related_ulids" in trace
    assert trace["related_count"] == 0  # Only one ULID registered


def test_get_cross_system_trace_not_found():
    """Should return error for non-existent ULID."""
    trace = get_cross_system_trace("NONEXISTENT")

    assert "error" in trace
    assert trace["ulid"] == "NONEXISTENT"


def test_export_registry():
    """Should export complete registry."""
    # Register some test references
    register_reference(
        ulid="01ARZ3NDEKTS6PQRYF",
        system="akosha",
        reference_type="entity",
    )
    register_reference(
        ulid="01KH85B0X6000A9VB7CGN42ED8",
        system="crackerjack",
        reference_type="test",
    )

    exported = export_registry()

    assert len(exported) == 2
    assert "01ARZ3NDEKTS6PQRYF" in exported
    assert "01KH85B0X6000A9VB7CGN42ED8" in exported

    # Verify structure
    akosha_entry = exported["01ARZ3NDEKTS6PQRYF"]
    assert akosha_entry["system"] == "akosha"
    assert akosha_entry["reference_type"] == "entity"

    crackerjack_entry = exported["01KH85B0X6000A9VB7CGN42ED8"]
    assert crackerjack_entry["system"] == "crackerjack"


def test_get_registry_stats():
    """Should calculate registry statistics correctly."""
    # Register multiple references
    register_reference(
        ulid="01ARZ3NDEKTS6PQRYF",
        system="akosha",
        reference_type="entity",
    )
    register_reference(
        ulid="01KH85B0X6000A9VB7CGN42ED8",
        system="crackerjack",
        reference_type="test",
    )
    register_reference(
        ulid="01XKD6RF5Y2K1VQH9",
        system="mahavishnu",
        reference_type="workflow",
    )

    stats = get_registry_stats()

    assert stats["total_registrations"] == 3
    assert stats["by_system"]["akosha"] == 1
    assert stats["by_system"]["crackerjack"] == 1
    assert stats["by_system"]["mahavishnu"] == 1
    assert stats["by_reference_type"]["entity"] == 1
    assert stats["by_reference_type"]["test"] == 1
    assert stats["by_reference_type"]["workflow"] == 1
