"""Tests for RedisCacheSettings additions + factory-string leading-space guards."""
from __future__ import annotations

from importlib import import_module

import pytest
from pydantic import ValidationError

from oneiric.adapters.cache import RedisCacheSettings


def test_default_ttl_seconds_is_3600() -> None:
    s = RedisCacheSettings()
    assert s.ttl_seconds == 3600


def test_default_stampede_jitter_ms_is_zero() -> None:
    s = RedisCacheSettings()
    assert s.stampede_jitter_ms == 0


def test_ttl_seconds_zero_is_allowed() -> None:
    """Plan-level addition beyond the spec's seven-test list; coverage for `ge=0` lower bound."""
    s = RedisCacheSettings(ttl_seconds=0)
    assert s.ttl_seconds == 0


def test_negative_ttl_seconds_rejected() -> None:
    with pytest.raises(ValidationError):
        RedisCacheSettings(ttl_seconds=-1)


def test_negative_stampede_jitter_ms_rejected() -> None:
    with pytest.raises(ValidationError):
        RedisCacheSettings(stampede_jitter_ms=-1)


def test_factory_string_redis_has_no_leading_space() -> None:
    """Regression guard for D11 (the prerequisite Task 2.0 fix).

    Reads `AdapterMetadata.factory` *raw* and exercises the same
    `getattr(module, attr)` path that Dhara's `resolve_cache_adapter`
    uses via `import_string`. A leading space would make the `getattr`
    raise `AttributeError`.
    """
    from oneiric.adapters.cache.redis import RedisCacheAdapter

    factory = RedisCacheAdapter.metadata.factory
    assert factory == "oneiric.adapters.cache.redis:RedisCacheAdapter", (
        f"factory string has leading/trailing whitespace: {factory!r}"
    )
    module_name, _, attr = factory.partition(":")
    resolved = getattr(import_module(module_name), attr)
    assert resolved is RedisCacheAdapter


def test_factory_string_memory_has_no_leading_space() -> None:
    from oneiric.adapters.cache.memory import MemoryCacheAdapter

    factory = MemoryCacheAdapter.metadata.factory
    assert factory == "oneiric.adapters.cache.memory:MemoryCacheAdapter", (
        f"factory string has leading/trailing whitespace: {factory!r}"
    )
    module_name, _, attr = factory.partition(":")
    resolved = getattr(import_module(module_name), attr)
    assert resolved is MemoryCacheAdapter


def test_existing_fields_round_trip_unchanged() -> None:
    s = RedisCacheSettings(
        url="redis://example:6379/0",
        username="alice",
        password="secret",
        ttl_seconds=120,
        stampede_jitter_ms=10,
    )
    assert s.host == "localhost"
    assert s.password == "secret"
    assert s.ttl_seconds == 120
    assert s.stampede_jitter_ms == 10
