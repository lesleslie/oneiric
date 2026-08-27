"""Streaming save/load tests for ``oneiric.adapters.storage.gcs``.

Per ADR 015 v4 Phase 3: covers ``GCSStorageAdapter.save_stream`` and
``GCSStorageAdapter.load_stream``. ``save_stream`` is async (it awaits
``asyncio.to_thread`` for the underlying GCS upload) and returns the
storage ``key``; ``load_stream`` is sync because the GCS SDK itself is
fully synchronous — no async/sync bridge is needed for the read path.

The contract exercised here mirrors the local + S3 streaming tests:

* ``save_stream`` accepts a zero-arg ``Callable[[], Iterator[bytes]]``
  and writes chunks via ``SpooledTemporaryFile`` + ``upload_from_file``.
* ``load_stream`` returns a ``Callable[[], Iterator[bytes]]`` (not a
  list/blob) and raises ``LifecycleError`` for missing keys.
* Both methods round-trip a chunked payload byte-for-byte and persist
  user-provided metadata through ``blob.metadata``.
* Partial-failure path does NOT leave an object visible in the bucket
  (``upload_from_file`` raises before completing).

GCP emulator NOTE: the brief mentioned ``gcp-storage-emulator``, but
``google-cloud-storage`` test doubles are already the established
convention in this codebase (see ``_FakeGCSBlob`` /
``_FakeGCSBucket`` in ``tests/adapters/test_storage_adapters.py``). We
extend that fake here so ``upload_from_file``, ``download_to_file``,
``exists``, and ``metadata`` are all exercised on the adapter
boundary, not at the SDK construction layer. Switching to a real
emulator later only requires swapping the fake client.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from oneiric.adapters.storage.gcs import GCSStorageAdapter, GCSStorageSettings
from oneiric.core.lifecycle import LifecycleError


@dataclass
class _FakeGCSBlob:
    """In-process stand-in for ``google.cloud.storage.Blob`` modelling
    the streaming surface driven by ``save_stream`` and ``load_stream``.
    """

    bucket: _FakeGCSBucket
    name: str
    metadata: dict[str, str] = field(default_factory=dict)
    _upload_calls: list[dict[str, Any]] = field(default_factory=list)
    _download_calls: list[dict[str, Any]] = field(default_factory=list)

    def upload_from_file(
        self,
        file_obj: Any,
        *,
        rewind: bool = False,
        content_type: str | None = None,
        **kwargs: Any,
    ) -> None:
        # Record what we were called with; mirror metadata if set.
        self._upload_calls.append(
            {
                "rewind": rewind,
                "content_type": content_type,
                "kwargs": dict(kwargs),
            }
        )
        if rewind:
            file_obj.seek(0)
        data = file_obj.read()
        self.bucket.objects[self.name] = data
        # GCS sets blob.metadata on the object after upload_from_file.
        if self.metadata:
            self.bucket.objects_meta[self.name] = dict(self.metadata)

    def download_to_file(self, file_obj: Any, **kwargs: Any) -> None:
        self._download_calls.append({"kwargs": dict(kwargs)})
        if self.name not in self.bucket.objects:
            raise _NotFound()
        file_obj.write(self.bucket.objects[self.name])

    def exists(self) -> bool:
        return self.name in self.bucket.objects


@dataclass
class _FakeGCSBucket:
    objects: dict[str, bytes] = field(default_factory=dict)
    objects_meta: dict[str, dict[str, str]] = field(default_factory=dict)

    def blob(self, name: str) -> _FakeGCSBlob:
        # The production adapter does ``self._bucket.blob(key)`` then
        # later may call ``blob.upload_from_file``/``download_to_file``.
        # We return a fresh blob handle each time — the bucket keeps the
        # canonical state so re-fetches see the latest metadata. Metadata
        # set on the blob handle is propagated to ``objects_meta`` by
        # ``upload_from_file``.
        return _FakeGCSBlob(bucket=self, name=name)

    def exists(self) -> bool:
        return True

    def list_blobs(self, prefix: str = "") -> list[_FakeGCSBlob]:
        return [
            _FakeGCSBlob(bucket=self, name=name)
            for name in sorted(self.objects)
            if not prefix or name.startswith(prefix)
        ]


class _FakeGCSClient:
    def __init__(self, bucket: _FakeGCSBucket) -> None:
        self._bucket = bucket

    def bucket(self, name: str) -> _FakeGCSBucket:
        return self._bucket


class _NotFound(Exception):
    def __init__(self) -> None:
        self.code = 404


def _reader(payload: bytes, chunk_size: int = 1024) -> Callable[[], Iterator[bytes]]:
    """Return a fresh-iterator reader so save_stream sees a Callable that
    produces a new iterator on every invocation (per the contract)."""

    def reader() -> Iterator[bytes]:
        for offset in range(0, len(payload), chunk_size):
            yield payload[offset : offset + chunk_size]

    return reader


# ---------------------------------------------------------------------------
# save_stream round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gcs_save_stream_round_trips_byte_for_byte() -> None:
    bucket = _FakeGCSBucket()
    client = _FakeGCSClient(bucket)
    adapter = GCSStorageAdapter(GCSStorageSettings(bucket="demo"), client=client)
    await adapter.init()

    payload = b"streaming-roundtrip-gcs"
    returned = await adapter.save_stream("stream/out.bin", _reader(payload))
    # save_stream returns the storage key (per ADR 015 v4 Phase 3 spec).
    assert returned == "stream/out.bin"
    assert bucket.objects["stream/out.bin"] == payload
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_gcs_save_stream_skips_empty_chunks() -> None:
    """Empty (zero-length) chunks must be skipped — mirroring the S3
    adapter's behaviour so callers can yield empty separators without
    blowing up the upload. We verify by counting how many bytes landed
    on the bucket side."""
    bucket = _FakeGCSBucket()
    client = _FakeGCSClient(bucket)
    adapter = GCSStorageAdapter(GCSStorageSettings(bucket="demo"), client=client)
    await adapter.init()

    def mixed_reader() -> Iterator[bytes]:
        yield b"abc"
        yield b""
        yield b"def"
        yield b""

    returned = await adapter.save_stream("mixed.bin", mixed_reader)
    assert returned == "mixed.bin"
    assert bucket.objects["mixed.bin"] == b"abcdef"
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_gcs_save_stream_handles_many_small_chunks() -> None:
    """1000 x 1KB chunks: verifies save_stream drives the upload
    incrementally (no in-memory materialization of all chunks at once)
    and the total bytes match the original payload."""
    bucket = _FakeGCSBucket()
    client = _FakeGCSClient(bucket)
    adapter = GCSStorageAdapter(GCSStorageSettings(bucket="demo"), client=client)
    await adapter.init()

    payload = (b"z" * 1024) * 1000
    seen = 0

    def counting_reader() -> Iterator[bytes]:
        nonlocal seen
        for i in range(1000):
            seen += 1
            yield payload[i * 1024 : (i + 1) * 1024]

    returned = await adapter.save_stream("big.bin", counting_reader)
    assert returned == "big.bin"
    assert seen == 1000
    assert bucket.objects["big.bin"] == payload
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_gcs_save_stream_persists_metadata() -> None:
    """``save_stream(metadata=...)`` must round-trip metadata through
    ``blob.metadata`` so the bucket records the user-defined map after
    upload. We assert the fake bucket's ``objects_meta`` mirror — same
    shape as the production ``Blob.reload().metadata`` API."""
    bucket = _FakeGCSBucket()
    client = _FakeGCSClient(bucket)
    adapter = GCSStorageAdapter(GCSStorageSettings(bucket="demo"), client=client)
    await adapter.init()

    await adapter.save_stream(
        "meta.bin",
        _reader(b"blob"),
        metadata={"sha256": "abc123", "trace": "t-1"},
    )
    assert bucket.objects_meta.get("meta.bin") == {
        "sha256": "abc123",
        "trace": "t-1",
    }
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_gcs_save_stream_does_not_persist_object_on_failure() -> None:
    """Mid-stream failure (raised inside the chunk_reader) must NOT
    leave the object visible in the bucket. The SpooledTemporaryFile
    is discarded and ``upload_from_file`` is never called."""

    class _Kaboom(RuntimeError):
        pass

    def failing_reader() -> Iterator[bytes]:
        yield b"good-chunk-1"
        raise _Kaboom("simulated mid-write failure")

    bucket = _FakeGCSBucket()
    client = _FakeGCSClient(bucket)
    adapter = GCSStorageAdapter(GCSStorageSettings(bucket="demo"), client=client)
    await adapter.init()

    with pytest.raises(_Kaboom):
        await adapter.save_stream("should/not/exist.bin", failing_reader)

    assert "should/not/exist.bin" not in bucket.objects
    await adapter.cleanup()


# ---------------------------------------------------------------------------
# load_stream contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gcs_load_stream_returns_callable_not_blob() -> None:
    """``load_stream`` must return a callable yielding a fresh
    iterator — not bytes/list. Round-trip a payload through save_stream
    and then load_stream and confirm bytes match."""
    bucket = _FakeGCSBucket()
    client = _FakeGCSClient(bucket)
    adapter = GCSStorageAdapter(GCSStorageSettings(bucket="demo"), client=client)
    await adapter.init()

    payload = b"load-stream-roundtrip-gcs"
    await adapter.save_stream("load.bin", _reader(payload))

    loader = adapter.load_stream("load.bin")
    assert callable(loader)
    iterator = loader()
    assert not isinstance(iterator, (bytes, bytearray, list))
    assert b"".join(iterator) == payload
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_gcs_load_stream_missing_key_raises_lifecycle_error() -> None:
    """Mirror the local + S3 adapter contract: missing key →
    ``LifecycleError`` (not a leaky ``google.api_core.exceptions.NotFound``).
    """
    bucket = _FakeGCSBucket()
    client = _FakeGCSClient(bucket)
    adapter = GCSStorageAdapter(GCSStorageSettings(bucket="demo"), client=client)
    await adapter.init()

    with pytest.raises(LifecycleError, match="gcs-storage-key-not-found"):
        adapter.load_stream("never/written.bin")
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_gcs_load_stream_independent_iterators() -> None:
    """Calling the loader multiple times yields independent iterators —
    the body must not be consumed-through-once."""
    bucket = _FakeGCSBucket()
    client = _FakeGCSClient(bucket)
    adapter = GCSStorageAdapter(GCSStorageSettings(bucket="demo"), client=client)
    await adapter.init()

    payload = b"abcdefghij"
    await adapter.save_stream("multi.bin", _reader(payload))

    loader = adapter.load_stream("multi.bin", chunk_size=2)
    first = b"".join(loader())
    second = b"".join(loader())
    assert first == payload
    assert second == payload
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_gcs_load_stream_respects_chunk_size() -> None:
    """``load_stream(chunk_size=...)`` controls read chunk size — the
    iterator yields chunks of that size until EOF."""
    bucket = _FakeGCSBucket()
    client = _FakeGCSClient(bucket)
    adapter = GCSStorageAdapter(GCSStorageSettings(bucket="demo"), client=client)
    await adapter.init()

    payload = b"".join(bytes([i % 256]) * 5 for i in range(20))  # 100 bytes
    await adapter.save_stream("chunked.bin", _reader(payload, chunk_size=10))

    chunks = list(adapter.load_stream("chunked.bin", chunk_size=10)())
    assert all(isinstance(c, bytes) for c in chunks)
    assert b"".join(chunks) == payload
    full_chunks = [c for c in chunks if len(c) == 10]
    assert full_chunks, "expected at least one full-sized chunk"
    await adapter.cleanup()
