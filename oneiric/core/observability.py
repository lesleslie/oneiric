"""Observability utilities."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Span, Tracer
from pydantic import BaseModel, Field

from .logging import get_logger


class ObservabilityConfig(BaseModel):
    """Declarative configuration for tracing/metrics hooks."""

    service_name: str = Field(default="oneiric")
    instrumentation_scope: str = Field(default="oneiric.core")


_config = ObservabilityConfig()
_logger = get_logger("observability")


def configure_observability(config: ObservabilityConfig | None = None) -> None:
    global _config
    _config = config or ObservabilityConfig()


def get_tracer(component: str | None = None) -> Tracer:
    scope = component or _config.instrumentation_scope
    return trace.get_tracer(scope)


@dataclass
class DecisionEvent:
    domain: str
    key: str
    provider: str | None
    decision: str
    details: Mapping[str, Any]

    def as_attributes(self) -> dict[str, Any]:
        attrs = {
            "domain": self.domain,
            "key": self.key,
            "provider": self.provider or "unknown",
            "decision": self.decision,
        }
        attrs.update(self.details)
        return attrs


@contextmanager
def traced_decision(event: DecisionEvent) -> Iterator[Span]:
    tracer = get_tracer(f"resolver.{event.domain}")
    with tracer.start_as_current_span("resolver.decision") as span:
        span.set_attributes(event.as_attributes())
        _logger.debug(
            "resolver-decision",
            domain=event.domain,
            key=event.key,
            provider=event.provider,
            decision=event.decision,
            details=event.details,
        )
        yield span
