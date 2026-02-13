"""Tests for ULID migration utilities."""

import pytest
from oneiric.core.ulid_migration import (
    MigrationPlan,
    detect_id_type,
    generate_migration_map,
    create_expand_contract_migration,
    validate_migration_integrity,
    estimate_migration_time,
)


def test_detect_ulid_type():
    """Should correctly identify ULID format."""
    # Valid Crockford Base32 ULIDs (from Dhruva)
    assert detect_id_type("01kh85b0x6000a9vb7cgn42ed8") == "ulid"
    assert detect_id_type("01kh85b0x70004j6njsda15ffh") == "ulid"
    assert detect_id_type("550e8400-e29b-41d4-a716-446655440000") == "uuid"  # UUID format
    assert detect_id_type("abc-123") == "custom"


def test_detect_oid_type():
    """Should detect legacy OID format (36-char hex)."""
    # 36-char hex string = legacy OID
    oid_36_char = "A" * 36  # 72 bytes
    assert detect_id_type(oid_36_char) == "oid"


def test_generate_migration_map():
    """Should generate legacy -> ULID mapping."""
    map_result = generate_migration_map("test_table", "id", limit=5)

    assert len(map_result) == 5
    assert "1" in map_result
    assert map_result["1"].startswith("01")  # ULID starts with timestamp
    for ulid in map_result.values():
        assert len(ulid) == 26
        assert ulid[0].isdigit() or ulid[0].islower()


def test_create_expand_contract_migration():
    """Should generate proper expand-contract SQL."""
    sql = create_expand_contract_migration("users", "id", "user_ulid")

    assert len(sql) == 17  # 4 phase comments + SQL + blank lines + notes
    assert sql[0] == "-- EXPAND phase: Add new ULID column alongside legacy ID"
    assert sql[3] == "-- MIGRATION phase: Backfill ULIDs for existing records"
    assert sql[6] == "-- SWITCH phase: Update foreign keys to use ULID"
    assert sql[9] == "-- CONTRACT phase: Remove legacy ID column (after verification period)"
    assert sql[10].startswith("ALTER TABLE")  # Should use ALTER TABLE
    assert "DROP COLUMN" in sql[10]  # Verify DROP in contract phase


def test_validate_migration_integrity():
    """Should validate data integrity."""
    # Exact match
    assert validate_migration_integrity(1000, 1000) is True

    # Within tolerance (1%)
    assert validate_migration_integrity(1000, 990) is True

    # Beyond tolerance
    with pytest.raises(ValueError):
        validate_migration_integrity(1000, 1100)  # 10% difference


def test_estimate_migration_time():
    """Should estimate migration time accurately."""
    estimates = estimate_migration_time(100000, records_per_second=1000)

    assert estimates["record_count"] == 100000
    assert estimates["estimated_seconds"] == 100.0
    assert estimates["estimated_minutes"] == pytest.approx(1.67, 0.1)  # ~1.67 minutes
    assert estimates["estimated_hours"] == pytest.approx(0.028, 0.01)
    assert estimates["recommended_batch_size"] == 60000  # 1-minute batches


def test_migration_plan_creation():
    """Should create migration plan object."""
    plan = MigrationPlan(
        system_name="test_system",
        current_id_type="oid",
        estimated_records=50000,
        migration_strategy="expand-contract"
    )

    assert plan.system_name == "test_system"
    assert plan.current_id_type == "oid"
    assert plan.estimated_records == 50000
    assert plan.migration_strategy == "expand-contract"
    assert plan.created_at is not None  # Should have timestamp
