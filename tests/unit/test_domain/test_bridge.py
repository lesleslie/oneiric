"""
Comprehensive domain bridge tests.

Tests domain bridge functionality for adapters, services, tasks, events,
and workflows including registration, activation, and lifecycle management.
"""

import pytest
from unittest import mock
from datetime import datetime

from oneiric.domain import (
    DomainBridge,
    DomainType,
    DomainAdapter,
    DomainService,
    DomainTask,
    DomainEvent,
    DomainWorkflow,
    DomainAction,
    DomainState,
    DomainError,
    DomainNotFoundError,
    DomainActivationError,
)
from oneiric.lifecycle import LifecycleEvent


class TestDomainBridge:
    """Test suite for DomainBridge base class."""

    @pytest.fixture
    def bridge(self):
        """Create a fresh DomainBridge for each test."""
        return DomainBridge(domain_type=DomainType.ADAPTER)

    def test_bridge_initialization(self, bridge):
        """Test DomainBridge initialization."""
        assert bridge.domain_type == DomainType.ADAPTER
        assert len(bridge.registered_domains) == 0

    def test_bridge_register_domain(self, bridge):
        """Test registering a domain."""
        domain = DomainAdapter(
            name='test_adapter',
            provider='default',
            module_path='test.adapter'
        )

        bridge.register(domain)
        assert 'test_adapter' in bridge.registered_domains

    def test_bridge_unregister_domain(self, bridge):
        """Test unregistering a domain."""
        domain = DomainAdapter(
            name='test_adapter',
            provider='default',
            module_path='test.adapter'
        )

        bridge.register(domain)
        bridge.unregister('test_adapter')

        assert 'test_adapter' not in bridge.registered_domains

    def test_bridge_activate_domain(self, bridge):
        """Test activating a domain."""
        domain = DomainAdapter(
            name='test_adapter',
            provider='default',
            module_path='test.adapter'
        )

        bridge.register(domain)
        result = bridge.activate('test_adapter')

        assert result.success is True
        assert domain.state == DomainState.ACTIVE

    def test_bridge_deactivate_domain(self, bridge):
        """Test deactivating a domain."""
        domain = DomainAdapter(
            name='test_adapter',
            provider='default',
            module_path='test.adapter'
        )

        bridge.register(domain)
        bridge.activate('test_adapter')
        result = bridge.deactivate('test_adapter')

        assert result.success is True
        assert domain.state == DomainState.INACTIVE

    def test_bridge_list_domains(self, bridge):
        """Test listing all domains."""
        domain1 = DomainAdapter(
            name='adapter1',
            provider='default',
            module_path='test.adapter1'
        )
        domain2 = DomainAdapter(
            name='adapter2',
            provider='default',
            module_path='test.adapter2'
        )

        bridge.register(domain1)
        bridge.register(domain2)

        domains = bridge.list()
        assert len(domains) == 2

    def test_bridge_get_domain(self, bridge):
        """Test getting a specific domain."""
        domain = DomainAdapter(
            name='test_adapter',
            provider='default',
            module_path='test.adapter'
        )

        bridge.register(domain)
        retrieved = bridge.get('test_adapter')

        assert retrieved is not None
        assert retrieved.name == 'test_adapter'

    def test_bridge_get_nonexistent_domain(self, bridge):
        """Test getting non-existent domain."""
        with pytest.raises(DomainNotFoundError):
            bridge.get('nonexistent')

    def test_bridge_pause_domain(self, bridge):
        """Test pausing a domain."""
        domain = DomainAdapter(
            name='test_adapter',
            provider='default',
            module_path='test.adapter'
        )

        bridge.register(domain)
        bridge.activate('test_adapter')
        bridge.pause('test_adapter')

        assert domain.state == DomainState.PAUSED

    def test_bridge_resume_domain(self, bridge):
        """Test resuming a paused domain."""
        domain = DomainAdapter(
            name='test_adapter',
            provider='default',
            module_path='test.adapter'
        )

        bridge.register(domain)
        bridge.activate('test_adapter')
        bridge.pause('test_adapter')
        bridge.resume('test_adapter')

        assert domain.state == DomainState.ACTIVE

    def test_bridge_health_check(self, bridge):
        """Test domain health check."""
        domain = DomainAdapter(
            name='test_adapter',
            provider='default',
            module_path='test.adapter'
        )

        bridge.register(domain)
        bridge.activate('test_adapter')

        health = bridge.check_health('test_adapter')
        assert health is not None

    def test_bridge_get_metrics(self, bridge):
        """Test getting domain metrics."""
        domain = DomainAdapter(
            name='test_adapter',
            provider='default',
            module_path='test.adapter'
        )

        bridge.register(domain)
        bridge.activate('test_adapter')

        metrics = bridge.get_metrics('test_adapter')
        assert metrics is not None

    def test_bridge_error_handling(self, bridge):
        """Test error handling in bridge operations."""
        with pytest.raises(DomainNotFoundError):
            bridge.activate('nonexistent')


class TestDomainAdapter:
    """Test suite for DomainAdapter class."""

    def test_adapter_creation(self):
        """Test creating DomainAdapter."""
        adapter = DomainAdapter(
            name='test_adapter',
            provider='redis',
            module_path='oneiric.adapters.cache.redis',
            domain='cache',
            config={'host': 'localhost', 'port': 6379}
        )

        assert adapter.name == 'test_adapter'
        assert adapter.provider == 'redis'
        assert adapter.domain == 'cache'
        assert adapter.config['host'] == 'localhost'

    def test_adapter_state_transitions(self):
        """Test adapter state transitions."""
        adapter = DomainAdapter(
            name='state_test',
            provider='default',
            module_path='test.adapter'
        )

        assert adapter.state == DomainState.REGISTERED

        adapter.activate()
        assert adapter.state == DomainState.ACTIVE

        adapter.pause()
        assert adapter.state == DomainState.PAUSED

        adapter.resume()
        assert adapter.state == DomainState.ACTIVE

        adapter.deactivate()
        assert adapter.state == DomainState.INACTIVE

    def test_adapter_health_status(self):
        """Test adapter health status updates."""
        adapter = DomainAdapter(
            name='health_test',
            provider='default',
            module_path='test.adapter'
        )

        assert adapter.health_status is None

        adapter.update_health(status='healthy', message='OK')
        assert adapter.health_status == 'healthy'

    def test_adapter_dependencies(self):
        """Test adapter dependency tracking."""
        adapter = DomainAdapter(
            name='dep_test',
            provider='default',
            module_path='test.adapter',
            dependencies=['base_adapter']
        )

        assert len(adapter.dependencies) == 1
        assert 'base_adapter' in adapter.dependencies

    def test_adapter_metadata(self):
        """Test adapter metadata."""
        adapter = DomainAdapter(
            name='metadata_test',
            provider='default',
            module_path='test.adapter',
            metadata={'version': '1.0.0', 'author': 'test'}
        )

        assert adapter.metadata['version'] == '1.0.0'
        assert adapter.metadata['author'] == 'test'


class TestDomainService:
    """Test suite for DomainService class."""

    def test_service_creation(self):
        """Test creating DomainService."""
        service = DomainService(
            name='test_service',
            module_path='oneiric.services.test',
            config={'timeout': 30}
        )

        assert service.name == 'test_service'
        assert service.config['timeout'] == 30

    def test_service_start_stop(self):
        """Test service start and stop operations."""
        service = DomainService(
            name='lifecycle_service',
            module_path='test.service'
        )

        service.start()
        assert service.state == DomainState.ACTIVE

        service.stop()
        assert service.state == DomainState.INACTIVE

    def test_service_restart(self):
        """Test service restart."""
        service = DomainService(
            name='restart_service',
            module_path='test.service'
        )

        service.start()
        service.restart()

        assert service.state == DomainState.ACTIVE

    def test_service_status(self):
        """Test getting service status."""
        service = DomainService(
            name='status_service',
            module_path='test.service'
        )

        service.start()
        status = service.get_status()

        assert status['state'] == DomainState.ACTIVE


class TestDomainTask:
    """Test suite for DomainTask class."""

    def test_task_creation(self):
        """Test creating DomainTask."""
        task = DomainTask(
            name='test_task',
            module_path='oneiric.tasks.test',
            schedule='0 * * * *',  # Hourly
            config={'retries': 3}
        )

        assert task.name == 'test_task'
        assert task.schedule == '0 * * * *'
        assert task.config['retries'] == 3

    def test_task_execution(self):
        """Test task execution."""
        task = DomainTask(
            name='exec_task',
            module_path='test.task'
        )

        result = task.execute(context={'test': 'data'})
        assert result is not None

    def test_task_schedule_validation(self):
        """Test task schedule validation."""
        # Valid cron schedule
        task = DomainTask(
            name='valid_task',
            module_path='test.task',
            schedule='*/5 * * * *'
        )
        assert task.is_valid_schedule()

        # Invalid schedule
        invalid_task = DomainTask(
            name='invalid_task',
            module_path='test.task',
            schedule='invalid'
        )
        assert not invalid_task.is_valid_schedule()


class TestDomainEvent:
    """Test suite for DomainEvent class."""

    def test_event_creation(self):
        """Test creating DomainEvent."""
        event = DomainEvent(
            name='test_event',
            topic='test.events',
            module_path='oneiric.events.test'
        )

        assert event.name == 'test_event'
        assert event.topic == 'test.events'

    def test_event_dispatch(self):
        """Test event dispatch."""
        event = DomainEvent(
            name='dispatch_event',
            topic='test.events',
            module_path='test.event'
        )

        payload = {'data': 'test'}
        result = event.dispatch(payload=payload)

        assert result is not None

    def test_event_listener_registration(self):
        """Test registering event listeners."""
        event = DomainEvent(
            name='listener_event',
            topic='test.events',
            module_path='test.event'
        )

        def listener(payload):
            return payload

        event.register_listener(listener)
        assert len(event.listeners) == 1

    def test_event_filter_registration(self):
        """Test registering event filters."""
        event = DomainEvent(
            name='filter_event',
            topic='test.events',
            module_path='test.event'
        )

        def filter_func(payload):
            return payload.get('enabled', True)

        event.register_filter(filter_func)
        assert len(event.filters) == 1


class TestDomainWorkflow:
    """Test suite for DomainWorkflow class."""

    def test_workflow_creation(self):
        """Test creating DomainWorkflow."""
        workflow = DomainWorkflow(
            name='test_workflow',
            module_path='oneiric.workflows.test',
            dag={'nodes': ['a', 'b'], 'edges': [('a', 'b')]}
        )

        assert workflow.name == 'test_workflow'
        assert workflow.dag['nodes'] == ['a', 'b']

    def test_workflow_execution(self):
        """Test workflow execution."""
        workflow = DomainWorkflow(
            name='exec_workflow',
            module_path='test.workflow',
            dag={'nodes': ['start'], 'edges': []}
        )

        context = {'input': 'data'}
        result = workflow.execute(context=context)

        assert result is not None

    def test_workflow_validation(self):
        """Test workflow DAG validation."""
        # Valid DAG
        workflow = DomainWorkflow(
            name='valid_workflow',
            module_path='test.workflow',
            dag={
                'nodes': ['a', 'b', 'c'],
                'edges': [('a', 'b'), ('b', 'c')]
            }
        )
        assert workflow.is_valid_dag()

        # Invalid DAG (circular)
        invalid_workflow = DomainWorkflow(
            name='invalid_workflow',
            module_path='test.workflow',
            dag={
                'nodes': ['a', 'b'],
                'edges': [('a', 'b'), ('b', 'a')]
            }
        )
        assert not invalid_workflow.is_valid_dag()

    def test_workflow_checkpoint(self):
        """Test workflow checkpoint creation."""
        workflow = DomainWorkflow(
            name='checkpoint_workflow',
            module_path='test.workflow',
            dag={'nodes': ['a'], 'edges': []}
        )

        workflow.create_checkpoint(node='a', data={'status': 'complete'})
        assert 'a' in workflow.checkpoints

    def test_workflow_resume_from_checkpoint(self):
        """Test resuming workflow from checkpoint."""
        workflow = DomainWorkflow(
            name='resume_workflow',
            module_path='test.workflow',
            dag={'nodes': ['a', 'b'], 'edges': [('a', 'b')]}
        )

        workflow.create_checkpoint(node='a', data={'status': 'complete'})
        result = workflow.resume_from_checkpoint(node='b')

        assert result is not None


class TestDomainAction:
    """Test suite for DomainAction class."""

    def test_action_creation(self):
        """Test creating DomainAction."""
        action = DomainAction(
            name='test_action',
            module_path='oneiric.actions.test',
            action_type='task'
        )

        assert action.name == 'test_action'
        assert action.action_type == 'task'

    def test_action_execution(self):
        """Test action execution."""
        action = DomainAction(
            name='exec_action',
            module_path='test.action',
            action_type='task'
        )

        params = {'param1': 'value1'}
        result = action.execute(params=params)

        assert result is not None

    def test_action_validation(self):
        """Test action parameter validation."""
        action = DomainAction(
            name='validate_action',
            module_path='test.action',
            action_type='task',
            schema={
                'type': 'object',
                'properties': {
                    'param1': {'type': 'string'}
                },
                'required': ['param1']
            }
        )

        # Valid params
        assert action.validate_params({'param1': 'value'})

        # Invalid params
        assert not action.validate_params({})


class TestDomainError:
    """Test suite for DomainError exception handling."""

    def test_domain_error_creation(self):
        """Test creating DomainError."""
        error = DomainError(
            message='Test error',
            domain_name='test_domain',
            details={'key': 'value'}
        )

        assert error.message == 'Test error'
        assert error.domain_name == 'test_domain'
        assert error.details['key'] == 'value'

    def test_domain_error_to_dict(self):
        """Test converting DomainError to dictionary."""
        error = DomainError(
            message='Test error',
            domain_name='test_domain',
            details={'key': 'value'}
        )

        error_dict = error.to_dict()
        assert error_dict['message'] == 'Test error'
        assert error_dict['domain_name'] == 'test_domain'

    def test_domain_not_found_error(self):
        """Test DomainNotFoundError."""
        error = DomainNotFoundError(domain_name='missing_domain')

        assert 'missing_domain' in str(error)
        assert error.domain_name == 'missing_domain'

    def test_domain_activation_error(self):
        """Test DomainActivationError."""
        error = DomainActivationError(
            domain_name='failing_domain',
            reason='Dependency not found'
        )

        assert 'failing_domain' in str(error)
        assert error.reason == 'Dependency not found'


class TestDomainType:
    """Test suite for DomainType enum."""

    def test_domain_type_values(self):
        """Test DomainType enum values."""
        assert DomainType.ADAPTER.value == 'adapter'
        assert DomainType.SERVICE.value == 'service'
        assert DomainType.TASK.value == 'task'
        assert DomainType.EVENT.value == 'event'
        assert DomainType.WORKFLOW.value == 'workflow'
        assert DomainType.ACTION.value == 'action'

    def test_domain_type_from_string(self):
        """Test creating DomainType from string."""
        assert DomainType('adapter') == DomainType.ADAPTER
        assert DomainType('service') == DomainType.SERVICE


class TestDomainState:
    """Test suite for DomainState enum."""

    def test_domain_state_values(self):
        """Test DomainState enum values."""
        assert DomainState.REGISTERED.value == 'registered'
        assert DomainState.ACTIVE.value == 'active'
        assert DomainState.INACTIVE.value == 'inactive'
        assert DomainState.PAUSED.value == 'paused'
        assert DomainState.DRAINED.value == 'drained'
        assert DomainState.FAILED.value == 'failed'

    def test_domain_state_transitions(self):
        """Test valid state transitions."""
        # Registered -> Active
        state = DomainState.REGISTERED
        assert state.can_transition_to(DomainState.ACTIVE)

        # Active -> Paused
        state = DomainState.ACTIVE
        assert state.can_transition_to(DomainState.PAUSED)

        # Paused -> Active
        state = DomainState.PAUSED
        assert state.can_transition_to(DomainState.ACTIVE)

        # Active -> Inactive
        state = DomainState.ACTIVE
        assert state.can_transition_to(DomainState.INACTIVE)
