"""Pydantic models for admin shell session event validation.

This module provides type-safe models for session lifecycle events emitted
by admin shells (Mahavishnu, Session-Buddy, Oneiric, etc.) to Session-Buddy
for tracking and analysis.

Event Flow:
    1. Admin shell starts → SessionStartEvent emitted
    2. Session-Buddy receives event via MCP tool
    3. Session record created in database
    4. Admin shell exits → SessionEndEvent emitted
    5. Session-Buddy updates record with end time and duration

Example:
    >>> from oneiric.shell.event_models import SessionStartEvent
    >>> event = SessionStartEvent(
    ...     event_version="1.0",
    ...     event_id="550e8400-e29b-41d4-a716-446655440000",
    ...     component_name="mahavishnu",
    ...     shell_type="MahavishnuShell",
    ...     pid=12345,
    ...     user=UserInfo(username="john", home="/home/john"),
    ...     hostname="server01",
    ...     environment=EnvironmentInfo(
    ...         python_version="3.13.0",
    ...         platform="Linux-6.5.0-x86_64",
    ...         cwd="/home/john/projects/mahavishnu",
    ...     ),
    ... )
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class UserInfo(BaseModel):
    """User information for session tracking.

    Attributes:
        username: System username (sanitized, max 100 chars)
        home: User home directory path (max 500 chars)

    Example:
        >>> user = UserInfo(username="john", home="/home/john")
    """

    username: str = Field(
        ...,
        max_length=100,
        description="System username (truncated to 100 characters)",
    )
    home: str = Field(
        ...,
        max_length=500,
        description="User home directory path (truncated to 500 characters)",
    )

    @field_validator("username", "home")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        """Strip leading/trailing whitespace from user fields.

        Args:
            v: Field value to validate

        Returns:
            Stripped string value
        """
        return v.strip()


class EnvironmentInfo(BaseModel):
    """Environment information for session tracking.

    Attributes:
        python_version: Python interpreter version (e.g., "3.13.0")
        platform: Platform identifier (e.g., "Linux-6.5.0-x86_64")
        cwd: Current working directory (max 500 chars)

    Example:
        >>> env = EnvironmentInfo(
        ...     python_version="3.13.0",
        ...     platform="Linux-6.5.0-x86_64",
        ...     cwd="/home/john/projects",
        ... )
    """

    python_version: str = Field(
        ...,
        description="Python interpreter version",
    )
    platform: str = Field(
        ...,
        description="Operating system and platform identifier",
    )
    cwd: str = Field(
        ...,
        max_length=500,
        description="Current working directory (truncated to 500 characters)",
    )

    @field_validator("cwd")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        """Strip leading/trailing whitespace from path.

        Args:
            v: Field value to validate

        Returns:
            Stripped string value
        """
        return v.strip()


class SessionStartEvent(BaseModel):
    """Session start event emitted by admin shells.

    This event is emitted when an admin shell (MahavishnuShell, SessionBuddyShell,
    etc.) starts up. It contains comprehensive metadata about the session for
    tracking and analysis.

    Attributes:
        event_version: Event format version (must be "1.0")
        event_id: Unique event identifier (UUID v4)
        event_type: Event type discriminator (must be "session_start")
        component_name: Component name (alphanumeric, underscore, hyphen only)
        shell_type: Shell class name (e.g., "MahavishnuShell")
        timestamp: ISO 8601 timestamp in UTC
        pid: Process ID (1-4194304 range)
        user: User information (username, home directory)
        hostname: System hostname
        environment: Environment information (Python version, platform, cwd)
        metadata: Optional additional metadata dict

    Example:
        >>> event = SessionStartEvent(
        ...     event_version="1.0",
        ...     event_id="550e8400-e29b-41d4-a716-446655440000",
        ...     component_name="mahavishnu",
        ...     shell_type="MahavishnuShell",
        ...     timestamp="2026-02-06T12:34:56.789Z",
        ...     pid=12345,
        ...     user=UserInfo(username="john", home="/home/john"),
        ...     hostname="server01",
        ...     environment=EnvironmentInfo(
        ...         python_version="3.13.0",
        ...         platform="Linux-6.5.0-x86_64",
        ...         cwd="/home/john/projects",
        ...     ),
        ... )
    """

    event_version: str = Field(
        ...,
        description="Event format version (currently '1.0')",
    )
    event_id: str = Field(
        ...,
        description="Unique event identifier (UUID v4 string)",
    )
    event_type: str = Field(
        default="session_start",
        description="Event type discriminator",
    )
    component_name: str = Field(
        ...,
        description="Component name (e.g., 'mahavishnu', 'session-buddy')",
    )
    shell_type: str = Field(
        ...,
        description="Shell class name (e.g., 'MahavishnuShell')",
    )
    timestamp: str = Field(
        ...,
        description="ISO 8601 timestamp in UTC",
    )
    pid: int = Field(
        ...,
        description="Process ID (1-4194304)",
        ge=1,
        le=4194304,
    )
    user: UserInfo = Field(
        ...,
        description="User information",
    )
    hostname: str = Field(
        ...,
        description="System hostname",
    )
    environment: EnvironmentInfo = Field(
        ...,
        description="Environment information",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional additional metadata",
    )

    @field_validator("event_id")
    @classmethod
    def validate_uuid(cls, v: str) -> str:
        """Validate that event_id is a valid UUID v4.

        Args:
            v: Event ID string to validate

        Returns:
            Validated event ID

        Raises:
            ValueError: If event_id is not a valid UUID
        """
        try:
            UUID(v, version=4)
        except ValueError as e:
            raise ValueError(f"Invalid UUID v4 format: {v}") from e
        return v

    @field_validator("event_version")
    @classmethod
    def validate_version(cls, v: str) -> str:
        """Validate that event_version is supported.

        Args:
            v: Event version string to validate

        Returns:
            Validated version

        Raises:
            ValueError: If version is not supported
        """
        if v != "1.0":
            raise ValueError(f"Unsupported event version: {v} (expected '1.0')")
        return v

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v: str) -> str:
        """Validate that event_type matches model.

        Args:
            v: Event type string to validate

        Returns:
            Validated event type

        Raises:
            ValueError: If event_type is incorrect
        """
        if v != "session_start":
            raise ValueError(f"Invalid event_type for SessionStartEvent: {v}")
        return v

    @field_validator("component_name")
    @classmethod
    def validate_component_name(cls, v: str) -> str:
        """Validate component name format (alphanumeric, underscore, hyphen).

        Args:
            v: Component name to validate

        Returns:
            Validated component name

        Raises:
            ValueError: If component name contains invalid characters
        """
        pattern = r"^[a-zA-Z0-9_-]+$"
        if not re.match(pattern, v):
            raise ValueError(
                f"Invalid component_name '{v}': must match pattern {pattern}"
            )
        return v

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v: str) -> str:
        """Validate ISO 8601 timestamp format.

        Args:
            v: Timestamp string to validate

        Returns:
            Validated timestamp

        Raises:
            ValueError: If timestamp is not valid ISO 8601
        """
        # Check for 'T' separator to ensure time component is present
        if "T" not in v:
            raise ValueError(
                f"Invalid ISO 8601 timestamp: {v} (missing time component, expected format: 2026-02-06T12:34:56.789Z)"
            )

        try:
            # Try parsing with timezone
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError as e:
            raise ValueError(
                f"Invalid ISO 8601 timestamp: {v} (expected format: 2026-02-06T12:34:56.789Z)"
            ) from e
        return v

    @model_validator(mode="after")
    def validate_consistency(self) -> SessionStartEvent:
        """Validate cross-field consistency.

        Returns:
            Validated SessionStartEvent instance

        Raises:
            ValueError: If fields are inconsistent
        """
        # Ensure event_type matches model
        if self.event_type != "session_start":
            raise ValueError(
                f"event_type must be 'session_start' for SessionStartEvent, got '{self.event_type}'"
            )
        return self


class SessionEndEvent(BaseModel):
    """Session end event emitted by admin shells.

    This event is emitted when an admin shell exits. It references the
    session_id from the initial SessionStartEvent to link the lifecycle.

    Attributes:
        event_type: Event type discriminator (must be "session_end")
        session_id: Session ID from SessionStartEvent response
        timestamp: ISO 8601 timestamp in UTC
        metadata: Optional additional metadata dict

    Example:
        >>> event = SessionEndEvent(
        ...     session_id="sess_abc123",
        ...     timestamp="2026-02-06T13:45:67.890Z",
        ...     metadata={"exit_reason": "user_exit"},
        ... )
    """

    event_type: str = Field(
        default="session_end",
        description="Event type discriminator",
    )
    session_id: str = Field(
        ...,
        description="Session ID from SessionStartEvent response",
    )
    timestamp: str = Field(
        ...,
        description="ISO 8601 timestamp in UTC",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional additional metadata",
    )

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v: str) -> str:
        """Validate that event_type matches model.

        Args:
            v: Event type string to validate

        Returns:
            Validated event type

        Raises:
            ValueError: If event_type is incorrect
        """
        if v != "session_end":
            raise ValueError(f"Invalid event_type for SessionEndEvent: {v}")
        return v

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v: str) -> str:
        """Validate ISO 8601 timestamp format.

        Args:
            v: Timestamp string to validate

        Returns:
            Validated timestamp

        Raises:
            ValueError: If timestamp is not valid ISO 8601
        """
        # Check for 'T' separator to ensure time component is present
        if "T" not in v:
            raise ValueError(
                f"Invalid ISO 8601 timestamp: {v} (missing time component, expected format: 2026-02-06T12:34:56.789Z)"
            )

        try:
            # Try parsing with timezone
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError as e:
            raise ValueError(
                f"Invalid ISO 8601 timestamp: {v} (expected format: 2026-02-06T12:34:56.789Z)"
            ) from e
        return v


# JSON Schema exports for external validation
def get_session_start_event_schema() -> dict[str, Any]:
    """Get JSON Schema for SessionStartEvent validation.

    This schema can be used for external validation or documentation.

    Returns:
        JSON Schema dictionary

    Example:
        >>> schema = get_session_start_event_schema()
        >>> # Use with jsonschema library or other validators
    """
    return SessionStartEvent.model_json_schema()


def get_session_end_event_schema() -> dict[str, Any]:
    """Get JSON Schema for SessionEndEvent validation.

    This schema can be used for external validation or documentation.

    Returns:
        JSON Schema dictionary

    Example:
        >>> schema = get_session_end_event_schema()
        >>> # Use with jsonschema library or other validators
    """
    return SessionEndEvent.model_json_schema()
