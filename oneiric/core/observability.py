"""Observability utilities."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Span, Tracer
from pydantic import BaseModel, Field

from .logging import get_logger, scoped_log_context


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


def inject_trace_context(headers: dict[str, str]) -> dict[str, str]:
    try:  # pragma: no cover - depends on opentelemetry SDK extras
        from opentelemetry.propagate import inject
    except Exception:
        return headers
    inject(headers)
    return headers


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
    log_context = {
        "domain": event.domain,
        "key": event.key,
        "provider": event.provider,
        "decision": event.decision,
    }
    with observed_span(
        "resolver.decision",
        component=f"resolver.{event.domain}",
        attributes=event.as_attributes(),
        log_context=log_context,
    ) as span:
        _logger.debug(
            "resolver-decision",
            domain=event.domain,
            key=event.key,
            provider=event.provider,
            decision=event.decision,
            details=event.details,
        )
        yield span


@contextmanager
def observed_span(
    name: str,
    *,
    component: str | None = None,
    attributes: Mapping[str, Any] | None = None,
    log_context: Mapping[str, Any] | None = None,
) -> Iterator[Span]:
    tracer = get_tracer(component)
    context_scope = scoped_log_context(**log_context) if log_context else nullcontext()
    with context_scope:
        with tracer.start_as_current_span(name) as span:
            if attributes:
                span.set_attributes(dict(attributes))
            yield span
