"""Lifecycle management tests.

These tests verify component activation, hot-swapping, rollback on failure,
health checks, pre/post hooks, cleanup, and status persistence.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from oneiric.core.lifecycle import (
    LifecycleError,
    LifecycleHooks,
    LifecycleManager,
    LifecycleSafetyOptions,
    LifecycleStatus,
)
from oneiric.core.resolution import Candidate, CandidateSource, Resolver


class MockComponent:
    """Mock component for testing."""

    def __init__(self, name: str, should_fail_health: bool = False):
        self.name = name
        self.initialized = False
        self.cleaned_up = False
        self.should_fail_health = should_fail_health

    async def initialize(self):
        """Async initialization."""
        await asyncio.sleep(0.01)  # Simulate async work
        self.initialized = True

    async def cleanup(self):
        """Async cleanup."""
        await asyncio.sleep(0.01)  # Simulate async work
        self.cleaned_up = True

    async def health_check(self) -> bool:
        """Async health check."""
        await asyncio.sleep(0.01)  # Simulate async work
        return not self.should_fail_health


class TestLifecycleStatus:
    """Test LifecycleStatus model."""

    def test_status_model_fields(self):
        """LifecycleStatus has correct fields."""
        status = LifecycleStatus(
            domain="adapter",
            key="cache",
            state="ready",
            current_provider="redis",
        )

        assert status.domain == "adapter"
        assert status.key == "cache"
        assert status.state == "ready"
        assert status.current_provider == "redis"
        assert status.last_error is None

    def test_status_with_error(self):
        """LifecycleStatus can include error information."""
        status = LifecycleStatus(
            domain="adapter",
            key="cache",
            state="failed",
            current_provider="redis",
            last_error="Connection refused",
        )

        assert status.state == "failed"
        assert status.last_error == "Connection refused"

    def test_status_as_dict_serializable(self):
        """LifecycleStatus.as_dict returns JSON-serializable structure."""
        status = LifecycleStatus(
            domain="adapter",
            key="cache",
            state="ready",
            current_provider="redis",
        )

        data = status.as_dict()

        assert data["domain"] == "adapter"
        assert data["key"] == "cache"
        assert data["state"] == "ready"
        assert data["current_provider"] == "redis"


class TestLifecycleActivation:
    """Test component activation flow."""

    @pytest.mark.asyncio
    async def test_activate_simple_component(self):
        """Activate a simple component successfully."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)

        # Register candidate
        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: MockComponent("redis"),
                source=CandidateSource.MANUAL,
            )
        )

        # Activate
        instance = await lifecycle.activate("adapter", "cache")

        assert instance is not None
        assert instance.name == "redis"

        # Check status
        status = lifecycle.get_status("adapter", "cache")
        assert status.state == "ready"
        assert status.current_provider == "redis"

    @pytest.mark.asyncio
    async def test_activate_with_health_check(self):
        """Activate component with health check."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)

        async def health_check() -> bool:
            await asyncio.sleep(0.01)
            return True

        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: MockComponent("redis"),
                health=health_check,
                source=CandidateSource.MANUAL,
            )
        )

        instance = await lifecycle.activate("adapter", "cache")

        assert instance is not None
        assert instance.name == "redis"

    @pytest.mark.asyncio
    async def test_activate_fails_on_bad_health_check(self):
        """Activation fails when health check fails."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)

        async def failing_health_check() -> bool:
            await asyncio.sleep(0.01)
            return False

        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: MockComponent("redis"),
                health=failing_health_check,
                source=CandidateSource.MANUAL,
            )
        )

        # Activation should fail
        with pytest.raises(LifecycleError, match="Health check failed"):
            await lifecycle.activate("adapter", "cache")

        # Status should show failure
        status = lifecycle.get_status("adapter", "cache")
        assert status.state == "failed"

    @pytest.mark.asyncio
    async def test_activate_records_swap_metric(self, monkeypatch):
        """Successful activation records swap duration metrics."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)

        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: MockComponent("redis"),
                source=CandidateSource.MANUAL,
            )
        )

        calls = []
        monkeypatch.setattr(
            "oneiric.core.lifecycle.record_swap_duration",
            lambda domain, key, provider, duration_ms, success: calls.append(
                (domain, key, provider, success)
            ),
        )

        await lifecycle.activate("adapter", "cache")

        assert calls
        assert calls[0] == ("adapter", "cache", "redis", True)

    @pytest.mark.asyncio
    async def test_swap_metrics_persist_on_status(self):
        """LifecycleStatus captures swap latency samples."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)
        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: MockComponent("redis"),
            )
        )

        await lifecycle.activate("adapter", "cache")

        status = lifecycle.get_status("adapter", "cache")
        assert status is not None
        assert status.successful_swaps == 1
        assert status.failed_swaps == 0
        assert status.last_swap_duration_ms is not None
        assert len(status.recent_swap_durations_ms) == 1

    @pytest.mark.asyncio
    async def test_activate_failure_records_metric(self, monkeypatch):
        """Failed activation still emits swap duration metric."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)

        async def failing_health_check() -> bool:
            return False

        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: MockComponent("redis"),
                health=failing_health_check,
                source=CandidateSource.MANUAL,
            )
        )

        outcomes = []
        monkeypatch.setattr(
            "oneiric.core.lifecycle.record_swap_duration",
            lambda domain, key, provider, duration_ms, success: outcomes.append(
                success
            ),
        )

        with pytest.raises(LifecycleError):
            await lifecycle.activate("adapter", "cache")

        assert outcomes and outcomes[0] is False

    @pytest.mark.asyncio
    async def test_activate_with_force_skips_health_check(self):
        """Force activation skips health check."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)

        async def failing_health_check() -> bool:
            return False

        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: MockComponent("redis"),
                health=failing_health_check,
                source=CandidateSource.MANUAL,
            )
        )

        # Force activation should succeed despite bad health
        instance = await lifecycle.activate("adapter", "cache", force=True)

        assert instance is not None
        assert instance.name == "redis"

    @pytest.mark.asyncio
    async def test_activate_nonexistent_component_fails(self):
        """Activating non-existent component raises error."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)

        with pytest.raises(LifecycleError, match="No candidate registered"):
            await lifecycle.activate("adapter", "nonexistent")

    @pytest.mark.asyncio
    async def test_activate_creates_new_instance_on_reactivate(self):
        """Re-activation creates new instance (hot-swap behavior)."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)

        call_count = 0

        def factory():
            nonlocal call_count
            call_count += 1
            return MockComponent(f"redis-{call_count}")

        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=factory,
                source=CandidateSource.MANUAL,
            )
        )

        # First activation
        instance1 = await lifecycle.activate("adapter", "cache")
        assert call_count == 1

        # Second activation (hot-swap, creates new instance)
        instance2 = await lifecycle.activate("adapter", "cache")
        assert call_count == 2  # Factory called again
        assert instance1 is not instance2  # Different instances

    @pytest.mark.asyncio
    async def test_get_instance_returns_active_instance(self):
        """get_instance returns activated instance."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)

        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: MockComponent("redis"),
                source=CandidateSource.MANUAL,
            )
        )

        # Before activation
        assert lifecycle.get_instance("adapter", "cache") is None

        # After activation
        instance = await lifecycle.activate("adapter", "cache")
        assert lifecycle.get_instance("adapter", "cache") is instance


class TestLifecycleHotSwap:
    """Test hot-swapping components."""

    @pytest.mark.asyncio
    async def test_swap_to_different_provider(self):
        """Swap from one provider to another."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)

        # Register two providers
        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: MockComponent("redis"),
                priority=1,
                source=CandidateSource.MANUAL,
            )
        )
        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="memcached",
                factory=lambda: MockComponent("memcached"),
                priority=10,
                source=CandidateSource.MANUAL,
            )
        )

        # Activate redis (explicit provider)
        instance1 = await lifecycle.activate("adapter", "cache", provider="redis")
        assert instance1.name == "redis"

        # Swap to memcached
        instance2 = await lifecycle.swap("adapter", "cache", provider="memcached")
        assert instance2.name == "memcached"

    @pytest.mark.asyncio
    async def test_swap_cleans_up_old_instance(self):
        """Swap cleans up old instance if it has cleanup method."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)

        old_instance = MockComponent("redis")
        new_instance = MockComponent("memcached")

        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: old_instance,
                source=CandidateSource.MANUAL,
            )
        )
        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="memcached",
                factory=lambda: new_instance,
                source=CandidateSource.MANUAL,
            )
        )

        # Activate redis
        await lifecycle.activate("adapter", "cache", provider="redis")
        assert not old_instance.cleaned_up

        # Swap to memcached (should cleanup redis)
        await lifecycle.swap("adapter", "cache", provider="memcached")
        assert old_instance.cleaned_up  # Old instance cleaned up
        assert not new_instance.cleaned_up  # New instance active

    @pytest.mark.asyncio
    async def test_swap_rollback_on_health_check_failure(self):
        """Swap rolls back to old instance on health check failure."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)

        old_instance = MockComponent("redis", should_fail_health=False)
        new_instance = MockComponent("memcached", should_fail_health=True)

        async def old_health():
            return await old_instance.health_check()

        async def new_health():
            return await new_instance.health_check()

        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: old_instance,
                health=old_health,
                source=CandidateSource.MANUAL,
            )
        )
        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="memcached",
                factory=lambda: new_instance,
                health=new_health,
                source=CandidateSource.MANUAL,
            )
        )

        # Activate redis
        await lifecycle.activate("adapter", "cache", provider="redis")

        # Try to swap to memcached (should fail and rollback)
        with pytest.raises(LifecycleError, match="Health check failed"):
            await lifecycle.swap("adapter", "cache", provider="memcached")

        # Should still be using redis (rollback)
        status = lifecycle.get_status("adapter", "cache")
        assert status.current_provider == "redis"
        # State is "failed" because the swap attempt failed (even though rollback worked)
        assert status.state == "failed"
        # But the instance should still be the old one
        instance = lifecycle.get_instance("adapter", "cache")
        assert instance is old_instance

    @pytest.mark.asyncio
    async def test_swap_with_force_skips_health_check(self):
        """Force swap skips health check even if it would fail."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)

        async def failing_health():
            return False

        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: MockComponent("redis"),
                source=CandidateSource.MANUAL,
            )
        )
        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="memcached",
                factory=lambda: MockComponent("memcached"),
                health=failing_health,
                source=CandidateSource.MANUAL,
            )
        )

        # Activate redis
        await lifecycle.activate("adapter", "cache", provider="redis")

        # Force swap to memcached (skip health check)
        instance = await lifecycle.swap(
            "adapter", "cache", provider="memcached", force=True
        )
        assert instance.name == "memcached"

    @pytest.mark.asyncio
    async def test_health_timeout_enforced(self):
        """Lifecycle enforces health timeouts when configured."""
        resolver = Resolver()
        lifecycle = LifecycleManager(
            resolver,
            safety=LifecycleSafetyOptions(
                activation_timeout=1.0,
                health_timeout=0.01,
                cleanup_timeout=1.0,
                hook_timeout=1.0,
            ),
        )

        async def slow_health():
            await asyncio.sleep(0.05)
            return True

        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: MockComponent("redis"),
                health=slow_health,
            )
        )

        with pytest.raises(LifecycleError, match="timed out"):
            await lifecycle.activate("adapter", "cache")


class TestLifecycleHooks:
    """Test pre/post swap hooks."""

    @pytest.mark.asyncio
    async def test_pre_swap_hook_called(self):
        """Pre-swap hook is called before swap."""
        resolver = Resolver()

        pre_swap_called = False
        candidate_captured = None
        new_instance_captured = None
        old_instance_captured = None

        async def pre_swap(candidate, new_instance, old_instance):
            nonlocal \
                pre_swap_called, \
                candidate_captured, \
                new_instance_captured, \
                old_instance_captured
            pre_swap_called = True
            candidate_captured = candidate
            new_instance_captured = new_instance
            old_instance_captured = old_instance
            await asyncio.sleep(0.01)

        hooks = LifecycleHooks()
        hooks.add_pre_swap(pre_swap)
        lifecycle = LifecycleManager(resolver, hooks=hooks)

        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: MockComponent("redis"),
                source=CandidateSource.MANUAL,
            )
        )
        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="memcached",
                factory=lambda: MockComponent("memcached"),
                source=CandidateSource.MANUAL,
            )
        )

        # Activate redis
        await lifecycle.activate("adapter", "cache", provider="redis")

        # Swap to memcached
        await lifecycle.swap("adapter", "cache", provider="memcached")

        assert pre_swap_called
        assert candidate_captured.provider == "memcached"
        assert new_instance_captured.name == "memcached"
        assert old_instance_captured.name == "redis"

    @pytest.mark.asyncio
    async def test_post_swap_hook_called(self):
        """Post-swap hook is called after successful swap."""
        resolver = Resolver()

        post_swap_called = False
        candidate_captured = None
        new_instance_captured = None
        old_instance_captured = None

        async def post_swap(candidate, new_instance, old_instance):
            nonlocal \
                post_swap_called, \
                candidate_captured, \
                new_instance_captured, \
                old_instance_captured
            post_swap_called = True
            candidate_captured = candidate
            new_instance_captured = new_instance
            old_instance_captured = old_instance
            await asyncio.sleep(0.01)

        hooks = LifecycleHooks()
        hooks.add_post_swap(post_swap)
        lifecycle = LifecycleManager(resolver, hooks=hooks)

        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: MockComponent("redis"),
                source=CandidateSource.MANUAL,
            )
        )
        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="memcached",
                factory=lambda: MockComponent("memcached"),
                source=CandidateSource.MANUAL,
            )
        )

        # Activate redis
        await lifecycle.activate("adapter", "cache", provider="redis")

        # Swap to memcached
        await lifecycle.swap("adapter", "cache", provider="memcached")

        assert post_swap_called
        assert candidate_captured.provider == "memcached"
        assert new_instance_captured.name == "memcached"
        assert old_instance_captured.name == "redis"

    @pytest.mark.asyncio
    async def test_post_swap_hook_not_called_on_failure(self):
        """Post-swap hook is NOT called if swap fails."""
        resolver = Resolver()

        post_swap_call_count = 0

        async def post_swap(candidate, new_instance, old_instance):
            nonlocal post_swap_call_count
            post_swap_call_count += 1

        async def failing_health():
            return False

        hooks = LifecycleHooks()
        hooks.add_post_swap(post_swap)
        lifecycle = LifecycleManager(resolver, hooks=hooks)

        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: MockComponent("redis"),
                source=CandidateSource.MANUAL,
            )
        )
        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="memcached",
                factory=lambda: MockComponent("memcached"),
                health=failing_health,
                source=CandidateSource.MANUAL,
            )
        )

        # Activate redis (will call post-swap hook once)
        await lifecycle.activate("adapter", "cache", provider="redis")
        assert post_swap_call_count == 1

        # Try to swap to memcached (should fail, NOT call post-swap hook again)
        with pytest.raises(LifecycleError):
            await lifecycle.swap("adapter", "cache", provider="memcached")

        # Post-swap hook should NOT have been called again (still 1, not 2)
        assert post_swap_call_count == 1


class TestLifecycleHealthProbes:
    """Test health probe functionality."""

    @pytest.mark.asyncio
    async def test_probe_healthy_instance(self):
        """Probe returns True for healthy instance."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)

        async def health_check():
            return True

        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: MockComponent("redis"),
                health=health_check,
                source=CandidateSource.MANUAL,
            )
        )

        await lifecycle.activate("adapter", "cache")

        # Probe health
        is_healthy = await lifecycle.probe_instance_health("adapter", "cache")
        assert is_healthy is True

    @pytest.mark.asyncio
    async def test_probe_unhealthy_instance(self):
        """Probe returns False for unhealthy instance."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)

        async def health_check():
            return False

        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: MockComponent("redis"),
                health=health_check,
                source=CandidateSource.MANUAL,
            )
        )

        # Force activation (skip initial health check)
        await lifecycle.activate("adapter", "cache", force=True)

        # Probe health (should fail)
        is_healthy = await lifecycle.probe_instance_health("adapter", "cache")
        assert is_healthy is False

    @pytest.mark.asyncio
    async def test_probe_nonexistent_instance(self):
        """Probe returns None for non-activated instance."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)

        is_healthy = await lifecycle.probe_instance_health("adapter", "nonexistent")
        assert is_healthy is None


class TestLifecycleStatusPersistence:
    """Test status persistence to JSON."""

    @pytest.mark.asyncio
    async def test_status_persisted_to_file(self, tmp_path: Path):
        """Status is persisted to JSON file."""
        status_file = tmp_path / "lifecycle_status.json"
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver, status_snapshot_path=str(status_file))

        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: MockComponent("redis"),
                source=CandidateSource.MANUAL,
            )
        )

        # Activate (should persist status)
        await lifecycle.activate("adapter", "cache")

        # Check file exists and contains correct data
        assert status_file.exists()

        with open(status_file) as f:
            data = json.load(f)

        # JSON format is a list of status dicts
        assert isinstance(data, list)
        assert len(data) == 1
        status_entry = data[0]
        assert status_entry["domain"] == "adapter"
        assert status_entry["key"] == "cache"
        assert status_entry["state"] == "ready"
        assert status_entry["current_provider"] == "redis"

    @pytest.mark.asyncio
    async def test_status_updated_on_swap(self, tmp_path: Path):
        """Status is updated in file after swap."""
        status_file = tmp_path / "lifecycle_status.json"
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver, status_snapshot_path=str(status_file))

        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: MockComponent("redis"),
                source=CandidateSource.MANUAL,
            )
        )
        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="memcached",
                factory=lambda: MockComponent("memcached"),
                source=CandidateSource.MANUAL,
            )
        )

        # Activate redis
        await lifecycle.activate("adapter", "cache", provider="redis")

        # Swap to memcached
        await lifecycle.swap("adapter", "cache", provider="memcached")

        # Check file updated
        with open(status_file) as f:
            data = json.load(f)

        # JSON format is a list of status dicts
        assert isinstance(data, list)
        assert len(data) == 1
        status_entry = data[0]
        assert status_entry["domain"] == "adapter"
        assert status_entry["key"] == "cache"
        assert status_entry["current_provider"] == "memcached"

    @pytest.mark.asyncio
    async def test_all_statuses_returns_all(self):
        """all_statuses returns all tracked statuses."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)

        # Register and activate multiple components
        for i in range(3):
            resolver.register(
                Candidate(
                    domain="adapter",
                    key=f"cache-{i}",
                    provider=f"provider-{i}",
                    factory=lambda i=i: MockComponent(f"component-{i}"),
                    source=CandidateSource.MANUAL,
                )
            )
            await lifecycle.activate("adapter", f"cache-{i}")

        # Get all statuses
        statuses = lifecycle.all_statuses()
        assert len(statuses) == 3
        assert all(s.state == "ready" for s in statuses)


class TestLifecycleEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_activate_already_active_returns_new_instance(self):
        """Re-activating replaces instance (hot-swap behavior)."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)

        call_count = 0

        def factory():
            nonlocal call_count
            call_count += 1
            return MockComponent(f"redis-{call_count}")

        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=factory,
                source=CandidateSource.MANUAL,
            )
        )

        # First activation
        instance1 = await lifecycle.activate("adapter", "cache")
        assert call_count == 1
        assert instance1.name == "redis-1"

        # Second activation (hot-swap, new instance)
        instance2 = await lifecycle.activate("adapter", "cache")
        assert call_count == 2  # Called again (hot-swap)
        assert instance2.name == "redis-2"
        assert instance1 is not instance2

    @pytest.mark.asyncio
    async def test_swap_is_alias_for_activate(self):
        """swap() is an alias for activate()."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)

        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: MockComponent("redis"),
                source=CandidateSource.MANUAL,
            )
        )

        # Swap without prior activation (should work like initial activation)
        instance = await lifecycle.swap("adapter", "cache", provider="redis")
        assert instance.name == "redis"

    @pytest.mark.asyncio
    async def test_get_status_for_never_activated_returns_none(self):
        """get_status for never-activated component returns None."""
        resolver = Resolver()
        lifecycle = LifecycleManager(resolver)

        resolver.register(
            Candidate(
                domain="adapter",
                key="cache",
                provider="redis",
                factory=lambda: MockComponent("redis"),
                source=CandidateSource.MANUAL,
            )
        )

        # Get status without activation
        status = lifecycle.get_status("adapter", "cache")
        assert status is None
