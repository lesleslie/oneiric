from __future__ import annotations

import base64
import json

import pytest

from oneiric.actions.serialization import (
    SerializationAction,
    SerializationActionSettings,
)
from oneiric.core.lifecycle import LifecycleError


@pytest.mark.asyncio
async def test_serialization_action_json_roundtrip(tmp_path) -> None:
    action = SerializationAction(SerializationActionSettings(default_format="json"))
    path = tmp_path / "payload.json"

    encoded = await action.execute(
        {"value": {"id": 1, "name": "Oneiric"}, "path": path}
    )

    assert encoded["format"] == "json"
    assert json.loads(encoded["text"]) == {"id": 1, "name": "Oneiric"}
    assert path.read_text().strip() == encoded["text"].strip()

    decoded = await action.execute({"mode": "decode", "path": path, "format": "json"})

    assert decoded["data"] == {"id": 1, "name": "Oneiric"}


@pytest.mark.asyncio
async def test_serialization_action_yaml_text_payload() -> None:
    action = SerializationAction()

    encoded = await action.execute(
        {"format": "yaml", "value": {"items": [1, 2], "flag": True}}
    )

    assert encoded["format"] == "yaml"
    assert "items" in encoded["text"]

    decoded = await action.execute(
        {"mode": "decode", "format": "yaml", "text": encoded["text"]}
    )
    assert decoded["data"]["items"] == [1, 2]


@pytest.mark.asyncio
async def test_serialization_action_pickle_base64() -> None:
    action = SerializationAction(SerializationActionSettings(default_format="pickle"))
    payload = {"key": "value", "count": 3}

    encoded = await action.execute({"value": payload})
    assert encoded["format"] == "pickle"
    token = encoded["data"]
    raw = base64.b64decode(token)
    assert len(raw) > 0

    decoded = await action.execute(
        {"mode": "decode", "format": "pickle", "data": token}
    )
    assert decoded["data"] == payload


@pytest.mark.asyncio
async def test_serialization_action_invalid_format() -> None:
    action = SerializationAction()

    with pytest.raises(LifecycleError):
        await action.execute({"value": {}, "format": "msgpack"})


@pytest.mark.asyncio
async def test_serialization_action_invalid_mode_raises() -> None:
    action = SerializationAction()
    with pytest.raises(LifecycleError, match="serialization-invalid-mode"):
        await action.execute({"value": {}, "mode": "validate"})


@pytest.mark.asyncio
async def test_serialization_encode_uses_data_key_fallback() -> None:
    action = SerializationAction()
    result = await action.execute({"data": {"x": 1}, "format": "json"})
    assert result["status"] == "encoded"
    assert json.loads(result["text"]) == {"x": 1}


@pytest.mark.asyncio
async def test_serialization_encode_no_value_raises() -> None:
    action = SerializationAction()
    with pytest.raises(LifecycleError, match="serialization-value-required"):
        await action.execute({"format": "json"})


@pytest.mark.asyncio
async def test_serialization_decode_no_source_raises() -> None:
    action = SerializationAction()
    with pytest.raises(LifecycleError, match="serialization-source-required"):
        await action.execute({"mode": "decode", "format": "json"})


@pytest.mark.asyncio
async def test_serialization_decode_uses_value_key_fallback() -> None:
    action = SerializationAction()
    result = await action.execute(
        {"mode": "decode", "format": "json", "value": '{"x": 1}'}
    )
    assert result["data"] == {"x": 1}


@pytest.mark.asyncio
async def test_serialization_decode_text_format_bytes_input() -> None:
    action = SerializationAction()
    result = await action.execute(
        {"mode": "decode", "format": "json", "data": b'{"y": 2}'}
    )
    assert result["data"] == {"y": 2}


@pytest.mark.asyncio
async def test_serialization_decode_text_format_non_str_raises() -> None:
    action = SerializationAction()
    with pytest.raises(LifecycleError, match="serialization-text-required"):
        await action.execute({"mode": "decode", "format": "json", "data": 99})


@pytest.mark.asyncio
async def test_serialization_decode_binary_format_non_bytes_raises() -> None:
    action = SerializationAction()
    with pytest.raises(LifecycleError, match="serialization-binary-required"):
        await action.execute({"mode": "decode", "format": "pickle", "data": 42})


@pytest.mark.asyncio
async def test_serialization_pickle_path_roundtrip(tmp_path) -> None:
    action = SerializationAction()
    path = tmp_path / "payload.pkl"

    encoded = await action.execute(
        {"format": "pickle", "value": {"k": "v"}, "path": str(path)}
    )
    assert encoded["format"] == "pickle"
    assert path.exists()

    decoded = await action.execute(
        {"mode": "decode", "format": "pickle", "path": str(path)}
    )
    assert decoded["data"] == {"k": "v"}


@pytest.mark.asyncio
async def test_serialization_decode_binary_bytes_input() -> None:
    action = SerializationAction()
    # Encode via the action to get valid raw bytes without importing pickle
    encoded = await action.execute({"format": "pickle", "value": {"z": 3}})
    raw_bytes = base64.b64decode(encoded["data"])
    # Pass raw bytes directly to exercise the `isinstance(value, bytes) -> return value` branch
    result = await action.execute(
        {"mode": "decode", "format": "pickle", "data": raw_bytes}
    )
    assert result["data"] == {"z": 3}
