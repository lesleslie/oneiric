from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from oneiric.adapters.storage.azure import AzureBlobStorageAdapter, AzureBlobStorageSettings
from oneiric.adapters.storage.gcs import GCSStorageAdapter, GCSStorageSettings
from oneiric.adapters.storage.local import LocalStorageAdapter, LocalStorageSettings
from oneiric.adapters.storage.s3 import S3StorageAdapter, S3StorageSettings


@pytest.mark.asyncio
async def test_local_storage_roundtrip(tmp_path) -> None:
    adapter = LocalStorageAdapter(
        LocalStorageSettings(base_path=tmp_path, create_parents=True),
    )
    await adapter.init()
    await adapter.save("foo/bar.txt", b"hello")
    assert await adapter.exists("foo/bar.txt")
    assert await adapter.read("foo/bar.txt") == b"hello"
    await adapter.save("foo/baz.txt", b"bye")
    files = await adapter.list("foo/")
    assert sorted(files) == ["foo/bar.txt", "foo/baz.txt"]
    await adapter.delete("foo/bar.txt")
    assert not await adapter.exists("foo/bar.txt")
    await adapter.cleanup()


@dataclass
class _FakeBody:
    data: bytes

    async def read(self) -> bytes:
        return self.data

    async def close(self) -> None:  # pragma: no cover - simple stub
        return None


class _NoSuchKeyError(Exception):
    def __init__(self) -> None:
        self.response = {"Error": {"Code": "NoSuchKey"}}


class _NotFound(Exception):
    def __init__(self) -> None:
        self.code = 404


class _FakeS3Client:
    def __init__(self) -> None:
        self.bucket = "demo"
        self.objects: dict[str, bytes] = {}

    async def put_object(self, Bucket: str, Key: str, Body: bytes, **_: Any) -> None:
        assert Bucket == self.bucket
        self.objects[Key] = Body

    async def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        assert Bucket == self.bucket
        if Key not in self.objects:
            raise _NoSuchKeyError()
        return {"Body": _FakeBody(self.objects[Key])}

    async def delete_object(self, Bucket: str, Key: str) -> None:
        assert Bucket == self.bucket
        self.objects.pop(Key, None)

    async def list_objects_v2(self, Bucket: str, Prefix: str = "", **_: Any) -> dict[str, Any]:
        assert Bucket == self.bucket
        contents = [{"Key": key} for key in self.objects if key.startswith(Prefix)]
        return {"Contents": contents, "IsTruncated": False}

    async def head_bucket(self, Bucket: str) -> None:
        assert Bucket == self.bucket

    async def head_object(self, Bucket: str, Key: str) -> None:
        assert Bucket == self.bucket
        if Key not in self.objects:
            raise _NoSuchKeyError()


@pytest.mark.asyncio
async def test_s3_storage_adapter_uses_client_stub() -> None:
    client = _FakeS3Client()
    settings = S3StorageSettings(bucket="demo")
    adapter = S3StorageAdapter(settings, client=client)
    await adapter.init()
    await adapter.upload("file.txt", b"value")
    data = await adapter.download("file.txt")
    assert data == b"value"
    assert await adapter.download("missing.txt") is None
    listing = await adapter.list()
    assert listing == ["file.txt"]
    assert await adapter.health()
    await adapter.delete("file.txt")
    assert await adapter.list() == []
    await adapter.cleanup()


class _FakeGCSBlob:
    def __init__(self, bucket: "_FakeGCSBucket", name: str) -> None:
        self._bucket = bucket
        self.name = name

    def upload_from_string(self, data: bytes, content_type: str | None = None) -> None:
        self._bucket.objects[self.name] = data

    def download_as_bytes(self) -> bytes:
        if self.name not in self._bucket.objects:
            raise _NotFound()
        return self._bucket.objects[self.name]

    def delete(self) -> None:
        if self.name not in self._bucket.objects:
            raise _NotFound()
        del self._bucket.objects[self.name]


class _FakeGCSBucket:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def blob(self, name: str) -> _FakeGCSBlob:
        return _FakeGCSBlob(self, name)

    def exists(self) -> bool:
        return True

    def list_blobs(self, prefix: str = "") -> list[_FakeGCSBlob]:
        return [
            _FakeGCSBlob(self, name)
            for name in sorted(self.objects)
            if not prefix or name.startswith(prefix)
        ]


class _FakeGCSClient:
    def __init__(self, bucket: _FakeGCSBucket) -> None:
        self._bucket = bucket

    def bucket(self, name: str) -> _FakeGCSBucket:
        return self._bucket


@pytest.mark.asyncio
async def test_gcs_storage_adapter_uses_stub() -> None:
    bucket = _FakeGCSBucket()
    client = _FakeGCSClient(bucket)
    adapter = GCSStorageAdapter(GCSStorageSettings(bucket="demo"), client=client)
    await adapter.init()
    await adapter.upload("foo.txt", b"hello", content_type="text/plain")
    data = await adapter.download("foo.txt")
    assert data == b"hello"
    listing = await adapter.list()
    assert listing == ["foo.txt"]
    await adapter.delete("foo.txt")
    assert await adapter.download("foo.txt") is None
    await adapter.cleanup()


class _AzureNotFound(Exception):
    status_code = 404
    error_code = "BlobNotFound"


class _FakeAzureDownload:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def readall(self) -> bytes:
        return self._data


class _FakeAzureBlob:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeAzureBlobClient:
    def __init__(self, container: "_FakeAzureContainerClient", name: str) -> None:
        self._container = container
        self._name = name

    async def upload_blob(self, data: bytes, *, overwrite: bool, content_type: str) -> None:
        if not overwrite and self._name in self._container.objects:
            raise ValueError("blob exists")
        self._container.objects[self._name] = data

    async def download_blob(self) -> _FakeAzureDownload:
        if self._name not in self._container.objects:
            raise _AzureNotFound()
        return _FakeAzureDownload(self._container.objects[self._name])

    async def delete_blob(self) -> None:
        if self._name not in self._container.objects:
            raise _AzureNotFound()
        del self._container.objects[self._name]


class _FakeAzureBlobIterator:
    def __init__(self, blobs: list[_FakeAzureBlob]) -> None:
        self._blobs = blobs
        self._index = 0

    def __aiter__(self) -> "_FakeAzureBlobIterator":
        return self

    async def __anext__(self) -> _FakeAzureBlob:
        if self._index >= len(self._blobs):
            raise StopAsyncIteration
        blob = self._blobs[self._index]
        self._index += 1
        return blob


class _FakeAzureContainerClient:
    def __init__(self, name: str) -> None:
        self.objects: dict[str, bytes] = {}
        self.name = name

    def get_blob_client(self, name: str) -> _FakeAzureBlobClient:
        return _FakeAzureBlobClient(self, name)

    async def exists(self) -> bool:
        return True

    def list_blobs(self, name_starts_with: str = "") -> _FakeAzureBlobIterator:
        blobs = [
            _FakeAzureBlob(name)
            for name in sorted(self.objects)
            if not name_starts_with or name.startswith(name_starts_with)
        ]
        return _FakeAzureBlobIterator(blobs)

    async def close(self) -> None:  # pragma: no cover - trivial
        return None


class _FakeAzureServiceClient:
    def __init__(self, container: _FakeAzureContainerClient) -> None:
        self._container = container

    def get_container_client(self, name: str) -> _FakeAzureContainerClient:
        assert name == self._container.name
        return self._container

    async def close(self) -> None:  # pragma: no cover - trivial
        return None


@pytest.mark.asyncio
async def test_azure_storage_adapter_uses_stub() -> None:
    container = _FakeAzureContainerClient(name="demo")
    client = _FakeAzureServiceClient(container)
    adapter = AzureBlobStorageAdapter(
        AzureBlobStorageSettings(container="demo"),
        client=client,
    )
    await adapter.init()
    await adapter.upload("foo.txt", b"hello", content_type="text/plain")
    assert await adapter.download("foo.txt") == b"hello"
    assert await adapter.download("missing.txt") is None
    await adapter.upload("bar.txt", b"bye")
    listing = await adapter.list()
    assert listing == ["bar.txt", "foo.txt"]
    await adapter.delete("foo.txt")
    assert await adapter.list() == ["bar.txt"]
    await adapter.cleanup()
