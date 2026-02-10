"""
Comprehensive logging and observability tests.

Tests structured logging, telemetry recording, health snapshots,
and observability integration for the Oneiric system.
"""

import pytest
import json
import tempfile
from pathlib import Path
from unittest import mock
from datetime import datetime

from oneiric.logging import (
    OneiricLogger,
    StructuredLogger,
    TelemetryRecorder,
    HealthSnapshot,
    LogSink,
    LogLevel,
    LogContext,
)
from oneiric.observation import (
    MetricType,
    MetricValue,
    ObservationEvent,
)


class TestOneiricLogger:
    """Test suite for OneiricLogger class."""

    @pytest.fixture
    def logger(self):
        """Create a fresh OneiricLogger for each test."""
        return OneiricLogger()

    def test_logger_initialization(self, logger):
        """Test logger initialization."""
        assert logger is not None
        assert logger.logger is not None

    def test_logger_with_context(self, logger):
        """Test logging with context."""
        logger.info(
            'Test message',
            context={'domain': 'adapter', 'provider': 'redis'}
        )

        # Context should be included in log output
        assert logger.context.get('domain') == 'adapter'

    def test_logger_log_levels(self, logger):
        """Test different log levels."""
        logger.debug('Debug message')
        logger.info('Info message')
        logger.warning('Warning message')
        logger.error('Error message')
        logger.critical('Critical message')

    def test_logger_with_exception(self, logger):
        """Test logging with exception."""
        try:
            raise ValueError('Test exception')
        except Exception as e:
            logger.exception('Exception occurred', exc_info=e)

    def test_logger_bind_context(self, logger):
        """Test binding context to logger."""
        logger.bind(domain='adapter', provider='redis')
        logger.info('Message with bound context')

        assert logger.bound_context.get('domain') == 'adapter'

    def test_logger_unbind_context(self, logger):
        """Test unbinding context from logger."""
        logger.bind(domain='adapter')
        assert 'domain' in logger.bound_context

        logger.unbind('domain')
        assert 'domain' not in logger.bound_context

    def test_logger_clear_context(self, logger):
        """Test clearing all bound context."""
        logger.bind(domain='adapter', provider='redis', key='value')
        logger.clear_context()

        assert len(logger.bound_context) == 0


class TestStructuredLogger:
    """Test suite for StructuredLogger class."""

    @pytest.fixture
    def structured_logger(self):
        """Create a StructuredLogger instance."""
        return StructuredLogger()

    def test_structured_logger_json_output(self, structured_logger):
        """Test JSON output from structured logger."""
        with tempfile.NamedTemporaryFile(mode='w+', suffix='.log') as f:
            structured_logger.add_sink(
                LogSink(type='file', path=f.name)
            )

            structured_logger.info(
                'Test message',
                extra={'key': 'value'}
            )

            # Read log file
            f.seek(0)
            log_entry = json.loads(f.read())

            assert log_entry['message'] == 'Test message'
            assert log_entry['key'] == 'value'

    def test_structured_logger_multiple_sinks(self, structured_logger):
        """Test logging to multiple sinks."""
        with tempfile.NamedTemporaryFile(mode='w+', suffix='.log') as f1:
            with tempfile.NamedTemporaryFile(mode='w+', suffix='.log') as f2:
                structured_logger.add_sink(
                    LogSink(type='file', path=f1.name)
                )
                structured_logger.add_sink(
                    LogSink(type='file', path=f2.name)
                )

                structured_logger.info('Multi-sink message')

                # Check both files
                f1.seek(0)
                f2.seek(0)

                assert 'Multi-sink message' in f1.read()
                assert 'Multi-sink message' in f2.read()

    def test_structured_logger_stdout_sink(self, structured_logger):
        """Test stdout logging sink."""
        structured_logger.add_sink(
            LogSink(type='stdout')
        )

        structured_logger.info('Stdout message')
        # Should not raise exception

    def test_structured_logger_stderr_sink(self, structured_logger):
        """Test stderr logging sink."""
        structured_logger.add_sink(
            LogSink(type='stderr')
        )

        structured_logger.error('Stderr message')
        # Should not raise exception

    def test_structured_logger_http_sink(self, structured_logger):
        """Test HTTP logging sink."""
        with mock.patch('httpx.post') as mock_post:
            mock_response = mock.Mock()
            mock_response.status_code = 200
            mock_post.return_value = mock_response

            structured_logger.add_sink(
                LogSink(
                    type='http',
                    url='https://logs.example.com'
                )
            )

            structured_logger.info('HTTP log message')
            mock_post.assert_called_once()

    def test_structured_logger_timestamp(self, structured_logger):
        """Test timestamp in log entries."""
        with tempfile.NamedTemporaryFile(mode='w+', suffix='.log') as f:
            structured_logger.add_sink(
                LogSink(type='file', path=f.name)
            )

            structured_logger.info('Timestamp test')

            f.seek(0)
            log_entry = json.loads(f.read())

            assert 'timestamp' in log_entry
            assert isinstance(log_entry['timestamp'], str)


class TestTelemetryRecorder:
    """Test suite for TelemetryRecorder class."""

    @pytest.fixture
    def recorder(self):
        """Create a TelemetryRecorder instance."""
        return TelemetryRecorder()

    def test_recorder_initialization(self, recorder):
        """Test recorder initialization."""
        assert recorder is not None
        assert len(recorder.metrics) == 0

    def test_record_counter(self, recorder):
        """Test recording counter metric."""
        recorder.record_counter(
            name='events_dispatched',
            value=1,
            tags={'topic': 'test.events'}
        )

        assert 'events_dispatched' in recorder.metrics

    def test_record_gauge(self, recorder):
        """Test recording gauge metric."""
        recorder.record_gauge(
            name='active_connections',
            value=42,
            tags={'adapter': 'redis'}
        )

        assert 'active_connections' in recorder.metrics

    def test_record_histogram(self, recorder):
        """Test recording histogram metric."""
        recorder.record_histogram(
            name='execution_duration',
            value=1.5,
            tags={'workflow': 'test'}
        )

        assert 'execution_duration' in recorder.metrics

    def test_record_event(self, recorder):
        """Test recording observation event."""
        event = ObservationEvent(
            event_type='workflow_execution',
            timestamp=datetime.now(),
            data={'workflow_id': 'test'}
        )

        recorder.record_event(event)
        assert len(recorder.events) == 1

    def test_get_metrics_summary(self, recorder):
        """Test getting metrics summary."""
        recorder.record_counter('counter1', value=1)
        recorder.record_gauge('gauge1', value=42)

        summary = recorder.get_summary()
        assert 'counter1' in summary
        assert 'gauge1' in summary

    def test_reset_metrics(self, recorder):
        """Test resetting metrics."""
        recorder.record_counter('test', value=1)

        recorder.reset()
        assert len(recorder.metrics) == 0

    def test_export_metrics(self, recorder):
        """Test exporting metrics."""
        recorder.record_counter('test', value=1)

        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False
        ) as f:
            temp_path = f.name

        try:
            recorder.export_to_file(temp_path)

            with open(temp_path, 'r') as f:
                data = json.load(f)

            assert 'metrics' in data
        finally:
            Path(temp_path).unlink()

    def test_aggregate_metrics(self, recorder):
        """Test aggregating metrics."""
        for i in range(5):
            recorder.record_counter('requests', value=1)

        aggregated = recorder.aggregate('requests')
        assert aggregated['count'] == 5


class TestHealthSnapshot:
    """Test suite for HealthSnapshot class."""

    @pytest.fixture
    def snapshot(self):
        """Create a HealthSnapshot instance."""
        return HealthSnapshot()

    def test_snapshot_creation(self, snapshot):
        """Test creating health snapshot."""
        assert snapshot is not None
        assert snapshot.timestamp is not None

    def test_snapshot_add_component_status(self, snapshot):
        """Test adding component status."""
        snapshot.add_component(
            component='adapter_cache',
            status='healthy',
            metadata={'provider': 'redis'}
        )

        assert 'adapter_cache' in snapshot.components

    def test_snapshot_add_metric(self, snapshot):
        """Test adding metric to snapshot."""
        snapshot.add_metric(
            name='uptime_seconds',
            value=3600.0
        )

        assert 'uptime_seconds' in snapshot.metrics

    def test_snapshot_overall_status(self, snapshot):
        """Test calculating overall status."""
        snapshot.add_component('comp1', status='healthy')
        snapshot.add_component('comp2', status='healthy')

        overall = snapshot.get_overall_status()
        assert overall == 'healthy'

    def test_snapshot_with_unhealthy_component(self, snapshot):
        """Test snapshot with unhealthy component."""
        snapshot.add_component('comp1', status='healthy')
        snapshot.add_component('comp2', status='unhealthy')

        overall = snapshot.get_overall_status()
        assert overall == 'unhealthy'

    def test_snapshot_serialization(self, snapshot):
        """Test snapshot serialization."""
        snapshot.add_component('test', status='healthy')
        snapshot.add_metric('test_metric', value=42)

        data = snapshot.to_dict()
        assert 'components' in data
        assert 'metrics' in data
        assert 'timestamp' in data

    def test_snapshot_persistence(self, snapshot):
        """Test snapshot persistence."""
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False
        ) as f:
            temp_path = f.name

        try:
            snapshot.add_component('test', status='healthy')
            snapshot.save(temp_path)

            # Load snapshot
            loaded = HealthSnapshot.load(temp_path)
            assert 'test' in loaded.components
        finally:
            Path(temp_path).unlink()


class TestLogSink:
    """Test suite for LogSink class."""

    def test_file_sink_creation(self):
        """Test creating file sink."""
        sink = LogSink(
            type='file',
            path='/tmp/test.log'
        )

        assert sink.type == 'file'
        assert sink.path == '/tmp/test.log'

    def test_http_sink_creation(self):
        """Test creating HTTP sink."""
        sink = LogSink(
            type='http',
            url='https://logs.example.com'
        )

        assert sink.type == 'http'
        assert sink.url == 'https://logs.example.com'

    def test_stdout_sink_creation(self):
        """Test creating stdout sink."""
        sink = LogSink(type='stdout')

        assert sink.type == 'stdout'

    def test_stderr_sink_creation(self):
        """Test creating stderr sink."""
        sink = LogSink(type='stderr')

        assert sink.type == 'stderr'

    def test_sink_validation(self):
        """Test sink validation."""
        # Invalid sink type
        with pytest.raises(ValueError):
            LogSink(type='invalid')


class TestLogLevel:
    """Test suite for LogLevel enum."""

    def test_log_levels(self):
        """Test log level values."""
        assert LogLevel.DEBUG.value == 'DEBUG'
        assert LogLevel.INFO.value == 'INFO'
        assert LogLevel.WARNING.value == 'WARNING'
        assert LogLevel.ERROR.value == 'ERROR'
        assert LogLevel.CRITICAL.value == 'CRITICAL'


class TestLogContext:
    """Test suite for LogContext class."""

    def test_context_creation(self):
        """Test creating log context."""
        context = LogContext(
            domain='adapter',
            provider='redis',
            key='value'
        )

        assert context.domain == 'adapter'
        assert context.provider == 'redis'

    def test_context_merge(self):
        """Test merging contexts."""
        context1 = LogContext(domain='adapter')
        context2 = LogContext(provider='redis')

        merged = context1.merge(context2)
        assert merged.domain == 'adapter'
        assert merged.provider == 'redis'

    def test_context_to_dict(self):
        """Test converting context to dictionary."""
        context = LogContext(
            domain='service',
            name='test_service'
        )

        data = context.to_dict()
        assert data['domain'] == 'service'
        assert data['name'] == 'test_service'


class TestObservabilityIntegration:
    """Test suite for observability system integration."""

    def test_logger_telemetry_integration(self):
        """Test logger and telemetry recorder integration."""
        logger = OneiricLogger()
        recorder = TelemetryRecorder()

        # Log event should be recorded in telemetry
        logger.info('Test event')
        recorder.record_event(
            ObservationEvent(
                event_type='log',
                timestamp=datetime.now(),
                data={'level': 'INFO', 'message': 'Test event'}
            )
        )

        assert len(recorder.events) == 1

    def test_health_snapshot_logging(self):
        """Test health snapshot logging."""
        snapshot = HealthSnapshot()
        snapshot.add_component('test', status='healthy')

        # Snapshot should be loggable
        data = snapshot.to_dict()
        assert isinstance(data, dict)

    def test_otel_integration(self):
        """Test OpenTelemetry integration."""
        with mock.patch('opentelemetry.trace.get_tracer') as mock_tracer:
            mock_tracer.return_value = mock.Mock()

            from oneiric.logging import OneiricLogger

            logger = OneiricLogger()
            logger.info('OTel test')

            # Should not raise exception
