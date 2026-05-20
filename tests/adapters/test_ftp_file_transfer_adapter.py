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
async def test_ftp_init_reuses_provided_client() -> None:
    """init() returns early when client is pre-provided (lines 56-58)."""
    client = _FakeFTPClient()
    adapter = FTPFileTransferAdapter(
        FTPFileTransferSettings(host="localhost", username="u", password=SecretStr("p")),
        client=client,
    )
    await adapter.init()
    assert adapter._client is client


@pytest.mark.asyncio
async def test_ftp_init_with_factory() -> None:
    """init() uses client_factory when provided (lines 59-63)."""
    client = _FakeFTPClient()

    def factory(settings: FTPFileTransferSettings) -> _FakeFTPClient:
        return client

    adapter = FTPFileTransferAdapter(
        FTPFileTransferSettings(host="localhost", username="u", password=SecretStr("p")),
        client_factory=factory,
    )
    await adapter.init()
    assert adapter._client is client
    assert adapter._owns_client is True
    await adapter.cleanup()  # covers cleanup line 87 (_owns_client=True)
    assert adapter._client is None


@pytest.mark.asyncio
async def test_ftp_health_returns_true() -> None:
    """health() awaits list() and returns True (lines 95-98)."""

    class AwaitableListClient(_FakeFTPClient):
        async def list(self, prefix: str) -> list:
            return []

    adapter = FTPFileTransferAdapter(
        FTPFileTransferSettings(host="localhost", username="u", password=SecretStr("p")),
        client=AwaitableListClient(),
    )
    await adapter.init()
    assert await adapter.health() is True


@pytest.mark.asyncio
async def test_ftp_download_exception_raises_lifecycle_error() -> None:
    """download() wraps exceptions in LifecycleError (lines 120-122)."""
    class BrokenDownload(_FakeFTPClient):
        @asynccontextmanager
        async def download_stream(self, remote_path: str):
            raise OSError("read error")
            yield  # pragma: no cover

    adapter = FTPFileTransferAdapter(
        FTPFileTransferSettings(host="localhost", username="u", password=SecretStr("p")),
        client=BrokenDownload(),
    )
    await adapter.init()
    with pytest.raises(LifecycleError, match="ftp-download-failed"):
        await adapter.download("fail.txt")


@pytest.mark.asyncio
async def test_ftp_delete_general_exception_raises() -> None:
    """delete() wraps non-FileNotFoundError exceptions (lines 131-133)."""
    class PermDenied(_FakeFTPClient):
        async def remove_file(self, remote_path: str) -> None:
            raise PermissionError("access denied")

    adapter = FTPFileTransferAdapter(
        FTPFileTransferSettings(host="localhost", username="u", password=SecretStr("p")),
        client=PermDenied(),
    )
    await adapter.init()
    with pytest.raises(LifecycleError, match="ftp-delete-failed"):
        await adapter.delete("file.txt")


@pytest.mark.asyncio
async def test_ftp_list_exception_raises_lifecycle_error() -> None:
    """list() wraps exceptions in LifecycleError (lines 143-145)."""
    class BrokenList(_FakeFTPClient):
        async def list(self, prefix: str):
            raise OSError("list failed")
            yield  # pragma: no cover - async generator stub

    adapter = FTPFileTransferAdapter(
        FTPFileTransferSettings(host="localhost", username="u", password=SecretStr("p")),
        client=BrokenList(),
    )
    await adapter.init()
    with pytest.raises(LifecycleError, match="ftp-list-failed"):
        await adapter.list()


def test_ftp_ensure_client_raises_when_not_initialized() -> None:
    """_ensure_client raises LifecycleError when client is not set (line 149)."""
    adapter = FTPFileTransferAdapter(
        FTPFileTransferSettings(host="localhost", username="u", password=SecretStr("p"))
    )
    with pytest.raises(LifecycleError, match="ftp-client-not-initialized"):
        adapter._ensure_client()


@pytest.mark.asyncio
async def test_ftp_init_aioftp_path(monkeypatch) -> None:
    """init() creates aioftp.ClientSession when no factory provided (lines 64-83)."""
    import sys
    import types

    chdir_calls: list[str] = []

    class FakeSession:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def connect(self) -> None:
            pass

        async def login(self) -> None:
            pass

        async def change_directory(self, path: str) -> None:
            chdir_calls.append(path)

        async def quit(self) -> None:
            pass

    class FakeAioftp:
        ClientSession = FakeSession

    monkeypatch.setitem(sys.modules, "aioftp", FakeAioftp)  # type: ignore[arg-type]

    adapter = FTPFileTransferAdapter(
        FTPFileTransferSettings(
            host="ftp.example.com",
            username="user",
            password=SecretStr("secret"),
            ssl=True,
            root_path="/uploads",
        ),
    )
    await adapter.init()
    assert isinstance(adapter._client, FakeSession)
    assert chdir_calls == ["/uploads"]


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
