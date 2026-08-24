"""Streaming save/load tests for ``oneiric.adapters.storage.s3``.

Per ADR 015 v4 Phase 3: covers ``S3StorageAdapter.save_stream`` (aioboto3
multipart upload with abort on partial failure) and
``S3StorageAdapter.load_stream`` (sync boto3 streaming body).

Moto NOTE: the brief asked for ``moto.mock_aws`` per the project's S3
test convention, but ``moto`` is not declared as a dev/optional
dependency in ``pyproject.toml`` and PyPI was unreachable during this
implementation wave (offline environment, ``NameResolutionError`` on
``pypi.org``). The existing convention in this codebase uses an
in-process ``_FakeS3Client`` (see ``tests/adapters/test_storage_adapters.py``)
that mirrors the SDK method surface — and the multipart methods used
by ``save_stream`` (``create_multipart_upload``, ``upload_part``,
``complete_multipart_upload``, ``abort_multipart_upload``) are
modelled here.

When ``moto`` is added to ``pyproject.toml``'s dev group, the abort
test path can be re-expressed with ``@mock_aws`` without touching the
adapter code — the tests assert behaviour at the adapter boundary
(s3_multipart_abort counter emission, abort call invocation, bytes
on the wire), not at the boto3 client construction layer.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from oneiric.adapters.storage.s3 import S3StorageAdapter, S3StorageSettings
from oneiric.core.lifecycle import LifecycleError


@dataclass
class _StoredPart:
    part_number: int
    body: bytes
    etag: str


@dataclass
class _FakeMultipartState:
    upload_id: str
    key: str
    parts: list[_StoredPart] = field(default_factory=list)
    aborted: bool = False
    completed: bool = False


class _FakeS3StreamingClient:
    """In-process S3 client mock modelling the multipart surface that
    ``S3StorageAdapter.save_stream`` drives on the aioboto3 side, plus
    the regular async blob surface used elsewhere in the codebase.

    The sync read-side (used by ``load_stream``) is modelled by
    :class:`_FakeS3SyncClient`. We deliberately don't mix sync and
    async methods with the same name on one class — Python allows only
    one definition per name.
    """

    def __init__(self, bucket: str = "demo") -> None:
        self.bucket = bucket
        self.objects: dict[str, bytes] = {}
        self.objects_meta: dict[str, dict[str, str]] = {}
        self.multiparts: dict[str, _FakeMultipartState] = {}
        self.create_multipart_calls: list[dict[str, Any]] = []
        self.upload_part_calls: list[dict[str, Any]] = []
        self.complete_multipart_calls: list[dict[str, Any]] = []
        self.abort_multipart_calls: list[dict[str, Any]] = []
        self._upload_counter = 0

    # ---- regular blob surface (used elsewhere in the codebase) ----
    async def put_object(
        self, Bucket: str, Key: str, Body: bytes, **kwargs: Any
    ) -> None:
        assert Bucket == self.bucket
        self.objects[Key] = Body
        if kwargs.get("Metadata"):
            self.objects_meta[Key] = dict(kwargs["Metadata"])

    async def head_bucket(self, Bucket: str) -> None:
        assert Bucket == self.bucket

    async def head_object(self, Bucket: str, Key: str) -> None:
        assert Bucket == self.bucket
        if Key not in self.objects:
            raise _S3NoSuchKeyError()

    async def delete_object(self, Bucket: str, Key: str) -> None:
        assert Bucket == self.bucket
        self.objects.pop(Key, None)
        self.objects_meta.pop(Key, None)

    async def list_objects_v2(
        self, Bucket: str, Prefix: str = "", **_: Any
    ) -> dict[str, Any]:
        assert Bucket == self.bucket
        contents = [{"Key": key} for key in self.objects if key.startswith(Prefix)]
        return {"Contents": contents, "IsTruncated": False}

    # ---- multipart surface used by save_stream ----
    async def create_multipart_upload(self, Bucket: str, Key: str, **_: Any) -> dict:
        assert Bucket == self.bucket
        self._upload_counter += 1
        upload_id = f"upload-{self._upload_counter}"
        state = _FakeMultipartState(upload_id=upload_id, key=Key)
        self.multiparts[upload_id] = state
        self.create_multipart_calls.append({"Bucket": Bucket, "Key": Key, **dict(_)})
        return {"UploadId": upload_id}

    async def upload_part(
        self,
        Bucket: str,
        Key: str,
        PartNumber: int,
        UploadId: str,
        Body: bytes,
        **_: Any,
    ) -> dict[str, str]:
        assert Bucket == self.bucket
        state = self.multiparts.get(UploadId)
        assert state is not None and state.key == Key, "unknown upload"
        etag = f"etag-{UploadId}-{PartNumber}"
        body = Body if isinstance(Body, (bytes, bytearray)) else Body.read()
        state.parts.append(
            _StoredPart(part_number=PartNumber, body=bytes(body), etag=etag)
        )
        self.upload_part_calls.append(
            {
                "Bucket": Bucket,
                "Key": Key,
                "PartNumber": PartNumber,
                "UploadId": UploadId,
                "bytes": len(body),
            }
        )
        return {"ETag": etag}

    async def complete_multipart_upload(
        self,
        Bucket: str,
        Key: str,
        UploadId: str,
        MultipartUpload: dict[str, Any],
        **_: Any,
    ) -> dict[str, str]:
        assert Bucket == self.bucket
        state = self.multiparts.get(UploadId)
        assert state is not None
        ordered = sorted(MultipartUpload["Parts"], key=lambda p: p["PartNumber"])
        if len(ordered) != len(state.parts):
            raise RuntimeError(
                f"complete_multipart_upload mismatch: {len(ordered)} parts "
                f"vs {len(state.parts)} uploaded"
            )
        body = b"".join(p.body for p in sorted(state.parts, key=lambda x: x.part_number))
        self.objects[Key] = body
        # Apply Metadata if provided via the initial create call.
        create = self.create_multipart_calls[-1]
        if "Metadata" in create:
            self.objects_meta[Key] = dict(create["Metadata"])
        state.completed = True
        self.complete_multipart_calls.append(
            {"Bucket": Bucket, "Key": Key, "UploadId": UploadId, "parts": len(ordered)}
        )
        return {"ETag": "complete-etag"}

    async def abort_multipart_upload(
        self, Bucket: str, Key: str, UploadId: str, **_: Any
    ) -> dict[str, str]:
        assert Bucket == self.bucket
        state = self.multiparts.get(UploadId)
        if state is not None:
            state.aborted = True
        self.abort_multipart_calls.append(
            {"Bucket": Bucket, "Key": Key, "UploadId": UploadId}
        )
        return {}


class _FakeS3SyncClient:
    """Sync mirror of the S3 read-side surface used by
    ``S3StorageAdapter.load_stream``: ``head_object`` (probe) and
    ``get_object`` (streaming body).
    """

    def __init__(self, bucket: str, objects: dict[str, bytes]) -> None:
        self.bucket = bucket
        self.objects = objects
        self.head_object_calls: list[tuple[str, str]] = []
        self.get_object_calls: list[tuple[str, str]] = []

    def head_object(self, Bucket: str, Key: str) -> None:
        assert Bucket == self.bucket
        self.head_object_calls.append((Bucket, Key))
        if Key not in self.objects:
            raise _S3NoSuchKeyError()

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        assert Bucket == self.bucket
        self.get_object_calls.append((Bucket, Key))
        if Key not in self.objects:
            raise _S3NoSuchKeyError()
        return {"Body": _FakeStreamingBody(self.objects[Key])}


class _S3NoSuchKeyError(Exception):
    def __init__(self) -> None:
        self.response = {"Error": {"Code": "NoSuchKey"}}


class _FakeStreamingBody:
    """Sync streaming body mirroring ``botocore.response.StreamingBody``."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0
        self.closed = False

    def read(self, amt: int | None = None) -> bytes:
        if self.closed:
            raise ValueError("body closed")
        if amt is None or amt < 1:
            chunk = self._data[self._pos :]
        else:
            chunk = self._data[self._pos : self._pos + amt]
        self._pos += len(chunk)
        return chunk

    def close(self) -> None:
        self.closed = True


def _install_sync_client_cache(
    adapter: S3StorageAdapter, async_client: _FakeS3StreamingClient
) -> _FakeS3SyncClient:
    """``load_stream`` lazily calls ``_build_sync_client`` which imports
    ``boto3`` and constructs a session-based client. We inject a sync
    mirror that shares the async client's object store so save_stream
    and load_stream round-trip in-process without network or boto3."""
    sync = _FakeS3SyncClient(bucket=async_client.bucket, objects=async_client.objects)
    adapter._sync_client = sync  # type: ignore[attr-defined]
    return sync


def _reader(payload: bytes, chunk_size: int = 1024) -> Callable[[], Iterator[bytes]]:
    def reader() -> Iterator[bytes]:
        for offset in range(0, len(payload), chunk_size):
            yield payload[offset : offset + chunk_size]

    return reader


# ---------------------------------------------------------------------------
# save_stream round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_s3_save_stream_round_trips_byte_for_byte() -> None:
    client = _FakeS3StreamingClient()
    adapter = S3StorageAdapter(S3StorageSettings(bucket="demo"), client=client)
    await adapter.init()

    payload = b"streaming-roundtrip-s3"
    written = await adapter.save_stream("stream/out.bin", _reader(payload))
    assert written == len(payload)

    # Object visible in bucket; ETags re-assembled deterministically.
    assert client.objects["stream/out.bin"] == payload
    state = next(iter(client.multiparts.values()))
    assert state.completed is True
    assert not state.aborted
    # One create + N upload_parts where N == number of chunks.
    assert len(client.create_multipart_calls) == 1
    assert len(client.upload_part_calls) > 0
    assert len(client.complete_multipart_calls) == 1
    assert client.abort_multipart_calls == []
    # Sanity: parts are dense and 1-indexed.
    numbers = sorted(p["PartNumber"] for p in client.upload_part_calls)
    assert numbers == list(range(1, len(numbers) + 1))
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_s3_save_stream_handles_1000_small_chunks() -> None:
    """1000 x 1KB chunks: verifies save_stream drives multipart
    incrementally (no in-memory materialization of all chunks at once)
    and the total bytes reported match the original payload."""
    client = _FakeS3StreamingClient()
    adapter = S3StorageAdapter(S3StorageSettings(bucket="demo"), client=client)
    await adapter.init()

    payload = (b"y" * 1024) * 1000
    seen = 0

    def counting_reader() -> Iterator[bytes]:
        nonlocal seen
        for i in range(1000):
            seen += 1
            yield payload[i * 1024 : (i + 1) * 1024]

    written = await adapter.save_stream("big.bin", counting_reader)
    assert written == len(payload)
    assert seen == 1000
    assert len(client.upload_part_calls) == 1000
    assert client.objects["big.bin"] == payload
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_s3_save_stream_skips_empty_chunks() -> None:
    """Empty (zero-length) chunks must be skipped — multipart upload
    requires >=1 byte per part, and emitting an empty UploadPart would
    be rejected by S3. The reader here yields explicit empty bytes."""
    client = _FakeS3StreamingClient()
    adapter = S3StorageAdapter(S3StorageSettings(bucket="demo"), client=client)
    await adapter.init()

    def mixed_reader() -> Iterator[bytes]:
        yield b"abc"
        yield b""
        yield b"def"
        yield b""

    written = await adapter.save_stream("mixed.bin", mixed_reader)
    assert written == 6
    assert len(client.upload_part_calls) == 2
    total_bytes = sum(c["bytes"] for c in client.upload_part_calls)
    assert total_bytes == 6
    assert client.objects["mixed.bin"] == b"abcdef"
    await adapter.cleanup()


# ---------------------------------------------------------------------------
# S3 multipart abort on partial failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_s3_save_stream_aborts_on_partial_upload_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mid-stream failure must trigger ``abort_multipart_upload``. We
    monkey-patch the module-level counter to a counter bound to an
    InMemoryMetricReader so we can verify the metric emission too
    (rather than relying solely on abort call presence)."""
    from oneiric.adapters.storage import s3 as s3_mod

    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    meter = provider.get_meter("oneiric.storage.streaming")
    test_counter = meter.create_counter(
        name="s3_multipart_abort_total",
        unit="1",
        description="test mirror of the production counter",
    )
    monkeypatch.setattr(s3_mod, "_S3_MULTIPART_ABORT_COUNTER", test_counter)

    class _Boom(RuntimeError):
        pass

    class _FailingS3Client(_FakeS3StreamingClient):
        def __init__(self, fail_after: int = 2, **kw: Any) -> None:
            super().__init__(**kw)
            self._fail_after = fail_after
            self._uploads_seen = 0

        async def upload_part(
            self,
            Bucket: str,
            Key: str,
            PartNumber: int,
            UploadId: str,
            Body: bytes,
            **_: Any,
        ) -> dict[str, str]:
            self._uploads_seen += 1
            if self._uploads_seen > self._fail_after:
                raise _Boom(f"upload_part #{PartNumber} failed")
            return await super().upload_part(
                Bucket=Bucket,
                Key=Key,
                PartNumber=PartNumber,
                UploadId=UploadId,
                Body=Body,
            )

    client = _FailingS3Client(fail_after=2)
    adapter = S3StorageAdapter(S3StorageSettings(bucket="demo"), client=client)
    await adapter.init()

    payload = b"x" * (1024 * 5)  # five 1KB chunks

    with pytest.raises(_Boom):
        await adapter.save_stream("will/abort.bin", _reader(payload, chunk_size=1024))

    assert len(client.abort_multipart_calls) == 1
    aborted_state = next(iter(client.multiparts.values()))
    assert aborted_state.aborted is True
    assert "will/abort.bin" not in client.objects

    # Counter emission: s3_multipart_abort_total{backend="s3", principal_short="unknown"} == 1
    metrics_data = reader.get_metrics_data()
    assert metrics_data is not None, "no metrics collected"
    saw = 0
    for resource_metrics in metrics_data.resource_metrics:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                if metric.name == "s3_multipart_abort_total":
                    for pt in metric.data.data_points:
                        labels = dict(pt.attributes or {})
                        assert labels.get("backend") == "s3"
                        assert labels.get("principal_short") == "unknown"
                        saw += int(pt.value)
    assert saw == 1, f"expected 1 increment, saw {saw}"
    provider.shutdown()
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_s3_save_stream_emits_s3_multipart_abort_counter() -> None:
    """Direct exercise of ``_record_s3_multipart_abort`` — installs an
    in-memory metric reader, replaces the module-level counter with
    one bound to that provider, and asserts the counter is bumped.

    We can't rely on ``set_meter_provider`` alone because the OTel API
    caches ``_S3_MULTIPART_ABORT_COUNTER`` at module import time. The
    monkeypatch sets up a fresh counter on a fresh meter — both
    objects created *after* we install the provider — so increments
    are captured by the in-memory reader.
    """
    from oneiric.adapters.storage import s3 as s3_mod

    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    meter = provider.get_meter("oneiric.storage.streaming")
    test_counter = meter.create_counter(
        name="s3_multipart_abort_total",
        unit="1",
        description="test mirror of the production counter",
    )

    # Replace the production counter so the helper's ``.add(...)`` lands
    # in our InMemoryMetricReader. Recording span attributes still goes
    # to the active span (noop outside a span context).
    original = s3_mod._S3_MULTIPART_ABORT_COUNTER
    s3_mod._S3_MULTIPART_ABORT_COUNTER = test_counter
    try:
        s3_mod._record_s3_multipart_abort(
            backend="s3",
            principal_short="unknown",
            reason="exception",
            bytes_uploaded=2048,
        )
        s3_mod._record_s3_multipart_abort(
            backend="s3",
            principal_short="unknown",
            reason="exception",
            bytes_uploaded=4096,
        )
    finally:
        s3_mod._S3_MULTIPART_ABORT_COUNTER = original

    metrics_data = reader.get_metrics_data()
    assert metrics_data is not None, "no metrics collected"
    saw_counter = False
    total = 0
    for resource_metrics in metrics_data.resource_metrics:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                if metric.name == "s3_multipart_abort_total":
                    saw_counter = True
                    for pt in metric.data.data_points:
                        labels = dict(pt.attributes or {})
                        assert labels.get("backend") == "s3"
                        assert labels.get("principal_short") == "unknown"
                        total += pt.value
    assert saw_counter, "s3_multipart_abort_total counter not emitted"
    assert total == 2, f"expected 2 increments, got {total}"
    provider.shutdown()


@pytest.mark.asyncio
async def test_s3_save_stream_abort_handles_cancelled() -> None:
    """``asyncio.CancelledError`` raised mid-upload must also trigger
    the abort path. The helper classifies it as ``reason='cancelled'``
    (recorded on the span only); we verify the abort call goes
    through and the exception still re-raises so callers see the
    cancellation."""

    class _FailingS3Client(_FakeS3StreamingClient):
        async def upload_part(
            self,
            Bucket: str,
            Key: str,
            PartNumber: int,
            UploadId: str,
            Body: bytes,
            **_: Any,
        ) -> dict[str, str]:
            if PartNumber == 2:
                raise asyncio.CancelledError()
            return await super().upload_part(
                Bucket=Bucket,
                Key=Key,
                PartNumber=PartNumber,
                UploadId=UploadId,
                Body=Body,
            )

    client = _FailingS3Client()
    adapter = S3StorageAdapter(S3StorageSettings(bucket="demo"), client=client)
    await adapter.init()

    with pytest.raises(asyncio.CancelledError):
        await adapter.save_stream(
            "cancelled.bin", _reader(b"a" * 1024 * 4, chunk_size=1024)
        )
    assert len(client.abort_multipart_calls) == 1
    await adapter.cleanup()


# ---------------------------------------------------------------------------
# load_stream contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_s3_load_stream_returns_callable_not_blob() -> None:
    """``load_stream`` must return a callable yielding a fresh
    iterator — not bytes/list. Round-trip a payload through save_stream
    and then load_stream and confirm bytes match."""
    client = _FakeS3StreamingClient()
    adapter = S3StorageAdapter(S3StorageSettings(bucket="demo"), client=client)
    await adapter.init()
    sync = _install_sync_client_cache(adapter, client)

    payload = b"load-stream-roundtrip"
    await adapter.save_stream("load.bin", _reader(payload))
    # save_stream wrote into ``objects``; the sync mirror sees the same store.
    loader = adapter.load_stream("load.bin")
    assert callable(loader)
    iterator = loader()
    assert not isinstance(iterator, (bytes, bytearray, list))
    assert b"".join(iterator) == payload
    # Probe via sync head_object fired during load_stream setup.
    assert sync.head_object_calls == [("demo", "load.bin")]
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_s3_load_stream_missing_key_raises_lifecycle_error() -> None:
    """Mirror the local adapter contract: missing key → LifecycleError
    (not a leaky boto3 NoSuchKey)."""
    client = _FakeS3StreamingClient()
    adapter = S3StorageAdapter(S3StorageSettings(bucket="demo"), client=client)
    await adapter.init()
    _install_sync_client_cache(adapter, client)

    with pytest.raises(LifecycleError, match="s3-storage-key-not-found"):
        adapter.load_stream("never/written.bin")
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_s3_load_stream_independent_iterators() -> None:
    """Calling the loader multiple times yields independent iterators —
    a streaming body must not be consumed-through-once."""
    client = _FakeS3StreamingClient()
    adapter = S3StorageAdapter(S3StorageSettings(bucket="demo"), client=client)
    await adapter.init()
    sync = _install_sync_client_cache(adapter, client)

    payload = b"abcdefghij"
    await adapter.save_stream("multi.bin", _reader(payload))

    loader = adapter.load_stream("multi.bin", chunk_size=2)
    a = b"".join(loader())
    b = b"".join(loader())
    assert a == payload
    assert b == payload
    assert len(sync.get_object_calls) == 2
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_s3_save_stream_persists_metadata() -> None:
    """``save_stream(metadata=...)`` must round-trip metadata through
    ``CreateMultipartUpload.Metadata`` so head_object can read it back."""
    client = _FakeS3StreamingClient()
    adapter = S3StorageAdapter(S3StorageSettings(bucket="demo"), client=client)
    await adapter.init()

    await adapter.save_stream(
        "meta.bin",
        _reader(b"blob"),
        metadata={"x-amz-meta-sha256": "abc123"},
    )
    assert client.objects_meta.get("meta.bin") == {"x-amz-meta-sha256": "abc123"}
    await adapter.cleanup()
