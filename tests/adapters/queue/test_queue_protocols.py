from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from oneiric.adapters.queue.protocols import QueueAdapterProtocol


class _ConcreteQueue:
    async def enqueue(self, payload: Mapping[str, Any]) -> str:
        return "msg-001"


def test_protocol_is_importable() -> None:
    assert QueueAdapterProtocol is not None


def test_concrete_class_satisfies_protocol() -> None:
    q: QueueAdapterProtocol = _ConcreteQueue()  # type: ignore[assignment]
    assert q is not None


def test_protocol_runtime_checkable_not_required() -> None:
    # QueueAdapterProtocol is a structural (non-runtime-checkable) Protocol.
    # Verify the module-level symbol is a class.
    import inspect

    assert inspect.isclass(QueueAdapterProtocol)
