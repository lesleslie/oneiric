"""Lightweight event dispatcher prototype for orchestration parity work."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import anyio
import msgspec

from oneiric.core.logging import get_logger
from oneiric.core.observability import observed_span
from oneiric.core.resiliency import run_with_retry
from oneiric.runtime.metrics import record_event_handler_metrics


class EventEnvelope(msgspec.Struct):
    """Structured event payload used by the dispatcher prototype."""

    topic: str
    payload: dict[str, Any]
    headers: dict[str, Any] = {}


EventHandlerCallable = Callable[[EventEnvelope], Awaitable[Any]]

_UNSET = object()


def _resolve_filter_path(envelope: EventEnvelope, path: str) -> Any:
    """Resolve dotted path within envelope topic/payload/headers."""

    if path == "topic":
        return envelope.topic
    if path.startswith("payload."):
        target: Any = envelope.payload
        attr_path = path.split(".", 1)[1]
    elif path.startswith("headers."):
        target = envelope.headers
        attr_path = path.split(".", 1)[1]
    else:
        target = envelope.payload
        attr_path = path
    for segment in attr_path.split("."):
        if isinstance(target, Mapping) and segment in target:
            target = target[segment]
        else:
            return None
    return target


@dataclass(slots=True)
class EventFilter:
    """Filter descriptor applied to envelope fields."""

    path: str
    equals: Any = _UNSET
    any_of: Sequence[Any] | None = None
    exists: bool | None = None

    def matches(self, envelope: EventEnvelope) -> bool:
        value = _resolve_filter_path(envelope, self.path)
        if self.exists is True and value is None:
            return False
        if self.exists is False and value is not None:
            return False
        if self.equals is not _UNSET and value != self.equals:
            return False
        if self.any_of is not None and value not in self.any_of:
            return False
        return True


def parse_event_filters(
    entries: Iterable[Mapping[str, Any]] | None,
) -> tuple[EventFilter, ...]:
    """Convert raw metadata entries into EventFilter structs."""

    if not entries:
        return ()
    filters: list[EventFilter] = []
    for entry in entries:
        path = entry.get("path") or entry.get("field")
        if not path or not isinstance(path, str):
            continue
        equals = entry.get("equals", entry.get("value", _UNSET))
        any_of = entry.get("any_of") or entry.get("one_of") or entry.get("in")
        exists = entry.get("exists")
        if isinstance(any_of, Sequence) and not isinstance(any_of, (str, bytes)):
            any_seq = tuple(any_of)
        elif any_of is None:
            any_seq = None
        else:
            any_seq = (any_of,)
        filters.append(
            EventFilter(
                path=path,
                equals=equals,
                any_of=any_seq,
                exists=exists,
            )
        )
    return tuple(filters)


@dataclass(slots=True)
class EventHandler:
    """Metadata describing a registered event handler."""

    name: str
    callback: EventHandlerCallable
    topics: Sequence[str] | None = None
    max_concurrency: int = 1
    retry_policy: dict[str, Any] | None = None
    filters: Sequence[EventFilter] = ()
    priority: int = 0
    fanout_policy: str = "broadcast"

    def accepts(self, envelope: EventEnvelope) -> bool:
        if self.topics and envelope.topic not in self.topics:
            return False
        for event_filter in self.filters:
            if not event_filter.matches(envelope):
                return False
        return True


@dataclass(slots=True)
class HandlerResult:
    """Result object returned after invoking a handler."""

    handler: str
    success: bool
    duration: float
    value: Any = None
    error: str | None = None
    attempts: int = 1


class EventDispatcher:
    """Fan-out dispatcher that executes handlers concurrently via anyio."""

    def __init__(self, handlers: Iterable[EventHandler] | None = None) -> None:
        self._handlers: list[EventHandler] = sorted(
            list(handlers or []), key=lambda handler: handler.priority, reverse=True
        )
        self._logger = get_logger("runtime.event_dispatcher")

    def register(self, handler: EventHandler) -> None:
        self._handlers.append(handler)
        self._handlers.sort(key=lambda item: item.priority, reverse=True)

    def handlers(self) -> tuple[EventHandler, ...]:
        """Return snapshot of registered handlers."""

        return tuple(self._handlers)

    async def dispatch(self, envelope: EventEnvelope) -> list[HandlerResult]:
        """Dispatch an event to all interested handlers."""

        candidates = [
            handler for handler in self._handlers if handler.accepts(envelope)
        ]
        results: list[HandlerResult] = []
        if not candidates:
            return results
        exclusive = [
            handler for handler in candidates if handler.fanout_policy == "exclusive"
        ]
        if exclusive:
            candidates = exclusive[:1]

        async with anyio.create_task_group() as tg:
            for handler in candidates:
                tg.start_soon(self._run_handler, handler, envelope, results)

        return results

    async def _run_handler(
        self,
        handler: EventHandler,
        envelope: EventEnvelope,
        results: list[HandlerResult],
    ) -> None:
        start = time.perf_counter()
        attempts = 0
        policy = handler.retry_policy or {}
        max_attempts = int(policy.get("attempts") or policy.get("max_attempts") or 1)
        base_delay = float(
            policy.get("base_delay") or policy.get("initial_delay") or 0.0
        )
        max_delay = float(
            policy.get("max_delay") or policy.get("max_backoff") or base_delay
        )
        jitter = float(policy.get("jitter") or policy.get("backoff_jitter") or 0.25)
        max_attempts = max(max_attempts, 1)
        if max_delay < base_delay:
            max_delay = base_delay

        async def _execute():
            nonlocal attempts
            attempts += 1
            return await handler.callback(envelope)

        log_context = {
            "domain": "event",
            "key": handler.name,
            "event_topic": envelope.topic,
            "event_handler": handler.name,
        }
        span_attrs = {
            "oneiric.event.topic": envelope.topic,
            "oneiric.event.handler": handler.name,
            "oneiric.event.max_attempts": max_attempts,
        }
        with observed_span(
            "event.handler",
            component="runtime.events",
            attributes=span_attrs,
            log_context=log_context,
        ) as span:
            try:
                if max_attempts > 1:
                    value = await run_with_retry(
                        _execute,
                        attempts=max_attempts,
                        base_delay=base_delay,
                        max_delay=max_delay,
                        jitter=jitter,
                        adaptive_key=f"event:{handler.name}",
                        attributes={
                            "domain": "event",
                            "operation": "handler",
                            "handler": handler.name,
                            "topic": envelope.topic,
                        },
                    )
                else:
                    value = await _execute()
            except Exception as exc:  # pragma: no cover - protective log surface
                duration = time.perf_counter() - start
                attempts = max(attempts, 1)
                span.record_exception(exc)
                span.set_attributes(
                    {
                        "oneiric.event.success": False,
                        "oneiric.event.attempts": attempts,
                        "oneiric.event.duration_ms": duration * 1000.0,
                    }
                )
                results.append(
                    HandlerResult(
                        handler=handler.name,
                        success=False,
                        duration=duration,
                        error=str(exc),
                        attempts=attempts,
                    )
                )
                record_event_handler_metrics(
                    handler=handler.name,
                    topic=envelope.topic,
                    success=False,
                    duration_ms=duration * 1000.0,
                    attempts=attempts,
                )
                self._logger.warning(
                    "event-handler-error",
                    handler=handler.name,
                    topic=envelope.topic,
                    attempts=attempts,
                    duration_ms=duration * 1000.0,
                    error=str(exc),
                )
            else:
                duration = time.perf_counter() - start
                attempts = max(attempts, 1)
                span.set_attributes(
                    {
                        "oneiric.event.success": True,
                        "oneiric.event.attempts": attempts,
                        "oneiric.event.duration_ms": duration * 1000.0,
                    }
                )
                results.append(
                    HandlerResult(
                        handler=handler.name,
                        success=True,
                        duration=duration,
                        value=value,
                        attempts=attempts,
                    )
                )
                record_event_handler_metrics(
                    handler=handler.name,
                    topic=envelope.topic,
                    success=True,
                    duration_ms=duration * 1000.0,
                    attempts=attempts,
                )
                self._logger.info(
                    "event-handler-complete",
                    handler=handler.name,
                    topic=envelope.topic,
                    attempts=attempts,
                    duration_ms=duration * 1000.0,
                )
