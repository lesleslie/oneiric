"""Protocol interfaces for resolver-backed domain handlers."""

from __future__ import annotations

from typing import Any, Protocol

from oneiric.runtime.events import EventEnvelope


class TaskHandlerProtocol(Protocol):
    async def run(self, payload: dict[str, Any] | None = None) -> Any: ...


class EventHandlerProtocol(Protocol):
    async def handle(self, envelope: EventEnvelope) -> Any: ...
