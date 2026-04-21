"""Tests for ULID collision detection."""

import pytest

from oneiric.core.ulid_collision import (
    CollisionError,
    detect_collision,
    generate_with_retry,
    get_collision_stats,
)


@pytest.fixture(autouse=True)
def reset_collision_state():
    """Reset global collision tracking state between tests."""
    import oneiric.core.ulid_collision as m
    m._collision_count = 0
    m._collision_registry.clear()
    yield


def test_no_collision_when_unique():
    """Should return ULID when no collision."""
    result = generate_with_retry(
        context="test",
        _generate_fn=lambda: "unique_ulid",
    )
    assert result == "unique_ulid"


def test_collision_detection():
    """Should detect collisions correctly."""
    existing = {"abc", "def"}
    assert detect_collision("abc", existing) is True
    assert detect_collision("xyz", existing) is False


def test_collision_retry_raises_after_max_attempts():
    """Should raise CollisionError after exhausting all attempts.

    Seed existing_ulids so the first generate() already collides,
    then with max_attempts=1 the function must raise.
    """
    with pytest.raises(CollisionError):
        generate_with_retry(
            max_attempts=1,
            context="test",
            _generate_fn=lambda: "already_exists",
            _existing_ulids={"already_exists"},
        )


def test_get_collision_stats():
    """Should return statistics dictionary."""
    stats = get_collision_stats()
    assert stats["total_collisions"] == 0
    assert stats["unique_ulids_involved"] == 0
