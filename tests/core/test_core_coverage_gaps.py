"""Gap-fill tests for small core infrastructure modules."""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# client_mixins.py:12 — raise path when _client is None
# ---------------------------------------------------------------------------


def test_ensure_client_raises_lifecycle_error_when_no_client() -> None:
    from oneiric.core.client_mixins import EnsureClientMixin
    from oneiric.core.lifecycle import LifecycleError

    class _Stub(EnsureClientMixin):
        _client = None

    with pytest.raises(LifecycleError):
        _Stub()._ensure_client("not-initialized")


def test_ensure_client_returns_existing_client() -> None:
    from oneiric.core.client_mixins import EnsureClientMixin

    sentinel = object()

    class _Stub(EnsureClientMixin):
        _client = sentinel  # type: ignore[assignment]

    assert _Stub()._ensure_client("not-initialized") is sentinel


# ---------------------------------------------------------------------------
# secrets_cache.py:57-62 — _invalidate_all with provider filter (not None)
# ---------------------------------------------------------------------------


def test_secrets_cache_invalidate_all_by_provider() -> None:
    from oneiric.core.secrets_cache import SecretValueCache

    cache = SecretValueCache(ttl_seconds=60)
    cache.set("provA", "key1", "val1")
    cache.set("provA", "key2", "val2")
    cache.set("provB", "key3", "val3")

    # invalidate(keys=None, provider="provA") → _invalidate_all("provA")
    removed = cache.invalidate(provider="provA")

    assert removed == 2
    assert cache.get("provA", "key1") == (False, None)
    assert cache.get("provA", "key2") == (False, None)
    assert cache.get("provB", "key3") == (True, "val3")


def test_secrets_cache_invalidate_all_by_provider_no_matches() -> None:
    from oneiric.core.secrets_cache import SecretValueCache

    cache = SecretValueCache(ttl_seconds=60)
    cache.set("provA", "key1", "val1")

    removed = cache.invalidate(provider="provZ")
    assert removed == 0
    assert cache.get("provA", "key1") == (True, "val1")


# ---------------------------------------------------------------------------
# ulid_collision.py:81 — real import path when _generate_fn is None
# ---------------------------------------------------------------------------


def test_generate_with_retry_uses_real_generate_fn() -> None:
    """When _generate_fn is not supplied, generate_with_retry imports from oneiric.core.ulid."""
    from oneiric.core.ulid_collision import generate_with_retry

    result = generate_with_retry(max_attempts=3, context="test-real-fn")
    assert isinstance(result, str)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# ulid_resolution.py:49-51 — SystemReference swallows get_timestamp exceptions
# ---------------------------------------------------------------------------


def test_system_reference_handles_get_timestamp_exception() -> None:
    """SystemReference sets timestamp=0 when get_timestamp raises."""
    import oneiric.core.ulid_resolution as mod
    from oneiric.core.ulid_resolution import SystemReference

    original_fn = mod.get_timestamp
    try:
        mod.get_timestamp = lambda ulid: 1 / 0  # type: ignore[assignment]
        ref = SystemReference("bad-ulid", "test-system", "test-type")
        assert ref.timestamp == 0
        assert ref.system == "test-system"
    finally:
        mod.get_timestamp = original_fn


# ---------------------------------------------------------------------------
# ulid_resolution.py:118-119 — find_related_ulids returns [] for unknown ULID
# ---------------------------------------------------------------------------


def test_find_related_ulids_returns_empty_for_unregistered() -> None:
    from oneiric.core.ulid_resolution import _ulid_registry, find_related_ulids

    _ulid_registry.clear()
    result = find_related_ulids("not-in-registry")
    assert result == []
    _ulid_registry.clear()
