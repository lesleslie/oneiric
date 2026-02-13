"""Tests for ULID collision detection."""

import pytest
from oneiric.core.ulid_collision import (
    detect_collision,
    generate_with_retry,
    CollisionError,
    get_collision_stats,
)


def test_no_collision_when_unique():
    """Should return ULID when no collision."""
    existing = {"existing1", "existing2"}
    # Use unittest.mock to patch generate function
    from unittest.mock import patch
    import oneiric.core.ulid_collision as collision_module

    with patch.object(collision_module, 'generate', return_value="unique_ulid"):
        result = collision_module.generate_with_retry(context="test")
        assert result == "unique_ulid"


def test_collision_detection():
    """Should detect collisions correctly."""
    existing = {"abc", "def"}
    assert detect_collision("abc", existing) is True
    assert detect_collision("xyz", existing) is False


def test_collision_retry_raises_after_max_attempts():
    """Should raise after max attempts."""
    from unittest.mock import patch
    import oneiric.core.ulid_collision as collision_module

    # Patch generate to always return colliding value
    with patch.object(collision_module, 'generate', return_value="colliding_ulid"):
        with pytest.raises(CollisionError):
            collision_module.generate_with_retry(max_attempts=2, context="test")


def test_get_collision_stats():
    """Should return statistics dictionary."""
    stats = get_collision_stats()
    assert stats["total_collisions"] == 0
    assert stats["unique_ulids_involved"] == 0
