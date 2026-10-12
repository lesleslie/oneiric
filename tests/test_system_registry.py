"""Tests for the cross-system entity registry (oneiric.core.system_registry).

Covers the public surface:
    register, find_entity, find_entities_by_system, find_related_entities,
    export, import_from, get_stats, clear, SystemReference.

The registry is process-global; tests use the ``clear`` fixture to
isolate state.
"""

from __future__ import annotations

import pytest

from oneiric.core.ids import generate_id
from oneiric.core.system_registry import (
    SystemReference,
    clear,
    export,
    find_entities_by_system,
    find_entity,
    find_related_entities,
    get_stats,
    import_from,
    register,
)


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Ensure the global registry is empty before and after each test."""
    clear()
    yield
    clear()


class TestRegister:
    def test_register_accepts_uuid7(self) -> None:
        gid = generate_id()
        register(gid, "akosha")
        ref = find_entity(gid)
        assert ref is not None
        assert ref.entity_id == gid
        assert ref.system_id == "akosha"

    def test_register_with_metadata(self) -> None:
        gid = generate_id()
        register(gid, "crackerjack", {"test_file": "x.py", "status": "passed"})
        ref = find_entity(gid)
        assert ref is not None
        assert ref.metadata == {"test_file": "x.py", "status": "passed"}

    def test_register_rejects_non_uuid7(self) -> None:
        with pytest.raises(ValueError, match="UUID7"):
            register("not-a-uuid7", "akosha")
        with pytest.raises(ValueError, match="UUID7"):
            # 26-char ULID is a valid legacy id but not a UUID7.
            register("01ARZ3NDEKTS6PQRYF0AB1C2D3E", "akosha")

    def test_register_overwrites_existing(self) -> None:
        gid = generate_id()
        register(gid, "system-a", {"v": 1})
        register(gid, "system-b", {"v": 2})
        ref = find_entity(gid)
        assert ref is not None
        assert ref.system_id == "system-b"
        assert ref.metadata == {"v": 2}


class TestFindEntity:
    def test_returns_registered_reference(self) -> None:
        gid = generate_id()
        register(gid, "akosha", {"k": "v"})
        ref = find_entity(gid)
        assert ref is not None
        assert ref.entity_id == gid

    def test_returns_none_for_unknown(self) -> None:
        assert find_entity(generate_id()) is None
        assert find_entity("not-an-id") is None


class TestFindEntitiesBySystem:
    def test_returns_only_matching_system(self) -> None:
        a1, a2, c1 = generate_id(), generate_id(), generate_id()
        register(a1, "akosha")
        register(a2, "akosha", {"role": "ingest"})
        register(c1, "crackerjack")
        akosha = find_entities_by_system("akosha")
        assert len(akosha) == 2
        assert {r.entity_id for r in akosha} == {a1, a2}
        assert len(find_entities_by_system("crackerjack")) == 1
        assert find_entities_by_system("unknown-system") == []


class TestFindRelatedEntities:
    def test_returns_entities_within_time_window(self) -> None:
        # Register two entities with timestamps within the same second.
        a, b = generate_id(), generate_id()
        register(a, "akosha")
        register(b, "crackerjack")
        # Default 60s window; same-second entities must correlate.
        related = find_related_entities(a)
        assert b in related
        assert a not in related  # excludes self

    def test_excludes_target(self) -> None:
        gid = generate_id()
        register(gid, "akosha")
        assert find_related_entities(gid) == []

    def test_unknown_target_returns_empty(self) -> None:
        assert find_related_entities(generate_id()) == []

    def test_custom_time_window(self) -> None:
        a = generate_id()
        register(a, "akosha")
        # Zero-ms window → nothing correlates.
        assert find_related_entities(a, time_window_ms=0) == []
        # Very wide window → still empty (no other entities).
        assert find_related_entities(a, time_window_ms=10**9) == []


class TestExportImport:
    def test_export_returns_full_registry(self) -> None:
        a, b = generate_id(), generate_id()
        register(a, "akosha", {"entity_type": "test"})
        register(b, "crackerjack")
        data = export()
        assert set(data.keys()) == {a, b}
        assert data[a]["system_id"] == "akosha"
        assert data[a]["metadata"] == {"entity_type": "test"}
        assert data[b]["system_id"] == "crackerjack"
        assert "timestamp_ms" in data[a]
        assert "timestamp_ms" in data[b]

    def test_import_from_round_trip(self) -> None:
        a, b = generate_id(), generate_id()
        register(a, "akosha", {"k": "v"})
        register(b, "crackerjack")
        snapshot = export()
        clear()
        assert find_entities_by_system("akosha") == []
        import_from(snapshot)
        akosha_refs = find_entities_by_system("akosha")
        assert len(akosha_refs) == 1
        assert akosha_refs[0].entity_id == a
        assert akosha_refs[0].metadata == {"k": "v"}
        crackerjack_refs = find_entities_by_system("crackerjack")
        assert len(crackerjack_refs) == 1
        assert crackerjack_refs[0].entity_id == b

    def test_import_from_replaces_existing(self) -> None:
        a = generate_id()
        register(a, "system-a")
        # Importing an empty dict wipes the registry.
        import_from({})
        assert find_entity(a) is None

    def test_import_from_rejects_non_uuid7_keys(self) -> None:
        with pytest.raises(ValueError, match="UUID7"):
            import_from({"not-a-uuid7": {"system_id": "akosha"}})

    def test_import_from_requires_system_id_field(self) -> None:
        gid = generate_id()
        with pytest.raises(KeyError):
            import_from({gid: {}})  # missing system_id


class TestGetStats:
    def test_empty_registry(self) -> None:
        assert get_stats() == {
            "total_registrations": 0,
            "by_system": {},
        }

    def test_counts_by_system(self) -> None:
        a1, a2, c1 = generate_id(), generate_id(), generate_id()
        register(a1, "akosha")
        register(a2, "akosha")
        register(c1, "crackerjack")
        assert get_stats() == {
            "total_registrations": 3,
            "by_system": {"akosha": 2, "crackerjack": 1},
        }


class TestSystemReference:
    def test_construction_uses_uuid7(self) -> None:
        gid = generate_id()
        ref = SystemReference(gid, "mahavishnu", {"workflow": "ingest"})
        assert ref.entity_id == gid
        assert ref.system_id == "mahavishnu"
        assert ref.metadata == {"workflow": "ingest"}
        assert ref.timestamp_ms > 0

    def test_metadata_is_a_copy(self) -> None:
        meta = {"k": "v"}
        ref = SystemReference(generate_id(), "akosha", meta)
        meta["k"] = "tampered"
        assert ref.metadata == {"k": "v"}

    def test_repr_includes_system_and_entity_id(self) -> None:
        gid = generate_id()
        ref = SystemReference(gid, "akosha")
        r = repr(ref)
        assert "SystemReference" in r
        assert "akosha" in r
        assert gid in r

    def test_rejects_non_uuid7(self) -> None:
        with pytest.raises(ValueError, match="UUID7"):
            SystemReference("not-a-uuid7", "akosha")


class TestClear:
    def test_clear_empties_registry(self) -> None:
        gid = generate_id()
        register(gid, "akosha")
        assert find_entity(gid) is not None
        clear()
        assert find_entity(gid) is None
        assert get_stats() == {"total_registrations": 0, "by_system": {}}
