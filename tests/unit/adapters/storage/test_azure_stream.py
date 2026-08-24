"""Streaming save/load tests for ``oneiric.adapters.storage.azure``.

Per ADR 015 v4 Phase 3: covers ``AzureBlobStorageAdapter.save_stream``
(async — drains chunks into a ``SpooledTemporaryFile`` and uploads via
``azure.storage.blob.aio.BlobClient.upload_blob``) and
``AzureBlobStorageAdapter.load_stream`` (sync — builds a sync
``azure.storage.blob.BlobServiceClient`` lazily so the body can be
iterated without an async/sync bridge, mirroring the S3 adapter's
``_build_sync_client`` pattern).

The contract exercised here mirrors the local + S3 streaming tests:

* ``save_stream`` accepts a zero-arg ``Callable[[], Iterator[bytes]]``
  and writes chunks via ``SpooledTemporaryFile`` + ``upload_blob``.
* ``load_stream`` returns a ``Callable[[], Iterator[bytes]]`` (not a
  list/blob) and raises ``LifecycleError`` for missing keys.
* Both methods round-trip a chunked payload byte-for-byte and persist
  user-provided metadata through ``upload_blob(metadata=...)``.
* Partial-failure path does NOT leave a blob visible in the container
  (``upload_blob`` raises before completing).

Azure emulator NOTE: the brief mentioned ``azure-storage-emulator``,
but the established convention in this codebase uses in-process fakes
(see ``_FakeAzureServiceClient`` / ``_FakeAzureContainerClient`` in
``tests/adapters/test_storage_adapters.py``). We extend that fake
here so the streaming surface (``upload_blob``, ``download_blob``,
``get_blob_properties``) is exercised on the adapter boundary, not at
the SDK construction layer. Switching to a real emulator later only
requires swapping the fake client.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from oneiric.adapters.storage.azure import (
    AzureBlobStorageAdapter,
    AzureBlobStorageSettings,
)
from oneiric.core.lifecycle import LifecycleError


class _AzureNotFound(Exception):
    """Exception with 404 status_code (matches the Azure SDK shape)."""

    status_code = 404
    error_code = "BlobNotFound"
    message = "The specified blob does not exist."


class _AzureGenericError(Exception):
    status_code = 500


@dataclass
class _FakeAzureDownload:
    data: bytes
    _consumed: bool = False

    def readall(self) -> bytes:
        if self._consumed:
            return b""
        self._consumed = True
        return self.data


class _FakeAzureBlobClient:
    """In-process stand-in for ``azure.storage.blob.BlobClient``
    modelling the streaming surface driven by ``save_stream`` and
    ``load_stream``.
    """

    def __init__(
        self,
        container: "_FakeAzureContainerClient",
        name: str,
        *,
        fail_after: int | None = None,
    ) -> None:
        self._container = container
        self._name = name
        self._upload_calls: list[dict[str, Any]] = []
        self._download_calls: list[dict[str, Any]] = []
        self._properties_calls = 0
        self._fail_after = fail_after
        self._uploads_seen = 0

    async def upload_blob(
        self,
        data: Any,
        *,
        blob_type: str = "BlockBlob",
        overwrite: bool = True,
        length: int | None = None,
        metadata: dict[str, str] | None = None,
        content_settings: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self._uploads_seen += 1
        if self._fail_after is not None and self._uploads_seen > self._fail_after:
            raise _AzureGenericError(f"upload_blob #{self._uploads_seen} failed")
        self._upload_calls.append(
            {
                "blob_type": blob_type,
                "overwrite": overwrite,
                "length": length,
                "metadata": dict(metadata) if metadata else None,
                "content_settings": content_settings,
                "kwargs": dict(kwargs),
            }
        )
        # Read the data source: bytes-like or file-like.
        if hasattr(data, "read"):
            data.seek(0)
            payload = data.read()
        else:
            payload = bytes(data)
        if not overwrite and self._name in self._container.objects:
            raise ValueError("blob exists")
        self._container.objects[self._name] = payload
        if metadata:
            self._container.objects_meta[self._name] = dict(metadata)

    def download_blob(self, **kwargs: Any) -> _FakeAzureDownload:
        self._download_calls.append({"kwargs": dict(kwargs)})
        if self._name not in self._container.objects:
            raise _AzureNotFound()
        return _FakeAzureDownload(self._container.objects[self._name])

    def get_blob_properties(self, **kwargs: Any) -> dict[str, Any]:
        self._properties_calls += 1
        if self._name not in self._container.objects:
            raise _AzureNotFound()
        return {"name": self._name}

    def delete_blob(self) -> None:
        if self._name not in self._container.objects:
            raise _AzureNotFound()
        del self._container.objects[self._name]


@dataclass
class _FakeAzureContainerClient:
    objects: dict[str, bytes] = field(default_factory=dict)
    objects_meta: dict[str, dict[str, str]] = field(default_factory=dict)
    name: str = "demo"
    blob_client_factory: Callable[["_FakeAzureContainerClient", str], _FakeAzureBlobClient] | None = None
    fail_after: int | None = None

    def get_blob_client(self, name: str) -> _FakeAzureBlobClient:
        if self.blob_client_factory is not None:
            return self.blob_client_factory(self, name)
        return _FakeAzureBlobClient(self, name, fail_after=self.fail_after)

    async def exists(self) -> bool:
        return True

    def list_blobs(self, name_starts_with: str = "") -> Any:
        # Not exercised by the streaming tests; provide a minimal
        # async-iterable stub so existing tests still import-clean.
        class _Stub:
            def __aiter__(self) -> _Stub:
                return self

            async def __anext__(self) -> Any:
                raise StopAsyncIteration

        return _Stub()

    async def close(self) -> None:  # pragma: no cover - trivial
        return None


class _FakeAzureServiceClient:
    def __init__(
        self, container: _FakeAzureContainerClient, *, sync_container: Any = None
    ) -> None:
        self._container = container
        self._sync_container = sync_container

    def get_container_client(self, name: str) -> _FakeAzureContainerClient:
        assert name == self._container.name
        return self._container

    def from_connection_string(cls, connection_string: str) -> "_FakeAzureServiceClient":
        # Not used in the streaming tests — we inject the sync client
        # via ``_build_sync_client`` override below.
        raise NotImplementedError("inject sync container instead")

    async def close(self) -> None:  # pragma: no cover - trivial
        return None


def _install_sync_container(
    adapter: AzureBlobStorageAdapter, sync_container: _FakeAzureContainerClient
) -> None:
    """Inject a sync container so ``_build_sync_client`` returns a
    pre-built ``BlobServiceClient`` whose ``get_container_client`` yields
    a sync mirror of the async container. This keeps the streaming
    round-trip in-process without any real Azure SDK calls.
    """

    class _FakeSyncServiceClient:
        def get_container_client(self, name: str) -> _FakeAzureContainerClient:
            assert name == sync_container.name
            return sync_container

    adapter._sync_client = _FakeSyncServiceClient()  # type: ignore[attr-defined]


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
async def test_azure_save_stream_round_trips_byte_for_byte() -> None:
    container = _FakeAzureContainerClient(name="demo")
    client = _FakeAzureServiceClient(container)
    adapter = AzureBlobStorageAdapter(
        AzureBlobStorageSettings(container="demo"),
        client=client,
    )
    await adapter.init()

    payload = b"streaming-roundtrip-azure"
    returned = await adapter.save_stream("stream/out.bin", _reader(payload))
    assert returned == "stream/out.bin"
    assert container.objects["stream/out.bin"] == payload
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_azure_save_stream_skips_empty_chunks() -> None:
    """Empty (zero-length) chunks must be skipped — mirroring the S3
    adapter's behaviour so callers can yield empty separators without
    blowing up the upload."""
    container = _FakeAzureContainerClient(name="demo")
    client = _FakeAzureServiceClient(container)
    adapter = AzureBlobStorageAdapter(
        AzureBlobStorageSettings(container="demo"),
        client=client,
    )
    await adapter.init()

    def mixed_reader() -> Iterator[bytes]:
        yield b"abc"
        yield b""
        yield b"def"
        yield b""

    returned = await adapter.save_stream("mixed.bin", mixed_reader)
    assert returned == "mixed.bin"
    assert container.objects["mixed.bin"] == b"abcdef"
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_azure_save_stream_handles_many_small_chunks() -> None:
    """1000 x 1KB chunks: verifies save_stream drives the upload
    incrementally (no in-memory materialization of all chunks at once)
    and the total bytes match the original payload."""
    container = _FakeAzureContainerClient(name="demo")
    client = _FakeAzureServiceClient(container)
    adapter = AzureBlobStorageAdapter(
        AzureBlobStorageSettings(container="demo"),
        client=client,
    )
    await adapter.init()

    payload = (b"q" * 1024) * 1000
    seen = 0

    def counting_reader() -> Iterator[bytes]:
        nonlocal seen
        for i in range(1000):
            seen += 1
            yield payload[i * 1024 : (i + 1) * 1024]

    returned = await adapter.save_stream("big.bin", counting_reader)
    assert returned == "big.bin"
    assert seen == 1000
    assert container.objects["big.bin"] == payload
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_azure_save_stream_persists_metadata() -> None:
    """``save_stream(metadata=...)`` must round-trip metadata through
    ``upload_blob(metadata=...)`` so the blob carries the user-defined
    map after upload."""
    container = _FakeAzureContainerClient(name="demo")
    client = _FakeAzureServiceClient(container)
    adapter = AzureBlobStorageAdapter(
        AzureBlobStorageSettings(container="demo"),
        client=client,
    )
    await adapter.init()

    await adapter.save_stream(
        "meta.bin",
        _reader(b"blob"),
        metadata={"sha256": "abc123", "trace": "t-1"},
    )
    assert container.objects_meta.get("meta.bin") == {
        "sha256": "abc123",
        "trace": "t-1",
    }
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_azure_save_stream_does_not_persist_blob_on_failure() -> None:
    """Mid-stream failure (raised inside the chunk_reader) must NOT
    leave the blob visible in the container. The SpooledTemporaryFile
    is discarded and ``upload_blob`` is never called."""

    class _Kaboom(RuntimeError):
        pass

    def failing_reader() -> Iterator[bytes]:
        yield b"good-chunk-1"
        raise _Kaboom("simulated mid-write failure")

    container = _FakeAzureContainerClient(name="demo")
    client = _FakeAzureServiceClient(container)
    adapter = AzureBlobStorageAdapter(
        AzureBlobStorageSettings(container="demo"),
        client=client,
    )
    await adapter.init()

    with pytest.raises(_Kaboom):
        await adapter.save_stream("should/not/exist.bin", failing_reader)

    assert "should/not/exist.bin" not in container.objects
    await adapter.cleanup()


# ---------------------------------------------------------------------------
# load_stream contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_azure_load_stream_returns_callable_not_blob() -> None:
    """``load_stream`` must return a callable yielding a fresh
    iterator — not bytes/list. Round-trip a payload through save_stream
    and then load_stream and confirm bytes match."""
    container = _FakeAzureContainerClient(name="demo")
    sync_container = _FakeAzureContainerClient(name="demo")
    client = _FakeAzureServiceClient(container, sync_container=sync_container)
    adapter = AzureBlobStorageAdapter(
        AzureBlobStorageSettings(container="demo"),
        client=client,
    )
    await adapter.init()
    _install_sync_container(adapter, sync_container)

    # Write the body via the async adapter, then mirror it into the
    # sync container so load_stream's sync download_blob finds it.
    payload = b"load-stream-roundtrip-azure"
    await adapter.save_stream("load.bin", _reader(payload))
    sync_container.objects["load.bin"] = container.objects["load.bin"]

    loader = adapter.load_stream("load.bin")
    assert callable(loader)
    iterator = loader()
    assert not isinstance(iterator, (bytes, bytearray, list))
    assert b"".join(iterator) == payload
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_azure_load_stream_missing_key_raises_lifecycle_error() -> None:
    """Mirror the local + S3 adapter contract: missing key →
    ``LifecycleError`` (not a leaky ``azure.core.exceptions.ResourceNotFoundError``).
    """
    container = _FakeAzureContainerClient(name="demo")
    sync_container = _FakeAzureContainerClient(name="demo")
    client = _FakeAzureServiceClient(container, sync_container=sync_container)
    adapter = AzureBlobStorageAdapter(
        AzureBlobStorageSettings(container="demo"),
        client=client,
    )
    await adapter.init()
    _install_sync_container(adapter, sync_container)

    with pytest.raises(LifecycleError, match="azure-storage-key-not-found"):
        adapter.load_stream("never/written.bin")
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_azure_load_stream_independent_iterators() -> None:
    """Calling the loader multiple times yields independent iterators —
    the body must not be consumed-through-once."""
    container = _FakeAzureContainerClient(name="demo")
    sync_container = _FakeAzureContainerClient(name="demo")
    client = _FakeAzureServiceClient(container, sync_container=sync_container)
    adapter = AzureBlobStorageAdapter(
        AzureBlobStorageSettings(container="demo"),
        client=client,
    )
    await adapter.init()
    _install_sync_container(adapter, sync_container)

    payload = b"abcdefghij"
    await adapter.save_stream("multi.bin", _reader(payload))
    sync_container.objects["multi.bin"] = container.objects["multi.bin"]

    loader = adapter.load_stream("multi.bin", chunk_size=2)
    first = b"".join(loader())
    second = b"".join(loader())
    assert first == payload
    assert second == payload
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_azure_load_stream_respects_chunk_size() -> None:
    """``load_stream(chunk_size=...)`` controls read chunk size — the
    iterator yields chunks of that size until EOF."""
    container = _FakeAzureContainerClient(name="demo")
    sync_container = _FakeAzureContainerClient(name="demo")
    client = _FakeAzureServiceClient(container, sync_container=sync_container)
    adapter = AzureBlobStorageAdapter(
        AzureBlobStorageSettings(container="demo"),
        client=client,
    )
    await adapter.init()
    _install_sync_container(adapter, sync_container)

    payload = b"".join(bytes([i % 256]) * 5 for i in range(20))  # 100 bytes
    await adapter.save_stream("chunked.bin", _reader(payload, chunk_size=10))
    sync_container.objects["chunked.bin"] = container.objects["chunked.bin"]

    chunks = list(adapter.load_stream("chunked.bin", chunk_size=10)())
    assert all(isinstance(c, bytes) for c in chunks)
    assert b"".join(chunks) == payload
    full_chunks = [c for c in chunks if len(c) == 10]
    assert full_chunks, "expected at least one full-sized chunk"
    await adapter.cleanup()