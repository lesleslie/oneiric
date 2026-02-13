"""ULID collision detection and resolution.

Handles rare collision events in distributed ULID generation,
providing retry strategies and resolution tracking.
"""

import logging
from typing import Optional
from oneiric.core.ulid import generate, is_ulid, get_timestamp

logger = logging.getLogger(__name__)

# Track collisions for monitoring
_collision_count: int = 0
_collision_registry: dict[str, list[str]] = {}


class CollisionError(Exception):
    """ULID collision detected."""

    def __init__(self, existing_ulid: str, new_ulid: str):
        self.existing_ulid = existing_ulid
        self.new_ulid = new_ulid
        super().__init__(
            f"ULID collision detected: {new_ulid} already exists as {existing_ulid}"
        )

def detect_collision(new_ulid: str, existing_ulids: set[str]) -> bool:
    """Check if new ULID collides with existing set.

    Args:
        new_ulid: Newly generated ULID
        existing_ulids: Set of existing ULIDs to check against

    Returns:
        True if collision detected
    """
    return new_ulid in existing_ulids

def register_collision(existing_ulid: str, new_ulid: str, context: str) -> None:
    """Register collision for monitoring and analysis.

    Args:
        existing_ulid: The ULID that already existed
        new_ulid: The newly generated ULID that collided
        context: Context where collision occurred (system, operation)
    """
    global _collision_count
    _collision_count += 1

    if new_ulid not in _collision_registry:
        _collision_registry[new_ulid] = []
    _collision_registry[new_ulid].append(existing_ulid)

    logger.warning(
        f"ULID collision #{_collision_count}: {new_ulid} collided with {existing_ulid} in {context}"
    )

def generate_with_retry(
    max_attempts: int = 3,
    context: str = "unknown",
) -> str:
    """Generate ULID with collision retry.

    Args:
        max_attempts: Maximum generation attempts (default: 3)
        context: Context for collision tracking

    Returns:
        Valid ULID string

    Raises:
        CollisionError: If all attempts result in collisions
    """
    existing_ulids = set()  # In practice, load from storage

    for attempt in range(max_attempts):
        new_ulid = generate()

        if not detect_collision(new_ulid, existing_ulids):
            return new_ulid

        # Collision detected - register and retry
        register_collision(new_ulid, new_ulid, context)
        logger.warning(f"Collision attempt {attempt + 1}/{max_attempts}, regenerating...")

    # Only raise error if collision detected and attempts exhausted
    if attempt == max_attempts - 1 and detect_collision(new_ulid, existing_ulids):
        raise CollisionError(new_ulid, existing_ulids.pop() if existing_ulids else "empty_set")

def get_collision_stats() -> dict[str, int]:
    """Get collision statistics for monitoring.

    Returns:
        Dictionary with collision metrics
    """
    return {
        "total_collisions": _collision_count,
        "unique_ulids_involved": len(_collision_registry),
    }
