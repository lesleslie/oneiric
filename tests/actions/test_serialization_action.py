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
