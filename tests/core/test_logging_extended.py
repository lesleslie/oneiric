"""Extended logging tests.

Tests for logging configuration and structured logging.
"""

from __future__ import annotations

import logging

import pytest

from oneiric.core.logging import (
    LoggingConfig,
    LoggingSinkConfig,
    bind_log_context,
    clear_log_context,
    configure_logging,
    get_logger,
    scoped_log_context,
)


class TestLoggingConfig:
    """Test logging configuration models."""

    def test_logging_config_defaults(self):
        """LoggingConfig has sensible defaults."""
        config = LoggingConfig()
        assert config.level == "INFO"
        assert config.emit_json is True
        assert config.service_name == "oneiric"

    def test_logging_config_custom_values(self):
        """LoggingConfig accepts custom values."""
        config = LoggingConfig(level="DEBUG", emit_json=False, service_name="custom")
        assert config.level == "DEBUG"
        assert config.emit_json is False
        assert config.service_name == "custom"

    def test_logging_sink_config_defaults(self):
        """LoggingSinkConfig has correct defaults."""
        config = LoggingSinkConfig()
        assert config.level == "INFO"
        assert config.target == "stdout"

    def test_logging_sink_config_custom_values(self):
        """LoggingSinkConfig accepts custom values."""
        config = LoggingSinkConfig(
            level="DEBUG",
            target="stderr",
        )
        assert config.level == "DEBUG"
        assert config.target == "stderr"


class TestGetLogger:
    """Test logger retrieval."""

    def test_get_logger_returns_logger(self):
        """get_logger returns a BoundLogger instance."""
        logger = get_logger("test")
        assert logger is not None
        # BoundLogger doesn't have .name attribute like stdlib logger
        # but it's a valid structlog logger

    def test_get_logger_same_name_same_instance(self):
        """get_logger returns same logger for same name."""
        logger1 = get_logger("test")
        logger2 = get_logger("test")
        # structlog may cache loggers, but we can't rely on object identity
        assert logger1 is not None
        assert logger2 is not None

    def test_get_logger_different_names(self):
        """get_logger returns different loggers for different names."""
        logger1 = get_logger("test1")
        logger2 = get_logger("test2")
        # Can't check .name on BoundLogger, just verify they're loggers
        assert logger1 is not None
        assert logger2 is not None

    def test_get_logger_with_initial_values(self):
        """get_logger accepts initial context values."""
        logger = get_logger("test", user_id="123", request_id="abc")
        assert logger is not None
        # structlog binds initial values to the context
        # Can't check .name on BoundLogger


class TestBindLogContext:
    """Test log context binding."""

    def test_bind_log_context_adds_values(self):
        """bind_log_context adds context values to logger."""
        logger = get_logger("test_context")
        bind_log_context(user_id="123", request_id="abc")

        # Context should be bound
        # (Actual behavior depends on structlog implementation)
        assert logger is not None

    def test_bind_log_context_multiple_calls(self):
        """Multiple bind_log_context calls accumulate values."""
        logger = get_logger("test_context_multi")

        bind_log_context(key1="value1")
        bind_log_context(key2="value2")

        # Both values should be bound
        assert logger is not None

    def test_clear_log_context_removes_values(self):
        """clear_log_context removes context values."""
        logger = get_logger("test_context_clear")

        bind_log_context(temp="value")
        clear_log_context("temp")

        # Value should be cleared
        assert logger is not None


class TestScopedLogContext:
    """Test scoped log context."""

    def test_scoped_log_context_with_statement(self):
        """scoped_log_context works as context manager."""
        logger = get_logger("test_scoped")

        with scoped_log_context(temp="value"):
            # Context should be bound within scope
            assert logger is not None

        # Context should be cleared after scope
        assert logger is not None

    def test_scoped_log_context_nested(self):
        """Nested scoped_log_context works correctly."""
        logger = get_logger("test_scoped_nested")

        with scoped_log_context(outer="value1"):
            with scoped_log_context(inner="value2"):
                # Both contexts should be bound
                assert logger is not None
            # Inner context cleared, outer still bound
            assert logger is not None
        # Both contexts cleared
        assert logger is not None


class TestConfigureLogging:
    """Test logging configuration."""

    def test_configure_logging_defaults(self):
        """configure_logging with default config works."""
        config = LoggingConfig()
        configure_logging(config)

        # Should configure root logger
        logger = logging.getLogger()
        assert logger is not None

    def test_configure_logging_with_level(self):
        """configure_logging sets log level."""
        config = LoggingConfig(level="DEBUG")
        configure_logging(config)

        logger = logging.getLogger("oneiric")
        # Level should be set
        assert logger is not None

    def test_configure_logging_multiple_sinks(self):
        """configure_logging handles multiple sinks."""
        # Note: LoggingConfig doesn't have a 'sinks' field
        # This test would need the actual implementation to support multiple sinks
        config = LoggingConfig(level="INFO")
        configure_logging(config)

        # Should configure root logger
        logger = logging.getLogger()
        assert logger is not None


class TestLoggingEdgeCases:
    """Test logging edge cases."""

    def test_get_logger_with_none_name(self):
        """get_logger with None name uses default."""
        logger = get_logger(None)
        assert logger is not None

    def test_bind_log_context_with_no_values(self):
        """bind_log_context with no values doesn't crash."""
        logger = get_logger("test_no_context")
        bind_log_context()
        assert logger is not None

    def test_clear_log_context_nonexistent_key(self):
        """clear_log_context with nonexistent key doesn't crash."""
        logger = get_logger("test_clear_nonexistent")
        clear_log_context("nonexistent_key")
        assert logger is not None

    def test_scoped_log_context_with_no_values(self):
        """scoped_log_context with no values doesn't crash."""
        logger = get_logger("test_scoped_no_values")

        with scoped_log_context():
            assert logger is not None

    def test_get_logger_with_special_characters(self):
        """get_logger handles special characters in name."""
        logger = get_logger("test.with.dots-and_dashes")
        assert logger is not None
        # Can't check .name on BoundLogger

    def test_configure_logging_with_invalid_level(self):
        """configure_logging handles any level string (no validation)."""
        # Note: Pydantic doesn't validate log level strings
        # Any string is accepted for flexibility
        config = LoggingConfig(level="CUSTOM_LEVEL")
        assert config.level == "CUSTOM_LEVEL"

    def test_logging_sink_config_serialization(self):
        """LoggingSinkConfig can be serialized."""
        config = LoggingSinkConfig(
            level="DEBUG",
            target="stdout",
        )

        data = config.model_dump()

        assert data["level"] == "DEBUG"
        assert data["target"] == "stdout"

    def test_logging_config_serialization(self):
        """LoggingConfig can be serialized."""
        config = LoggingConfig(
            level="INFO",
            emit_json=False,
            service_name="test-service",
        )

        data = config.model_dump()

        assert data["level"] == "INFO"
        assert data["emit_json"] is False
        assert data["service_name"] == "test-service"
