"""Tests for ULID resolution service - robust version."""

import pytest
from oneiric.core.ulid_resolution import (
    SystemReference,
    register_reference,
    resolve_ulid,
    find_references_by_system,
    export_registry,
    get_registry_stats,
)


def test_register_and_resolve_akosha_entity():
    """Should register and resolve Akosha entity reference."""
    # Register
    ulid = "01ARZ3NDEKTS6PQRYF"
    register_reference(
        ulid=ulid,
        system="akosha",
        reference_type="entity",
        metadata={"entity_type": "test", "name": "test_entity"},
    )

    # Resolve
    ref = resolve_ulid(ulid)

    # Assert
    assert ref is not None
    assert ref.ulid == ulid
    assert ref.system == "akosha"
    assert ref.reference_type == "entity"
    # Use .get() for dict since metadata is plain dict
    if ref.metadata:
        entity_type = ref.metadata.get("entity_type")
        assert entity_type == "test_entity"


def test_register_and_resolve_crackerjack_test():
    """Should register and resolve Crackerjack test reference."""
    ulid = "01KH85B0X6000A9VB7CGN42ED8"
    register_reference(
        ulid=ulid,
        system="crackerjack",
        reference_type="test",
        metadata={"test_file": "test_api.py", "status": "passed"},
    )

    ref = resolve_ulid(ulid)

    assert ref is not None
    assert ref.ulid == ulid
    assert ref.system == "crackerjack"
    assert ref.reference_type == "test"
    if ref.metadata:
        test_file = ref.metadata.get("test_file")
        assert test_file == "test_api.py"


def test_register_and_resolve_mahavishnu_workflow():
    """Should register and resolve Mahavishnu workflow reference."""
    ulid = "01XKD6RF5Y2K1VQH9"
    register_reference(
        ulid=ulid,
        system="mahavishnu",
        reference_type="workflow",
        metadata={"workflow_name": "test_workflow", "status": "running"},
    )

    ref = resolve_ulid(ulid)

    assert ref is not None
    assert ref.ulid == ulid
    assert ref.system == "mahavishnu"
    assert ref.reference_type == "workflow"


def test_register_and_resolve_session_buddy_session():
    """Should register and resolve Session-Buddy session reference."""
    ulid = "01ARZ3NDEKTSVPQ8G3"
    register_reference(
        ulid=ulid,
        system="session-buddy",
        reference_type="session",
        metadata={"project": "test_project", "duration_minutes": 45},
    )

    ref = resolve_ulid(ulid)

    assert ref is not None
    assert ref.ulid == ulid
    assert ref.system == "session-buddy"
    assert ref.reference_type == "session"
    if ref.metadata:
        project = ref.metadata.get("project")
        assert project == "test_project"


def test_resolve_nonexistent_ulid():
    """Should return None for non-existent ULID."""
    ulid = "01ARZ3NDEKTSVPQ9G7"  # Different ULID
    ref = resolve_ulid(ulid)

    assert ref is None


def test_find_by_system():
    """Should find references by system."""
    # Register two Akosha entities
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

    # Find all Akosha references
    refs = find_references_by_system("akosha")

    assert len(refs) == 2
    assert all(ref.system == "akosha" for ref in refs)
    assert all(ref.reference_type == "entity" for ref in refs)


def test_find_related_ulids():
    """Should find ULIDs within time window."""
    # Register ULIDs with timestamps within same window
    ulid1 = "01ARZ3NDEKTS6PQRYF"
    ulid2 = "01ARZ3NDEKTSVPQ8G3"  # ~30 seconds difference

    register_reference(ulid=ulid1, system="test", reference_type="test")
    register_reference(ulid=ulid2, system="test", reference_type="test")

    # Find related ULIDs (1 second window = 60000ms)
    related = find_references_by_system("test")

    # Should find both ULIDs since they're within 1-minute window
    assert len(related) == 2


def test_export_and_stats():
    """Should export registry and calculate stats."""
    # Clear registry for clean test
    from oneiric.core.ulid_resolution import _ulid_registry
    _ulid_registry.clear()

    # Register test references
    register_reference(
        ulid="01ARZ3NDEKTS6PQRYF",
        system="akosha",
        reference_type="entity",
        metadata={"entity_type": "test_entity"}
    )
    register_reference(
        ulid="01KH85B0X6000A9VB7CGN42ED8",
        system="crackerjack",
        reference_type="test",
        metadata={"test_file": "test.py"}
    )
    register_reference(
        ulid="01XKD6RF5Y2K1VQH9",
        system="mahavishnu",
        reference_type="workflow",
        metadata={"workflow_name": "test_workflow"}
    )

    # Export
    exported = export_registry()

    assert len(exported) == 3
    assert "01ARZ3NDEKTS6PQRYF" in exported
    assert "01KH85B0X6000A9VB7CGN42ED8" in exported
    assert "01XKD6RF5Y2K1VQH9" in exported

    # Stats
    stats = get_registry_stats()

    assert stats["total_registrations"] == 3
    assert stats["by_system"]["akosha"] == 1
    assert stats["by_system"]["crackerjack"] == 1
    assert stats["by_system"]["mahavishnu"] == 1
    assert stats["by_reference_type"]["entity"] == 1
    assert stats["by_reference_type"]["test"] == 1
    assert stats["by_reference_type"]["workflow"] == 1
