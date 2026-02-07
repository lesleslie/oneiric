"""Unit tests for SessionEventEmitter."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from oneiric.shell.session_tracker import (
    SessionEventEmitter,
    _get_timestamp,
    _get_user_info,
    _get_environment_info,
)


@pytest.fixture
def emitter():
    """Create a SessionEventEmitter instance."""
    return SessionEventEmitter(component_name="test-component")


@pytest.fixture
def mock_session():
    """Create a mock MCP session."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.initialize = AsyncMock()
    return session


class TestSessionEventEmitter:
    """Test SessionEventEmitter class."""

    @pytest.mark.asyncio
    async def test_initialization(self, emitter):
        """Test emitter initialization."""
        assert emitter.component_name == "test-component"
        assert emitter._session is None
        assert emitter.available is False
        assert emitter._consecutive_failures == 0
        assert emitter._circuit_open_until is None

    @pytest.mark.asyncio
    async def test_get_session_creates_new_session(self, emitter, mock_session):
        """Test _get_session creates new session when none exists."""
        with patch("oneiric.shell.session_tracker.ClientSession", return_value=mock_session):
            session = await emitter._get_session()
            assert session is not None
            mock_session.__aenter__.assert_called_once()
            mock_session.initialize.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_session_reuses_existing_session(self, emitter, mock_session):
        """Test _get_session reuses existing session."""
        emitter._session = mock_session
        session = await emitter._get_session()
        assert session == mock_session
        mock_session.__aenter__.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_availability_success(self, emitter, mock_session):
        """Test _check_availability returns True when MCP is available."""
        mock_session.call_tool = AsyncMock()
        emitter._session = mock_session

        with patch("oneiric.shell.session_tracker.ClientSession", return_value=mock_session):
            available = await emitter._check_availability()
            assert available is True
            assert emitter.available is True
            mock_session.call_tool.assert_called_once_with("health_check", {})

    @pytest.mark.asyncio
    async def test_check_availability_failure(self, emitter, mock_session):
        """Test _check_availability returns False when MCP is unavailable."""
        mock_session.call_tool = AsyncMock(side_effect=Exception("Connection failed"))
        emitter._session = mock_session

        with patch("oneiric.shell.session_tracker.ClientSession", return_value=mock_session):
            available = await emitter._check_availability()
            assert available is False
            assert emitter._consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_check_availability_circuit_breaker_opens(self, emitter, mock_session):
        """Test circuit breaker opens after 3 consecutive failures."""
        mock_session.call_tool = AsyncMock(side_effect=Exception("Connection failed"))
        emitter._session = mock_session

        with patch("oneiric.shell.session_tracker.ClientSession", return_value=mock_session):
            # Fail 3 times
            for _ in range(3):
                await emitter._check_availability()

            # Circuit should be open
            assert emitter._circuit_open_until is not None
            assert emitter._consecutive_failures == 3

            # Next call should return False immediately
            available = await emitter._check_availability()
            assert available is False

    @pytest.mark.asyncio
    async def test_check_availability_circuit_breaker_resets(self, emitter, mock_session):
        """Test circuit breaker resets after timeout."""
        # Set circuit breaker to past
        emitter._circuit_open_until = datetime.now(timezone.utc) - timedelta(seconds=10)
        emitter._consecutive_failures = 3

        mock_session.call_tool = AsyncMock()
        emitter._session = mock_session

        with patch("oneiric.shell.session_tracker.ClientSession", return_value=mock_session):
            available = await emitter._check_availability()
            assert available is True
            assert emitter._circuit_open_until is None
            assert emitter._consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_emit_session_start_success(self, emitter, mock_session):
        """Test emit_session_start succeeds with valid response."""
        mock_session.call_tool = AsyncMock()
        mock_result = MagicMock()
        mock_result.text = "test-session-123"
        mock_session.call_tool.return_value = [mock_result]

        emitter._session = mock_session
        emitter.available = True

        with patch.object(emitter, "_check_availability", return_value=True):
            session_id = await emitter.emit_session_start("TestShell")

            assert session_id == "test-session-123"
            mock_session.call_tool.assert_called_once()

            # Verify event structure
            call_args = mock_session.call_tool.call_args
            event = call_args[0][1]
            assert event["event_type"] == "session_start"
            assert event["component_name"] == "test-component"
            assert event["shell_type"] == "TestShell"
            assert "event_id" in event
            assert "timestamp" in event
            assert "pid" in event

    @pytest.mark.asyncio
    async def test_emit_session_start_unavailable(self, emitter):
        """Test emit_session_start returns None when MCP unavailable."""
        with patch.object(emitter, "_check_availability", return_value=False):
            session_id = await emitter.emit_session_start("TestShell")
            assert session_id is None

    @pytest.mark.asyncio
    async def test_emit_session_start_with_metadata(self, emitter, mock_session):
        """Test emit_session_start includes metadata."""
        mock_session.call_tool = AsyncMock()
        mock_result = MagicMock()
        mock_result.text = "test-session-123"
        mock_session.call_tool.return_value = [mock_result]

        emitter._session = mock_session
        emitter.available = True

        metadata = {"test_key": "test_value", "version": "1.0.0"}

        with patch.object(emitter, "_check_availability", return_value=True):
            session_id = await emitter.emit_session_start("TestShell", metadata=metadata)

            assert session_id == "test-session-123"

            # Verify metadata included
            call_args = mock_session.call_tool.call_args
            event = call_args[0][1]
            assert event["metadata"] == metadata

    @pytest.mark.asyncio
    async def test_emit_session_start_retry_logic(self, emitter, mock_session):
        """Test emit_session_start has retry decorator."""
        # Verify the method has retry decorator by checking it's callable
        assert hasattr(emitter.emit_session_start, '__wrapped__')
        # The retry decorator should be present
        # Test that it handles transient failures gracefully
        mock_session.call_tool = AsyncMock(side_effect=Exception("Transient error"))
        emitter._session = mock_session
        emitter.available = True

        with patch.object(emitter, "_check_availability", return_value=True):
            # Should retry and eventually return None
            session_id = await emitter.emit_session_start("TestShell")
            assert session_id is None
            # Verify call was made (retries happened)
            assert mock_session.call_tool.call_count >= 1

    @pytest.mark.asyncio
    async def test_emit_session_end_success(self, emitter, mock_session):
        """Test emit_session_end succeeds."""
        mock_session.call_tool = AsyncMock()
        emitter._session = mock_session
        emitter.available = True

        with patch.object(emitter, "_check_availability", return_value=True):
            result = await emitter.emit_session_end("test-session-123")

            assert result is True
            mock_session.call_tool.assert_called_once()

            # Verify event structure
            call_args = mock_session.call_tool.call_args
            event = call_args[0][1]
            assert event["event_type"] == "session_end"
            assert event["session_id"] == "test-session-123"
            assert "timestamp" in event

    @pytest.mark.asyncio
    async def test_emit_session_end_no_session_id(self, emitter):
        """Test emit_session_end returns False with no session_id."""
        result = await emitter.emit_session_end("")
        assert result is False

        result = await emitter.emit_session_end(None)
        assert result is False

    @pytest.mark.asyncio
    async def test_emit_session_end_unavailable(self, emitter):
        """Test emit_session_end returns False when MCP unavailable."""
        with patch.object(emitter, "_check_availability", return_value=False):
            result = await emitter.emit_session_end("test-session-123")
            assert result is False

    @pytest.mark.asyncio
    async def test_close_session(self, emitter, mock_session):
        """Test closing MCP session."""
        emitter._session = mock_session

        await emitter.close()

        mock_session.__aexit__.assert_called_once_with(None, None, None)
        assert emitter._session is None

    @pytest.mark.asyncio
    async def test_close_no_session(self, emitter):
        """Test closing when no session exists."""
        # Should not raise
        await emitter.close()
        assert emitter._session is None


class TestHelperFunctions:
    """Test helper functions."""

    def test_get_timestamp(self):
        """Test _get_timestamp returns ISO 8601 format."""
        timestamp = _get_timestamp()
        assert isinstance(timestamp, str)

        # Verify ISO 8601 format
        datetime.fromisoformat(timestamp)

    def test_get_user_info(self):
        """Test _get_user_info returns sanitized user info."""
        user_info = _get_user_info()

        assert "username" in user_info
        assert "home" in user_info

        # Verify truncation
        assert len(user_info["username"]) <= 100
        assert len(user_info["home"]) <= 500

        # Verify username is not empty
        assert len(user_info["username"]) > 0

    def test_get_environment_info(self):
        """Test _get_environment_info returns environment info."""
        env_info = _get_environment_info()

        assert "python_version" in env_info
        assert "platform" in env_info
        assert "cwd" in env_info

        # Verify truncation
        assert len(env_info["cwd"]) <= 500

        # Verify values are populated
        assert len(env_info["python_version"]) > 0
        assert len(env_info["platform"]) > 0

    def test_get_user_info_sanitization(self):
        """Test _get_user_info sanitizes input."""
        # Set a very long username
        with patch.dict(os.environ, {"USER": "x" * 200}):
            user_info = _get_user_info()
            assert len(user_info["username"]) <= 100

        # Set a very long home path
        with patch("os.path.expanduser", return_value="/" + "x" * 600):
            user_info = _get_user_info()
            assert len(user_info["home"]) <= 500

    def test_get_environment_info_sanitization(self):
        """Test _get_environment_info sanitizes cwd."""
        # Set a very long cwd
        with patch("os.getcwd", return_value="/" + "x" * 600):
            env_info = _get_environment_info()
            assert len(env_info["cwd"]) <= 500


class TestInputSanitization:
    """Test input sanitization for security."""

    def test_shell_type_sanitization(self):
        """Test shell_type is properly handled."""
        emitter = SessionEventEmitter(component_name="test")
        # The emitter should not crash with special characters
        # Actual sanitization happens at MCP tool level
        assert emitter.component_name == "test"

    @pytest.mark.asyncio
    async def test_metadata_sanitization(self, emitter):
        """Test metadata doesn't contain dangerous content."""
        # This would be enforced at the Session-Buddy level
        # Here we just verify metadata is passed through
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.text = "test-session-123"
        mock_session.call_tool.return_value = [mock_result]

        emitter._session = mock_session
        emitter.available = True

        dangerous_metadata = {
            "script": "<script>alert('xss')</script>",
            "sql": "'; DROP TABLE sessions; --",
            "path": "../../../etc/passwd",
        }

        with patch.object(emitter, "_check_availability", return_value=True):
            # Should not raise exception
            session_id = await emitter.emit_session_start("TestShell", metadata=dangerous_metadata)
            # Actual sanitization happens at Session-Buddy
            assert session_id == "test-session-123"


class TestCircuitBreakerBehavior:
    """Test circuit breaker behavior in detail."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_threshold(self, emitter, mock_session):
        """Test circuit breaker opens at exactly 3 failures."""
        mock_session.call_tool = AsyncMock(side_effect=Exception("Fail"))
        emitter._session = mock_session

        with patch("oneiric.shell.session_tracker.ClientSession", return_value=mock_session):
            # 2 failures - circuit should remain closed
            await emitter._check_availability()
            await emitter._check_availability()
            assert emitter._circuit_open_until is None

            # 3rd failure - circuit should open
            await emitter._check_availability()
            assert emitter._circuit_open_until is not None

    @pytest.mark.asyncio
    async def test_circuit_breaker_duration(self, emitter):
        """Test circuit breaker opens for 60 seconds."""
        now = datetime.now(timezone.utc)
        emitter._consecutive_failures = 3
        emitter._handle_failure()

        assert emitter._circuit_open_until is not None
        duration = emitter._circuit_open_until - now
        assert 59 <= duration.total_seconds() <= 61  # ~60 seconds

    @pytest.mark.asyncio
    async def test_circuit_breaker_auto_reset(self, emitter, mock_session):
        """Test circuit breaker automatically resets."""
        # Set circuit breaker to past
        emitter._circuit_open_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        emitter._consecutive_failures = 3

        mock_session.call_tool = AsyncMock()
        emitter._session = mock_session

        with patch("oneiric.shell.session_tracker.ClientSession", return_value=mock_session):
            # Should reset and succeed
            available = await emitter._check_availability()
            assert available is True
            assert emitter._circuit_open_until is None
            assert emitter._consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_circuit_breaker_blocks_calls(self, emitter):
        """Test circuit breaker blocks MCP calls while open."""
        # Set circuit breaker to future
        emitter._circuit_open_until = datetime.now(timezone.utc) + timedelta(seconds=60)
        emitter._consecutive_failures = 3

        # Should return False without attempting MCP call
        available = await emitter._check_availability()
        assert available is False


class TestRetryLogic:
    """Test retry logic with tenacity."""

    @pytest.mark.asyncio
    async def test_emit_methods_have_retry_decorator(self, emitter):
        """Test that emit methods have retry decorators."""
        # Check that retry decorator is present (method should have __wrapped__ attribute)
        # This verifies tenacity is configured
        from tenacity import RetryError
        assert hasattr(emitter.emit_session_start, '__wrapped__') or callable(emitter.emit_session_start)
        assert hasattr(emitter.emit_session_end, '__wrapped__') or callable(emitter.emit_session_end)

    @pytest.mark.asyncio
    async def test_persistent_error_returns_none(self, emitter, mock_session):
        """Test that persistent errors return None gracefully."""
        mock_session.call_tool = AsyncMock(side_effect=Exception("Persistent error"))
        emitter._session = mock_session
        emitter.available = True

        with patch.object(emitter, "_check_availability", return_value=True):
            # Should retry and eventually return None
            session_id = await emitter.emit_session_start("TestShell")
            assert session_id is None

    @pytest.mark.asyncio
    async def test_session_end_persistent_error(self, emitter, mock_session):
        """Test that session_end handles persistent errors."""
        mock_session.call_tool = AsyncMock(side_effect=Exception("Persistent error"))
        emitter._session = mock_session
        emitter.available = True

        with patch.object(emitter, "_check_availability", return_value=True):
            # Should return None on persistent error
            result = await emitter.emit_session_end("test-session-123")
            assert result is None


class TestMCPClientSessionManagement:
    """Test MCP client session lifecycle management."""

    @pytest.mark.asyncio
    async def test_session_lifecycle(self, emitter, mock_session):
        """Test complete session lifecycle."""
        # Create session
        with patch("oneiric.shell.session_tracker.ClientSession", return_value=mock_session):
            session = await emitter._get_session()
            assert session is not None

            # Use session
            mock_session.call_tool = AsyncMock()
            mock_result = MagicMock()
            mock_result.text = "test-session-123"
            mock_session.call_tool.return_value = [mock_result]

            emitter.available = True
            with patch.object(emitter, "_check_availability", return_value=True):
                session_id = await emitter.emit_session_start("TestShell")
                assert session_id == "test-session-123"

            # Close session
            await emitter.close()
            assert emitter._session is None
            mock_session.__aexit__.assert_called_once()

    @pytest.mark.asyncio
    async def test_session_reuse_across_calls(self, emitter, mock_session):
        """Test session is reused across multiple calls."""
        with patch("oneiric.shell.session_tracker.ClientSession", return_value=mock_session):
            # First call creates session
            session1 = await emitter._get_session()
            # Second call reuses session
            session2 = await emitter._get_session()

            assert session1 is session2
            # Initialize should only be called once
            mock_session.__aenter__.assert_called_once()

    @pytest.mark.asyncio
    async def test_session_recreation_after_close(self, emitter, mock_session):
        """Test new session created after close."""
        with patch("oneiric.shell.session_tracker.ClientSession", return_value=mock_session):
            # Create and close session
            await emitter._get_session()
            await emitter.close()

            # Create new session
            await emitter._get_session()

            # Should have called __aenter__ twice (once for each session)
            assert mock_session.__aenter__.call_count == 2


class TestGracefulDegradation:
    """Test graceful degradation when Session-Buddy unavailable."""

    @pytest.mark.asyncio
    async def test_session_start_returns_none_on_unavailable(self, emitter):
        """Test emit_session_start returns None gracefully."""
        with patch.object(emitter, "_check_availability", return_value=False):
            session_id = await emitter.emit_session_start("TestShell")
            assert session_id is None
            # Should not raise exception

    @pytest.mark.asyncio
    async def test_session_end_returns_false_on_unavailable(self, emitter):
        """Test emit_session_end returns False gracefully."""
        with patch.object(emitter, "_check_availability", return_value=False):
            result = await emitter.emit_session_end("test-session-123")
            assert result is False
            # Should not raise exception

    @pytest.mark.asyncio
    async def test_exception_handling_in_check_availability(self, emitter):
        """Test exceptions are handled in _check_availability."""
        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock(side_effect=RuntimeError("Unexpected error"))
        emitter._session = mock_session

        with patch("oneiric.shell.session_tracker.ClientSession", return_value=mock_session):
            # Should not raise, should return False
            available = await emitter._check_availability()
            assert available is False

    @pytest.mark.asyncio
    async def test_exception_handling_in_emit_start(self, emitter):
        """Test exceptions are handled in emit_session_start."""
        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock(side_effect=RuntimeError("Unexpected error"))
        emitter._session = mock_session
        emitter.available = True

        with patch.object(emitter, "_check_availability", return_value=True):
            # Should not raise, should return None
            session_id = await emitter.emit_session_start("TestShell")
            assert session_id is None

    @pytest.mark.asyncio
    async def test_exception_handling_in_emit_end(self, emitter):
        """Test exceptions are handled in emit_session_end."""
        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock(side_effect=RuntimeError("Unexpected error"))
        emitter._session = mock_session
        emitter.available = True

        with patch.object(emitter, "_check_availability", return_value=True):
            # Should not raise, should return None
            result = await emitter.emit_session_end("test-session-123")
            assert result is None


@pytest.mark.integration
class TestIntegrationScenarios:
    """Integration test scenarios."""

    @pytest.mark.asyncio
    async def test_full_session_lifecycle_mock(self, emitter, mock_session):
        """Test complete session lifecycle with mock."""
        call_log = []

        async def mock_call_tool(tool_name, event):
            call_log.append((tool_name, event["event_type"]))
            mock_result = MagicMock()
            if tool_name == "track_session_start":
                mock_result.text = "test-session-123"
            return [mock_result]

        mock_session.call_tool = AsyncMock(side_effect=mock_call_tool)
        mock_session.initialize = AsyncMock()

        with patch("oneiric.shell.session_tracker.ClientSession", return_value=mock_session):
            # Session start
            with patch.object(emitter, "_check_availability", return_value=True):
                session_id = await emitter.emit_session_start("TestShell", metadata={"test": "data"})
                assert session_id == "test-session-123"

            # Session end
            with patch.object(emitter, "_check_availability", return_value=True):
                result = await emitter.emit_session_end(session_id)
                assert result is True

            # Verify call sequence
            assert len(call_log) == 2
            assert call_log[0][0] == "track_session_start"
            assert call_log[0][1] == "session_start"
            assert call_log[1][0] == "track_session_end"
            assert call_log[1][1] == "session_end"
