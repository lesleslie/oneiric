from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

import pytest

from oneiric.adapters.file_transfer.scp import (
    SCPFileTransferAdapter,
    SCPFileTransferSettings,
)
from oneiric.core.lifecycle import LifecycleError


class _FakeSSHResult:
    def __init__(
        self, *, stdout: str = "", stderr: str = "", exit_status: int = 0
    ) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.exit_status = exit_status


class _FakeSSHConnection:
    def __init__(self) -> None:
        self.remote_files: dict[str, bytes] = {}
        self.closed = False

    async def run(self, command: str, *, check: bool = False):
        parts = shlex.split(command)
        if not parts:
            raise AssertionError("empty command")
        if parts[0] == "ls" and parts[1:2] == ["-1"]:
            path = parts[2] if len(parts) > 2 else "."
            if path in (".", "./"):
                items = sorted(self.remote_files.keys())
            else:
                prefix = path.rstrip("/")
                items = sorted(
                    [key for key in self.remote_files if key.startswith(prefix)]
                )
            return _FakeSSHResult(stdout="\n".join(items))
        if parts[0:2] == ["rm", "-f"]:
            path = parts[2]
            self.remote_files.pop(path, None)
            return _FakeSSHResult()
        if parts[0:2] == ["test", "-e"]:
            path = parts[2]
            exists = path in self.remote_files
            return _FakeSSHResult(exit_status=0 if exists else 1)
        raise AssertionError(f"unexpected command: {command}")

    async def close(self, *, wait_closed: bool = True) -> None:
        self.closed = True


class _FakeAsyncSSH:
    def __init__(self, connection: _FakeSSHConnection) -> None:
        self.connection = connection

    async def scp(self, source: Any, destination: Any) -> None:
        if isinstance(destination, tuple):
            conn, remote_path = destination
            assert conn is self.connection
            data = Path(source).read_bytes()
            conn.remote_files[remote_path] = data
            return
        if isinstance(source, tuple):
            conn, remote_path = source
            assert conn is self.connection
            data = conn.remote_files.get(remote_path, b"")
            Path(destination).write_bytes(data)
            return
        raise AssertionError("unexpected scp arguments")


@pytest.mark.asyncio
async def test_scp_adapter_upload_download_delete() -> None:
    conn = _FakeSSHConnection()
    fake_asyncssh = _FakeAsyncSSH(conn)
    adapter = SCPFileTransferAdapter(
        SCPFileTransferSettings(host="localhost", username="demo"),
        connection=conn,
        asyncssh_module=fake_asyncssh,
    )

    await adapter.init()

    await adapter.upload("demo.txt", b"hello")
    assert conn.remote_files["demo.txt"] == b"hello"

    data = await adapter.download("demo.txt")
    assert data == b"hello"

    entries = await adapter.list()
    assert entries == ["demo.txt"]

    assert await adapter.delete("demo.txt") is True
    assert await adapter.delete("missing.txt") is False

    await adapter.cleanup()
    assert conn.closed is False  # connection owned externally


@pytest.mark.asyncio
async def test_scp_adapter_errors_raise_lifecycle_error() -> None:
    conn = _FakeSSHConnection()

    class BrokenAsyncSSH(_FakeAsyncSSH):
        async def scp(self, source: Any, destination: Any) -> None:  # type: ignore[override]
            raise RuntimeError("boom")

    adapter = SCPFileTransferAdapter(
        SCPFileTransferSettings(host="localhost", username="demo"),
        connection=conn,
        asyncssh_module=BrokenAsyncSSH(conn),
    )

    await adapter.init()
    with pytest.raises(LifecycleError):
        await adapter.upload("demo.txt", b"x")
