"""Protocol interface for queue adapters used by workflows."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol


class QueueAdapterProtocol(Protocol):
    async def enqueue(self, payload: Mapping[str, Any]) -> str: ...
