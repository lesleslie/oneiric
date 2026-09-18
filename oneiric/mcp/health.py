"""Per-feed health state + aggregation for the oneiric FastMCP server.

Migrated from oneiric/http/routes/substrate.py. The shape and semantics
are unchanged; only the location moved.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass
class HealthFeedState:
    """Per-route health state used by the aggregated /health endpoint."""

    name: str
    entities_count: int = 0
    last_updated_timestamp: str | None = None
    errors_total: int = 0
    cycles_total: int = 0

    def record_success(self, entities_count: int) -> None:
        self.cycles_total += 1
        self.entities_count = entities_count
        self.last_updated_timestamp = datetime.now(UTC).isoformat()

    def record_error(self) -> None:
        self.cycles_total += 1
        self.errors_total += 1

    def is_healthy(self) -> bool:
        # Degraded if any errors recorded AND we've had cycles.
        if self.cycles_total == 0:
            return False
        return self.errors_total == 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "entities_count": self.entities_count,
            "last_updated_timestamp": self.last_updated_timestamp,
            "errors_total": self.errors_total,
            "cycles_total": self.cycles_total,
            "healthy": self.is_healthy(),
        }


def aggregate_health(
    feeds: dict[str, HealthFeedState],
) -> tuple[int, dict[str, Any]]:
    """Aggregate per-feed health into a single (status_code, body) tuple.

    200 when every feed is healthy; 503 when ANY feed is degraded.
    """
    healthy = all(feed.is_healthy() for feed in feeds.values())
    body: dict[str, Any] = {
        "component": "oneiric",
        "routes": {name: feed.as_dict() for name, feed in feeds.items()},
        "cycles_total": sum(feed.cycles_total for feed in feeds.values()),
        "errors_total": sum(feed.errors_total for feed in feeds.values()),
    }
    body["status"] = "healthy" if healthy else "degraded"
    return (200 if healthy else 503), body


__all__ = ["HealthFeedState", "aggregate_health"]
