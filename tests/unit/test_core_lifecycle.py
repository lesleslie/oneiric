"""Tests for oneiric.core.lifecycle helpers and dataclasses."""

from __future__ import annotations

from oneiric.core.lifecycle import (
    LifecycleError,
    LifecycleHooks,
    LifecycleSafetyOptions,
    LifecycleStatus,
    _is_number,
    _parse_timestamp,
    _status_from_dict,
)

# ---------------------------------------------------------------------------
# LifecycleError
# ---------------------------------------------------------------------------

class TestLifecycleError:
    def test_is_runtime_error(self) -> None:
        exc = LifecycleError("swap failed")
        assert isinstance(exc, RuntimeError)
        assert str(exc) == "swap failed"


# ---------------------------------------------------------------------------
# LifecycleSafetyOptions
# ---------------------------------------------------------------------------

class TestLifecycleSafetyOptions:
    def test_defaults(self) -> None:
        opts = LifecycleSafetyOptions()
        assert opts.activation_timeout == 30.0
        assert opts.health_timeout == 5.0
        assert opts.cleanup_timeout == 10.0
        assert opts.hook_timeout == 5.0
        assert opts.shield_tasks is True
        assert opts.max_swap_samples == 20

    def test_custom(self) -> None:
        opts = LifecycleSafetyOptions(activation_timeout=60.0, shield_tasks=False)
        assert opts.activation_timeout == 60.0
        assert opts.shield_tasks is False


# ---------------------------------------------------------------------------
# LifecycleHooks
# ---------------------------------------------------------------------------

class TestLifecycleHooks:
    def test_defaults_empty(self) -> None:
        h = LifecycleHooks()
        assert h.pre_swap == []
        assert h.post_swap == []
        assert h.on_cleanup == []

    def test_add_hooks(self) -> None:
        h = LifecycleHooks()
        async def dummy_pre(): ...
        async def dummy_post(): ...
        async def dummy_cleanup(): ...
        h.add_pre_swap(dummy_pre)
        h.add_post_swap(dummy_post)
        h.add_cleanup(dummy_cleanup)
        assert len(h.pre_swap) == 1
        assert len(h.post_swap) == 1
        assert len(h.on_cleanup) == 1


# ---------------------------------------------------------------------------
# LifecycleStatus
# ---------------------------------------------------------------------------

class TestLifecycleStatus:
    def test_defaults(self) -> None:
        s = LifecycleStatus(domain="adapter", key="cache")
        assert s.state == "unknown"
        assert s.current_provider is None
        assert s.last_error is None
        assert s.recent_swap_durations_ms == []
        assert s.successful_swaps == 0
        assert s.failed_swaps == 0

    def test_as_dict(self) -> None:
        s = LifecycleStatus(
            domain="adapter", key="cache", state="active",
            current_provider="redis",
        )
        d = s.as_dict()
        assert d["domain"] == "adapter"
        assert d["key"] == "cache"
        assert d["state"] == "active"
        assert d["current_provider"] == "redis"


# ---------------------------------------------------------------------------
# _parse_timestamp
# ---------------------------------------------------------------------------

class TestParseTimestamp:
    def test_none(self) -> None:
        assert _parse_timestamp(None) is None

    def test_empty_string(self) -> None:
        assert _parse_timestamp("") is None

    def test_valid_iso(self) -> None:
        ts = _parse_timestamp("2025-06-15T12:00:00+00:00")
        assert ts is not None
        assert ts.tzinfo is not None

    def test_invalid_string(self) -> None:
        assert _parse_timestamp("not-a-date") is None

    def test_utc_format(self) -> None:
        ts = _parse_timestamp("2025-06-15T12:00:00Z")
        assert ts is not None


# ---------------------------------------------------------------------------
# _is_number
# ---------------------------------------------------------------------------

class TestIsNumber:
    def test_int(self) -> None:
        assert _is_number(42) is True

    def test_float(self) -> None:
        assert _is_number(3.14) is True

    def test_string_number(self) -> None:
        assert _is_number("42") is True

    def test_string_float(self) -> None:
        assert _is_number("3.14") is True

    def test_none(self) -> None:
        assert _is_number(None) is False

    def test_string_text(self) -> None:
        assert _is_number("abc") is False

    def test_list(self) -> None:
        assert _is_number([1, 2]) is False

    def test_nan(self) -> None:
        assert _is_number(float("nan")) is True  # float() succeeds

    def test_negative(self) -> None:
        assert _is_number(-1.5) is True


# ---------------------------------------------------------------------------
# _status_from_dict
# ---------------------------------------------------------------------------

class TestStatusFromDict:
    def test_none_input(self) -> None:
        assert _status_from_dict(None) is None

    def test_non_dict(self) -> None:
        assert _status_from_dict("not a dict") is None
        assert _status_from_dict(42) is None

    def test_missing_domain(self) -> None:
        assert _status_from_dict({"key": "x"}) is None

    def test_missing_key(self) -> None:
        assert _status_from_dict({"domain": "adapter"}) is None

    def test_minimal_valid(self) -> None:
        status = _status_from_dict({"domain": "adapter", "key": "cache"})
        assert status is not None
        assert status.domain == "adapter"
        assert status.key == "cache"
        assert status.state == "unknown"

    def test_full_dict(self) -> None:
        status = _status_from_dict({
            "domain": "service",
            "key": "auth",
            "state": "active",
            "current_provider": "google",
            "pending_provider": "okta",
            "last_error": "timeout",
            "last_swap_duration_ms": 42.5,
            "successful_swaps": 10,
            "failed_swaps": 2,
        })
        assert status.state == "active"
        assert status.current_provider == "google"
        assert status.pending_provider == "okta"
        assert status.last_error == "timeout"
        assert status.last_swap_duration_ms == 42.5
        assert status.successful_swaps == 10
        assert status.failed_swaps == 2

    def test_recent_swap_durations(self) -> None:
        status = _status_from_dict({
            "domain": "adapter", "key": "cache",
            "recent_swap_durations_ms": [10.0, 20.0, "bad", 30.0],
        })
        assert status.recent_swap_durations_ms == [10.0, 20.0, 30.0]

    def test_timestamps_parsed(self) -> None:
        status = _status_from_dict({
            "domain": "adapter", "key": "cache",
            "last_state_change_at": "2025-01-01T00:00:00+00:00",
            "last_activated_at": "2025-06-01T00:00:00+00:00",
        })
        assert status.last_state_change_at is not None
        assert status.last_activated_at is not None

    def test_invalid_timestamp_ignored(self) -> None:
        status = _status_from_dict({
            "domain": "adapter", "key": "cache",
            "last_state_change_at": "not-a-date",
        })
        assert status.last_state_change_at is None

    def test_non_number_duration_ignored(self) -> None:
        status = _status_from_dict({
            "domain": "adapter", "key": "cache",
            "last_swap_duration_ms": "not-a-number",
        })
        assert status.last_swap_duration_ms is None
