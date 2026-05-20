from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from oneiric.adapters.storage.azure import (
    AzureBlobStorageAdapter,
    AzureBlobStorageSettings,
)
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

    async def list_objects_v2(
        self, Bucket: str, Prefix: str = "", **_: Any
    ) -> dict[str, Any]:
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
    def __init__(self, bucket: _FakeGCSBucket, name: str) -> None:
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


# ---------------------------------------------------------------------------
# GCS coverage-gap tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gcs_health_calls_bucket_exists() -> None:
    """health() calls bucket.exists() and returns True (lines 78-81)."""
    bucket = _FakeGCSBucket()
    client = _FakeGCSClient(bucket)
    adapter = GCSStorageAdapter(GCSStorageSettings(bucket="demo"), client=client)
    await adapter.init()
    assert await adapter.health() is True
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_gcs_download_not_found_returns_none() -> None:
    """download() returns None when blob raises a 404-like error (line 108)."""
    bucket = _FakeGCSBucket()
    client = _FakeGCSClient(bucket)
    adapter = GCSStorageAdapter(GCSStorageSettings(bucket="demo"), client=client)
    await adapter.init()
    result = await adapter.download("missing.txt")
    assert result is None
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_gcs_delete_not_found_suppressed() -> None:
    """delete() suppresses NotFound when key does not exist (lines 113-115)."""
    bucket = _FakeGCSBucket()
    client = _FakeGCSClient(bucket)
    adapter = GCSStorageAdapter(GCSStorageSettings(bucket="demo"), client=client)
    await adapter.init()
    await adapter.delete("nonexistent.txt")  # must not raise
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_gcs_download_raises_non_404_propagates(monkeypatch) -> None:
    """download() re-raises when exception is not a not-found error (line 108 coverage via direct exc)."""
    import asyncio

    bucket = _FakeGCSBucket()
    client = _FakeGCSClient(bucket)
    adapter = GCSStorageAdapter(GCSStorageSettings(bucket="demo"), client=client)
    await adapter.init()

    class _IOError(Exception):
        pass

    async def fail(*a: Any, **kw: Any) -> None:
        raise _IOError("disk error")

    monkeypatch.setattr(asyncio, "to_thread", fail)
    with pytest.raises(_IOError):
        await adapter.download("any.txt")
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_gcs_delete_raises_non_404_propagates(monkeypatch) -> None:
    """delete() re-raises when exception is not a not-found error (line 115)."""
    import asyncio

    bucket = _FakeGCSBucket()
    client = _FakeGCSClient(bucket)
    adapter = GCSStorageAdapter(GCSStorageSettings(bucket="demo"), client=client)
    await adapter.init()

    class _PermissionDenied(Exception):
        pass

    async def fail(*a: Any, **kw: Any) -> None:
        raise _PermissionDenied("access denied")

    monkeypatch.setattr(asyncio, "to_thread", fail)
    with pytest.raises(_PermissionDenied):
        await adapter.delete("any.txt")
    await adapter.cleanup()


def test_gcs_ensure_bucket_raises_when_not_initialized() -> None:
    """_ensure_bucket raises LifecycleError when bucket is not set (line 123)."""
    from oneiric.core.lifecycle import LifecycleError

    adapter = GCSStorageAdapter(GCSStorageSettings(bucket="demo"))
    with pytest.raises(LifecycleError, match="gcs-bucket-not-initialized"):
        adapter._ensure_bucket()


@pytest.mark.asyncio
async def test_gcs_init_without_client_uses_google_cloud_storage(monkeypatch) -> None:
    """init() creates storage.Client from google.cloud when client=None (lines 58-73)."""
    import sys
    import types

    created: list[dict] = []

    class FakeStorageClient:
        def __init__(self, **kwargs: Any) -> None:
            created.append(kwargs)
            self._bucket = _FakeGCSBucket()

        def bucket(self, name: str) -> _FakeGCSBucket:
            return self._bucket

    fake_storage = types.ModuleType("google.cloud.storage")
    fake_storage.Client = FakeStorageClient  # type: ignore[attr-defined]

    fake_service_account = types.ModuleType("google.oauth2.service_account")
    fake_service_account.Credentials = object  # type: ignore[attr-defined]

    fake_oauth2 = types.ModuleType("google.oauth2")
    fake_google_cloud = types.ModuleType("google.cloud")
    fake_google_cloud.storage = fake_storage  # type: ignore[attr-defined]
    fake_google = types.ModuleType("google")

    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.cloud", fake_google_cloud)
    monkeypatch.setitem(sys.modules, "google.cloud.storage", fake_storage)
    monkeypatch.setitem(sys.modules, "google.oauth2", fake_oauth2)
    monkeypatch.setitem(sys.modules, "google.oauth2.service_account", fake_service_account)

    adapter = GCSStorageAdapter(GCSStorageSettings(bucket="demo", project="my-project"))
    await adapter.init()
    assert adapter._bucket is not None
    assert created[0].get("project") == "my-project"
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_gcs_init_with_credentials_file(monkeypatch, tmp_path) -> None:
    """init() loads credentials when credentials_file is set (lines 64-70)."""
    import sys
    import types

    loaded: list[str] = []

    class FakeCredentials:
        @staticmethod
        def from_service_account_file(path: str) -> "FakeCredentials":
            loaded.append(path)
            return FakeCredentials()

    class FakeStorageClient:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def bucket(self, name: str) -> _FakeGCSBucket:
            return _FakeGCSBucket()

    fake_storage = types.ModuleType("google.cloud.storage")
    fake_storage.Client = FakeStorageClient  # type: ignore[attr-defined]

    fake_sa = types.ModuleType("google.oauth2.service_account")
    fake_sa.Credentials = FakeCredentials  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "google", types.ModuleType("google"))
    monkeypatch.setitem(sys.modules, "google.cloud", types.ModuleType("google.cloud"))
    monkeypatch.setitem(sys.modules, "google.cloud.storage", fake_storage)
    monkeypatch.setitem(sys.modules, "google.oauth2", types.ModuleType("google.oauth2"))
    monkeypatch.setitem(sys.modules, "google.oauth2.service_account", fake_sa)

    creds_path = tmp_path / "creds.json"
    creds_path.write_text("{}")
    adapter = GCSStorageAdapter(
        GCSStorageSettings(bucket="demo", credentials_file=creds_path)
    )
    await adapter.init()
    assert loaded == [str(creds_path)]
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
    def __init__(self, container: _FakeAzureContainerClient, name: str) -> None:
        self._container = container
        self._name = name

    async def upload_blob(
        self, data: bytes, *, overwrite: bool, content_type: str
    ) -> None:
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

    def __aiter__(self) -> _FakeAzureBlobIterator:
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


# ---------------------------------------------------------------------------
# Tests — LocalStorageAdapter gap coverage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_storage_delete_nonexistent(tmp_path) -> None:
    """delete() returns early without error when key doesn't exist (line 81)."""
    adapter = LocalStorageAdapter(LocalStorageSettings(base_path=tmp_path))
    await adapter.init()
    await adapter.delete("no/such/file.txt")  # should not raise


@pytest.mark.asyncio
async def test_local_storage_list_prefix_filters_mismatches(tmp_path) -> None:
    """_list_relative_paths continue branch fires when file doesn't match prefix (line 111)."""
    adapter = LocalStorageAdapter(LocalStorageSettings(base_path=tmp_path))
    await adapter.init()
    await adapter.save("alpha/a.txt", b"a")
    await adapter.save("beta/b.txt", b"b")
    result = await adapter.list("alpha/")
    assert result == ["alpha/a.txt"]  # beta/ file skipped by the continue branch


class _AzureErrorCodeNotFound(Exception):
    """Exception with error_code but no 404 status_code."""
    status_code = 200
    error_code = "BlobNotFound"


class _AzureMessageNotFound(Exception):
    """Exception with a 404 in the message."""
    status_code = 200
    error_code = None
    message = "Request failed with status 404"


class _AzureGenericError(Exception):
    """Non-not-found exception."""
    status_code = 500


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


# ---------------------------------------------------------------------------
# Azure coverage-gap tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_azure_health_returns_true() -> None:
    """health() calls container.exists() and returns True (lines 93-95)."""
    container = _FakeAzureContainerClient(name="demo")
    client = _FakeAzureServiceClient(container)
    adapter = AzureBlobStorageAdapter(
        AzureBlobStorageSettings(container="demo"), client=client
    )
    await adapter.init()
    assert await adapter.health() is True
    await adapter.cleanup()


def test_azure_ensure_container_raises_when_not_initialized() -> None:
    """_ensure_container raises LifecycleError when not initialized (line 150)."""
    from oneiric.core.lifecycle import LifecycleError

    adapter = AzureBlobStorageAdapter(AzureBlobStorageSettings(container="demo"))
    with pytest.raises(LifecycleError, match="azure-storage-container-not-initialized"):
        adapter._ensure_container()


@pytest.mark.asyncio
async def test_azure_download_reraises_non_notfound() -> None:
    """download() re-raises exceptions that are not not-found (line 130)."""
    class FailBlob:
        async def download_blob(self) -> None:
            raise _AzureGenericError("server error")

    class FailContainer:
        def get_blob_client(self, name: str) -> FailBlob:
            return FailBlob()

    adapter = AzureBlobStorageAdapter(AzureBlobStorageSettings(container="demo"))
    adapter._container_client = FailContainer()
    with pytest.raises(_AzureGenericError):
        await adapter.download("any.txt")


@pytest.mark.asyncio
async def test_azure_delete_reraises_non_notfound() -> None:
    """delete() re-raises non-not-found exceptions (lines 135-137)."""
    class FailBlob:
        async def delete_blob(self) -> None:
            raise _AzureGenericError("server error")

    class FailContainer:
        def get_blob_client(self, name: str) -> FailBlob:
            return FailBlob()

    adapter = AzureBlobStorageAdapter(AzureBlobStorageSettings(container="demo"))
    adapter._container_client = FailContainer()
    with pytest.raises(_AzureGenericError):
        await adapter.delete("any.txt")


def test_azure_is_not_found_via_error_code() -> None:
    """_is_not_found returns True when error_code is BlobNotFound (lines 157-159)."""
    adapter = AzureBlobStorageAdapter(AzureBlobStorageSettings(container="demo"))
    assert adapter._is_not_found(_AzureErrorCodeNotFound()) is True


def test_azure_is_not_found_via_message() -> None:
    """_is_not_found returns True when message contains '404' (lines 160-162)."""
    adapter = AzureBlobStorageAdapter(AzureBlobStorageSettings(container="demo"))
    assert adapter._is_not_found(_AzureMessageNotFound()) is True


def test_azure_is_not_found_returns_false() -> None:
    """_is_not_found returns False for generic exceptions (line 163)."""
    adapter = AzureBlobStorageAdapter(AzureBlobStorageSettings(container="demo"))
    assert adapter._is_not_found(_AzureGenericError("server error")) is False


@pytest.mark.asyncio
async def test_azure_init_with_connection_string(monkeypatch) -> None:
    """init() uses connection_string when provided (lines 65-76)."""
    import sys
    import types

    container = _FakeAzureContainerClient(name="demo")
    created_from_cs: list[str] = []

    class FakeBlobServiceClient:
        @classmethod
        def from_connection_string(cls, cs: str) -> "FakeBlobServiceClient":
            created_from_cs.append(cs)
            return cls()

        def get_container_client(self, name: str) -> _FakeAzureContainerClient:
            return container

        async def close(self) -> None:
            pass

    fake_blob = types.ModuleType("azure.storage.blob.aio")
    fake_blob.BlobServiceClient = FakeBlobServiceClient  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "azure", types.ModuleType("azure"))
    monkeypatch.setitem(sys.modules, "azure.storage", types.ModuleType("azure.storage"))
    monkeypatch.setitem(sys.modules, "azure.storage.blob", types.ModuleType("azure.storage.blob"))
    monkeypatch.setitem(sys.modules, "azure.storage.blob.aio", fake_blob)

    adapter = AzureBlobStorageAdapter(
        AzureBlobStorageSettings(container="demo", connection_string="DefaultEndpointsProtocol=https;...")
    )
    await adapter.init()
    assert created_from_cs == ["DefaultEndpointsProtocol=https;..."]
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_azure_init_with_account_url_and_credential(monkeypatch) -> None:
    """init() uses account_url + credential when connection_string absent (lines 77-82)."""
    import sys
    import types

    container = _FakeAzureContainerClient(name="demo")
    created_with_url: list[dict] = []

    class FakeBlobServiceClient:
        def __init__(self, *, account_url: str, credential: str) -> None:
            created_with_url.append({"account_url": account_url, "credential": credential})

        def get_container_client(self, name: str) -> _FakeAzureContainerClient:
            return container

        async def close(self) -> None:
            pass

    fake_blob = types.ModuleType("azure.storage.blob.aio")
    fake_blob.BlobServiceClient = FakeBlobServiceClient  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "azure", types.ModuleType("azure"))
    monkeypatch.setitem(sys.modules, "azure.storage", types.ModuleType("azure.storage"))
    monkeypatch.setitem(sys.modules, "azure.storage.blob", types.ModuleType("azure.storage.blob"))
    monkeypatch.setitem(sys.modules, "azure.storage.blob.aio", fake_blob)

    adapter = AzureBlobStorageAdapter(
        AzureBlobStorageSettings(container="demo", account_url="https://acc.blob.core.windows.net", credential="key123")
    )
    await adapter.init()
    assert created_with_url[0]["credential"] == "key123"
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_azure_init_missing_credential_raises(monkeypatch) -> None:
    """init() raises LifecycleError when account_url set but no credential (lines 78-79)."""
    import sys
    import types
    from oneiric.core.lifecycle import LifecycleError

    class FakeBlobServiceClient:
        pass

    fake_blob = types.ModuleType("azure.storage.blob.aio")
    fake_blob.BlobServiceClient = FakeBlobServiceClient  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "azure", types.ModuleType("azure"))
    monkeypatch.setitem(sys.modules, "azure.storage", types.ModuleType("azure.storage"))
    monkeypatch.setitem(sys.modules, "azure.storage.blob", types.ModuleType("azure.storage.blob"))
    monkeypatch.setitem(sys.modules, "azure.storage.blob.aio", fake_blob)

    adapter = AzureBlobStorageAdapter(
        AzureBlobStorageSettings(container="demo", account_url="https://acc.blob.core.windows.net")
    )
    with pytest.raises(LifecycleError, match="azure-storage-credential-required"):
        await adapter.init()


@pytest.mark.asyncio
async def test_azure_init_no_client_config_raises(monkeypatch) -> None:
    """init() raises LifecycleError when neither connection_string nor account_url set (lines 83-84)."""
    import sys
    import types
    from oneiric.core.lifecycle import LifecycleError

    class FakeBlobServiceClient:
        pass

    fake_blob = types.ModuleType("azure.storage.blob.aio")
    fake_blob.BlobServiceClient = FakeBlobServiceClient  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "azure", types.ModuleType("azure"))
    monkeypatch.setitem(sys.modules, "azure.storage", types.ModuleType("azure.storage"))
    monkeypatch.setitem(sys.modules, "azure.storage.blob", types.ModuleType("azure.storage.blob"))
    monkeypatch.setitem(sys.modules, "azure.storage.blob.aio", fake_blob)

    adapter = AzureBlobStorageAdapter(AzureBlobStorageSettings(container="demo"))
    with pytest.raises(LifecycleError, match="azure-storage-client-misconfigured"):
        await adapter.init()


# ---------------------------------------------------------------------------
# S3 coverage-gap tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_s3_health_with_healthcheck_key() -> None:
    """health() calls head_object when healthcheck_key is set (lines 102-105)."""
    client = _FakeS3Client()
    client.objects["probe.txt"] = b"alive"
    adapter = S3StorageAdapter(
        S3StorageSettings(bucket="demo", healthcheck_key="probe.txt"), client=client
    )
    await adapter.init()
    assert await adapter.health() is True
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_s3_cleanup_with_client_cm() -> None:
    """cleanup() calls client_cm.__aexit__ when set (line 113)."""
    exited: list[bool] = []

    class FakeClientCM:
        async def __aenter__(self) -> _FakeS3Client:
            return _FakeS3Client()

        async def __aexit__(self, *args: object) -> None:
            exited.append(True)

    adapter = S3StorageAdapter(S3StorageSettings(bucket="demo"))
    adapter._client_cm = FakeClientCM()
    adapter._client = _FakeS3Client()
    await adapter.cleanup()
    assert exited == [True]


@pytest.mark.asyncio
async def test_s3_download_reraises_non_nosuchkey() -> None:
    """download() re-raises when exception is not a NoSuchKey error (line 137)."""
    class FailClient(_FakeS3Client):
        async def get_object(self, Bucket: str, Key: str) -> Any:
            raise RuntimeError("connection lost")

    adapter = S3StorageAdapter(S3StorageSettings(bucket="demo"), client=FailClient())
    await adapter.init()
    with pytest.raises(RuntimeError):
        await adapter.download("key.txt")
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_s3_list_with_continuation_token() -> None:
    """list() handles paginated results using ContinuationToken (lines 157, 165-167)."""
    call_count = 0

    class PaginatedClient(_FakeS3Client):
        async def list_objects_v2(self, Bucket: str, Prefix: str = "", **kwargs: Any) -> dict:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "Contents": [{"Key": "a.txt"}],
                    "IsTruncated": True,
                    "NextContinuationToken": "token-2",
                }
            return {
                "Contents": [{"Key": "b.txt"}],
                "IsTruncated": False,
            }

    adapter = S3StorageAdapter(S3StorageSettings(bucket="demo"), client=PaginatedClient())
    await adapter.init()
    result = await adapter.list()
    assert result == ["a.txt", "b.txt"]
    assert call_count == 2


@pytest.mark.asyncio
async def test_s3_list_breaks_when_no_continuation_token() -> None:
    """list() breaks when IsTruncated but no NextContinuationToken (lines 165-167)."""
    call_count = 0

    class TruncatedNoTokenClient(_FakeS3Client):
        async def list_objects_v2(self, Bucket: str, Prefix: str = "", **kwargs: Any) -> dict:
            nonlocal call_count
            call_count += 1
            return {"Contents": [{"Key": "a.txt"}], "IsTruncated": True}

    adapter = S3StorageAdapter(S3StorageSettings(bucket="demo"), client=TruncatedNoTokenClient())
    await adapter.init()
    result = await adapter.list()
    assert result == ["a.txt"]
    assert call_count == 1  # stopped because no NextContinuationToken


@pytest.mark.asyncio
async def test_s3_init_with_client_factory() -> None:
    """init() uses client_factory when provided (lines 69-71)."""
    client = _FakeS3Client()

    async def factory() -> _FakeS3Client:
        return client

    adapter = S3StorageAdapter(S3StorageSettings(bucket="demo"), client_factory=factory)
    await adapter.init()
    assert adapter._client is client
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_s3_init_via_aioboto3(monkeypatch) -> None:
    """init() creates S3 client via aioboto3.Session when no factory/client (lines 73-96)."""
    import sys
    import types

    client = _FakeS3Client()
    created_sessions: list[dict] = []

    class FakeClientCM:
        async def __aenter__(self) -> _FakeS3Client:
            return client

        async def __aexit__(self, *args: object) -> None:
            pass

    class FakeSession:
        def __init__(self, **kwargs: Any) -> None:
            created_sessions.append(dict(kwargs))

        def client(self, **kwargs: Any) -> FakeClientCM:
            return FakeClientCM()

    class FakeConfig:
        def __init__(self, **kwargs: Any) -> None:
            pass

    class FakeBotocore:
        class config:
            Config = FakeConfig

    class FakeAioboto3:
        Session = FakeSession

    monkeypatch.setitem(sys.modules, "aioboto3", FakeAioboto3)  # type: ignore[arg-type]
    monkeypatch.setitem(sys.modules, "botocore", FakeBotocore)  # type: ignore[arg-type]
    monkeypatch.setitem(sys.modules, "botocore.config", FakeBotocore.config)  # type: ignore[arg-type]

    adapter = S3StorageAdapter(
        S3StorageSettings(bucket="demo", profile_name="dev", region="us-east-1")
    )
    await adapter.init()
    assert adapter._client is client
    assert created_sessions[0]["profile_name"] == "dev"
    assert created_sessions[0]["region_name"] == "us-east-1"
