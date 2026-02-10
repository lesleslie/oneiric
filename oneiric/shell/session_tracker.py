"""Session lifecycle event emitter for admin shells."""

from __future__ import annotations

import logging
import os
import platform
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from mcp import ClientSession, StdioServerParameters
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


class SessionEventEmitter:
    """Emit session lifecycle events to Session-Buddy MCP."""

    def __init__(
        self,
        component_name: str,
        session_buddy_path: str | None = None,
    ) -> None:
        """Initialize session event emitter.

        Args:
            component_name: Component name (e.g., "mahavishnu", "session-buddy")
            session_buddy_path: Path to Session-Buddy package (for stdio MCP)
        """
        self.component_name = component_name
        self.session_buddy_path = session_buddy_path or os.getenv(
            "SESSION_BUDDY_PATH", "/Users/les/Projects/session-buddy"
        )

        # MCP server parameters (stdio transport)
        self._server_params = StdioServerParameters(
            command="uv",
            args=[
                "--directory",
                self.session_buddy_path,
                "run",
                "python",
                "-m",
                "session_buddy",
            ],
        )

        self._session: ClientSession | None = None
        self.available = False
        self._consecutive_failures = 0
        self._circuit_open_until: datetime | None = None

    async def _get_session(self) -> ClientSession:
        """Get or create MCP client session."""
        if self._session is None:
            self._session = ClientSession(self._server_params)
            await self._session.__aenter__()
            await self._session.initialize()
            self._consecutive_failures = 0
        return self._session

    async def _check_availability(self) -> bool:
        """Check if Session-Buddy MCP is available."""
        # Check circuit breaker
        if self._circuit_open_until:
            if datetime.now(UTC) < self._circuit_open_until:
                return False  # Circuit is open
            else:
                # Reset circuit breaker
                self._circuit_open_until = None
                self._consecutive_failures = 0

        try:
            session = await self._get_session()
            # Call health_check tool
            await session.call_tool("health_check", {})
            self.available = True
            return True
        except Exception as e:
            logger.debug(f"Session-Buddy MCP unavailable: {e}")
            self._handle_failure()
            return False

    def _handle_failure(self) -> None:
        """Handle consecutive failures with circuit breaker."""
        self._consecutive_failures += 1
        if self._consecutive_failures >= 3:
            # Open circuit for 60 seconds
            self._circuit_open_until = datetime.now(UTC) + timedelta(seconds=60)
            logger.warning("Circuit breaker opened - Session-Buddy unavailable")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def emit_session_start(
        self,
        shell_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        """Emit session start event.

        Args:
            shell_type: Shell type (e.g., "MahavishnuShell", "SessionBuddyShell")
            metadata: Optional additional metadata

        Returns:
            Session ID if successful, None otherwise
        """
        try:
            available = await self._check_availability()
            if not available:
                logger.warning("Session-Buddy MCP unavailable - session not tracked")
                return None

            event = {
                "event_version": "1.0",
                "event_id": str(uuid.uuid4()),
                "event_type": "session_start",
                "component_name": self.component_name,
                "shell_type": shell_type,
                "timestamp": _get_timestamp(),
                "pid": os.getpid(),
                "user": _get_user_info(),
                "hostname": platform.node(),
                "environment": _get_environment_info(),
                "metadata": metadata or {},
            }

            session = await self._get_session()
            result = await session.call_tool("track_session_start", event)

            # MCP tools return list of TextContent items
            # Extract session_id from result
            if isinstance(result, list) and len(result) > 0:
                # First item is usually TextContent with text attribute
                first_item = result[0]
                if hasattr(first_item, "text"):
                    session_id = first_item.text
                    logger.info(f"Session started: {session_id}")
                    return session_id
                else:
                    # Fallback: convert to string
                    session_id = str(first_item)
                    logger.info(f"Session started: {session_id}")
                    return session_id
            elif isinstance(result, str):
                # Direct string result
                logger.info(f"Session started: {result}")
                return result
            else:
                logger.error(f"Unexpected result type: {type(result)}")
                return None

        except Exception as e:
            logger.error(f"Failed to emit session start event: {e}")
            return None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def emit_session_end(
        self,
        session_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Emit session end event.

        Args:
            session_id: Session ID from session_start
            metadata: Optional additional metadata

        Returns:
            True if successful, False otherwise
        """
        if not session_id:
            return False

        try:
            available = await self._check_availability()
            if not available:
                return False

            event = {
                "event_type": "session_end",
                "session_id": session_id,
                "timestamp": _get_timestamp(),
                "metadata": metadata or {},
            }

            session = await self._get_session()
            await session.call_tool("track_session_end", event)
            logger.info(f"Session ended: {session_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to emit session end event: {e}")
            return False

    async def close(self) -> None:
        """Close MCP session."""
        if self._session:
            await self._session.__aexit__(None, None, None)
            self._session = None


def _get_timestamp() -> str:
    """Get ISO 8601 timestamp."""
    return datetime.now(UTC).isoformat()


def _get_user_info() -> dict[str, str]:
    """Get sanitized user information."""
    username = os.getenv("USER") or os.getenv("USERNAME") or "unknown"
    home = os.path.expanduser("~")

    # Sanitize input (truncate, escape special chars)
    return {
        "username": username[:100],  # Truncate long values
        "home": home[:500],  # Limit path length
    }


def _get_environment_info() -> dict[str, str]:
    """Get environment information."""
    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "cwd": os.getcwd()[:500],  # Limit path length
    }
