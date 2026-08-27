from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest

# Phase 3 BLOCKER R2-11: fail fast on missing zstandard. pytest.importorskip
# silently green-skips, which would defeat the coverage gate.
try:
    import zstandard  # noqa: F401
except ImportError:
    pytest.fail(
        "zstandard required for Phase 3 streaming compression; "
        "install with `uv sync --group compression-zstd`",
        pytrace=False,
    )

from oneiric.actions.streaming_compression import (  # noqa: E402
    StreamingCompressionAction,
)


def _chunk_reader(source: bytes, *, chunk_size: int = 8) -> Callable[[], Iterator[bytes]]:
    """Build a sync chunk_reader that yields source bytes in fixed-size chunks.

    Mirrors the Phase 3 spec signature:
    ``chunk_reader: Callable[[], Iterator[bytes]]`` (no offset/size args).
    """

    def reader() -> Iterator[bytes]:
        for start in range(0, len(source), chunk_size):
            yield source[start : start + chunk_size]

    return reader


def test_compress_yields_compressed_stream() -> None:
    action = StreamingCompressionAction()
    source = b"hello world " *  1024
    reader = _chunk_reader(source)

    stream = list(action.compress(reader))

    assert stream, "compress() must yield at least one chunk"
    assert all(isinstance(chunk, bytes) for chunk in stream)
    # Concatenated output must not equal the plaintext and must be smaller
    # for repetitive input (zstd exploits repetition).
    combined = b"".join(stream)
    assert combined != source
    assert len(combined) < len(source)


def test_decompress_round_trip_restores_original_bytes() -> None:
    action = StreamingCompressionAction()
    source = b"round-trip payload \x00\x01\x02 binary bytes \xff" * 256
    compressed_chunks = list(action.compress(_chunk_reader(source)))
    assert compressed_chunks, "fixture precondition: compress must produce bytes"

    compressed_reader = _chunk_reader(b"".join(compressed_chunks))

    restored_chunks = list(action.decompress(compressed_reader))

    assert b"".join(restored_chunks) == source


def test_chunk_reader_is_called_fresh_per_stream() -> None:
    """chunk_reader is a callable invoked once per compress/decompress call.

    The Phase 3 spec removed vestigial (offset, chunk_size) parameters; the
    callable shape lets the caller re-invoke the reader for retries. This
    test pins that contract so a future maintainer doesn't reintroduce args.
    """

    action = StreamingCompressionAction()
    source = b"abc " * 1024

    calls = {"compress": 0, "decompress": 0}

    def compress_reader() -> Iterator[bytes]:
        calls["compress"] += 1
        for start in range(0, len(source), 16):
            yield source[start : start + 16]

    compressed = list(action.compress(compress_reader))
    assert calls["compress"] == 1

    def decompress_reader() -> Iterator[bytes]:
        calls["decompress"] += 1
        for chunk in compressed:
            yield chunk

    restored = b"".join(action.decompress(decompress_reader))
    assert calls["decompress"] == 1
    assert restored == source


def test_compress_unknown_algorithm_raises_lifecycle_error() -> None:
    from oneiric.core.lifecycle import LifecycleError

    action = StreamingCompressionAction()

    with pytest.raises(LifecycleError):
        list(action.compress(_chunk_reader(b"x"), algorithm="unknown-algo"))
