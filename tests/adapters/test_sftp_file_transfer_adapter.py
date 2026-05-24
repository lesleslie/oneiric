from __future__ import annotations

import io
from typing import Any

import pytest

from oneiric.adapters.file_transfer.sftp import (
    SFTPFileTransferAdapter,
    SFTPFileTransferSettings,
)
from oneiric.core.lifecycle import LifecycleError


class _FakeListEntry:
    def __init__(self, filename: str) -> None:
        self.filename = filename


class _FakeSFTPClient:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    async def listdir(self, path: str) -> list[_FakeListEntry]:
        return [_FakeListEntry(name) for name in self.files if name.startswith(path)]

    async def put(self, buffer: io.BytesIO, remote_path: str) -> None:
        self.files[remote_path] = buffer.getvalue()

    async def get(self, remote_path: str, buffer: io.BytesIO) -> None:
        buffer.write(self.files.get(remote_path, b""))

    async def remove(self, remote_path: str) -> None:
        if remote_path not in self.files:
            raise FileNotFoundError
        del self.files[remote_path]

    async def exit(self) -> None: ...


class _FakeConn:
    def __init__(self, client: _FakeSFTPClient) -> None:
        self.client = client
        self.closed = False

    async def start_sftp_client(self) -> _FakeSFTPClient:
        return self.client

    async def close(self, *, wait_closed: bool = True) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_sftp_adapter_upload_download_delete() -> None:
    client = _FakeSFTPClient()
    conn = _FakeConn(client)

    async def factory(settings: SFTPFileTransferSettings) -> tuple[Any, Any]:
        return conn, client

    adapter = SFTPFileTransferAdapter(
        SFTPFileTransferSettings(host="localhost", username="demo"),
        client_factory=factory,
    )
    await adapter.init()

    await adapter.upload("demo.txt", b"hello")
    data = await adapter.download("demo.txt")
    assert data == b"hello"

    listing = await adapter.list(prefix="demo")
    assert listing == ["demo.txt"]

    assert await adapter.delete("demo.txt") is True
    assert await adapter.delete("missing.txt") is False

    await adapter.cleanup()
    assert conn.closed


@pytest.mark.asyncio
async def test_sftp_adapter_errors_raise_lifecycle_error() -> None:
    class BrokenClient(_FakeSFTPClient):
        async def put(self, buffer: io.BytesIO, remote_path: str) -> None:
            raise RuntimeError("boom")

    async def factory(settings: SFTPFileTransferSettings) -> tuple[Any, Any]:
        broken = BrokenClient()
        return _FakeConn(broken), broken

    adapter = SFTPFileTransferAdapter(
        SFTPFileTransferSettings(host="localhost", username="demo"),
        client_factory=factory,
    )
    with pytest.raises(LifecycleError):
        await adapter.upload("demo.txt", b"x")


# ---------------------------------------------------------------------------
# Tests — coverage gaps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sftp_init_reuses_provided_sftp_client() -> None:
    """init() returns early when sftp_client is pre-provided (lines 62-63)."""
    client = _FakeSFTPClient()
    conn = _FakeConn(client)
    adapter = SFTPFileTransferAdapter(
        SFTPFileTransferSettings(host="localhost", username="demo"),
        connection=conn,
        sftp_client=client,
    )
    await adapter.init()  # must not raise or re-create
    assert adapter._sftp is client


@pytest.mark.asyncio
async def test_sftp_health_returns_true() -> None:
    """health() calls listdir('.') and returns True (lines 106-109)."""
    client = _FakeSFTPClient()
    conn = _FakeConn(client)
    adapter = SFTPFileTransferAdapter(
        SFTPFileTransferSettings(host="localhost", username="demo"),
        sftp_client=client,
        connection=conn,
    )
    await adapter.init()
    assert await adapter.health() is True


@pytest.mark.asyncio
async def test_sftp_upload_exception_raises_lifecycle_error() -> None:
    """upload() wraps exceptions in LifecycleError (lines 119-121)."""

    class FailingClient(_FakeSFTPClient):
        async def put(self, buffer: io.BytesIO, remote_path: str) -> None:
            raise OSError("disk full")

    client = FailingClient()
    adapter = SFTPFileTransferAdapter(
        SFTPFileTransferSettings(host="localhost", username="demo"),
        sftp_client=client,
    )
    await adapter.init()
    with pytest.raises(LifecycleError, match="sftp-upload-failed"):
        await adapter.upload("fail.txt", b"data")


@pytest.mark.asyncio
async def test_sftp_download_exception_raises_lifecycle_error() -> None:
    """download() wraps exceptions in LifecycleError (lines 129-131)."""

    class FailingClient(_FakeSFTPClient):
        async def get(self, remote_path: str, buffer: io.BytesIO) -> None:
            raise OSError("read error")

    client = FailingClient()
    adapter = SFTPFileTransferAdapter(
        SFTPFileTransferSettings(host="localhost", username="demo"),
        sftp_client=client,
    )
    await adapter.init()
    with pytest.raises(LifecycleError, match="sftp-download-failed"):
        await adapter.download("fail.txt")


@pytest.mark.asyncio
async def test_sftp_delete_general_exception_raises_lifecycle_error() -> None:
    """delete() wraps non-FileNotFoundError exceptions in LifecycleError (lines 140-142)."""

    class FailingClient(_FakeSFTPClient):
        async def remove(self, remote_path: str) -> None:
            raise PermissionError("access denied")

    client = FailingClient()
    adapter = SFTPFileTransferAdapter(
        SFTPFileTransferSettings(host="localhost", username="demo"),
        sftp_client=client,
    )
    await adapter.init()
    with pytest.raises(LifecycleError, match="sftp-delete-failed"):
        await adapter.delete("fail.txt")


@pytest.mark.asyncio
async def test_sftp_list_exception_raises_lifecycle_error() -> None:
    """list() wraps exceptions in LifecycleError (lines 150-152)."""

    class FailingClient(_FakeSFTPClient):
        async def listdir(self, path: str) -> list:
            raise OSError("permission denied")

    client = FailingClient()
    adapter = SFTPFileTransferAdapter(
        SFTPFileTransferSettings(host="localhost", username="demo"),
        sftp_client=client,
    )
    await adapter.init()
    with pytest.raises(LifecycleError, match="sftp-list-failed"):
        await adapter.list()


@pytest.mark.asyncio
async def test_sftp_init_asyncssh_path_with_password(monkeypatch) -> None:
    """init() uses asyncssh.connect with password when no factory provided (lines 71-94)."""
    import sys

    from pydantic import SecretStr

    client = _FakeSFTPClient()
    conn = _FakeConn(client)

    class FakeAsyncSSH:
        @staticmethod
        async def connect(**kwargs: Any) -> _FakeConn:
            return conn

    monkeypatch.setitem(sys.modules, "asyncssh", FakeAsyncSSH)  # type: ignore[arg-type]

    adapter = SFTPFileTransferAdapter(
        SFTPFileTransferSettings(
            host="sftp.example.com",
            username="user",
            password=SecretStr("secret"),
            root_path="",  # skip chdir
        ),
    )
    await adapter.init()
    assert adapter._sftp is client
    assert adapter._conn is conn


@pytest.mark.asyncio
async def test_sftp_init_asyncssh_path_with_private_key_and_root(monkeypatch) -> None:
    """init() uses client_keys when private_key set and chdirs to root_path (lines 86-92)."""
    import sys

    chdirs: list[str] = []

    class ChdirClient(_FakeSFTPClient):
        async def chdir(self, path: str) -> None:
            chdirs.append(path)

    client = ChdirClient()
    conn = _FakeConn(client)

    class FakeAsyncSSH:
        @staticmethod
        async def connect(**kwargs: Any) -> _FakeConn:
            return conn

    monkeypatch.setitem(sys.modules, "asyncssh", FakeAsyncSSH)  # type: ignore[arg-type]

    adapter = SFTPFileTransferAdapter(
        SFTPFileTransferSettings(
            host="sftp.example.com",
            username="user",
            private_key="-----BEGIN RSA PRIVATE KEY-----",
            root_path="/uploads",
        ),
    )
    await adapter.init()
    assert chdirs == ["/uploads"]
