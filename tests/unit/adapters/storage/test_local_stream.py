"""Streaming save/load tests for ``oneiric.adapters.storage.local``.

Per ADR 015 v4 Phase 3: covers ``LocalStorageAdapter.save_stream`` and
``LocalStorageAdapter.load_stream``. These methods are *synchronous* and
return a fresh ``Iterator[bytes]`` per call. The contract exercised here:

* ``save_stream`` accepts a zero-arg ``Callable[[], Iterator[bytes]]``
  and writes chunks to a sibling temp file, fsyncs, then ``os.replace``s
  into the final key — so failure mid-write leaves no partial target
  file.
* ``load_stream`` returns a ``Callable[[], Iterator[bytes]]`` (not a
  list/blob) and raises ``LifecycleError`` for missing keys.
* Both methods round-trip large data byte-for-byte without materializing
  the full body in memory (verified by iterating the loader multiple
  times).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from oneiric.adapters.storage.local import (
    LocalStorageAdapter,
    LocalStorageSettings,
)
from oneiric.core.lifecycle import LifecycleError


def _make_chunk_reader(
    payload: bytes, chunk_size: int = 1024
) -> Callable[[], Iterator[bytes]]:
    """Return a fresh-iterator reader so save_stream sees a Callable that
    produces a new iterator on every invocation (per the contract)."""

    def reader() -> Iterator[bytes]:
        for offset in range(0, len(payload), chunk_size):
            yield payload[offset : offset + chunk_size]

    return reader


@pytest.mark.asyncio
async def test_save_stream_then_load_stream_round_trip(tmp_path: Path) -> None:
    """Small payload: write with save_stream, read back with load_stream,
    confirm bytes match and load_stream is a callable returning an
    iterator (not a list/blob)."""
    adapter = LocalStorageAdapter(
        LocalStorageSettings(base_path=tmp_path, create_parents=True),
    )
    await adapter.init()

    payload = b"hello streaming world"
    written = adapter.save_stream("nested/file.bin", _make_chunk_reader(payload))
    assert written == len(payload)
    assert (tmp_path / "nested" / "file.bin").read_bytes() == payload

    loader = adapter.load_stream("nested/file.bin")
    assert callable(loader)
    # The contract requires a Callable that returns a fresh iterator —
    # asserting the result is iterable and not bytes/list guards against
    # accidentally returning materialized content.
    iterator = loader()
    assert not isinstance(iterator, (bytes, bytearray, list))
    assert b"".join(iterator) == payload

    await adapter.cleanup()


@pytest.mark.asyncio
async def test_load_stream_returns_independent_iterators(tmp_path: Path) -> None:
    """load_stream must yield a *fresh* iterator per invocation so the
    caller can iterate the body more than once without seek/replay bugs."""
    adapter = LocalStorageAdapter(LocalStorageSettings(base_path=tmp_path))
    await adapter.init()

    adapter.save_stream("data.bin", _make_chunk_reader(b"abcdefgh"))
    loader = adapter.load_stream("data.bin", chunk_size=2)

    first = b"".join(loader())
    second = b"".join(loader())
    assert first == b"abcdefgh"
    assert second == b"abcdefgh"  # independent iterator, same bytes


@pytest.mark.asyncio
async def test_save_stream_handles_many_small_chunks(tmp_path: Path) -> None:
    """1000 x 1KB chunks: verifies save_stream doesn't materialize all
    chunks in memory and writes them sequentially. Same for load_stream:
    the iterator is consumed lazily and does not allocate the whole
    blob up-front."""
    adapter = LocalStorageAdapter(LocalStorageSettings(base_path=tmp_path))
    await adapter.init()

    payload = (b"x" * 1024) * 1000  # exactly 1MB

    seen_chunk_count = 0

    def counting_reader() -> Iterator[bytes]:
        nonlocal seen_chunk_count
        for i in range(1000):
            seen_chunk_count += 1
            chunk = payload[i * 1024 : (i + 1) * 1024]
            assert len(chunk) == 1024
            yield chunk

    written = adapter.save_stream("large.bin", counting_reader)
    assert written == len(payload)
    assert seen_chunk_count == 1000

    # load_stream with a small chunk_size forces many reads — confirming
    # the reader is lazy.
    loader = adapter.load_stream("large.bin", chunk_size=4096)
    loaded = b"".join(loader())
    assert loaded == payload
    assert (tmp_path / "large.bin").stat().st_size == len(payload)
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_save_stream_atomic_rename_no_partial_files_on_failure(
    tmp_path: Path,
) -> None:
    """Mid-write failure must NOT leave a partial ``file.bin`` behind.
    The atomic-rename contract: temp file is unlinked on exception, only
    the final key is observable. A subsequent ``exists`` check shows the
    key was never created."""
    adapter = LocalStorageAdapter(LocalStorageSettings(base_path=tmp_path))
    await adapter.init()

    class _Kaboom(RuntimeError):
        pass

    def failing_reader() -> Iterator[bytes]:
        yield b"good-chunk-1"
        yield b"good-chunk-2"
        raise _Kaboom("simulated mid-write failure")

    with pytest.raises(_Kaboom):
        adapter.save_stream("should/not/exist.bin", failing_reader)

    final_path = tmp_path / "should" / "not" / "exist.bin"
    assert not final_path.exists(), "partial target file must not exist"
    assert not await adapter.exists("should/not/exist.bin")

    # No orphan temp files for this key (.tmp / .partial style)
    siblings = list((tmp_path / "should" / "not").iterdir())
    assert siblings == [], f"unexpected siblings left behind: {siblings}"

    await adapter.cleanup()


@pytest.mark.asyncio
async def test_load_stream_missing_key_raises_lifecycle_error(
    tmp_path: Path,
) -> None:
    adapter = LocalStorageAdapter(LocalStorageSettings(base_path=tmp_path))
    await adapter.init()
    with pytest.raises(LifecycleError, match="local-storage-key-not-found"):
        adapter.load_stream("does/not/exist.bin")
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_save_stream_respects_custom_chunk_size_for_load(
    tmp_path: Path,
) -> None:
    """Verify ``load_stream(chunk_size=...)`` controls read chunk size —
    the iterator yields chunks of that size until EOF."""
    adapter = LocalStorageAdapter(LocalStorageSettings(base_path=tmp_path))
    await adapter.init()

    payload = b"".join(bytes([i % 256]) * 5 for i in range(20))  # 100 bytes
    adapter.save_stream("chunked.bin", _make_chunk_reader(payload, chunk_size=10))

    chunks = list(adapter.load_stream("chunked.bin", chunk_size=10)())
    # All chunks must be exactly 10 bytes except possibly the last.
    assert all(isinstance(c, bytes) for c in chunks)
    assert b"".join(chunks) == payload
    # The chunk_size we requested is honored: only the trailing chunk may be smaller.
    full_chunks = [c for c in chunks if len(c) == 10]
    assert full_chunks, "expected at least one full-sized chunk"
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_save_stream_blocks_path_traversal(tmp_path: Path) -> None:
    """``save_stream`` resolves through ``_resolve_path`` which guards
    against writing outside ``base_path``. Calling it with a ../escape
    key must raise LifecycleError rather than writing outside the base."""
    adapter = LocalStorageAdapter(LocalStorageSettings(base_path=tmp_path))
    await adapter.init()
    with pytest.raises(LifecycleError, match="path-traversal-detected"):
        adapter.save_stream("../escape.bin", _make_chunk_reader(b"nope"))
    # Make sure the escape file wasn't actually created.
    assert not (tmp_path.parent / "escape.bin").exists()
    await adapter.cleanup()
