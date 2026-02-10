"""
Comprehensive adapter lifecycle tests.

Tests adapter installation, updates, removal, activation, deactivation,
and health monitoring for the Oneiric adapter system.
"""

import pytest
from unittest import mock
from datetime import datetime

from oneiric.adapter import (
    AdapterManager,
    Adapter,
    AdapterState,
    AdapterHealthStatus,
    AdapterError,
    AdapterNotFoundError,
    AdapterActivationError,
)
from oneiric.lifecycle import LifecycleManager, LifecycleEvent


class TestAdapterManager:
    """Test suite for AdapterManager class."""

    @pytest.fixture
    def manager(self):
        """Create a fresh AdapterManager for each test."""
        return AdapterManager()

    def test_install_adapter_success(self, manager):
        """Test successful adapter installation."""
        result = manager.install(
            name='postgresql',
            version='1.0.0',
            module_path='oneiric.adapters.database.postgresql'
        )
        assert result.success is True
        assert result.adapter_name == 'postgresql'
        assert result.version == '1.0.0'

    def test_install_adapter_already_exists(self, manager):
        """Test installing adapter that already exists."""
        manager.install(
            name='redis',
            version='1.0.0',
            module_path='oneiric.adapters.cache.redis'
        )

        with pytest.raises(AdapterError):
            manager.install(
                name='redis',
                version='2.0.0',
                module_path='oneiric.adapters.cache.redis'
            )

    def test_install_adapter_invalid_module(self, manager):
        """Test installing adapter with invalid module path."""
        with pytest.raises(ImportError):
            manager.install(
                name='invalid',
                version='1.0.0',
                module_path='nonexistent.module.path'
            )

    def test_update_adapter_success(self, manager):
        """Test successful adapter update."""
        manager.install(
            name='mysql',
            version='1.0.0',
            module_path='oneiric.adapters.database.mysql'
        )

        result = manager.update(
            name='mysql',
            version='2.0.0'
        )
        assert result.success is True
        assert result.version == '2.0.0'

    def test_update_adapter_not_found(self, manager):
        """Test updating non-existent adapter."""
        with pytest.raises(AdapterNotFoundError):
            manager.update(
                name='nonexistent',
                version='1.0.0'
            )

    def test_remove_adapter_success(self, manager):
        """Test successful adapter removal."""
        manager.install(
            name='sqlite',
            version='1.0.0',
            module_path='oneiric.adapters.database.sqlite'
        )

        result = manager.remove('sqlite')
        assert result.success is True

        # Verify it's removed
        with pytest.raises(AdapterNotFoundError):
            manager.get_adapter('sqlite')

    def test_remove_adapter_not_found(self, manager):
        """Test removing non-existent adapter."""
        with pytest.raises(AdapterNotFoundError):
            manager.remove('nonexistent')

    def test_list_adapters_empty(self, manager):
        """Test listing adapters when none installed."""
        adapters = manager.list()
        assert isinstance(adapters, list)
        assert len(adapters) == 0

    def test_list_adapters_multiple(self, manager):
        """Test listing multiple installed adapters."""
        manager.install(
            name='redis',
            version='1.0.0',
            module_path='oneiric.adapters.cache.redis'
        )
        manager.install(
            name='postgresql',
            version='1.0.0',
            module_path='oneiric.adapters.database.postgresql'
        )

        adapters = manager.list()
        assert len(adapters) == 2
        adapter_names = [a.name for a in adapters]
        assert 'redis' in adapter_names
        assert 'postgresql' in adapter_names

    def test_list_adapters_by_domain(self, manager):
        """Test listing adapters filtered by domain."""
        manager.install(
            name='redis',
            version='1.0.0',
            module_path='oneiric.adapters.cache.redis',
            domain='cache'
        )
        manager.install(
            name='postgresql',
            version='1.0.0',
            module_path='oneiric.adapters.database.postgresql',
            domain='database'
        )

        cache_adapters = manager.list(domain='cache')
        assert len(cache_adapters) == 1
        assert cache_adapters[0].name == 'redis'

    def test_get_adapter_success(self, manager):
        """Test getting installed adapter."""
        manager.install(
            name='mongodb',
            version='1.0.0',
            module_path='oneiric.adapters.database.mongodb'
        )

        adapter = manager.get_adapter('mongodb')
        assert adapter is not None
        assert adapter.name == 'mongodb'
        assert adapter.version == '1.0.0'

    def test_get_adapter_not_found(self, manager):
        """Test getting non-existent adapter."""
        with pytest.raises(AdapterNotFoundError):
            manager.get_adapter('nonexistent')

    def test_activate_adapter_success(self, manager):
        """Test successful adapter activation."""
        manager.install(
            name='logfire',
            version='1.0.0',
            module_path='oneiric.adapters.monitoring.logfire'
        )

        result = manager.activate('logfire')
        assert result.success is True
        assert result.state == AdapterState.ACTIVE

    def test_activate_adapter_already_active(self, manager):
        """Test activating already active adapter."""
        manager.install(
            name='sentry',
            version='1.0.0',
            module_path='oneiric.adapters.monitoring.sentry'
        )
        manager.activate('sentry')

        # Second activation should be idempotent
        result = manager.activate('sentry')
        assert result.success is True

    def test_deactivate_adapter_success(self, manager):
        """Test successful adapter deactivation."""
        manager.install(
            name='otlp',
            version='1.0.0',
            module_path='oneiric.adapters.monitoring.otlp'
        )
        manager.activate('otlp')

        result = manager.deactivate('otlp')
        assert result.success is True
        assert result.state == AdapterState.INACTIVE

    def test_deactivate_adapter_not_active(self, manager):
        """Test deactivating adapter that's not active."""
        manager.install(
            name='netdata',
            version='1.0.0',
            module_path='oneiric.adapters.monitoring.netdata'
        )

        # Should succeed even if not active
        result = manager.deactivate('netdata')
        assert result.success is True

    def test_check_adapter_health_healthy(self, manager):
        """Test health check for healthy adapter."""
        manager.install(
            name='redis',
            version='1.0.0',
            module_path='oneiric.adapters.cache.redis'
        )
        manager.activate('redis')

        health = manager.check_health('redis')
        assert health.status == AdapterHealthStatus.HEALTHY

    def test_check_adapter_health_unhealthy(self, manager):
        """Test health check for unhealthy adapter."""
        manager.install(
            name='failing_adapter',
            version='1.0.0',
            module_path='oneiric.adapters.test.failing'
        )

        health = manager.check_health('failing_adapter')
        assert health.status == AdapterHealthStatus.UNHEALTHY

    def test_swap_adapter_success(self, manager):
        """Test swapping adapter provider."""
        manager.install(
            name='cache',
            version='1.0.0',
            module_path='oneiric.adapters.cache.redis',
            provider='redis'
        )
        manager.activate('cache')

        result = manager.swap(
            name='cache',
            new_provider='memory',
            new_module_path='oneiric.adapters.cache.memory'
        )
        assert result.success is True
        assert result.provider == 'memory'

    def test_swap_adapter_not_found(self, manager):
        """Test swapping non-existent adapter."""
        with pytest.raises(AdapterNotFoundError):
            manager.swap(
                name='nonexistent',
                new_provider='other'
            )


class TestAdapter:
    """Test suite for Adapter class."""

    def test_adapter_creation(self):
        """Test creating an Adapter instance."""
        adapter = Adapter(
            name='test_adapter',
            version='1.0.0',
            module_path='oneiric.adapters.test',
            domain='test'
        )
        assert adapter.name == 'test_adapter'
        assert adapter.version == '1.0.0'
        assert adapter.state == AdapterState.REGISTERED

    def test_adapter_state_transitions(self):
        """Test adapter state transitions."""
        adapter = Adapter(
            name='state_test',
            version='1.0.0',
            module_path='oneiric.adapters.test'
        )

        # Registered -> Active
        adapter.activate()
        assert adapter.state == AdapterState.ACTIVE

        # Active -> Inactive
        adapter.deactivate()
        assert adapter.state == AdapterState.INACTIVE

    def test_adapter_metadata(self):
        """Test adapter metadata handling."""
        adapter = Adapter(
            name='metadata_test',
            version='1.0.0',
            module_path='oneiric.adapters.test',
            metadata={'key': 'value', 'number': 42}
        )

        assert adapter.metadata['key'] == 'value'
        assert adapter.metadata['number'] == 42

    def test_adapter_dependencies(self):
        """Test adapter dependency tracking."""
        adapter = Adapter(
            name='dep_test',
            version='1.0.0',
            module_path='oneiric.adapters.test',
            dependencies=['base_adapter', 'utils_adapter']
        )

        assert len(adapter.dependencies) == 2
        assert 'base_adapter' in adapter.dependencies

    def test_adapter_health_status(self):
        """Test adapter health status updates."""
        adapter = Adapter(
            name='health_test',
            version='1.0.0',
            module_path='oneiric.adapters.test'
        )

        assert adapter.health_status == AdapterHealthStatus.UNKNOWN

        adapter.update_health(AdapterHealthStatus.HEALTHY)
        assert adapter.health_status == AdapterHealthStatus.HEALTHY

    def test_adapter_last_health_check(self):
        """Test last health check timestamp."""
        adapter = Adapter(
            name='timestamp_test',
            version='1.0.0',
            module_path='oneiric.adapters.test'
        )

        assert adapter.last_health_check is None

        adapter.update_health(AdapterHealthStatus.HEALTHY)
        assert adapter.last_health_check is not None
        assert isinstance(adapter.last_health_check, datetime)


class TestLifecycleManager:
    """Test suite for LifecycleManager class."""

    @pytest.fixture
    def lifecycle_mgr(self):
        """Create a fresh LifecycleManager for each test."""
        return LifecycleManager()

    @pytest.fixture
    def sample_adapter(self):
        """Create a sample adapter for testing."""
        return Adapter(
            name='lifecycle_test',
            version='1.0.0',
            module_path='oneiric.adapters.test'
        )

    def test_lifecycle_initialization(self, lifecycle_mgr):
        """Test LifecycleManager initialization."""
        assert lifecycle_mgr is not None
        assert len(lifecycle_mgr.managed_adapters) == 0

    def test_lifecycle_register_adapter(self, lifecycle_mgr, sample_adapter):
        """Test registering adapter with lifecycle manager."""
        lifecycle_mgr.register(sample_adapter)
        assert sample_adapter.name in lifecycle_mgr.managed_adapters

    def test_lifecycle_activate_adapter(self, lifecycle_mgr, sample_adapter):
        """Test activating adapter through lifecycle manager."""
        lifecycle_mgr.register(sample_adapter)

        event = lifecycle_mgr.activate(sample_adapter.name)
        assert event.event_type == LifecycleEvent.Activation
        assert event.success is True
        assert sample_adapter.state == AdapterState.ACTIVE

    def test_lifecycle_deactivate_adapter(self, lifecycle_mgr, sample_adapter):
        """Test deactivating adapter through lifecycle manager."""
        lifecycle_mgr.register(sample_adapter)
        lifecycle_mgr.activate(sample_adapter.name)

        event = lifecycle_mgr.deactivate(sample_adapter.name)
        assert event.event_type == LifecycleEvent.Deactivation
        assert event.success is True
        assert sample_adapter.state == AdapterState.INACTIVE

    def test_lifecycle_cleanup_adapter(self, lifecycle_mgr, sample_adapter):
        """Test cleaning up adapter resources."""
        lifecycle_mgr.register(sample_adapter)
        lifecycle_mgr.activate(sample_adapter.name)

        event = lifecycle_mgr.cleanup(sample_adapter.name)
        assert event.event_type == LifecycleEvent.Cleanup
        assert event.success is True

    def test_lifecycle_rollback_adapter(self, lifecycle_mgr, sample_adapter):
        """Test rolling back adapter to previous state."""
        lifecycle_mgr.register(sample_adapter)
        lifecycle_mgr.activate(sample_adapter.name)

        event = lifecycle_mgr.rollback(sample_adapter.name)
        assert event.event_type == LifecycleEvent.Rollback
        assert event.success is True

    def test_lifecycle_health_monitoring(self, lifecycle_mgr, sample_adapter):
        """Test health monitoring in lifecycle manager."""
        lifecycle_mgr.register(sample_adapter)
        lifecycle_mgr.activate(sample_adapter.name)

        health = lifecycle_mgr.check_health(sample_adapter.name)
        assert health is not None
        assert health.status in [
            AdapterHealthStatus.HEALTHY,
            AdapterHealthStatus.UNHEALTHY,
            AdapterHealthStatus.UNKNOWN
        ]

    def test_lifecycle_get_state_history(self, lifecycle_mgr, sample_adapter):
        """Test getting adapter state history."""
        lifecycle_mgr.register(sample_adapter)
        lifecycle_mgr.activate(sample_adapter.name)
        lifecycle_mgr.deactivate(sample_adapter.name)

        history = lifecycle_mgr.get_state_history(sample_adapter.name)
        assert len(history) >= 2  # At least activation and deactivation

    def test_lifecycle_get_metrics(self, lifecycle_mgr, sample_adapter):
        """Test getting adapter lifecycle metrics."""
        lifecycle_mgr.register(sample_adapter)
        lifecycle_mgr.activate(sample_adapter.name)

        metrics = lifecycle_mgr.get_metrics(sample_adapter.name)
        assert metrics is not None
        assert 'activation_count' in metrics or 'state' in metrics

    def test_lifecycle_concurrent_activation(self, lifecycle_mgr):
        """Test handling concurrent activation requests."""
        adapter1 = Adapter(
            name='concurrent_test1',
            version='1.0.0',
            module_path='oneiric.adapters.test1'
        )
        adapter2 = Adapter(
            name='concurrent_test2',
            version='1.0.0',
            module_path='oneiric.adapters.test2'
        )

        lifecycle_mgr.register(adapter1)
        lifecycle_mgr.register(adapter2)

        # Activate both
        event1 = lifecycle_mgr.activate(adapter1.name)
        event2 = lifecycle_mgr.activate(adapter2.name)

        assert event1.success is True
        assert event2.success is True
        assert adapter1.state == AdapterState.ACTIVE
        assert adapter2.state == AdapterState.ACTIVE

    def test_lifecycle_error_handling(self, lifecycle_mgr):
        """Test error handling in lifecycle operations."""
        # Try to activate non-existent adapter
        with pytest.raises(AdapterNotFoundError):
            lifecycle_mgr.activate('nonexistent')

    def test_lifecycle_event_emission(self, lifecycle_mgr, sample_adapter):
        """Test lifecycle event emission."""
        events = []

        def event_handler(event):
            events.append(event)

        lifecycle_mgr.register_event_handler(event_handler)
        lifecycle_mgr.register(sample_adapter)
        lifecycle_mgr.activate(sample_adapter.name)

        assert len(events) > 0
        assert events[0].event_type == LifecycleEvent.Activation
