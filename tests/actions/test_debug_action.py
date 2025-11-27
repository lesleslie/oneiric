from __future__ import annotations

import io

import pytest

from oneiric.actions.debug import DebugConsoleAction, DebugConsoleSettings
from oneiric.core.lifecycle import LifecycleError


@pytest.mark.asyncio
async def test_debug_console_action_emits_and_scrubs(monkeypatch) -> None:
    action = DebugConsoleAction(DebugConsoleSettings(echo=False, include_timestamp=False))
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        action,
        "_emit_log",
        lambda level, record: captured.update({"level": level, "record": record}),
    )

    result = await action.execute(
        {
            "message": "hello",
            "level": "WARNING",
            "details": {"secret": "abc", "ok": True},
        }
    )

    assert result["status"] == "emitted"
    assert result["level"] == "warning"
    assert result["details"]["secret"] == "***"
    assert result["details"]["ok"] is True
    assert captured["level"] == "warning"
    assert captured["record"]["message"] == "hello"


@pytest.mark.asyncio
async def test_debug_console_action_echoes(monkeypatch) -> None:
    action = DebugConsoleAction(DebugConsoleSettings(include_timestamp=False))
    monkeypatch.setattr(action, "_emit_log", lambda *args, **kwargs: None)
    buffer = io.StringIO()
    monkeypatch.setattr("sys.stdout", buffer)

    await action.execute({"message": "ping", "prefix": "[test]", "details": {"value": 1}})

    output = buffer.getvalue()
    assert "[test] ping" in output
    assert "{'value': 1}" in output


@pytest.mark.asyncio
async def test_debug_console_action_validates_inputs() -> None:
    action = DebugConsoleAction(DebugConsoleSettings())

    with pytest.raises(LifecycleError):
        await action.execute({"details": "invalid"})
