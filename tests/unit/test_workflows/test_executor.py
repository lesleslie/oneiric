"""
Comprehensive workflow executor tests.

Tests workflow execution, DAG traversal, node dependencies,
checkpoint management, and error handling for the Oneiric workflow system.
"""

import pytest
import asyncio
from unittest import mock
from datetime import datetime
from networkx import DiGraph

from oneiric.workflows import (
    WorkflowExecutor,
    WorkflowDAG,
    WorkflowNode,
    WorkflowEdge,
    WorkflowCheckpoint,
    WorkflowResult,
    WorkflowError,
    WorkflowValidationError,
    ExecutionStatus,
    CheckpointManager,
)
from oneiric.config import WorkflowContext


class TestWorkflowDAG:
    """Test suite for WorkflowDAG class."""

    def test_dag_creation(self):
        """Test creating a workflow DAG."""
        dag = WorkflowDAG(name='test_dag')

        assert dag.name == 'test_dag'
        assert len(dag.nodes) == 0
        assert len(dag.edges) == 0

    def test_dag_add_node(self):
        """Test adding nodes to DAG."""
        dag = WorkflowDAG(name='node_test')

        node = WorkflowNode(
            id='node1',
            name='Test Node',
            handler='test.handler',
            config={'timeout': 30}
        )

        dag.add_node(node)
        assert 'node1' in dag.nodes
        assert dag.nodes['node1'].name == 'Test Node'

    def test_dag_add_edge(self):
        """Test adding edges to DAG."""
        dag = WorkflowDAG(name='edge_test')

        node1 = WorkflowNode(id='a', name='Node A', handler='a.handler')
        node2 = WorkflowNode(id='b', name='Node B', handler='b.handler')

        dag.add_node(node1)
        dag.add_node(node2)

        edge = WorkflowEdge(from_node='a', to_node='b')
        dag.add_edge(edge)

        assert 'a' in dag.edges
        assert dag.edges['a'][0].to_node == 'b'

    def test_dag_get_execution_order(self):
        """Test getting topological execution order."""
        dag = WorkflowDAG(name='order_test')

        # Create simple chain: a -> b -> c
        node_a = WorkflowNode(id='a', name='A', handler='a.handler')
        node_b = WorkflowNode(id='b', name='B', handler='b.handler')
        node_c = WorkflowNode(id='c', name='C', handler='c.handler')

        dag.add_node(node_a)
        dag.add_node(node_b)
        dag.add_node(node_c)

        dag.add_edge(WorkflowEdge(from_node='a', to_node='b'))
        dag.add_edge(WorkflowEdge(from_node='b', to_node='c'))

        order = dag.get_execution_order()
        assert order == ['a', 'b', 'c']

    def test_dag_detect_cycle(self):
        """Test cycle detection in DAG."""
        dag = WorkflowDAG(name='cycle_test')

        node_a = WorkflowNode(id='a', name='A', handler='a.handler')
        node_b = WorkflowNode(id='b', name='B', handler='b.handler')

        dag.add_node(node_a)
        dag.add_node(node_b)

        # Create cycle: a -> b -> a
        dag.add_edge(WorkflowEdge(from_node='a', to_node='b'))
        dag.add_edge(WorkflowEdge(from_node='b', to_node='a'))

        with pytest.raises(WorkflowValidationError):
            dag.validate()

    def test_dag_get_dependencies(self):
        """Test getting node dependencies."""
        dag = WorkflowDAG(name='dep_test')

        node_a = WorkflowNode(id='a', name='A', handler='a.handler')
        node_b = WorkflowNode(id='b', name='B', handler='b.handler')
        node_c = WorkflowNode(id='c', name='C', handler='c.handler')

        dag.add_node(node_a)
        dag.add_node(node_b)
        dag.add_node(node_c)

        dag.add_edge(WorkflowEdge(from_node='a', to_node='b'))
        dag.add_edge(WorkflowEdge(from_node='a', to_node='c'))

        deps = dag.get_dependencies('b')
        assert 'a' in deps

    def test_dag_get_dependents(self):
        """Test getting node dependents."""
        dag = WorkflowDAG(name='dependent_test')

        node_a = WorkflowNode(id='a', name='A', handler='a.handler')
        node_b = WorkflowNode(id='b', name='B', handler='b.handler')
        node_c = WorkflowNode(id='c', name='C', handler='c.handler')

        dag.add_node(node_a)
        dag.add_node(node_b)
        dag.add_node(node_c)

        dag.add_edge(WorkflowEdge(from_node='a', to_node='b'))
        dag.add_edge(WorkflowEdge(from_node='a', to_node='c'))

        dependents = dag.get_dependents('a')
        assert 'b' in dependents
        assert 'c' in dependents

    def test_dag_from_dict(self):
        """Test creating DAG from dictionary."""
        dag_dict = {
            'name': 'dict_dag',
            'nodes': [
                {'id': 'a', 'name': 'Node A', 'handler': 'a.handler'},
                {'id': 'b', 'name': 'Node B', 'handler': 'b.handler'}
            ],
            'edges': [
                {'from_node': 'a', 'to_node': 'b'}
            ]
        }

        dag = WorkflowDAG.from_dict(dag_dict)
        assert len(dag.nodes) == 2
        assert len(dag.edges) == 1

    def test_dag_to_dict(self):
        """Test converting DAG to dictionary."""
        dag = WorkflowDAG(name='convert_test')

        node = WorkflowNode(id='a', name='A', handler='a.handler')
        dag.add_node(node)

        dag_dict = dag.to_dict()
        assert dag_dict['name'] == 'convert_test'
        assert len(dag_dict['nodes']) == 1


class TestWorkflowExecutor:
    """Test suite for WorkflowExecutor class."""

    @pytest.fixture
    def executor(self):
        """Create a fresh WorkflowExecutor for each test."""
        return WorkflowExecutor()

    @pytest.fixture
    def simple_dag(self):
        """Create a simple DAG for testing."""
        dag = WorkflowDAG(name='simple')

        node_a = WorkflowNode(id='a', name='A', handler='test.a')
        node_b = WorkflowNode(id='b', name='B', handler='test.b')

        dag.add_node(node_a)
        dag.add_node(node_b)
        dag.add_edge(WorkflowEdge(from_node='a', to_node='b'))

        return dag

    def test_executor_initialization(self, executor):
        """Test WorkflowExecutor initialization."""
        assert executor is not None
        assert len(executor.workflows) == 0

    def test_register_workflow(self, executor, simple_dag):
        """Test registering a workflow."""
        executor.register(simple_dag)
        assert 'simple' in executor.workflows

    def test_execute_workflow_success(self, executor, simple_dag):
        """Test successful workflow execution."""
        executor.register(simple_dag)

        context = WorkflowContext(
            workflow_id='simple',
            input_data={'test': 'data'}
        )

        with mock.patch('oneiric.workflows.executor.execute_node') as mock_exec:
            mock_exec.return_value = {'status': 'success'}

            result = executor.execute('simple', context)
            assert result.status == ExecutionStatus.COMPLETED

    def test_execute_workflow_with_checkpoints(self, executor, simple_dag):
        """Test workflow execution with checkpoints."""
        executor.register(simple_dag)

        context = WorkflowContext(
            workflow_id='simple',
            input_data={},
            enable_checkpoints=True
        )

        with mock.patch('oneiric.workflows.executor.execute_node') as mock_exec:
            mock_exec.return_value = {'status': 'success'}

            result = executor.execute('simple', context)
            assert result.checkpoint_created is True

    def test_execute_workflow_resume_from_checkpoint(self, executor):
        """Test resuming workflow from checkpoint."""
        dag = WorkflowDAG(name='checkpoint_test')

        node_a = WorkflowNode(id='a', name='A', handler='test.a')
        node_b = WorkflowNode(id='b', name='B', handler='test.b')

        dag.add_node(node_a)
        dag.add_node(node_b)
        dag.add_edge(WorkflowEdge(from_node='a', to_node='b'))

        executor.register(dag)

        context = WorkflowContext(
            workflow_id='checkpoint_test',
            input_data={},
            resume_from='a'  # Resume from node A
        )

        with mock.patch('oneiric.workflows.executor.execute_node') as mock_exec:
            mock_exec.return_value = {'status': 'success'}

            result = executor.execute('checkpoint_test', context)
            assert result.status == ExecutionStatus.COMPLETED

    def test_execute_workflow_node_failure(self, executor, simple_dag):
        """Test workflow execution with node failure."""
        executor.register(simple_dag)

        context = WorkflowContext(
            workflow_id='simple',
            input_data={}
        )

        with mock.patch('oneiric.workflows.executor.execute_node') as mock_exec:
            mock_exec.side_effect = Exception('Node execution failed')

            result = executor.execute('simple', context)
            assert result.status == ExecutionStatus.FAILED

    def test_execute_workflow_parallel_nodes(self, executor):
        """Test executing parallel nodes."""
        dag = WorkflowDAG(name='parallel')

        node_start = WorkflowNode(id='start', name='Start', handler='test.start')
        node_a = WorkflowNode(id='a', name='A', handler='test.a')
        node_b = WorkflowNode(id='b', name='B', handler='test.b')
        node_end = WorkflowNode(id='end', name='End', handler='test.end')

        dag.add_node(node_start)
        dag.add_node(node_a)
        dag.add_node(node_b)
        dag.add_node(node_end)

        dag.add_edge(WorkflowEdge(from_node='start', to_node='a'))
        dag.add_edge(WorkflowEdge(from_node='start', to_node='b'))
        dag.add_edge(WorkflowEdge(from_node='a', to_node='end'))
        dag.add_edge(WorkflowEdge(from_node='b', to_node='end'))

        executor.register(dag)

        context = WorkflowContext(
            workflow_id='parallel',
            input_data={}
        )

        with mock.patch('oneiric.workflows.executor.execute_node') as mock_exec:
            mock_exec.return_value = {'status': 'success'}

            result = executor.execute('parallel', context)
            assert result.status == ExecutionStatus.COMPLETED

    def test_get_workflow_status(self, executor, simple_dag):
        """Test getting workflow execution status."""
        executor.register(simple_dag)

        context = WorkflowContext(
            workflow_id='simple',
            input_data={}
        )

        with mock.patch('oneiric.workflows.executor.execute_node') as mock_exec:
            mock_exec.return_value = {'status': 'success'}

            executor.execute('simple', context)
            status = executor.get_status('simple')

            assert status['workflow_id'] == 'simple'
            assert status['status'] in ['running', 'completed']

    def test_cancel_workflow(self, executor, simple_dag):
        """Test canceling workflow execution."""
        executor.register(simple_dag)

        context = WorkflowContext(
            workflow_id='simple',
            input_data={}
        )

        # Start execution
        with mock.patch('oneiric.workflows.executor.execute_node') as mock_exec:
            mock_exec.return_value = {'status': 'success'}

            # Execute in background
            future = asyncio.ensure_future(
                asyncio.create_task(executor.execute_async('simple', context))
            )

            # Cancel
            executor.cancel('simple')

            status = executor.get_status('simple')
            assert status['status'] == 'cancelled'


class TestCheckpointManager:
    """Test suite for CheckpointManager class."""

    @pytest.fixture
    def manager(self):
        """Create a fresh CheckpointManager for each test."""
        return CheckpointManager()

    def test_create_checkpoint(self, manager):
        """Test creating a checkpoint."""
        checkpoint = manager.create(
            workflow_id='test_workflow',
            node_id='node_a',
            data={'output': 'result'}
        )

        assert checkpoint.workflow_id == 'test_workflow'
        assert checkpoint.node_id == 'node_a'
        assert checkpoint.data['output'] == 'result'

    def test_get_checkpoint(self, manager):
        """Test getting a checkpoint."""
        manager.create(
            workflow_id='test_workflow',
            node_id='node_a',
            data={'output': 'result'}
        )

        checkpoint = manager.get('test_workflow', 'node_a')
        assert checkpoint is not None
        assert checkpoint.node_id == 'node_a'

    def test_get_checkpoint_not_found(self, manager):
        """Test getting non-existent checkpoint."""
        checkpoint = manager.get('nonexistent', 'node_a')
        assert checkpoint is None

    def test_list_checkpoints(self, manager):
        """Test listing all checkpoints for a workflow."""
        manager.create('test_workflow', 'node_a', {'data': 'a'})
        manager.create('test_workflow', 'node_b', {'data': 'b'})

        checkpoints = manager.list('test_workflow')
        assert len(checkpoints) == 2

    def test_delete_checkpoint(self, manager):
        """Test deleting a checkpoint."""
        manager.create('test_workflow', 'node_a', {'data': 'a'})

        manager.delete('test_workflow', 'node_a')

        checkpoint = manager.get('test_workflow', 'node_a')
        assert checkpoint is None

    def test_clear_workflow_checkpoints(self, manager):
        """Test clearing all checkpoints for a workflow."""
        manager.create('test_workflow', 'node_a', {'data': 'a'})
        manager.create('test_workflow', 'node_b', {'data': 'b'})

        manager.clear('test_workflow')

        checkpoints = manager.list('test_workflow')
        assert len(checkpoints) == 0

    def test_checkpoint_persistence(self, manager):
        """Test checkpoint persistence across saves."""
        checkpoint = manager.create(
            'test_workflow',
            'node_a',
            {'output': 'result'}
        )

        # Simulate save/load
        data = checkpoint.to_dict()
        restored = WorkflowCheckpoint.from_dict(data)

        assert restored.workflow_id == checkpoint.workflow_id
        assert restored.node_id == checkpoint.node_id
        assert restored.data == checkpoint.data


class TestWorkflowResult:
    """Test suite for WorkflowResult class."""

    def test_result_creation(self):
        """Test creating WorkflowResult."""
        result = WorkflowResult(
            workflow_id='test_workflow',
            status=ExecutionStatus.COMPLETED,
            node_results={'node_a': {'output': 'result'}},
            duration_seconds=1.5
        )

        assert result.workflow_id == 'test_workflow'
        assert result.status == ExecutionStatus.COMPLETED

    def test_result_with_error(self):
        """Test WorkflowResult with error."""
        result = WorkflowResult(
            workflow_id='failed_workflow',
            status=ExecutionStatus.FAILED,
            error='Node execution failed',
            failed_node='node_b'
        )

        assert result.status == ExecutionStatus.FAILED
        assert result.error == 'Node execution failed'
        assert result.failed_node == 'node_b'

    def test_result_aggregation(self):
        """Test aggregating multiple results."""
        result1 = WorkflowResult(
            workflow_id='test_workflow',
            status=ExecutionStatus.COMPLETED,
            node_results={'node_a': {'output': 'a'}}
        )

        result2 = WorkflowResult(
            workflow_id='test_workflow',
            status=ExecutionStatus.COMPLETED,
            node_results={'node_b': {'output': 'b'}}
        )

        aggregated = WorkflowResult.aggregate([result1, result2])
        assert len(aggregated.node_results) == 2


class TestExecutionStatus:
    """Test suite for ExecutionStatus enum."""

    def test_status_values(self):
        """Test ExecutionStatus enum values."""
        assert ExecutionStatus.PENDING.value == 'pending'
        assert ExecutionStatus.RUNNING.value == 'running'
        assert ExecutionStatus.COMPLETED.value == 'completed'
        assert ExecutionStatus.FAILED.value == 'failed'
        assert ExecutionStatus.CANCELLED.value == 'cancelled'
        assert ExecutionStatus.PAUSED.value == 'paused'


class TestWorkflowError:
    """Test suite for WorkflowError exception handling."""

    def test_workflow_error_creation(self):
        """Test creating WorkflowError."""
        error = WorkflowError(
            message='Test workflow error',
            workflow_id='test_workflow',
            node_id='node_a'
        )

        assert 'Test workflow error' in str(error)
        assert error.workflow_id == 'test_workflow'
        assert error.node_id == 'node_a'

    def test_workflow_validation_error(self):
        """Test WorkflowValidationError."""
        error = WorkflowValidationError(
            message='Invalid DAG structure',
            workflow_id='invalid_workflow'
        )

        assert 'Invalid DAG structure' in str(error)
        assert error.workflow_id == 'invalid_workflow'


class TestWorkflowNode:
    """Test suite for WorkflowNode class."""

    def test_node_creation(self):
        """Test creating WorkflowNode."""
        node = WorkflowNode(
            id='test_node',
            name='Test Node',
            handler='test.handler',
            config={'timeout': 30}
        )

        assert node.id == 'test_node'
        assert node.name == 'Test Node'
        assert node.handler == 'test.handler'
        assert node.config['timeout'] == 30

    def test_node_with_retry_policy(self):
        """Test WorkflowNode with retry policy."""
        from oneiric.events import RetryPolicy

        retry_policy = RetryPolicy(max_attempts=3)

        node = WorkflowNode(
            id='retry_node',
            name='Retry Node',
            handler='test.handler',
            retry_policy=retry_policy
        )

        assert node.retry_policy.max_attempts == 3


class TestWorkflowEdge:
    """Test suite for WorkflowEdge class."""

    def test_edge_creation(self):
        """Test creating WorkflowEdge."""
        edge = WorkflowEdge(
            from_node='a',
            to_node='b',
            condition='success'  # Only traverse on success
        )

        assert edge.from_node == 'a'
        assert edge.to_node == 'b'
        assert edge.condition == 'success'


class TestWorkflowCheckpoint:
    """Test suite for WorkflowCheckpoint class."""

    def test_checkpoint_creation(self):
        """Test creating WorkflowCheckpoint."""
        checkpoint = WorkflowCheckpoint(
            workflow_id='test_workflow',
            node_id='node_a',
            data={'output': 'result'},
            timestamp=datetime.now()
        )

        assert checkpoint.workflow_id == 'test_workflow'
        assert checkpoint.node_id == 'node_a'

    def test_checkpoint_serialization(self):
        """Test checkpoint serialization."""
        checkpoint = WorkflowCheckpoint(
            workflow_id='test_workflow',
            node_id='node_a',
            data={'output': 'result'}
        )

        data = checkpoint.to_dict()
        assert data['workflow_id'] == 'test_workflow'

        restored = WorkflowCheckpoint.from_dict(data)
        assert restored.workflow_id == checkpoint.workflow_id
        assert restored.data == checkpoint.data
