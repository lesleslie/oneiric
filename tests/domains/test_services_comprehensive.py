"""Comprehensive tests for the ServiceBridge domain wrapper.

ServiceBridge is a thin wrapper over DomainBridge that pins the domain name
to "service". These tests verify the wrapper preserves all DomainBridge
behaviour (active_candidates, shadowed_candidates, explain, use,
get_settings, register_settings_model, should_accept_work, activity_state)
and that the domain discriminator is correct.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from oneiric.core.lifecycle import LifecycleError
from oneiric.core.resolution import Candidate, CandidateSource, Resolver
from oneiric.domains.services import ServiceBridge
from oneiric.runtime.activity import DomainActivity


def test_domain_is_service(
    resolver: Resolver,
    lifecycle_manager,
    layer_settings,
) -> None:
    """ServiceBridge always reports domain == 'service'."""
    bridge = ServiceBridge(resolver, lifecycle_manager, layer_settings)

    assert bridge.domain == "service"


def test_inherits_domain_bridge_behavior(
    resolver: Resolver,
    lifecycle_manager,
    layer_settings,
) -> None:
    """active_candidates() returns a list (empty for a fresh resolver)."""
    bridge = ServiceBridge(resolver, lifecycle_manager, layer_settings)

    result = bridge.active_candidates()

    assert isinstance(result, list)
    assert result == []


def test_shadowed_candidates_returns_list(
    resolver: Resolver,
    lifecycle_manager,
    layer_settings,
) -> None:
    """shadowed_candidates() returns a list (empty when nothing is shadowed)."""
    bridge = ServiceBridge(resolver, lifecycle_manager, layer_settings)

    result = bridge.shadowed_candidates()

    assert isinstance(result, list)
    assert result == []


def test_explain_returns_dict(
    resolver: Resolver,
    lifecycle_manager,
    layer_settings,
) -> None:
    """explain('nonexistent') returns a dict for an unregistered key."""
    bridge = ServiceBridge(resolver, lifecycle_manager, layer_settings)

    result = bridge.explain("nonexistent")

    assert isinstance(result, dict)
    assert result["domain"] == "service"
    assert result["key"] == "nonexistent"


async def test_dummy_service_handler_runs(
    resolver: Resolver,
    lifecycle_manager,
    layer_settings,
) -> None:
    """bridge.use() activates a registered service factory via lifecycle."""

    class _DummyService:
        def ping(self) -> str:
            return "pong"

    resolver.register(
        Candidate(
            domain="service",
            key="test-service",
            provider="dummy",
            factory=lambda: _DummyService(),
            source=CandidateSource.MANUAL,
        )
    )
    bridge = ServiceBridge(resolver, lifecycle_manager, layer_settings)

    handle = await bridge.use("test-service")

    assert isinstance(handle.instance, _DummyService)
    assert handle.instance.ping() == "pong"
    assert handle.domain == "service"
    assert handle.key == "test-service"
    assert handle.provider == "dummy"


def test_settings_model_registered(
    resolver: Resolver,
    lifecycle_manager,
    layer_settings,
) -> None:
    """register_settings_model causes get_settings to return a parsed model."""

    class _RedisSettings(BaseModel):
        host: str = "localhost"
        port: int = 6379

    # Seed provider_settings with values that the model will parse.
    layer_settings.provider_settings["redis"] = {"host": "cache.local", "port": 6380}
    bridge = ServiceBridge(resolver, lifecycle_manager, layer_settings)

    bridge.register_settings_model("redis", _RedisSettings)

    settings = bridge.get_settings("redis")

    assert isinstance(settings, _RedisSettings)
    assert settings.host == "cache.local"
    assert settings.port == 6380


async def test_use_missing_candidate_raises(
    resolver: Resolver,
    lifecycle_manager,
    layer_settings,
) -> None:
    """bridge.use() with no registered candidate raises LifecycleError."""
    bridge = ServiceBridge(resolver, lifecycle_manager, layer_settings)

    with pytest.raises(LifecycleError):
        await bridge.use("never-registered")


def test_get_settings_unregistered_returns_raw(
    resolver: Resolver,
    lifecycle_manager,
    layer_settings,
) -> None:
    """get_settings for an unregistered provider returns the raw dict from settings."""
    layer_settings.provider_settings["not_registered"] = {"alpha": 1, "beta": "x"}
    bridge = ServiceBridge(resolver, lifecycle_manager, layer_settings)

    settings = bridge.get_settings("not_registered")

    assert settings == {"alpha": 1, "beta": "x"}
    # Raw dict, not a BaseModel instance.
    assert not isinstance(settings, BaseModel)


def test_should_accept_work_default(
    resolver: Resolver,
    lifecycle_manager,
    layer_settings,
) -> None:
    """Without a supervisor, should_accept_work() defaults to True."""
    bridge = ServiceBridge(resolver, lifecycle_manager, layer_settings)

    assert bridge.should_accept_work("anything") is True
    assert bridge.should_accept_work("never-seen") is True


def test_activity_state_returns_default_for_unseen_key(
    resolver: Resolver,
    lifecycle_manager,
    layer_settings,
) -> None:
    """activity_state() returns a default DomainActivity for unseen keys."""
    bridge = ServiceBridge(resolver, lifecycle_manager, layer_settings)

    state = bridge.activity_state("never_seen")

    assert isinstance(state, DomainActivity)
    assert state.paused is False
    assert state.draining is False
