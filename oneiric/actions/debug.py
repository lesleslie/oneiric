"""Debug/console action kit."""

from __future__ import annotations

import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from oneiric.actions.metadata import ActionMetadata
from oneiric.actions.payloads import normalize_payload
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class DebugConsoleSettings(BaseModel):
    """Settings for the debug console action."""

    default_level: Literal["debug", "info", "warning", "error", "critical"] = Field(
        default="info",
        description="Default log level when payload omits 'level'.",
    )
    include_timestamp: bool = Field(
        default=True,
        description="Include ISO timestamp in emitted payload/log.",
    )
    prefix: str = Field(
        default="[debug]",
        description="Prefix written before the message when echoing output.",
    )
    echo: bool = Field(
        default=True,
        description="Echo records to stdout in addition to structlog output.",
    )
    scrub_fields: list[str] = Field(
        default_factory=lambda: ["secret", "token", "password", "key"],
        description="Fields scrubbed from nested details payloads.",
    )


class DebugConsoleAction:
    """Action kit that emits structured console/debug records."""

    metadata = ActionMetadata(
        key="debug.console",
        provider="builtin-debug-console",
        factory="oneiric.actions.debug:DebugConsoleAction",
        description="Console/debug helper that logs structured records and optionally echoes them",
        domains=["workflow", "task", "event"],
        capabilities=["console", "debug", "observe"],
        stack_level=20,
        priority=390,
        source=CandidateSource.LOCAL_PKG,
        owner="Platform Core",
        requires_secrets=False,
        side_effect_free=False,
        settings_model=DebugConsoleSettings,
    )

    _LEVELS: tuple[str, ...] = ("debug", "info", "warning", "error", "critical")

    def __init__(self, settings: DebugConsoleSettings | None = None) -> None:
        self._settings = settings or DebugConsoleSettings()
        self._logger = get_logger("action.debug.console")

    async def execute(self, payload: dict | None = None) -> dict:
        payload = normalize_payload(payload)
        message = payload.get("message", "")
        if not isinstance(message, str):
            raise LifecycleError("debug-console-message-invalid")
        details = payload.get("details", {})
        if details is None:
            details = {}
        if not isinstance(details, dict):
            raise LifecycleError("debug-console-details-invalid")
        level = (payload.get("level") or self._settings.default_level or "info").lower()
        if level not in self._LEVELS:
            level = "info"
        prefix = payload.get("prefix")
        if prefix is None:
            prefix = self._settings.prefix
        include_timestamp = payload.get("include_timestamp")
        if include_timestamp is None:
            include_timestamp = self._settings.include_timestamp
        echo = payload.get("echo")
        if echo is None:
            echo = self._settings.echo
        scrub_fields = self._merge_scrub_fields(payload.get("scrub_fields"))
        record: dict[str, Any] = {
            "message": message,
            "level": level,
            "prefix": prefix,
            "details": self._scrub(details, scrub_fields),
        }
        if include_timestamp:
            record["timestamp"] = datetime.now(UTC).isoformat()
        self._emit_log(level, record)
        if echo:
            self._echo(record)
        return {"status": "emitted"} | record

    def _emit_log(self, level: str, record: dict[str, Any]) -> None:
        method = getattr(self._logger, level, self._logger.info)
        method("debug-console", **record)

    def _echo(self, record: dict[str, Any]) -> None:
        prefix = record.get("prefix") or ""
        message = record.get("message", "")
        timestamp = record.get("timestamp")
        details = record.get("details") or {}
        parts = []
        if timestamp:
            parts.append(timestamp)
        if prefix:
            parts.append(prefix)
        parts.append(message)
        if details:
            parts.append(str(details))
        sys.stdout.write(" ".join(part for part in parts if part) + "\n")

    def _merge_scrub_fields(self, payload_value: Any) -> set[str]:
        scrub = set(self._settings.scrub_fields)
        if payload_value is None:
            return scrub
        if isinstance(payload_value, str):
            scrub.add(payload_value)
            return scrub
        if isinstance(payload_value, Iterable) and not isinstance(
            payload_value, (bytes, bytearray)
        ):
            scrub.update(str(item) for item in payload_value)
            return scrub
        raise LifecycleError("debug-console-scrub-invalid")

    def _scrub(self, value: Any, scrub_fields: set[str]) -> Any:
        if isinstance(value, dict):
            return {
                key: (
                    "***" if key in scrub_fields else self._scrub(inner, scrub_fields)
                )
                for key, inner in value.items()
            }
        if isinstance(value, list):
            return [self._scrub(item, scrub_fields) for item in value]
        return value
