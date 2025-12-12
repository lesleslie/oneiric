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
