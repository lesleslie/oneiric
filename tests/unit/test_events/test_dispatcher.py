"""
Comprehensive event dispatcher tests.

Tests event dispatching, listener registration, filter application,
retry policies, and fan-out strategies for the Oneiric event system.
"""

import pytest
import asyncio
from unittest import mock
from datetime import datetime, timedelta

from oneiric.events import (
    EventDispatcher,
    EventListener,
    EventFilter,
    EventPayload,
    DispatchResult,
    DispatchError,
    ListenerError,
    RetryPolicy,
    FanOutStrategy,
    TopicMatcher,
)


class TestEventDispatcher:
    """Test suite for EventDispatcher class."""

    @pytest.fixture
    def dispatcher(self):
        """Create a fresh EventDispatcher for each test."""
        return EventDispatcher()

    @pytest.fixture
    def sample_listener(self):
        """Create a sample event listener."""
        def listener(payload: EventPayload):
            return {'processed': True, 'data': payload}
        return listener

    def test_dispatcher_initialization(self, dispatcher):
        """Test EventDispatcher initialization."""
        assert dispatcher is not None
        assert len(dispatcher.topics) == 0

    def test_register_topic(self, dispatcher):
        """Test registering a topic."""
        dispatcher.register_topic('test.events')
        assert 'test.events' in dispatcher.topics

    def test_register_listener(self, dispatcher, sample_listener):
        """Test registering an event listener."""
        dispatcher.register_topic('test.events')
        dispatcher.register_listener('test.events', sample_listener)

        topic = dispatcher.topics['test.events']
        assert len(topic.listeners) == 1

    def test_register_listener_multiple(self, dispatcher):
        """Test registering multiple listeners."""
        dispatcher.register_topic('multi.events')

        def listener1(payload):
            return {'id': 1}

        def listener2(payload):
            return {'id': 2}

        dispatcher.register_listener('multi.events', listener1)
        dispatcher.register_listener('multi.events', listener2)

        topic = dispatcher.topics['multi.events']
        assert len(topic.listeners) == 2

    def test_unregister_listener(self, dispatcher, sample_listener):
        """Test unregistering a listener."""
        dispatcher.register_topic('test.events')
        dispatcher.register_listener('test.events', sample_listener)
        dispatcher.unregister_listener('test.events', sample_listener)

        topic = dispatcher.topics['test.events']
        assert len(topic.listeners) == 0

    def test_dispatch_event_success(self, dispatcher, sample_listener):
        """Test successful event dispatch."""
        dispatcher.register_topic('test.events')
        dispatcher.register_listener('test.events', sample_listener)

        payload = EventPayload(
            topic='test.events',
            data={'message': 'test'},
            timestamp=datetime.now()
        )

        result = dispatcher.dispatch(payload)
        assert result.success is True
        assert result.listeners_reached == 1

    def test_dispatch_event_no_listeners(self, dispatcher):
        """Test dispatching event with no listeners."""
        dispatcher.register_topic('empty.events')

        payload = EventPayload(
            topic='empty.events',
            data={'message': 'test'},
            timestamp=datetime.now()
        )

        result = dispatcher.dispatch(payload)
        assert result.success is True
        assert result.listeners_reached == 0

    def test_dispatch_event_topic_not_found(self, dispatcher):
        """Test dispatching to non-existent topic."""
        payload = EventPayload(
            topic='nonexistent.events',
            data={'message': 'test'},
            timestamp=datetime.now()
        )

        with pytest.raises(DispatchError):
            dispatcher.dispatch(payload)

    def test_dispatch_with_filter(self, dispatcher):
        """Test dispatch with event filter."""
        dispatcher.register_topic('filtered.events')

        def listener(payload):
            return {'processed': True}

        # Filter that only processes payloads with 'enabled': True
        def filter_func(payload):
            return payload.data.get('enabled', False)

        dispatcher.register_listener('filtered.events', listener)
        dispatcher.register_filter('filtered.events', filter_func)

        # Should be filtered out
        payload1 = EventPayload(
            topic='filtered.events',
            data={'enabled': False},
            timestamp=datetime.now()
        )
        result1 = dispatcher.dispatch(payload1)
        assert result1.listeners_reached == 0

        # Should pass through
        payload2 = EventPayload(
            topic='filtered.events',
            data={'enabled': True},
            timestamp=datetime.now()
        )
        result2 = dispatcher.dispatch(payload2)
        assert result2.listeners_reached == 1

    def test_dispatch_with_retry_policy(self, dispatcher):
        """Test dispatch with retry policy."""
        dispatcher.register_topic('retry.events')

        attempts = []

        def failing_listener(payload):
            attempts.append(1)
            if len(attempts) < 3:
                raise Exception('Temporary failure')
            return {'success': True}

        retry_policy = RetryPolicy(
            max_attempts=3,
            backoff_seconds=0.1
        )

        dispatcher.register_listener('retry.events', failing_listener)
        dispatcher.set_retry_policy('retry.events', retry_policy)

        payload = EventPayload(
            topic='retry.events',
            data={'message': 'test'},
            timestamp=datetime.now()
        )

        result = dispatcher.dispatch(payload)
        assert result.success is True
        assert len(attempts) == 3

    def test_dispatch_fan_out_all(self, dispatcher):
        """Test fan-out to all listeners."""
        dispatcher.register_topic('fanout.events')

        results = []

        def listener1(payload):
            results.append(1)
            return {'id': 1}

        def listener2(payload):
            results.append(2)
            return {'id': 2}

        dispatcher.register_listener('fanout.events', listener1)
        dispatcher.register_listener('fanout.events', listener2)
        dispatcher.set_fanout_strategy('fanout.events', FanOutStrategy.ALL)

        payload = EventPayload(
            topic='fanout.events',
            data={},
            timestamp=datetime.now()
        )

        result = dispatcher.dispatch(payload)
        assert result.listeners_reached == 2
        assert len(results) == 2

    def test_dispatch_fan_out_first(self, dispatcher):
        """Test fan-out to first listener only."""
        dispatcher.register_topic('first.events')

        results = []

        def listener1(payload):
            results.append(1)
            return {'id': 1}

        def listener2(payload):
            results.append(2)
            return {'id': 2}

        dispatcher.register_listener('first.events', listener1)
        dispatcher.register_listener('first.events', listener2)
        dispatcher.set_fanout_strategy('first.events', FanOutStrategy.FIRST)

        payload = EventPayload(
            topic='first.events',
            data={},
            timestamp=datetime.now()
        )

        result = dispatcher.dispatch(payload)
        assert result.listeners_reached == 1
        assert len(results) == 1
        assert results[0] == 1

    def test_dispatch_async(self, dispatcher):
        """Test async event dispatch."""
        dispatcher.register_topic('async.events')

        async def async_listener(payload):
            await asyncio.sleep(0.1)
            return {'async': True}

        dispatcher.register_listener('async.events', async_listener)

        payload = EventPayload(
            topic='async.events',
            data={},
            timestamp=datetime.now()
        )

        result = asyncio.run(dispatcher.dispatch_async(payload))
        assert result.success is True

    def test_get_topic_stats(self, dispatcher):
        """Test getting topic statistics."""
        dispatcher.register_topic('stats.events')

        def listener(payload):
            return {'processed': True}

        dispatcher.register_listener('stats.events', listener)

        payload = EventPayload(
            topic='stats.events',
            data={},
            timestamp=datetime.now()
        )
        dispatcher.dispatch(payload)

        stats = dispatcher.get_topic_stats('stats.events')
        assert stats['events_dispatched'] == 1
        assert stats['listeners_count'] == 1

    def test_list_topics(self, dispatcher):
        """Test listing all topics."""
        dispatcher.register_topic('topic1.events')
        dispatcher.register_topic('topic2.events')

        topics = dispatcher.list_topics()
        assert 'topic1.events' in topics
        assert 'topic2.events' in topics

    def test_unregister_topic(self, dispatcher):
        """Test unregistering a topic."""
        dispatcher.register_topic('temp.events')
        dispatcher.unregister_topic('temp.events')

        assert 'temp.events' not in dispatcher.topics


class TestEventListener:
    """Test suite for EventListener class."""

    def test_listener_creation(self):
        """Test creating EventListener."""
        def handler(payload):
            return {'processed': True}

        listener = EventListener(
            name='test_listener',
            handler=handler,
            topic='test.events'
        )

        assert listener.name == 'test_listener'
        assert listener.topic == 'test.events'

    def test_listener_execution(self):
        """Test listener execution."""
        def handler(payload):
            return {'data': payload.data}

        listener = EventListener(
            name='exec_listener',
            handler=handler,
            topic='test.events'
        )

        payload = EventPayload(
            topic='test.events',
            data={'message': 'test'},
            timestamp=datetime.now()
        )

        result = listener.execute(payload)
        assert result['data']['message'] == 'test'

    def test_listener_with_timeout(self):
        """Test listener with execution timeout."""
        import time

        def slow_handler(payload):
            time.sleep(0.2)
            return {'done': True}

        listener = EventListener(
            name='timeout_listener',
            handler=slow_handler,
            topic='test.events',
            timeout_seconds=0.1
        )

        payload = EventPayload(
            topic='test.events',
            data={},
            timestamp=datetime.now()
        )

        with pytest.raises(ListenerError):
            listener.execute(payload)

    def test_listener_error_handling(self):
        """Test listener error handling."""
        def failing_handler(payload):
            raise Exception('Handler error')

        listener = EventListener(
            name='error_listener',
            handler=failing_handler,
            topic='test.events'
        )

        payload = EventPayload(
            topic='test.events',
            data={},
            timestamp=datetime.now()
        )

        with pytest.raises(ListenerError):
            listener.execute(payload)


class TestEventFilter:
    """Test suite for EventFilter class."""

    def test_filter_creation(self):
        """Test creating EventFilter."""
        def filter_func(payload):
            return payload.data.get('enabled', False)

        event_filter = EventFilter(
            name='test_filter',
            filter_func=filter_func,
            topic='test.events'
        )

        assert event_filter.name == 'test_filter'

    def test_filter_application(self):
        """Test applying event filter."""
        def filter_func(payload):
            return payload.data.get('enabled', False)

        event_filter = EventFilter(
            name='enabled_filter',
            filter_func=filter_func,
            topic='test.events'
        )

        # Should pass
        payload1 = EventPayload(
            topic='test.events',
            data={'enabled': True},
            timestamp=datetime.now()
        )
        assert event_filter.apply(payload1) is True

        # Should not pass
        payload2 = EventPayload(
            topic='test.events',
            data={'enabled': False},
            timestamp=datetime.now()
        )
        assert event_filter.apply(payload2) is False

    def test_filter_chaining(self):
        """Test chaining multiple filters."""
        def filter1(payload):
            return payload.data.get('enabled', False)

        def filter2(payload):
            return payload.data.get('valid', False)

        filter_chain = EventFilter(
            name='chain_filter',
            filter_func=lambda p: filter1(p) and filter2(p),
            topic='test.events'
        )

        # Both true
        payload1 = EventPayload(
            topic='test.events',
            data={'enabled': True, 'valid': True},
            timestamp=datetime.now()
        )
        assert filter_chain.apply(payload1) is True

        # One false
        payload2 = EventPayload(
            topic='test.events',
            data={'enabled': True, 'valid': False},
            timestamp=datetime.now()
        )
        assert filter_chain.apply(payload2) is False


class TestEventPayload:
    """Test suite for EventPayload class."""

    def test_payload_creation(self):
        """Test creating EventPayload."""
        payload = EventPayload(
            topic='test.events',
            data={'message': 'test'},
            timestamp=datetime.now(),
            metadata={'source': 'test'}
        )

        assert payload.topic == 'test.events'
        assert payload.data['message'] == 'test'
        assert payload.metadata['source'] == 'test'

    def test_payload_serialization(self):
        """Test EventPayload serialization."""
        payload = EventPayload(
            topic='test.events',
            data={'message': 'test'},
            timestamp=datetime.now()
        )

        payload_dict = payload.model_dump()
        assert payload_dict['topic'] == 'test.events'
        assert payload_dict['data']['message'] == 'test'


class TestRetryPolicy:
    """Test suite for RetryPolicy class."""

    def test_retry_policy_creation(self):
        """Test creating RetryPolicy."""
        policy = RetryPolicy(
            max_attempts=3,
            backoff_seconds=1.0,
            max_backoff_seconds=10.0
        )

        assert policy.max_attempts == 3
        assert policy.backoff_seconds == 1.0

    def test_retry_policy_exponential_backoff(self):
        """Test exponential backoff calculation."""
        policy = RetryPolicy(
            max_attempts=5,
            backoff_seconds=1.0,
            backoff_multiplier=2.0
        )

        # Attempt 1: 1s
        # Attempt 2: 2s
        # Attempt 3: 4s
        delays = policy.get_delays()
        assert delays[0] == 1.0
        assert delays[1] == 2.0
        assert delays[2] == 4.0

    def test_retry_policy_max_backoff(self):
        """Test max backoff cap."""
        policy = RetryPolicy(
            max_attempts=10,
            backoff_seconds=1.0,
            backoff_multiplier=2.0,
            max_backoff_seconds=5.0
        )

        delays = policy.get_delays()
        # Should cap at 5.0
        assert max(delays) == 5.0


class TestFanOutStrategy:
    """Test suite for FanOutStrategy enum."""

    def test_fanout_strategies(self):
        """Test fan-out strategy values."""
        assert FanOutStrategy.ALL.value == 'all'
        assert FanOutStrategy.FIRST.value == 'first'
        assert FanOutStrategy.ROUND_ROBIN.value == 'round_robin'
        assert FanOutStrategy.RANDOM.value == 'random'


class TestTopicMatcher:
    """Test suite for TopicMatcher class."""

    def test_exact_match(self):
        """Test exact topic matching."""
        matcher = TopicMatcher()
        assert matcher.match('test.events', 'test.events') is True
        assert matcher.match('test.events', 'other.events') is False

    def test_wildcard_match(self):
        """Test wildcard topic matching."""
        matcher = TopicMatcher()

        # Single-level wildcard
        assert matcher.match('test.events.*', 'test.events.created') is True
        assert matcher.match('test.events.*', 'test.events.updated') is True
        assert matcher.match('test.events.*', 'other.events.created') is False

    def test_multi_level_wildcard(self):
        """Test multi-level wildcard matching."""
        matcher = TopicMatcher()

        # Multi-level wildcard
        assert matcher.match('test.>', 'test.events.created') is True
        assert matcher.match('test.>', 'test.events.user.created') is True
        assert matcher.match('test.>', 'other.events.created') is False

    def test_pattern_compilation(self):
        """Test pattern compilation and caching."""
        matcher = TopicMatcher()

        # First call compiles pattern
        result1 = matcher.match('test.events.*', 'test.events.created')

        # Second call uses cached pattern
        result2 = matcher.match('test.events.*', 'test.events.updated')

        assert result1 is True
        assert result2 is True


class TestDispatchResult:
    """Test suite for DispatchResult class."""

    def test_result_creation(self):
        """Test creating DispatchResult."""
        result = DispatchResult(
            success=True,
            topic='test.events',
            listeners_reached=3,
            listeners_failed=0,
            duration_seconds=0.5
        )

        assert result.success is True
        assert result.listeners_reached == 3

    def test_result_aggregation(self):
        """Test aggregating multiple results."""
        result1 = DispatchResult(
            success=True,
            topic='test.events',
            listeners_reached=2,
            listeners_failed=0
        )
        result2 = DispatchResult(
            success=True,
            topic='test.events',
            listeners_reached=3,
            listeners_failed=1
        )

        aggregated = DispatchResult.aggregate([result1, result2])
        assert aggregated.listeners_reached == 5
        assert aggregated.listeners_failed == 1
