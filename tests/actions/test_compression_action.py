from __future__ import annotations

import pytest

from oneiric.actions.bootstrap import register_builtin_actions
from oneiric.actions.bridge import ActionBridge
import base64
import hashlib

from oneiric.actions.compression import CompressionAction, HashAction, HashActionSettings
from oneiric.core.config import LayerSettings
from oneiric.core.lifecycle import LifecycleManager
from oneiric.core.resolution import Resolver


@pytest.mark.asyncio
async def test_compression_action_roundtrip() -> None:
    action = CompressionAction()
    compressed = await action.execute({"text": "hello world"})
    assert compressed["mode"] == "compress"
    restored = await action.execute({"mode": "decompress", "data": compressed["data"]})
    assert restored["text"] == "hello world"


@pytest.mark.asyncio
async def test_action_bridge_activates_builtin_compression(tmp_path) -> None:
    resolver = Resolver()
    register_builtin_actions(resolver)
    lifecycle = LifecycleManager(resolver, status_snapshot_path=str(tmp_path / "status.json"))
    settings = LayerSettings(
        selections={"compression.encode": "builtin-compression"},
    )
    bridge = ActionBridge(resolver, lifecycle, settings)
    handle = await bridge.use("compression.encode")
    result = await handle.instance.execute({"text": "kit"})
    assert result["mode"] == "compress"
    assert result["algorithm"] == "zlib"


@pytest.mark.asyncio
async def test_hash_action_hex_digest() -> None:
    action = HashAction(HashActionSettings(algorithm="sha256", encoding="hex"))

    result = await action.execute({"text": "hash-me"})

    assert result["status"] == "hashed"
    assert result["digest"] == hashlib.sha256(b"hash-me").hexdigest()


@pytest.mark.asyncio
async def test_hash_action_base64_with_salt() -> None:
    action = HashAction()

    result = await action.execute(
        {
            "text": "payload",
            "salt": "pepper",
            "encoding": "base64",
            "algorithm": "blake2b",
        }
    )

    digest = hashlib.blake2b(b"pepper" + b"payload").digest()
    assert result["encoding"] == "base64"
    assert result["digest"] == base64.b64encode(digest).decode("ascii")
