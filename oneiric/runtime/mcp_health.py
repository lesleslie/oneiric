from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from oneiric.core.logging import get_logger

logger = get_logger(__name__)


class HealthStatus(Enum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    DEGRADED = "degraded"
    STARTING = "starting"
    SHUTTING_DOWN = "shutting_down"


@dataclass
class ComponentHealth:
    name: str
    status: HealthStatus
    details: dict[str, Any] = None
    error: str | None = None

    def __init__(
        self,
        name: str,
        status: HealthStatus,
        details: dict[str, Any] = None,
        error: str | None = None,
    ):
        self.name = name
        self.status = status
        self.details = {} if details is None else details
        self.error = error

    def to_dict(self) -> dict[str, Any]:
        result = {
            "name": self.name,
            "status": self.status.value,
            "details": self.details,
        }
        if self.error:
            result["error"] = self.error
        return result


@dataclass
class HealthCheckResponse:
    status: HealthStatus
    components: list[ComponentHealth]
    timestamp: str
    version: str = "1.0"
    metadata: dict[str, Any] = None

    def __init__(
        self, status: HealthStatus, components: list[ComponentHealth], timestamp: str
    ):
        self.status = status
        self.components = components
        self.timestamp = timestamp
        self.metadata = {}

    def add_metadata(self, key: str, value: Any) -> None:
        self.metadata[key] = value

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "components": [comp.to_dict() for comp in self.components],
            "timestamp": self.timestamp,
            "version": self.version,
            "metadata": self.metadata,
        }

    def is_healthy(self) -> bool:
        return self.status == HealthStatus.HEALTHY

    def has_unhealthy_components(self) -> bool:
        return any(
            comp.status in (HealthStatus.UNHEALTHY, HealthStatus.DEGRADED)
            for comp in self.components
        )


class HealthMonitor:
    def __init__(self, server_name: str = "mcp-server"):
        self.server_name = server_name

    def create_health_response(
        self, components: list[ComponentHealth], timestamp: str | None = None
    ) -> HealthCheckResponse:
        if timestamp is None:
            timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ")

        status = self._determine_overall_status(components)

        return HealthCheckResponse(
            status=status, components=components, timestamp=timestamp
        )

    def _determine_overall_status(
        self, components: list[ComponentHealth]
    ) -> HealthStatus:
        if any(comp.status == HealthStatus.UNHEALTHY for comp in components):
            return HealthStatus.UNHEALTHY

        if any(comp.status == HealthStatus.DEGRADED for comp in components):
            return HealthStatus.DEGRADED

        return HealthStatus.HEALTHY

    def create_component_health(
        self,
        name: str,
        status: HealthStatus,
        details: dict[str, Any] = None,
        error: str | None = None,
    ) -> ComponentHealth:
        return ComponentHealth(name, status, details, error)


__all__ = ["HealthStatus", "ComponentHealth", "HealthCheckResponse", "HealthMonitor"]
