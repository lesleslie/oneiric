"""
Comprehensive resolver tests.

Tests component resolution, dependency graph traversal, conflict resolution,
and explainable decision-making for the Oneiric resolver system.
"""

import pytest
from unittest import mock

from oneiric.resolver import (
    Resolver,
    ResolutionError,
    ResolutionResult,
    ResolutionStrategy,
    Candidate,
    ShadowedCandidate,
)
from oneiric.config import SelectionStack


class TestResolver:
    """Test suite for Resolver class."""

    @pytest.fixture
    def resolver(self):
        """Create a fresh Resolver for each test."""
        return Resolver()

    @pytest.fixture
    def sample_candidates(self):
        """Create sample candidates for testing."""
        return [
            Candidate(
                name='cache',
                provider='redis',
                domain='cache',
                priority=100,
                module_path='oneiric.adapters.cache.redis'
            ),
            Candidate(
                name='cache',
                provider='memory',
                domain='cache',
                priority=50,
                module_path='oneiric.adapters.cache.memory'
            ),
        ]

    def test_resolve_component_success(self, resolver, sample_candidates):
        """Test successful component resolution."""
        for candidate in sample_candidates:
            resolver.register(candidate)

        result = resolver.resolve('cache')
        assert result is not None
        assert result.name == 'cache'
        assert result.provider == 'redis'  # Higher priority

    def test_resolve_component_not_found(self, resolver):
        """Test resolving non-existent component."""
        with pytest.raises(ResolutionError):
            resolver.resolve('nonexistent')

    def test_resolve_with_explicit_selection(self, resolver, sample_candidates):
        """Test resolution with explicit selection."""
        for candidate in sample_candidates:
            resolver.register(candidate)

        # Explicitly select memory provider
        resolver.select('cache', provider='memory')

        result = resolver.resolve('cache')
        assert result.provider == 'memory'

    def test_resolve_with_stack_order(self, resolver):
        """Test resolution with stack-based precedence."""
        candidates = [
            Candidate(
                name='status',
                provider='provider1',
                domain='service',
                stack_order=1,
                module_path='oneiric.services.status1'
            ),
            Candidate(
                name='status',
                provider='provider2',
                domain='service',
                stack_order=2,
                module_path='oneiric.services.status2'
            ),
        ]

        for candidate in candidates:
            resolver.register(candidate)

        result = resolver.resolve('status')
        assert result.provider == 'provider1'  # Lower stack_order = higher precedence

    def test_resolve_with_priority(self, resolver, sample_candidates):
        """Test resolution with priority-based selection."""
        for candidate in sample_candidates:
            resolver.register(candidate)

        result = resolver.resolve('cache')
        assert result.provider == 'redis'  # Higher priority wins

    def test_resolve_with_registration_order(self, resolver):
        """Test resolution with registration order as tiebreaker."""
        candidates = [
            Candidate(
                name='queue',
                provider='redis',
                domain='queue',
                priority=100,
                module_path='oneiric.adapters.queue.redis'
            ),
            Candidate(
                name='queue',
                provider='memory',
                domain='queue',
                priority=100,  # Same priority
                module_path='oneiric.adapters.queue.memory'
            ),
        ]

        for candidate in candidates:
            resolver.register(candidate)

        result = resolver.resolve('queue')
        # First registered should win when priorities are equal
        assert result.provider == 'redis'

    def test_resolve_with_dependencies(self, resolver):
        """Test resolution with dependency graph."""
        # Register dependencies first
        base = Candidate(
            name='base',
            provider='default',
            domain='foundation',
            priority=100,
            module_path='oneiric.adapters.base'
        )
        resolver.register(base)

        # Register dependent component
        app = Candidate(
            name='web-app',
            provider='default',
            domain='app',
            priority=100,
            dependencies=['base'],
            module_path='oneiric.apps.web'
        )
        resolver.register(app)

        result = resolver.resolve('web-app', with_dependencies=True)
        assert result is not None
        assert len(result.dependencies) == 1
        assert result.dependencies[0].name == 'base'

    def test_resolve_with_circular_dependencies(self, resolver):
        """Test resolution with circular dependencies."""
        a = Candidate(
            name='a',
            provider='default',
            domain='test',
            dependencies=['b'],
            module_path='test.a'
        )
        b = Candidate(
            name='b',
            provider='default',
            domain='test',
            dependencies=['a'],
            module_path='test.b'
        )

        resolver.register(a)
        resolver.register(b)

        with pytest.raises(ResolutionError, match='circular'):
            resolver.resolve('a', with_dependencies=True)

    def test_resolve_with_missing_dependencies(self, resolver):
        """Test resolution with missing dependencies."""
        app = Candidate(
            name='app',
            provider='default',
            domain='test',
            dependencies=['missing_dep'],
            module_path='test.app'
        )
        resolver.register(app)

        with pytest.raises(ResolutionError, match='dependency'):
            resolver.resolve('app', with_dependencies=True)

    def test_explain_resolution(self, resolver, sample_candidates):
        """Test explainable resolution decisions."""
        for candidate in sample_candidates:
            resolver.register(candidate)

        explanation = resolver.explain('cache')
        assert explanation is not None
        assert 'selected' in explanation or 'candidate' in explanation
        assert explanation.get('name') == 'cache'

    def test_explain_resolution_with_shadowed(self, resolver, sample_candidates):
        """Test explanation showing shadowed candidates."""
        for candidate in sample_candidates:
            resolver.register(candidate)

        explanation = resolver.explain('cache', show_shadowed=True)
        assert explanation is not None

        # Should show why redis was selected over memory
        assert 'redis' in str(explanation).lower() or 'selected' in explanation

    def test_list_shadowed_candidates(self, resolver, sample_candidates):
        """Test listing shadowed candidates."""
        for candidate in sample_candidates:
            resolver.register(candidate)

        shadowed = resolver.get_shadowed('cache')
        assert isinstance(shadowed, list)
        assert len(shadowed) == 1
        assert shadowed[0].provider == 'memory'

    def test_register_candidate(self, resolver):
        """Test candidate registration."""
        candidate = Candidate(
            name='test',
            provider='default',
            domain='test',
            priority=100,
            module_path='test.module'
        )

        resolver.register(candidate)
        assert 'test' in resolver.list_registered()

    def test_register_duplicate_candidate(self, resolver, sample_candidates):
        """Test registering duplicate candidate."""
        resolver.register(sample_candidates[0])

        # Try to register same provider again
        with pytest.raises(ResolutionError):
            resolver.register(sample_candidates[0])

    def test_unregister_candidate(self, resolver):
        """Test unregistering candidate."""
        candidate = Candidate(
            name='test',
            provider='default',
            domain='test',
            priority=100,
            module_path='test.module'
        )

        resolver.register(candidate)
        resolver.unregister('test', provider='default')

        assert 'test' not in resolver.list_registered()

    def test_list_registered(self, resolver, sample_candidates):
        """Test listing registered components."""
        for candidate in sample_candidates:
            resolver.register(candidate)

        registered = resolver.list_registered()
        assert 'cache' in registered

    def test_list_registered_by_domain(self, resolver):
        """Test listing registered components by domain."""
        cache_candidate = Candidate(
            name='cache',
            provider='redis',
            domain='cache',
            priority=100,
            module_path='test.cache'
        )
        queue_candidate = Candidate(
            name='queue',
            provider='redis',
            domain='queue',
            priority=100,
            module_path='test.queue'
        )

        resolver.register(cache_candidate)
        resolver.register(queue_candidate)

        cache_components = resolver.list_registered(domain='cache')
        assert 'cache' in cache_components
        assert 'queue' not in cache_components

    def test_clear_selections(self, resolver):
        """Test clearing explicit selections."""
        resolver.register(sample_candidates[0])
        resolver.select('cache', provider='redis')

        assert 'cache' in resolver.selections

        resolver.clear_selections()
        assert 'cache' not in resolver.selections

    def test_resolution_strategy_explicit(self, resolver):
        """Test explicit resolution strategy."""
        resolver.set_strategy(ResolutionStrategy.EXPLICIT)

        for candidate in sample_candidates:
            resolver.register(candidate)

        resolver.select('cache', provider='memory')

        result = resolver.resolve('cache')
        assert result.provider == 'memory'

    def test_resolution_strategy_priority(self, resolver, sample_candidates):
        """Test priority-based resolution strategy."""
        resolver.set_strategy(ResolutionStrategy.PRIORITY)

        for candidate in sample_candidates:
            resolver.register(candidate)

        result = resolver.resolve('cache')
        assert result.provider == 'redis'  # Higher priority

    def test_resolution_error_handling(self, resolver):
        """Test resolution error handling."""
        with pytest.raises(ResolutionError) as exc_info:
            resolver.resolve('nonexistent')

        assert 'not found' in str(exc_info.value).lower()

    def test_resolve_multiple_components(self, resolver):
        """Test resolving multiple components."""
        components = [
            Candidate(
                name='cache',
                provider='redis',
                domain='cache',
                priority=100,
                module_path='test.cache'
            ),
            Candidate(
                name='queue',
                provider='redis',
                domain='queue',
                priority=100,
                module_path='test.queue'
            ),
        ]

        for component in components:
            resolver.register(component)

        results = resolver.resolve_multiple(['cache', 'queue'])
        assert len(results) == 2
        assert results[0].name == 'cache'
        assert results[1].name == 'queue'

    def test_resolve_with_context(self, resolver):
        """Test resolution with context information."""
        candidate = Candidate(
            name='context_test',
            provider='default',
            domain='test',
            priority=100,
            module_path='test.module'
        )

        resolver.register(candidate)

        context = {'environment': 'production', 'region': 'us-east'}
        result = resolver.resolve('context_test', context=context)

        assert result is not None
        assert result.name == 'context_test'

    def test_candidate_validation(self, resolver):
        """Test candidate validation during registration."""
        # Missing required fields
        with pytest.raises(ValueError):
            Candidate(
                name='invalid',
                # Missing provider
                domain='test',
                priority=100,
                module_path='test.module'
            )


class TestResolutionResult:
    """Test suite for ResolutionResult class."""

    def test_resolution_result_creation(self):
        """Test creating ResolutionResult."""
        result = ResolutionResult(
            name='test',
            provider='default',
            domain='test',
            module_path='test.module',
            priority=100
        )
        assert result.name == 'test'
        assert result.provider == 'default'

    def test_resolution_result_with_dependencies(self):
        """Test ResolutionResult with dependencies."""
        dep = ResolutionResult(
            name='dep',
            provider='default',
            domain='test',
            module_path='test.dep'
        )

        result = ResolutionResult(
            name='test',
            provider='default',
            domain='test',
            module_path='test.module',
            dependencies=[dep]
        )

        assert len(result.dependencies) == 1
        assert result.dependencies[0].name == 'dep'

    def test_resolution_result_metadata(self):
        """Test ResolutionResult metadata."""
        result = ResolutionResult(
            name='test',
            provider='default',
            domain='test',
            module_path='test.module',
            metadata={'key': 'value'}
        )

        assert result.metadata['key'] == 'value'


class TestShadowedCandidate:
    """Test suite for ShadowedCandidate class."""

    def test_shadowed_candidate_creation(self):
        """Test creating ShadowedCandidate."""
        shadowed = ShadowedCandidate(
            name='test',
            provider='shadowed',
            domain='test',
            priority=50,
            reason='Lower priority than selected candidate (100)',
            selected_by='redis'
        )

        assert shadowed.name == 'test'
        assert shadowed.provider == 'shadowed'
        assert shadowed.reason is not None
        assert shadowed.selected_by == 'redis'

    def test_shadowed_candidate_explanation(self):
        """Test shadowed candidate explanation generation."""
        shadowed = ShadowedCandidate(
            name='cache',
            provider='memory',
            domain='cache',
            priority=50,
            reason='Priority 50 < 100 (redis)',
            selected_by='redis'
        )

        explanation = shadowed.explain()
        assert 'memory' in explanation
        assert 'redis' in explanation
        assert 'priority' in explanation.lower()


class TestSelectionStack:
    """Test suite for SelectionStack class."""

    def test_selection_stack_creation(self):
        """Test creating SelectionStack."""
        stack = SelectionStack()
        assert len(stack.selections) == 0

    def test_selection_stack_push(self):
        """Test pushing selection to stack."""
        stack = SelectionStack()
        stack.push('cache', provider='redis', reason='explicit')

        assert len(stack.selections) == 1
        assert stack.selections[0].name == 'cache'
        assert stack.selections[0].provider == 'redis'

    def test_selection_stack_pop(self):
        """Test popping selection from stack."""
        stack = SelectionStack()
        stack.push('cache', provider='redis')
        stack.push('queue', provider='memory')

        selection = stack.pop()
        assert selection.name == 'queue'
        assert len(stack.selections) == 1

    def test_selection_stack_peek(self):
        """Test peeking at top selection."""
        stack = SelectionStack()
        stack.push('cache', provider='redis')

        selection = stack.peek()
        assert selection.name == 'cache'
        assert len(stack.selections) == 1  # Should not remove

    def test_selection_stack_clear(self):
        """Test clearing selection stack."""
        stack = SelectionStack()
        stack.push('cache', provider='redis')
        stack.push('queue', provider='memory')

        stack.clear()
        assert len(stack.selections) == 0

    def test_selection_stack_find(self):
        """Test finding selection by name."""
        stack = SelectionStack()
        stack.push('cache', provider='redis')
        stack.push('queue', provider='memory')

        selection = stack.find('cache')
        assert selection is not None
        assert selection.provider == 'redis'

    def test_selection_stack_find_not_found(self):
        """Test finding non-existent selection."""
        stack = SelectionStack()

        selection = stack.find('nonexistent')
        assert selection is None
