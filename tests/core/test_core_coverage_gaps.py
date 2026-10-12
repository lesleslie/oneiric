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
# ulid_collision.py:81 — REMOVED (Phase 2 of UUID7 migration; ulid_collision
# module is gone, replaced by oneiric.core.ids)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# ulid_resolution.py:49-51, 118-119 — REMOVED (Phase 2 of UUID7 migration;
# ulid_resolution module is gone, replaced by oneiric.core.system_registry)
# ---------------------------------------------------------------------------
