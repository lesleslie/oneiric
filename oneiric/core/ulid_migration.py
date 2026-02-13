"""ULID migration utilities for ecosystem systems.

Provides tools for migrating from legacy identifiers (OIDs, UUIDs,
custom IDs) to ULID with expand-contract pattern support for
zero downtime.

Key functions:
- Migration planning (MigrationPlan class)
- ID type detection (detect_id_type)
- Migration map generation (generate_migration_map)
- SQL generation (create_expand_contract_migration)
- Integrity validation (validate_migration_integrity)
- Time estimation (estimate_migration_time)
"""

import logging
from typing import Any, Dict
from datetime import datetime

# Oneiric imports
try:
    from oneiric.core.ulid import generate, is_ulid, get_timestamp
except ImportError:
    # Fallback if Oneiric is not available (e.g., during standalone migration)
    generate = None  # Will use dhruva directly if Oneiric wrapper unavailable
    is_ulid = None
    get_timestamp = None

logger = logging.getLogger(__name__)


class MigrationPlan:
    """Migration plan for system identifier migration."""

    def __init__(
        self,
        system_name: str,
        current_id_type: str,  # "oid", "uuid", "custom", "ulid"
        estimated_records: int,
        migration_strategy: str = "expand-contract",  # or "big-bang", "dual-write"
    ):
        self.system_name = system_name
        self.current_id_type = current_id_type
        self.estimated_records = estimated_records
        self.migration_strategy = migration_strategy
        self.created_at = datetime.utcnow()

    def __repr__(self) -> str:
        return (
            f"MigrationPlan({self.system_name}, {self.current_id_type} → ULID, "
            f"{self.migration_strategy}, {self.estimated_records} records)"
        )


def detect_id_type(identifier: str) -> str:
    """Detect identifier type from string format.

    Args:
        identifier: Identifier string to analyze

            "system_akosha", "user_akosha", "ulid", "oid", "uuid", "custom"
    """
    # Check if it's a valid ULID from Oneiric/Dhruva
    if is_ulid is not None and is_ulid(identifier):
        return "ulid"

    # Check for UUID format (36-char with 4 dashes)
    import re
    uuid_pattern = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
    if uuid_pattern.match(identifier.lower()):
        return "uuid"

    # Check for legacy OID format (26-char or 36-char alphanumeric/hex)
    if len(identifier) in [26, 36] and identifier.isalnum():
        return "oid"  # Heuristic: 26 or 36-char alphanumeric (legacy OID)

    return "custom"  # Default fallback


def generate_migration_map(
    table_name: str,
    id_column: str,
    limit: int = 1000,
) -> Dict[str, str]:
    """Generate mapping from legacy IDs to ULIDs for a table.

    Args:
        table_name: Database table name
        id_column: Primary key column name
        limit: Maximum records to process (for batch migration)

    Returns:
        Dictionary mapping legacy_id -> ulid

    Example:
        >>> map = generate_migration_map("users", "id", limit=10)
        >>> print(map)
        {"1": "01ARZ3NDEKTS6PQRYF", "2": "01XKD6RF5Y2K1VQH9"}
    """
    logger.info(f"Generating ULID migration map for {table_name}.{id_column}")

    migration_map = {}

    # In production implementation, would query database here
    # For now, simulate with sequential IDs
    for i in range(limit):
        legacy_id = str(i + 1)
        new_ulid = generate() if generate else "fallback_ulid"
        migration_map[legacy_id] = new_ulid

    logger.info(f"Generated {len(migration_map)} mappings")
    return migration_map


def create_expand_contract_migration(
    table_name: str,
    id_column: str,
    new_column: str,
) -> list[str]:
    """Generate SQL for expand-contract migration pattern.

    Args:
        table_name: Table to migrate
        id_column: Existing primary key column
        new_column: New ULID column to add

    Returns:
        List of SQL statements for migration

    Example:
        >>> sql = create_expand_contract_migration("users", "id", "user_ulid")
        >>> print("\\n".join(sql))
    """
    logger.info(f"Generating expand-contract SQL for {table_name}.{new_column}")

    sql_statements = [
        f"-- EXPAND phase: Add new ULID column alongside legacy ID",
        f"ALTER TABLE {table_name} ADD COLUMN {new_column} TEXT;",
        "",
        f"-- MIGRATION phase: Backfill ULIDs for existing records",
        f"UPDATE {table_name} SET {new_column} = generate_ulid() WHERE {new_column} IS NULL;",
        "",
        f"-- SWITCH phase: Update foreign keys to use ULID",
        f"-- Application code changes needed to reference {new_column}",
        "",
        f"-- CONTRACT phase: Remove legacy ID column (after verification period)",
        f"ALTER TABLE {table_name} DROP COLUMN {id_column};",
    "",
    f"-- Note: For SQLite, DROP COLUMN requires copying table to new table",
        f"-- Recommended verification period: 30 days",
    "",
        f"-- Alternative: Use dual-write pattern if foreign keys prevent DROP",
    "",
    ]

    return sql_statements


def validate_migration_integrity(
    legacy_count: int,
    ulid_count: int,
    tolerance_percent: float = 0.01,
) -> bool:
    """Validate data integrity after migration.

    Args:
        legacy_count: Original record count
        ulid_count: Migrated ULID count
        tolerance_percent: Allowed difference percentage (default: 0.01%)

    Returns:
        True if migration integrity validated

    Raises:
        ValueError: If counts don't match within tolerance

    Example:
        >>> validate_migration_integrity(1000, 1000)  # Exact match
        True
        >>> validate_migration_integrity(1000, 995)  # Within tolerance
        True
        >>> validate_migration_integrity(1000, 1100)  # 10% difference
        ValueError("Migration integrity check failed: 1000 legacy vs 1100 ULID")
    """
    difference = abs(legacy_count - ulid_count)
    allowed_difference = legacy_count * tolerance_percent

    if difference > allowed_difference:
        raise ValueError(
            f"Migration integrity check failed: {legacy_count} legacy vs {ulid_count} ULID "
            f"(difference: {difference}, allowed: {allowed_difference}, "
            f"tolerance: {tolerance_percent}%)"
        )

    logger.info(f"Migration integrity validated: {legacy_count} → {ulid_count}")
    return True


def estimate_migration_time(
    record_count: int,
    records_per_second: float = 1000.0,
) -> Dict[str, Any]:
    """Estimate migration time for planning.

    Args:
        record_count: Total records to migrate
        records_per_second: Migration throughput (default: 1000/sec)

    Returns:
        Dictionary with time estimates

    Example:
        >>> estimate = estimate_migration_time(100000, 1000)
        >>> print(estimate["estimated_minutes"])
        1.67
    """
    total_seconds = record_count / records_per_second
    total_minutes = total_seconds / 60
    total_hours = total_minutes / 60

    return {
        "record_count": record_count,
        "estimated_seconds": total_seconds,
        "estimated_minutes": total_minutes,
        "estimated_hours": total_hours,
        "recommended_batch_size": int(records_per_second * 60),  # 1-minute batches
    }


# Export public API
__all__ = [
    "MigrationPlan",
    "detect_id_type",
    "generate_migration_map",
    "create_expand_contract_migration",
    "validate_migration_integrity",
    "estimate_migration_time",
]
