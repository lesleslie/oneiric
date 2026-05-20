from __future__ import annotations

import io

import pytest

from oneiric.actions.debug import DebugConsoleAction, DebugConsoleSettings
from oneiric.core.lifecycle import LifecycleError


@pytest.mark.asyncio
async def test_debug_console_action_emits_and_scrubs(monkeypatch) -> None:
    action = DebugConsoleAction(
        DebugConsoleSettings(echo=False, include_timestamp=False)
    )
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

    await action.execute(
        {"message": "ping", "prefix": "[test]", "details": {"value": 1}}
    )

    output = buffer.getvalue()
    assert "[test] ping" in output
    assert "{'value': 1}" in output


@pytest.mark.asyncio
async def test_debug_console_action_validates_inputs() -> None:
    action = DebugConsoleAction(DebugConsoleSettings())

    with pytest.raises(LifecycleError):
        await action.execute({"details": "invalid"})


# ---------------------------------------------------------------------------
# Gap-fill: uncovered branches in debug.py
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_debug_message_not_string_raises() -> None:
    action = DebugConsoleAction()
    with pytest.raises(LifecycleError):
        await action.execute({"message": 42})


@pytest.mark.asyncio
async def test_debug_details_none_defaults_to_empty() -> None:
    action = DebugConsoleAction(DebugConsoleSettings(echo=False, include_timestamp=False))
    result = await action.execute({"message": "hi", "details": None})
    assert result["details"] == {}


@pytest.mark.asyncio
async def test_debug_invalid_level_falls_back_to_info() -> None:
    action = DebugConsoleAction(DebugConsoleSettings(echo=False, include_timestamp=False))
    result = await action.execute({"message": "hi", "level": "notarealevel"})
    assert result["level"] == "info"


@pytest.mark.asyncio
async def test_debug_include_timestamp_and_echo(monkeypatch) -> None:
    import io

    action = DebugConsoleAction(DebugConsoleSettings(include_timestamp=True, echo=True))
    buffer = io.StringIO()
    monkeypatch.setattr("sys.stdout", buffer)
    result = await action.execute({"message": "ts-test"})
    assert "timestamp" in result
    assert "ts-test" in buffer.getvalue()


@pytest.mark.asyncio
async def test_debug_emit_log_actual_body() -> None:
    action = DebugConsoleAction(DebugConsoleSettings(echo=False, include_timestamp=False))
    result = await action.execute({"message": "real-log"})
    assert result["status"] == "emitted"


def test_debug_merge_scrub_fields_string() -> None:
    action = DebugConsoleAction()
    result = action._merge_scrub_fields("api_key")
    assert "api_key" in result


def test_debug_merge_scrub_fields_list() -> None:
    action = DebugConsoleAction()
    result = action._merge_scrub_fields(["foo", "bar"])
    assert "foo" in result and "bar" in result


def test_debug_merge_scrub_fields_bytes_raises() -> None:
    action = DebugConsoleAction()
    with pytest.raises(LifecycleError):
        action._merge_scrub_fields(b"bytes-excluded")


def test_debug_scrub_list_branch() -> None:
    action = DebugConsoleAction()
    result = action._scrub([{"password": "s3cr3t"}, {"ok": True}], {"password"})
    assert result[0]["password"] == "***"
    assert result[1]["ok"] is True
