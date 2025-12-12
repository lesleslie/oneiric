from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from pydantic import SecretStr

from oneiric.adapters.file_transfer.ftp import (
    FTPFileTransferAdapter,
    FTPFileTransferSettings,
)
from oneiric.core.lifecycle import LifecycleError


class _FakeStream:
    def __init__(self) -> None:
        self.buffer: bytearray = bytearray()

    async def write(self, data: bytes) -> None:
        self.buffer.extend(data)

    async def iter_by_block(self) -> AsyncIterator[bytes]:
        yield bytes(self.buffer)


class _FakeFTPClient:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.list_calls: list[str] = []

    async def connect(self) -> None: ...

    async def login(self) -> None: ...

    async def change_directory(self, _path: str) -> None: ...

    async def quit(self) -> None: ...

    @asynccontextmanager
    async def upload_stream(self, remote_path: str) -> AsyncIterator[_FakeStream]:
        stream = _FakeStream()
        yield stream
        self.files[remote_path] = bytes(stream.buffer)

    @asynccontextmanager
    async def download_stream(self, remote_path: str) -> AsyncIterator[_FakeStream]:
        stream = _FakeStream()
        stream.buffer.extend(self.files.get(remote_path, b""))
        yield stream

    async def remove_file(self, remote_path: str) -> None:
        if remote_path not in self.files:
            raise FileNotFoundError
        del self.files[remote_path]

    async def list(self, prefix: str) -> AsyncIterator[tuple[str, Any]]:
        self.list_calls.append(prefix)
        for key in sorted(self.files.keys()):
            if key.startswith(prefix):
                yield (key, None)


@pytest.mark.asyncio
async def test_ftp_adapter_upload_download_delete() -> None:
    client = _FakeFTPClient()

    adapter = FTPFileTransferAdapter(
        FTPFileTransferSettings(
            host="localhost",
            username="demo",
            password=SecretStr("pass"),
        ),
        client=client,
    )
    await adapter.init()

    await adapter.upload("demo.txt", b"hello")
    assert client.files["demo.txt"] == b"hello"

    data = await adapter.download("demo.txt")
    assert data == b"hello"

    entries = await adapter.list(prefix="demo")
    assert entries == ["demo.txt"]

    assert await adapter.delete("demo.txt") is True
    assert await adapter.delete("missing.txt") is False

    await adapter.cleanup()


@pytest.mark.asyncio
async def test_ftp_adapter_errors_raise_lifecycle_error() -> None:
    class BrokenClient(_FakeFTPClient):
        @asynccontextmanager
        async def upload_stream(self, remote_path: str):
            raise RuntimeError("broken")
            yield  # pragma: no cover

    adapter = FTPFileTransferAdapter(
        FTPFileTransferSettings(
            host="localhost",
            username="demo",
            password=SecretStr("pass"),
        ),
        client=BrokenClient(),
    )
    await adapter.init()
    with pytest.raises(LifecycleError):
        await adapter.upload("demo.txt", b"x")
    await adapter.cleanup()
