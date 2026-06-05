"""Comprehensive tests for ``oneiric.domains.protocols``.

The module defines two ``typing.Protocol`` classes that are *shape-only* — they
describe the call surface of task and event handlers but carry no runtime
behavior. The tests below verify the contracts those protocols express and
confirm that concrete implementations (and duck-typed objects) honor them.

The protocols are *not* decorated with ``@runtime_checkable``; therefore
``isinstance`` checks against them would raise ``TypeError``. The tests below
rely on shape inspection (``hasattr`` + ``inspect.signature``) instead.
"""

from __future__ import annotations

import inspect
from typing import Any

from oneiric.domains.protocols import EventHandlerProtocol, TaskHandlerProtocol
from oneiric.runtime.events import EventEnvelope, create_event_envelope


def _has_async_method(obj: object, name: str) -> bool:
    """Return True iff ``obj`` exposes an async callable named ``name``."""
    attr = getattr(obj, name, None)
    return callable(attr) and inspect.iscoroutinefunction(attr)


def test_task_handler_protocol_defines_run() -> None:
    assert hasattr(TaskHandlerProtocol, "run")
    assert inspect.iscoroutinefunction(TaskHandlerProtocol.run)


def test_event_handler_protocol_defines_handle() -> None:
    assert hasattr(EventHandlerProtocol, "handle")
    assert inspect.iscoroutinefunction(EventHandlerProtocol.handle)


def test_dummy_classes_satisfy_protocols() -> None:
    class _TaskOK:
        async def run(self, payload: dict[str, Any] | None = None) -> str:
            return "ok"

    class _EventOK:
        async def handle(self, envelope: EventEnvelope) -> None:
            return None

    task = _TaskOK()
    event = _EventOK()
    assert _has_async_method(task, "run")
    assert _has_async_method(event, "handle")

    task_sig = inspect.signature(task.run)
    assert "payload" in task_sig.parameters
    assert task_sig.parameters["payload"].default is None

    event_sig = inspect.signature(event.handle)
    assert "envelope" in event_sig.parameters


def test_classes_missing_methods_do_not_satisfy_protocol() -> None:
    class _TaskMissing:
        async def execute(self) -> str:
            return "wrong-name"

    class _EventMissing:
        async def process(self, envelope: EventEnvelope) -> None:
            return None

    assert not _has_async_method(_TaskMissing(), "run")
    assert not _has_async_method(_EventMissing(), "handle")


async def test_task_handler_with_payload_returns_value() -> None:
    class _TaskHandler:
        async def run(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
            return {"echo": payload, "ok": True}

    handler: TaskHandlerProtocol = _TaskHandler()
    result = await handler.run({"input": "value"})
    assert result == {"echo": {"input": "value"}, "ok": True}

    default_result = await handler.run()
    assert default_result == {"echo": None, "ok": True}


async def test_event_handler_with_envelope_returns_value() -> None:
    received: list[EventEnvelope] = []

    class _EventHandler:
        async def handle(self, envelope: EventEnvelope) -> str:
            received.append(envelope)
            return envelope.topic

    handler: EventHandlerProtocol = _EventHandler()
    envelope = create_event_envelope(
        "test.topic",
        {"k": "v"},
        source="unit-test",
    )
    result = await handler.handle(envelope)
    assert result == "test.topic"
    assert received == [envelope]


def test_subclasses_of_compliant_classes_also_satisfy() -> None:
    class _BaseTask:
        async def run(self, payload: dict[str, Any] | None = None) -> str:
            return "base"

    class _ChildTask(_BaseTask):
        pass

    class _BaseEvent:
        async def handle(self, envelope: EventEnvelope) -> None:
            return None

    class _ChildEvent(_BaseEvent):
        pass

    assert _has_async_method(_ChildTask(), "run")
    assert _has_async_method(_ChildEvent(), "handle")


async def test_duck_typed_callable_satisfies_protocol() -> None:
    class _DuckTask:
        async def run(self, payload: dict[str, Any] | None = None) -> str:
            return f"duck:{payload}"

    class _DuckEvent:
        async def handle(self, envelope: EventEnvelope) -> str:
            return f"duck:{envelope.topic}"

    task: TaskHandlerProtocol = _DuckTask()
    event: EventHandlerProtocol = _DuckEvent()

    assert _has_async_method(task, "run")
    assert _has_async_method(event, "handle")

    assert await task.run({"x": 1}) == "duck:{'x': 1}"
    envelope = create_event_envelope("duck.topic", {}, source="unit-test")
    assert await event.handle(envelope) == "duck:duck.topic"


def test_protocols_are_not_runtime_checkable() -> None:
    """Sanity check: the protocols are shape-only (no ``@runtime_checkable``).

    If this guard ever fails, the duck-typed helpers above should be revisited
    to use ``isinstance`` checks instead of ``hasattr``.
    """

    class _Anything:
        async def run(self, payload: dict[str, Any] | None = None) -> None:
            return None

        async def handle(self, envelope: EventEnvelope) -> None:
            return None

    try:
        isinstance(_Anything(), TaskHandlerProtocol)
    except TypeError:
        task_runtime_checkable = False
    else:  # pragma: no cover - guard only fires if the source is updated
        task_runtime_checkable = True

    try:
        isinstance(_Anything(), EventHandlerProtocol)
    except TypeError:
        event_runtime_checkable = False
    else:  # pragma: no cover - guard only fires if the source is updated
        event_runtime_checkable = True

    assert not task_runtime_checkable
    assert not event_runtime_checkable
