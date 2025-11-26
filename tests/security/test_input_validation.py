"""Security tests for remote manifest entry validation.

These tests verify that remote manifest entries are properly validated
to prevent malicious or malformed data from being registered.
"""

from __future__ import annotations

import pytest

from oneiric.core.security import (
    validate_priority_bounds,
    validate_stack_level_bounds,
)
from oneiric.remote.loader import _validate_entry
from oneiric.remote.models import RemoteManifestEntry


class TestRemoteEntryValidation:
    """Test comprehensive validation of remote manifest entries."""

    def test_valid_entry_passes(self):
        """Well-formed entry passes validation."""
        entry = RemoteManifestEntry(
            domain="adapter",
            key="redis-cache",
            provider="redis",
            factory="oneiric.demo:RedisAdapter",
            priority=10,
            stack_level=5,
        )
        result = _validate_entry(entry)
        assert result is None  # None means valid

    def test_invalid_domain_rejected(self):
        """Unsupported domains rejected."""
        entry = RemoteManifestEntry(
            domain="invalid-domain",
            key="test",
            provider="test",
            factory="oneiric.demo:Test",
        )
        result = _validate_entry(entry)
        assert result is not None
        assert "unsupported domain" in result

    def test_missing_key_rejected(self):
        """Entries without key rejected."""
        entry = RemoteManifestEntry(
            domain="adapter",
            key="",
            provider="test",
            factory="oneiric.demo:Test",
        )
        result = _validate_entry(entry)
        assert result is not None
        assert "missing key" in result

    def test_path_traversal_key_rejected(self):
        """Keys with path traversal rejected."""
        entry = RemoteManifestEntry(
            domain="adapter",
            key="../../evil",
            provider="test",
            factory="oneiric.demo:Test",
        )
        result = _validate_entry(entry)
        assert result is not None
        assert "invalid key" in result

    def test_missing_provider_rejected(self):
        """Entries without provider rejected."""
        entry = RemoteManifestEntry(
            domain="adapter",
            key="test",
            provider="",
            factory="oneiric.demo:Test",
        )
        result = _validate_entry(entry)
        assert result is not None
        assert "missing provider" in result

    def test_invalid_provider_format_rejected(self):
        """Providers with invalid characters rejected."""
        entry = RemoteManifestEntry(
            domain="adapter",
            key="test",
            provider="../../bad",
            factory="oneiric.demo:Test",
        )
        result = _validate_entry(entry)
        assert result is not None
        assert "invalid provider" in result

    def test_missing_factory_rejected(self):
        """Entries without factory rejected."""
        entry = RemoteManifestEntry(
            domain="adapter",
            key="test",
            provider="test",
            factory="",
        )
        result = _validate_entry(entry)
        assert result is not None
        assert "missing factory" in result

    def test_malformed_factory_rejected(self):
        """Factories with invalid format rejected."""
        entry = RemoteManifestEntry(
            domain="adapter",
            key="test",
            provider="test",
            factory="nocolon",
        )
        result = _validate_entry(entry)
        assert result is not None
        assert "invalid factory" in result

    def test_blocked_factory_module_rejected(self):
        """Factories from blocked modules rejected."""
        entry = RemoteManifestEntry(
            domain="adapter",
            key="test",
            provider="test",
            factory="os:system",
        )
        result = _validate_entry(entry)
        assert result is not None
        assert "invalid factory" in result

    def test_disallowed_factory_prefix_rejected(self):
        """Factories from non-allowlisted modules rejected."""
        entry = RemoteManifestEntry(
            domain="adapter",
            key="test",
            provider="test",
            factory="random_evil.module:hack",
        )
        result = _validate_entry(entry)
        assert result is not None
        assert "invalid factory" in result

    def test_priority_out_of_bounds_rejected(self):
        """Priority values outside acceptable range rejected."""
        entry = RemoteManifestEntry(
            domain="adapter",
            key="test",
            provider="test",
            factory="oneiric.demo:Test",
            priority=9999,
        )
        result = _validate_entry(entry)
        assert result is not None
        assert "out of bounds" in result

    def test_negative_priority_out_of_bounds_rejected(self):
        """Large negative priority values rejected."""
        entry = RemoteManifestEntry(
            domain="adapter",
            key="test",
            provider="test",
            factory="oneiric.demo:Test",
            priority=-9999,
        )
        result = _validate_entry(entry)
        assert result is not None
        assert "out of bounds" in result

    def test_stack_level_out_of_bounds_rejected(self):
        """Stack level values outside acceptable range rejected."""
        entry = RemoteManifestEntry(
            domain="adapter",
            key="test",
            provider="test",
            factory="oneiric.demo:Test",
            stack_level=999,
        )
        result = _validate_entry(entry)
        assert result is not None
        assert "out of bounds" in result

    def test_uri_with_path_traversal_rejected(self):
        """URIs with path traversal rejected."""
        entry = RemoteManifestEntry(
            domain="adapter",
            key="test",
            provider="test",
            factory="oneiric.demo:Test",
            uri="../../evil.py",
        )
        result = _validate_entry(entry)
        assert result is not None
        assert "path traversal" in result


class TestPriorityBoundsValidation:
    """Test priority value bounds checking."""

    def test_valid_priority_accepted(self):
        """Valid priority values accepted."""
        valid_priorities = [0, 1, -1, 100, -100, 999, -999]
        for priority in valid_priorities:
            is_valid, error = validate_priority_bounds(priority)
            assert is_valid, f"Should accept priority {priority}"
            assert error is None

    def test_priority_at_max_bound_accepted(self):
        """Priority at maximum bound accepted."""
        is_valid, error = validate_priority_bounds(1000)
        assert is_valid
        assert error is None

    def test_priority_at_min_bound_accepted(self):
        """Priority at minimum bound accepted."""
        is_valid, error = validate_priority_bounds(-1000)
        assert is_valid
        assert error is None

    def test_priority_exceeds_max_rejected(self):
        """Priority above maximum rejected."""
        is_valid, error = validate_priority_bounds(1001)
        assert not is_valid
        assert "out of bounds" in error

    def test_priority_below_min_rejected(self):
        """Priority below minimum rejected."""
        is_valid, error = validate_priority_bounds(-1001)
        assert not is_valid
        assert "out of bounds" in error

    def test_non_integer_priority_rejected(self):
        """Non-integer priority values rejected."""
        is_valid, error = validate_priority_bounds("not-an-int")  # type: ignore
        assert not is_valid
        assert "must be integer" in error


class TestStackLevelBoundsValidation:
    """Test stack level value bounds checking."""

    def test_valid_stack_level_accepted(self):
        """Valid stack level values accepted."""
        valid_levels = [0, 1, -1, 50, -50, 99, -99]
        for level in valid_levels:
            is_valid, error = validate_stack_level_bounds(level)
            assert is_valid, f"Should accept stack level {level}"
            assert error is None

    def test_stack_level_at_max_bound_accepted(self):
        """Stack level at maximum bound accepted."""
        is_valid, error = validate_stack_level_bounds(100)
        assert is_valid

    def test_stack_level_at_min_bound_accepted(self):
        """Stack level at minimum bound accepted."""
        is_valid, error = validate_stack_level_bounds(-100)
        assert is_valid

    def test_stack_level_exceeds_max_rejected(self):
        """Stack level above maximum rejected."""
        is_valid, error = validate_stack_level_bounds(101)
        assert not is_valid
        assert "out of bounds" in error

    def test_stack_level_below_min_rejected(self):
        """Stack level below minimum rejected."""
        is_valid, error = validate_stack_level_bounds(-101)
        assert not is_valid
        assert "out of bounds" in error

    def test_non_integer_stack_level_rejected(self):
        """Non-integer stack level values rejected."""
        is_valid, error = validate_stack_level_bounds(3.14)  # type: ignore
        assert not is_valid
        assert "must be integer" in error


@pytest.mark.security
class TestMaliciousManifestScenarios:
    """Test realistic malicious manifest attack scenarios."""

    def test_rce_attack_via_factory(self):
        """RCE attack via os.system blocked."""
        entry = RemoteManifestEntry(
            domain="adapter",
            key="backdoor",
            provider="evil",
            factory="os:system",
        )
        result = _validate_entry(entry)
        assert result is not None
        assert "invalid factory" in result

    def test_path_injection_via_key(self):
        """Path injection via key blocked."""
        entry = RemoteManifestEntry(
            domain="adapter",
            key="../../../etc/passwd",
            provider="evil",
            factory="oneiric.demo:Test",
        )
        result = _validate_entry(entry)
        assert result is not None
        assert "invalid key" in result

    def test_integer_overflow_via_priority(self):
        """Integer overflow attempt via large priority blocked."""
        entry = RemoteManifestEntry(
            domain="adapter",
            key="test",
            provider="evil",
            factory="oneiric.demo:Test",
            priority=999999999999,
        )
        result = _validate_entry(entry)
        assert result is not None
        assert "out of bounds" in result

    def test_nested_import_attack(self):
        """Nested import attack blocked."""
        entry = RemoteManifestEntry(
            domain="adapter",
            key="test",
            provider="evil",
            factory="importlib:import_module",
        )
        result = _validate_entry(entry)
        assert result is not None
        assert "invalid factory" in result
