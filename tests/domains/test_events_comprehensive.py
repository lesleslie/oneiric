"""Comprehensive tests for oneiric.domains.events.EventBridge."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from oneiric.core.config import LayerSettings
from oneiric.core.lifecycle import LifecycleError, LifecycleManager
from oneiric.core.resolution import Candidate, CandidateSource, Resolver
from oneiric.domains.events import EventBridge
from oneiric.runtime.events import (
    EventDispatcher,
    EventEnvelope,
    HandlerResult,
    create_event_envelope,
)

# ---------------------------------------------------------------------------
# Shared factories
# ---------------------------------------------------------------------------


def _make_resolver() -> Resolver:
    return Resolver()


def _make_lifecycle(resolver: Resolver, tmp_path) -> LifecycleManager:
    snapshot = tmp_path / "lifecycle_status.json"
    return LifecycleManager(resolver, status_snapshot_path=str(snapshot))


def _make_bridge(
    resolver: Resolver | None = None,
    lifecycle: LifecycleManager | None = None,
    settings: LayerSettings | None = None,
    *,
    telemetry: Any | None = None,
    tmp_path=None,
) -> EventBridge:
    if resolver is None:
        resolver = _make_resolver()
    if lifecycle is None:
        if tmp_path is None:
            lifecycle = LifecycleManager(resolver)
        else:
            lifecycle = _make_lifecycle(resolver, tmp_path)
    if settings is None:
        settings = LayerSettings()
    return EventBridge(
        resolver, lifecycle, settings, telemetry=telemetry
    )


class _RecordingHandler:
    """Async-callable satisfying EventHandlerProtocol.handle()."""

    def __init__(self, recorder: list[str]) -> None:
        self.recorder = recorder
        self.last_envelope: EventEnvelope | None = None

    async def handle(self, envelope: EventEnvelope) -> str:
        self.last_envelope = envelope
        self.recorder.append(envelope.topic)
        return f"handled:{envelope.topic}"


# ---------------------------------------------------------------------------
# EventBridgeInit
# ---------------------------------------------------------------------------


class TestEventBridgeInit:
    def test_domain_is_event(self) -> None:
        bridge = _make_bridge()
        assert bridge.domain == "event"

    def test_dispatcher_built_from_active_candidates(self) -> None:
        resolver = _make_resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = _make_bridge(resolver=resolver, lifecycle=lifecycle)
        recorder: list[str] = []
        resolver.register(
            Candidate(
                domain="event",
                key="evt-1",
                provider="demo",
                factory=lambda: _RecordingHandler(recorder),
                metadata={"topics": ["topic.a"]},
                source=CandidateSource.MANUAL,
            )
        )
        bridge.refresh_dispatcher()

        dispatcher = bridge.dispatcher()
        assert isinstance(dispatcher, EventDispatcher)
        assert len(dispatcher.handlers()) == 1
        assert dispatcher.handlers()[0].topics == ("topic.a",)

    def test_works_without_telemetry(self) -> None:
        bridge = _make_bridge()
        assert getattr(bridge, "_telemetry", None) is None

    def test_telemetry_optional_when_supplied(self) -> None:
        recorder_telemetry = MagicMock()
        bridge = _make_bridge(telemetry=recorder_telemetry)
        assert bridge._telemetry is recorder_telemetry

    def test_empty_resolver_yields_no_handlers(self) -> None:
        bridge = _make_bridge()
        assert bridge.dispatcher().handlers() == ()


# ---------------------------------------------------------------------------
# RefreshDispatcher
# ---------------------------------------------------------------------------


class TestRefreshDispatcher:
    def test_rebuilds_from_list_active(self) -> None:
        resolver = _make_resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = _make_bridge(resolver=resolver, lifecycle=lifecycle)
        assert bridge.dispatcher().handlers() == ()

        resolver.register(
            Candidate(
                domain="event",
                key="evt-a",
                provider="demo",
                factory=lambda: _RecordingHandler([]),
                metadata={"topics": ["topic.a"]},
                source=CandidateSource.MANUAL,
            )
        )
        bridge.refresh_dispatcher()
        assert len(bridge.dispatcher().handlers()) == 1

    def test_ignores_other_domains(self) -> None:
        resolver = _make_resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = _make_bridge(resolver=resolver, lifecycle=lifecycle)
        resolver.register(
            Candidate(
                domain="task",
                key="not-event",
                provider="demo",
                factory=lambda: _RecordingHandler([]),
                source=CandidateSource.MANUAL,
            )
        )
        bridge.refresh_dispatcher()
        assert bridge.dispatcher().handlers() == ()

    def test_topics_metadata_becomes_tuple(self) -> None:
        resolver = _make_resolver()
        bridge = _make_bridge(resolver=resolver)
        resolver.register(
            Candidate(
                domain="event",
                key="t-1",
                provider="demo",
                factory=lambda: _RecordingHandler([]),
                metadata={"topics": ["a", "b", "c"]},
                source=CandidateSource.MANUAL,
            )
        )
        bridge.refresh_dispatcher()
        handler = bridge.dispatcher().handlers()[0]
        assert handler.topics == ("a", "b", "c")
        assert isinstance(handler.topics, tuple)

    def test_topics_absent_means_none(self) -> None:
        resolver = _make_resolver()
        bridge = _make_bridge(resolver=resolver)
        resolver.register(
            Candidate(
                domain="event",
                key="t-2",
                provider="demo",
                factory=lambda: _RecordingHandler([]),
                source=CandidateSource.MANUAL,
            )
        )
        bridge.refresh_dispatcher()
        handler = bridge.dispatcher().handlers()[0]
        assert handler.topics is None

    def test_filters_parsed_from_list_of_dicts(self) -> None:
        resolver = _make_resolver()
        bridge = _make_bridge(resolver=resolver)
        resolver.register(
            Candidate(
                domain="event",
                key="f-1",
                provider="demo",
                factory=lambda: _RecordingHandler([]),
                metadata={
                    "filters": [
                        {"path": "payload.kind", "equals": "user"},
                        {"path": "headers.x", "any_of": [1, 2]},
                    ]
                },
                source=CandidateSource.MANUAL,
            )
        )
        bridge.refresh_dispatcher()
        handler = bridge.dispatcher().handlers()[0]
        assert len(handler.filters) == 2
        assert handler.filters[0].path == "payload.kind"
        assert handler.filters[0].equals == "user"
        assert handler.filters[1].path == "headers.x"
        assert handler.filters[1].any_of == (1, 2)

    def test_filters_none_yields_empty(self) -> None:
        resolver = _make_resolver()
        bridge = _make_bridge(resolver=resolver)
        resolver.register(
            Candidate(
                domain="event",
                key="f-2",
                provider="demo",
                factory=lambda: _RecordingHandler([]),
                source=CandidateSource.MANUAL,
            )
        )
        bridge.refresh_dispatcher()
        handler = bridge.dispatcher().handlers()[0]
        assert handler.filters == ()

    def test_filters_non_list_falls_back_to_empty(self) -> None:
        resolver = _make_resolver()
        bridge = _make_bridge(resolver=resolver)
        resolver.register(
            Candidate(
                domain="event",
                key="f-3",
                provider="demo",
                factory=lambda: _RecordingHandler([]),
                metadata={"filters": "not-a-list"},
                source=CandidateSource.MANUAL,
            )
        )
        bridge.refresh_dispatcher()
        handler = bridge.dispatcher().handlers()[0]
        assert handler.filters == ()

    def test_event_priority_taken_from_metadata(self) -> None:
        resolver = _make_resolver()
        bridge = _make_bridge(resolver=resolver)
        resolver.register(
            Candidate(
                domain="event",
                key="p-1",
                provider="demo",
                factory=lambda: _RecordingHandler([]),
                metadata={"event_priority": 42},
                source=CandidateSource.MANUAL,
            )
        )
        bridge.refresh_dispatcher()
        handler = bridge.dispatcher().handlers()[0]
        assert handler.priority == 42

    def test_event_priority_falls_back_to_candidate_priority(self) -> None:
        resolver = _make_resolver()
        bridge = _make_bridge(resolver=resolver)
        resolver.register(
            Candidate(
                domain="event",
                key="p-2",
                provider="demo",
                factory=lambda: _RecordingHandler([]),
                priority=7,
                source=CandidateSource.MANUAL,
            )
        )
        bridge.refresh_dispatcher()
        handler = bridge.dispatcher().handlers()[0]
        assert handler.priority == 7

    def test_fanout_policy_defaults_to_broadcast(self) -> None:
        resolver = _make_resolver()
        bridge = _make_bridge(resolver=resolver)
        resolver.register(
            Candidate(
                domain="event",
                key="fan-1",
                provider="demo",
                factory=lambda: _RecordingHandler([]),
                source=CandidateSource.MANUAL,
            )
        )
        bridge.refresh_dispatcher()
        handler = bridge.dispatcher().handlers()[0]
        assert handler.fanout_policy == "broadcast"

    def test_fanout_policy_propagated_when_set(self) -> None:
        resolver = _make_resolver()
        bridge = _make_bridge(resolver=resolver)
        resolver.register(
            Candidate(
                domain="event",
                key="fan-2",
                provider="demo",
                factory=lambda: _RecordingHandler([]),
                metadata={"fanout_policy": "exclusive"},
                source=CandidateSource.MANUAL,
            )
        )
        bridge.refresh_dispatcher()
        handler = bridge.dispatcher().handlers()[0]
        assert handler.fanout_policy == "exclusive"

    def test_max_concurrency_default_one(self) -> None:
        resolver = _make_resolver()
        bridge = _make_bridge(resolver=resolver)
        resolver.register(
            Candidate(
                domain="event",
                key="mc-1",
                provider="demo",
                factory=lambda: _RecordingHandler([]),
                source=CandidateSource.MANUAL,
            )
        )
        bridge.refresh_dispatcher()
        handler = bridge.dispatcher().handlers()[0]
        assert handler.max_concurrency == 1

    def test_max_concurrency_propagated(self) -> None:
        resolver = _make_resolver()
        bridge = _make_bridge(resolver=resolver)
        resolver.register(
            Candidate(
                domain="event",
                key="mc-2",
                provider="demo",
                factory=lambda: _RecordingHandler([]),
                metadata={"max_concurrency": 8},
                source=CandidateSource.MANUAL,
            )
        )
        bridge.refresh_dispatcher()
        handler = bridge.dispatcher().handlers()[0]
        assert handler.max_concurrency == 8

    def test_handler_name_includes_key_and_provider(self) -> None:
        resolver = _make_resolver()
        bridge = _make_bridge(resolver=resolver)
        resolver.register(
            Candidate(
                domain="event",
                key="named",
                provider="remote",
                factory=lambda: _RecordingHandler([]),
                source=CandidateSource.MANUAL,
            )
        )
        bridge.refresh_dispatcher()
        handler = bridge.dispatcher().handlers()[0]
        assert handler.name == "named:remote"

    def test_handler_name_uses_auto_when_provider_missing(self) -> None:
        resolver = _make_resolver()
        bridge = _make_bridge(resolver=resolver)
        resolver.register(
            Candidate(
                domain="event",
                key="auto-named",
                factory=lambda: _RecordingHandler([]),
                source=CandidateSource.MANUAL,
            )
        )
        bridge.refresh_dispatcher()
        handler = bridge.dispatcher().handlers()[0]
        assert handler.name == "auto-named:auto"

    def test_retry_policy_propagated(self) -> None:
        resolver = _make_resolver()
        bridge = _make_bridge(resolver=resolver)
        retry = {"attempts": 3, "base_delay": 0.01}
        resolver.register(
            Candidate(
                domain="event",
                key="rp-1",
                provider="demo",
                factory=lambda: _RecordingHandler([]),
                metadata={"retry_policy": retry},
                source=CandidateSource.MANUAL,
            )
        )
        bridge.refresh_dispatcher()
        handler = bridge.dispatcher().handlers()[0]
        assert handler.retry_policy == retry


# ---------------------------------------------------------------------------
# Emit
# ---------------------------------------------------------------------------


class TestEmit:
    async def test_returns_list_of_handler_results(self) -> None:
        resolver = _make_resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = _make_bridge(resolver=resolver, lifecycle=lifecycle)
        recorder: list[str] = []
        resolver.register(
            Candidate(
                domain="event",
                key="evt-1",
                provider="demo",
                factory=lambda: _RecordingHandler(recorder),
                metadata={"topics": ["user.created"]},
                source=CandidateSource.MANUAL,
            )
        )
        bridge.refresh_dispatcher()

        results = await bridge.emit("user.created", {"user_id": 1})
        assert isinstance(results, list)
        assert len(results) == 1
        assert isinstance(results[0], HandlerResult)
        assert results[0].success is True
        assert results[0].handler == "evt-1:demo"

    async def test_envelope_source_is_event_bridge_qualname(self) -> None:
        resolver = _make_resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = _make_bridge(resolver=resolver, lifecycle=lifecycle)
        recorder: list[str] = []
        handler = _RecordingHandler(recorder)
        resolver.register(
            Candidate(
                domain="event",
                key="evt-1",
                provider="demo",
                factory=lambda: handler,
                metadata={"topics": ["user.created"]},
                source=CandidateSource.MANUAL,
            )
        )
        bridge.refresh_dispatcher()

        await bridge.emit("user.created", {"user_id": 1})
        assert isinstance(handler.recorder, list)
        envelope: EventEnvelope = handler.last_envelope  # type: ignore[attr-defined]
        assert envelope.headers["source"] == "oneiric.domains.events.EventBridge"

    async def test_custom_headers_merged_without_clobbering_source(self) -> None:
        resolver = _make_resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = _make_bridge(resolver=resolver, lifecycle=lifecycle)
        captured: list[EventEnvelope] = []
        handler = _CapturingHandler(captured)
        resolver.register(
            Candidate(
                domain="event",
                key="hdr-1",
                provider="demo",
                factory=lambda: handler,
                metadata={"topics": ["topic.h"]},
                source=CandidateSource.MANUAL,
            )
        )
        bridge.refresh_dispatcher()

        await bridge.emit(
            "topic.h",
            {"k": "v"},
            headers={"trace_id": "abc-123", "custom": True},
        )
        envelope = captured[0]
        assert envelope.headers["source"] == "oneiric.domains.events.EventBridge"
        assert envelope.headers["trace_id"] == "abc-123"
        assert envelope.headers["custom"] is True

    async def test_telemetry_recorder_invoked(self) -> None:
        resolver = _make_resolver()
        lifecycle = LifecycleManager(resolver)
        recorder: list[str] = []
        resolver.register(
            Candidate(
                domain="event",
                key="evt-1",
                provider="demo",
                factory=lambda: _RecordingHandler(recorder),
                metadata={"topics": ["t.t"]},
                source=CandidateSource.MANUAL,
            )
        )
        bridge = _make_bridge(
            resolver=resolver, lifecycle=lifecycle, telemetry=MagicMock()
        )
        bridge.refresh_dispatcher()

        results = await bridge.emit("t.t", {"x": 1})
        bridge._telemetry.record_event_dispatch.assert_called_once_with(  # type: ignore[union-attr]
            "t.t", results
        )

    async def test_no_telemetry_still_dispatches(self) -> None:
        resolver = _make_resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = _make_bridge(resolver=resolver, lifecycle=lifecycle)
        recorder: list[str] = []
        resolver.register(
            Candidate(
                domain="event",
                key="evt-1",
                provider="demo",
                factory=lambda: _RecordingHandler(recorder),
                metadata={"topics": ["t.n"]},
                source=CandidateSource.MANUAL,
            )
        )
        bridge.refresh_dispatcher()

        results = await bridge.emit("t.n", {"x": 1})
        assert len(results) == 1
        assert recorder == ["t.n"]

    async def test_no_matching_handlers_returns_empty(self) -> None:
        resolver = _make_resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = _make_bridge(resolver=resolver, lifecycle=lifecycle)
        recorder: list[str] = []
        resolver.register(
            Candidate(
                domain="event",
                key="evt-1",
                provider="demo",
                factory=lambda: _RecordingHandler(recorder),
                metadata={"topics": ["user.created"]},
                source=CandidateSource.MANUAL,
            )
        )
        bridge.refresh_dispatcher()

        results = await bridge.emit("order.shipped", {"order_id": 1})
        assert results == []
        assert recorder == []

    async def test_single_matching_handler_returns_one(self) -> None:
        resolver = _make_resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = _make_bridge(resolver=resolver, lifecycle=lifecycle)
        recorder: list[str] = []
        resolver.register(
            Candidate(
                domain="event",
                key="evt-1",
                provider="demo",
                factory=lambda: _RecordingHandler(recorder),
                metadata={"topics": ["user.created"]},
                source=CandidateSource.MANUAL,
            )
        )
        bridge.refresh_dispatcher()

        results = await bridge.emit("user.created", {"user_id": 1})
        assert len(results) == 1
        assert recorder == ["user.created"]


# ---------------------------------------------------------------------------
# UpdateSettings
# ---------------------------------------------------------------------------


class TestUpdateSettings:
    def test_super_call_replaces_settings(self) -> None:
        resolver = _make_resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = _make_bridge(resolver=resolver, lifecycle=lifecycle)
        new_settings = LayerSettings(options={"queue_category": "x"})
        bridge.update_settings(new_settings)
        assert bridge.settings is new_settings

    def test_dispatcher_refreshed_after_update(self) -> None:
        resolver = _make_resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = _make_bridge(resolver=resolver, lifecycle=lifecycle)
        first_dispatcher = bridge.dispatcher()
        new_settings = LayerSettings()
        bridge.update_settings(new_settings)
        assert bridge.dispatcher() is not first_dispatcher

    def test_handlers_reflect_new_candidate_set(self) -> None:
        resolver = _make_resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = _make_bridge(resolver=resolver, lifecycle=lifecycle)
        assert bridge.dispatcher().handlers() == ()

        new_settings = LayerSettings()
        resolver.register(
            Candidate(
                domain="event",
                key="evt-new",
                provider="demo",
                factory=lambda: _RecordingHandler([]),
                source=CandidateSource.MANUAL,
            )
        )
        bridge.update_settings(new_settings)
        assert len(bridge.dispatcher().handlers()) == 1


# ---------------------------------------------------------------------------
# HandlerSnapshot
# ---------------------------------------------------------------------------


class TestHandlerSnapshot:
    def test_one_entry_per_handler(self) -> None:
        resolver = _make_resolver()
        bridge = _make_bridge(resolver=resolver)
        for i in range(3):
            resolver.register(
                Candidate(
                    domain="event",
                    key=f"h-{i}",
                    provider="demo",
                    factory=lambda i=i: _RecordingHandler([]),
                    source=CandidateSource.MANUAL,
                )
            )
        bridge.refresh_dispatcher()
        snapshot = bridge.handler_snapshot()
        assert len(snapshot) == 3

    def test_entry_keys_present(self) -> None:
        resolver = _make_resolver()
        bridge = _make_bridge(resolver=resolver)
        resolver.register(
            Candidate(
                domain="event",
                key="key-1",
                provider="demo",
                factory=lambda: _RecordingHandler([]),
                metadata={"topics": ["t.a"]},
                source=CandidateSource.MANUAL,
            )
        )
        bridge.refresh_dispatcher()
        entry = bridge.handler_snapshot()[0]
        for key in (
            "name",
            "topics",
            "max_concurrency",
            "priority",
            "fanout_policy",
            "retry_policy",
            "filters",
        ):
            assert key in entry

    def test_snapshot_filter_equals_normalized_to_none(self) -> None:
        resolver = _make_resolver()
        bridge = _make_bridge(resolver=resolver)
        resolver.register(
            Candidate(
                domain="event",
                key="filt-1",
                provider="demo",
                factory=lambda: _RecordingHandler([]),
                metadata={"filters": [{"path": "payload.kind"}]},
                source=CandidateSource.MANUAL,
            )
        )
        bridge.refresh_dispatcher()
        entry = bridge.handler_snapshot()[0]
        assert entry["filters"][0]["path"] == "payload.kind"
        assert entry["filters"][0]["equals"] is None
        assert entry["filters"][0]["any_of"] is None
        assert entry["filters"][0]["exists"] is None

    def test_snapshot_filter_preserves_explicit_equals(self) -> None:
        resolver = _make_resolver()
        bridge = _make_bridge(resolver=resolver)
        resolver.register(
            Candidate(
                domain="event",
                key="filt-2",
                provider="demo",
                factory=lambda: _RecordingHandler([]),
                metadata={"filters": [{"path": "payload.kind", "equals": "x"}]},
                source=CandidateSource.MANUAL,
            )
        )
        bridge.refresh_dispatcher()
        entry = bridge.handler_snapshot()[0]
        assert entry["filters"][0]["equals"] == "x"

    def test_snapshot_topics_serialized_as_list(self) -> None:
        resolver = _make_resolver()
        bridge = _make_bridge(resolver=resolver)
        resolver.register(
            Candidate(
                domain="event",
                key="top-1",
                provider="demo",
                factory=lambda: _RecordingHandler([]),
                metadata={"topics": ["a", "b"]},
                source=CandidateSource.MANUAL,
            )
        )
        bridge.refresh_dispatcher()
        entry = bridge.handler_snapshot()[0]
        assert entry["topics"] == ["a", "b"]
        assert isinstance(entry["topics"], list)

    def test_snapshot_retry_policy_default_empty_dict(self) -> None:
        resolver = _make_resolver()
        bridge = _make_bridge(resolver=resolver)
        resolver.register(
            Candidate(
                domain="event",
                key="rp-1",
                provider="demo",
                factory=lambda: _RecordingHandler([]),
                source=CandidateSource.MANUAL,
            )
        )
        bridge.refresh_dispatcher()
        entry = bridge.handler_snapshot()[0]
        assert entry["retry_policy"] == {}


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


class TestDispatcherGetter:
    def test_returns_current_dispatcher(self) -> None:
        bridge = _make_bridge()
        result = bridge.dispatcher()
        assert isinstance(result, EventDispatcher)

    def test_same_instance_until_refreshed(self) -> None:
        bridge = _make_bridge()
        first = bridge.dispatcher()
        second = bridge.dispatcher()
        assert first is second

    def test_refresh_yields_new_dispatcher(self) -> None:
        bridge = _make_bridge()
        first = bridge.dispatcher()
        bridge.refresh_dispatcher()
        second = bridge.dispatcher()
        assert first is not second


# ---------------------------------------------------------------------------
# BuildHandlerMissingHandle
# ---------------------------------------------------------------------------


class TestBuildHandlerMissingHandle:
    async def test_handler_built_even_without_handle_method(self) -> None:
        resolver = _make_resolver()
        bridge = _make_bridge(resolver=resolver)
        candidate = Candidate(
            domain="event",
            key="broken",
            provider="demo",
            factory=lambda: object(),
            source=CandidateSource.MANUAL,
            metadata={"topics": ["t.broken"]},
        )
        handler = bridge._build_handler(candidate)
        assert handler is not None

    async def test_dispatch_surfaces_lifecycle_error(self) -> None:
        resolver = _make_resolver()
        bridge = _make_bridge(resolver=resolver)
        candidate = Candidate(
            domain="event",
            key="broken",
            provider="demo",
            factory=lambda: object(),
            source=CandidateSource.MANUAL,
            metadata={"topics": ["t.broken"]},
        )
        handler = bridge._build_handler(candidate)
        assert handler is not None

        bridge.use = AsyncMock(  # type: ignore[method-assign]
            return_value=SimpleNamespace(instance=object())
        )
        with pytest.raises(LifecycleError, match="missing-handle-method"):
            await handler.callback(
                create_event_envelope("t.broken", {}, source="test")
            )

    async def test_emit_with_only_missing_handle_handler_returns_failure_result(
        self,
    ) -> None:
        resolver = _make_resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = _make_bridge(resolver=resolver, lifecycle=lifecycle)
        candidate = Candidate(
            domain="event",
            key="broken",
            provider="demo",
            factory=lambda: object(),
            source=CandidateSource.MANUAL,
            metadata={"topics": ["t.broken"]},
        )
        resolver.register(candidate)
        bridge.refresh_dispatcher()

        bridge.use = AsyncMock(  # type: ignore[method-assign]
            return_value=SimpleNamespace(instance=object())
        )
        results = await bridge.emit("t.broken", {"k": "v"})
        assert len(results) == 1
        assert results[0].success is False
        assert "missing-handle-method" in (results[0].error or "")


# ---------------------------------------------------------------------------
# Integration scenarios
# ---------------------------------------------------------------------------


class TestIntegrationScenarios:
    async def test_registered_factory_invoked_on_emit(self) -> None:
        resolver = _make_resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = _make_bridge(resolver=resolver, lifecycle=lifecycle)
        recorder: list[str] = []
        resolver.register(
            Candidate(
                domain="event",
                key="user-handler",
                provider="remote",
                factory=lambda: _RecordingHandler(recorder),
                metadata={"topics": ["user.created"]},
                source=CandidateSource.MANUAL,
            )
        )
        bridge.refresh_dispatcher()

        results = await bridge.emit("user.created", {"user_id": 7})
        assert recorder == ["user.created"]
        assert len(results) == 1
        assert results[0].success is True

    async def test_dummy_event_handler_fixture(self, dummy_event_handler) -> None:
        bridge = _make_bridge()
        # Confirm fixture satisfies the EventHandlerProtocol surface
        assert hasattr(dummy_event_handler, "handle")
        assert callable(dummy_event_handler.handle)

    async def test_filter_rejects_payload_but_other_handlers_still_run(self) -> None:
        resolver = _make_resolver()
        lifecycle = LifecycleManager(resolver)
        bridge = _make_bridge(resolver=resolver, lifecycle=lifecycle)
        recorder: list[str] = []
        resolver.register(
            Candidate(
                domain="event",
                key="filt-only",
                provider="demo",
                factory=lambda: _RecordingHandler(recorder),
                metadata={
                    "topics": ["topic.f"],
                    "filters": [{"path": "payload.kind", "equals": "match"}],
                },
                source=CandidateSource.MANUAL,
            )
        )
        resolver.register(
            Candidate(
                domain="event",
                key="unfiltered",
                provider="demo",
                factory=lambda: _RecordingHandler(recorder),
                metadata={"topics": ["topic.f"]},
                source=CandidateSource.MANUAL,
            )
        )
        bridge.refresh_dispatcher()

        results = await bridge.emit("topic.f", {"kind": "match"})
        assert len(results) == 2
        assert sorted(recorder) == ["topic.f", "topic.f"]

        recorder.clear()
        results = await bridge.emit("topic.f", {"kind": "mismatch"})
        assert len(results) == 1
        assert recorder == ["topic.f"]


# ---------------------------------------------------------------------------
# Helpers used above
# ---------------------------------------------------------------------------


class _CapturingHandler:
    """Event handler that records the envelopes it received."""

    def __init__(self, captured: list[EventEnvelope]) -> None:
        self.captured = captured

    async def handle(self, envelope: EventEnvelope) -> None:
        self.captured.append(envelope)
