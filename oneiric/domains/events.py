"""Event bridge hooking into the runtime dispatcher."""

from __future__ import annotations

from typing import Any, cast

from oneiric.core.config import LayerSettings
from oneiric.core.lifecycle import LifecycleError, LifecycleManager
from oneiric.core.resolution import Candidate, Resolver
from oneiric.runtime.activity import DomainActivityStore
from oneiric.runtime.events import (
    _UNSET,
    EventDispatcher,
    EventEnvelope,
    EventHandler,
    HandlerResult,
    parse_event_filters,
)
from oneiric.runtime.supervisor import ServiceSupervisor
from oneiric.runtime.telemetry import RuntimeTelemetryRecorder

from .base import DomainBridge
from .protocols import EventHandlerProtocol


class EventBridge(DomainBridge):
    """Domain bridge that wires resolver candidates into the event dispatcher."""

    def __init__(
        self,
        resolver: Resolver,
        lifecycle: LifecycleManager,
        settings: LayerSettings,
        activity_store: DomainActivityStore | None = None,
        supervisor: ServiceSupervisor | None = None,
        telemetry: RuntimeTelemetryRecorder | None = None,
    ) -> None:
        super().__init__(
            "event",
            resolver,
            lifecycle,
            settings,
            activity_store=activity_store,
            supervisor=supervisor,
        )
        self._dispatcher = EventDispatcher()
        self._telemetry = telemetry
        self.refresh_dispatcher()

    def update_settings(self, settings: LayerSettings) -> None:
        super().update_settings(settings)
        self.refresh_dispatcher()

    def refresh_dispatcher(self) -> None:
        """Rebuild dispatcher handlers from the resolver's current candidates."""

        handlers: list[EventHandler] = []
        for candidate in self.resolver.list_active(self.domain):
            handler = self._build_handler(candidate)
            if handler:
                handlers.append(handler)
        self._dispatcher = EventDispatcher(handlers)

    async def emit(
        self,
        topic: str,
        payload: dict[str, Any],
        headers: dict[str, Any] | None = None,
    ) -> list[HandlerResult]:
        """Dispatch an event to registered handlers."""

        envelope = EventEnvelope(topic=topic, payload=payload, headers=headers or {})
        results = await self._dispatcher.dispatch(envelope)
        if self._telemetry:
            self._telemetry.record_event_dispatch(topic, results)
        return results

    def handler_snapshot(self) -> list[dict[str, Any]]:
        """Return metadata describing registered event handlers."""

        snapshot: list[dict[str, Any]] = []
        for handler in self._dispatcher.handlers():
            filters: list[dict[str, Any]] = []
            for event_filter in handler.filters:
                equals_value = getattr(event_filter, "equals", None)
                if equals_value is _UNSET:
                    equals_value = None
                filters.append(
                    {
                        "path": event_filter.path,
                        "equals": equals_value,
                        "any_of": (
                            list(event_filter.any_of) if event_filter.any_of else None
                        ),
                        "exists": event_filter.exists,
                    }
                )
            snapshot.append(
                {
                    "name": handler.name,
                    "topics": list(handler.topics) if handler.topics else [],
                    "max_concurrency": handler.max_concurrency,
                    "priority": handler.priority,
                    "fanout_policy": handler.fanout_policy,
                    "retry_policy": handler.retry_policy or {},
                    "filters": filters,
                }
            )
        return snapshot

    def dispatcher(self) -> EventDispatcher:
        return self._dispatcher

    def _build_handler(self, candidate: Candidate) -> EventHandler | None:
        topics = candidate.metadata.get("topics")
        max_concurrency = candidate.metadata.get("max_concurrency", 1)
        filters = candidate.metadata.get("filters")
        event_priority = candidate.metadata.get("event_priority")
        fanout_policy = candidate.metadata.get("fanout_policy")

        async def _callback(envelope: EventEnvelope) -> Any:
            handle = await self.use(candidate.key, provider=candidate.provider)
            instance = cast(EventHandlerProtocol, handle.instance)
            handler = getattr(instance, "handle", None)
            if not callable(handler):
                raise LifecycleError(
                    f"event-handler-missing-handle-method ({candidate.key})"
                )
            return await handler(envelope)

        retry_policy = candidate.metadata.get("retry_policy")

        return EventHandler(
            name=f"{candidate.key}:{candidate.provider or 'auto'}",
            callback=_callback,
            topics=tuple(topics) if topics else None,
            max_concurrency=max_concurrency,
            retry_policy=retry_policy,
            filters=parse_event_filters(
                filters if isinstance(filters, (list, tuple)) else None
            ),
            priority=int(event_priority)
            if event_priority is not None
            else (candidate.priority or 0),
            fanout_policy=str(fanout_policy) if fanout_policy else "broadcast",
        )
