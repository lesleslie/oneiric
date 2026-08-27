from __future__ import annotations

import zlib
from collections.abc import Callable, Iterator
from typing import ClassVar

from pydantic import BaseModel, Field

from oneiric.actions.metadata import ActionMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class StreamingCompressionSettings(BaseModel):
    algorithm: str = Field(
        default="zstd",
        description="Default streaming compression algorithm.",
    )
    level: int = Field(
        default=3,
        ge=1,
        le=22,
        description="Compression level for zstd (1-22). Ignored for gzip.",
    )


class StreamingCompressionAction:
    """Streaming compress/decompress for chunked sources too large for memory.

    Use when the source is an iterator of byte chunks (file chunks, network
    bytes) and you can't afford to materialize the whole blob in memory
    before compressing. For in-memory payloads, prefer CompressionAction
    (simpler API, base64 output, action-kit dispatch).

    Methods:

    - ``compress(chunk_reader)`` — accepts a ``Callable[[], Iterator[bytes]]``
      (sync chunk producer) and yields a stream of compressed bytes.
    - ``decompress(chunk_reader)`` — accepts a compressed
      ``Callable[[], Iterator[bytes]]`` and yields the original bytes.

    The callable shape (vs. passing the iterator directly) lets the caller
    re-invoke the reader for retries — Phase 3 spec removed the vestigial
    ``(offset, chunk_size)`` parameters from the previous revision.
    """

    metadata = ActionMetadata(
        key="compression.stream",
        provider="builtin-streaming-compression",
        factory="oneiric.actions.streaming_compression:StreamingCompressionAction",
        description="Streaming gzip/zstd compress/decompress for chunked input",
        domains=["task", "workflow"],
        capabilities=["compress", "decompress", "stream"],
        stack_level=25,
        priority=448,
        source=CandidateSource.LOCAL_PKG,
        owner="Platform Core",
        requires_secrets=False,
        side_effect_free=True,
        settings_model=StreamingCompressionSettings,
    )

    _SUPPORTED: ClassVar[set[str]] = {"gzip", "zstd"}

    def __init__(self, settings: StreamingCompressionSettings | None = None) -> None:
        self._settings = settings or StreamingCompressionSettings()
        self._logger = get_logger("action.compression.stream")

    def compress(
        self,
        chunk_reader: Callable[[], Iterator[bytes]],
        *,
        algorithm: str | None = None,
        level: int | None = None,
    ) -> Iterator[bytes]:
        """Compress a chunked source into a stream of compressed bytes.

        ``chunk_reader`` is invoked exactly once per ``compress`` call and
        yields the plaintext in fixed-size chunks. The caller may re-invoke
        the same callable for retries — the previous spec's vestigial
        ``(offset, chunk_size)`` args were removed in this revision.
        """
        algo = (algorithm or self._settings.algorithm).lower()
        if algo not in self._SUPPORTED:
            raise LifecycleError(f"compression-stream-unsupported-algorithm: {algo}")
        if algo == "zstd":
            yield from self._zstd_stream_compress(
                chunk_reader(),
                level if level is not None else self._settings.level,
            )
        else:  # "gzip"
            yield from self._gzip_stream_compress(
                chunk_reader(),
                level if level is not None else self._settings.level,
            )

    def decompress(
        self,
        chunk_reader: Callable[[], Iterator[bytes]],
        *,
        algorithm: str | None = None,
    ) -> Iterator[bytes]:
        """Decompress a chunked compressed source back into plaintext bytes."""
        algo = (algorithm or self._settings.algorithm).lower()
        if algo not in self._SUPPORTED:
            raise LifecycleError(f"compression-stream-unsupported-algorithm: {algo}")
        if algo == "zstd":
            yield from self._zstd_stream_decompress(chunk_reader())
        else:  # "gzip"
            yield from self._gzip_stream_decompress(chunk_reader())

    async def execute(self, payload: dict | None = None) -> dict:
        """Action-kit dispatch entrypoint. Returns metadata only.

        Callers wanting streamed bytes should invoke ``compress`` /
        ``decompress`` directly — the async envelope is for dispatchers
        that don't handle iterators.
        """
        from oneiric.actions.payloads import normalize_payload

        payload = normalize_payload(payload)
        mode = payload.get("mode", "compress")
        return {
            "status": "noop",
            "mode": mode,
            "note": "use compress/decompress directly",
        }

    @staticmethod
    def _zstd_stream_compress(chunks: Iterator[bytes], level: int) -> Iterator[bytes]:
        # Lazy import — zstandard is an optional dep via the
        # `compression-zstd` PEP 735 group; the runtime code must
        # raise a clear LifecycleError when it's missing rather than
        # blowing up at module-import time.
        try:
            import zstandard
        except ImportError as exc:
            raise LifecycleError(
                "zstandard dependency required for zstd algorithm; "
                "install with `uv sync --group compression-zstd`"
            ) from exc

        # ``chunker()`` exposes a stateful compressor that buffers across
        # calls. Each ``compress(chunk)`` returns an iterator of output
        # bytes; ``finish()`` flushes the trailing frame. Concatenating
        # all yielded bytes reproduces the full compressed frame.
        chunker = zstandard.ZstdCompressor(level=level).chunker()
        for chunk in chunks:
            for output in chunker.compress(chunk):
                yield output
        for output in chunker.finish():
            yield output

    @staticmethod
    def _zstd_stream_decompress(chunks: Iterator[bytes]) -> Iterator[bytes]:
        try:
            import zstandard
        except ImportError as exc:
            raise LifecycleError(
                "zstandard dependency required for zstd algorithm; "
                "install with `uv sync --group compression-zstd`"
            ) from exc

        # ``decompressobj()`` returns a stateful decompression object that
        # accepts arbitrary fragmented compressed input. Each ``decompress``
        # call returns any plaintext bytes that the new input made available;
        # ``flush()`` drains any trailing bytes after the frame end.
        decompressor = zstandard.ZstdDecompressor().decompressobj()
        for chunk in chunks:
            plaintext = decompressor.decompress(chunk)
            if plaintext:
                yield plaintext
        tail = decompressor.flush()
        if tail:
            yield tail

    @staticmethod
    def _gzip_stream_compress(chunks: Iterator[bytes], level: int) -> Iterator[bytes]:
        # Python's gzip module doesn't expose a streaming compressor, so use
        # zlib with a gzip header for streaming gzip output.
        cctx = zlib.compressobj(level, zlib.DEFLATED, wbits=15 + 16)
        for chunk in chunks:
            data = cctx.compress(chunk)
            if data:
                yield data
        tail = cctx.flush()
        if tail:
            yield tail

    @staticmethod
    def _gzip_stream_decompress(chunks: Iterator[bytes]) -> Iterator[bytes]:
        dctx = zlib.decompressobj(wbits=15 + 16)  # gzip header
        for chunk in chunks:
            data = dctx.decompress(chunk)
            if data:
                yield data
        tail = dctx.flush()
        if tail:
            yield tail
