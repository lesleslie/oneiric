from __future__ import annotations

import base64
import hashlib

# ---------------------------------------------------------------------------
# Gap-fill: uncovered branches in compression.py and HashAction
# ---------------------------------------------------------------------------

import pytest

from oneiric.actions.bootstrap import register_builtin_actions
from oneiric.actions.bridge import ActionBridge
from oneiric.actions.compression import (
    CompressionAction,
    HashAction,
    HashActionSettings,
)
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
    lifecycle = LifecycleManager(
        resolver, status_snapshot_path=str(tmp_path / "status.json")
    )
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


# ---------------------------------------------------------------------------
# CompressionAction — error paths and bz2/lzma algorithms
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compression_invalid_mode_raises() -> None:
    action = CompressionAction()
    from oneiric.core.lifecycle import LifecycleError

    with pytest.raises(LifecycleError):
        await action.execute({"mode": "invalid"})


@pytest.mark.asyncio
async def test_compression_non_string_text_raises() -> None:
    from oneiric.actions.compression import CompressionAction
    from oneiric.core.lifecycle import LifecycleError

    action = CompressionAction()
    with pytest.raises(LifecycleError):
        await action.execute({"mode": "compress", "text": 12345})


@pytest.mark.asyncio
async def test_compression_non_string_data_raises() -> None:
    from oneiric.actions.compression import CompressionAction
    from oneiric.core.lifecycle import LifecycleError

    action = CompressionAction()
    with pytest.raises(LifecycleError):
        await action.execute({"mode": "decompress", "data": 12345})


@pytest.mark.asyncio
async def test_compression_bz2_roundtrip() -> None:
    from oneiric.actions.compression import CompressionAction, CompressionActionSettings

    action = CompressionAction(CompressionActionSettings(algorithm="bz2"))
    compressed = await action.execute({"text": "bz2 payload"})
    assert compressed["algorithm"] == "bz2"
    restored = await action.execute({"mode": "decompress", "data": compressed["data"], "algorithm": "bz2"})
    assert restored["text"] == "bz2 payload"


@pytest.mark.asyncio
async def test_compression_lzma_roundtrip() -> None:
    from oneiric.actions.compression import CompressionAction, CompressionActionSettings

    action = CompressionAction(CompressionActionSettings(algorithm="lzma"))
    compressed = await action.execute({"text": "lzma payload"})
    assert compressed["algorithm"] == "lzma"
    restored = await action.execute({"mode": "decompress", "data": compressed["data"], "algorithm": "lzma"})
    assert restored["text"] == "lzma payload"


@pytest.mark.asyncio
async def test_compress_unknown_algorithm_raises() -> None:
    from oneiric.actions.compression import CompressionAction
    from oneiric.core.lifecycle import LifecycleError

    action = CompressionAction()
    with pytest.raises(LifecycleError):
        action._compress(b"data", "unknown-algo")


@pytest.mark.asyncio
async def test_decompress_unknown_algorithm_raises() -> None:
    from oneiric.actions.compression import CompressionAction
    from oneiric.core.lifecycle import LifecycleError

    action = CompressionAction()
    with pytest.raises(LifecycleError):
        action._decompress(b"data", "unknown-algo")


# ---------------------------------------------------------------------------
# HashAction — error paths and _to_bytes edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hash_action_invalid_algorithm_raises() -> None:
    from oneiric.actions.compression import HashAction
    from oneiric.core.lifecycle import LifecycleError

    action = HashAction()
    with pytest.raises(LifecycleError):
        await action.execute({"algorithm": "md5", "text": "hello"})


@pytest.mark.asyncio
async def test_hash_action_invalid_encoding_raises() -> None:
    from oneiric.actions.compression import HashAction
    from oneiric.core.lifecycle import LifecycleError

    action = HashAction()
    with pytest.raises(LifecycleError):
        await action.execute({"encoding": "binary", "text": "hello"})


@pytest.mark.asyncio
async def test_hash_action_missing_value_raises() -> None:
    from oneiric.actions.compression import HashAction
    from oneiric.core.lifecycle import LifecycleError

    action = HashAction()
    with pytest.raises(LifecycleError):
        await action.execute({})


@pytest.mark.asyncio
async def test_hash_action_bytes_input() -> None:
    from oneiric.actions.compression import HashAction

    action = HashAction()
    # Passing raw bytes exercises _to_bytes line 188
    result = await action.execute({"value": b"raw-bytes"})
    assert result["status"] == "hashed"
    assert result["digest"] == hashlib.sha256(b"raw-bytes").hexdigest()


@pytest.mark.asyncio
async def test_hash_action_dict_input() -> None:
    from oneiric.actions.compression import HashAction

    action = HashAction()
    # Passing a dict exercises _to_bytes json.dumps path (lines 191-192)
    result = await action.execute({"value": {"key": "val"}})
    expected = hashlib.sha256(b'{"key":"val"}').hexdigest()
    assert result["digest"] == expected
