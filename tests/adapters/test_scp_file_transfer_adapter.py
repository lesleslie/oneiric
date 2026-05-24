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


# ---------------------------------------------------------------------------
# Tests — coverage gaps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scp_init_factory_path() -> None:
    """init() uses client_factory when provided (lines 70-74)."""
    conn = _FakeSSHConnection()

    async def factory(settings: SCPFileTransferSettings) -> _FakeSSHConnection:
        return conn

    adapter = SCPFileTransferAdapter(
        SCPFileTransferSettings(host="localhost", username="u"),
        client_factory=factory,
    )
    await adapter.init()
    assert adapter._conn is conn
    assert adapter._owns_conn is True
    await adapter.cleanup()
    assert conn.closed is True


@pytest.mark.asyncio
async def test_scp_init_asyncssh_module_path() -> None:
    """init() uses injected asyncssh_module when no factory/connection (lines 76-99)."""
    conn = _FakeSSHConnection()
    fake_asyncssh = _FakeAsyncSSH(conn)

    class FakeAsyncSSHModule:
        async def connect(self, **kwargs: Any) -> _FakeSSHConnection:
            return conn

    module = FakeAsyncSSHModule()
    module.scp = fake_asyncssh.scp  # type: ignore[attr-defined]

    adapter = SCPFileTransferAdapter(
        SCPFileTransferSettings(host="host.example.com", username="user"),
        asyncssh_module=module,
    )
    await adapter.init()
    assert adapter._conn is conn
    assert adapter._owns_conn is True


@pytest.mark.asyncio
async def test_scp_init_imports_asyncssh_from_sys_modules(monkeypatch) -> None:
    """init() imports asyncssh when _asyncssh is None (lines 77-84)."""
    import sys

    conn = _FakeSSHConnection()
    _FakeAsyncSSH(conn)

    class FakeAsyncSSHModule:
        async def connect(self, **kwargs: Any) -> _FakeSSHConnection:
            return conn

        async def scp(self, *args: Any, **kwargs: Any) -> None:
            pass

    module = FakeAsyncSSHModule()
    monkeypatch.setitem(sys.modules, "asyncssh", module)  # type: ignore[arg-type]

    adapter = SCPFileTransferAdapter(
        SCPFileTransferSettings(host="host.example.com", username="user"),
        # no asyncssh_module injected — forces the import branch
    )
    await adapter.init()
    assert adapter._asyncssh is module
    assert adapter._conn is conn


@pytest.mark.asyncio
async def test_scp_init_asyncssh_with_password_and_key() -> None:
    """init() injects password and client_keys into connect_kwargs (lines 92-95)."""
    from pydantic import SecretStr

    conn = _FakeSSHConnection()
    connect_kwargs_captured: list[dict] = []

    class FakeAsyncSSHModule:
        async def connect(self, **kwargs: Any) -> _FakeSSHConnection:
            connect_kwargs_captured.append(kwargs)
            return conn

    module = FakeAsyncSSHModule()
    module.scp = _FakeAsyncSSH(conn).scp  # type: ignore[attr-defined]

    adapter = SCPFileTransferAdapter(
        SCPFileTransferSettings(
            host="host.example.com",
            username="user",
            password=SecretStr("secret"),
            private_key="-----BEGIN RSA PRIVATE KEY-----",
        ),
        asyncssh_module=module,
    )
    await adapter.init()
    assert connect_kwargs_captured[0]["password"] == "secret"
    assert (
        "-----BEGIN RSA PRIVATE KEY-----" in connect_kwargs_captured[0]["client_keys"]
    )


@pytest.mark.asyncio
async def test_scp_cleanup_owned_connection() -> None:
    """cleanup() calls close() when _owns_conn=True (line 103)."""
    conn = _FakeSSHConnection()
    fake_asyncssh = _FakeAsyncSSH(conn)
    adapter = SCPFileTransferAdapter(
        SCPFileTransferSettings(host="localhost", username="demo"),
        asyncssh_module=fake_asyncssh,
    )
    adapter._conn = conn
    adapter._owns_conn = True
    await adapter.cleanup()
    assert conn.closed is True
    assert adapter._conn is None


@pytest.mark.asyncio
async def test_scp_health_returns_true() -> None:
    """health() runs ls command and returns True on success (lines 108-114)."""
    conn = _FakeSSHConnection()
    fake_asyncssh = _FakeAsyncSSH(conn)
    adapter = SCPFileTransferAdapter(
        SCPFileTransferSettings(host="localhost", username="demo"),
        connection=conn,
        asyncssh_module=fake_asyncssh,
    )
    await adapter.init()
    assert await adapter.health() is True


@pytest.mark.asyncio
async def test_scp_health_returns_false_on_lifecycle_error() -> None:
    """health() returns False when _run_command raises LifecycleError (lines 113-114)."""

    class FailConn(_FakeSSHConnection):
        async def run(self, command: str, *, check: bool = False) -> Any:
            raise OSError("connection lost")

    conn = FailConn()
    adapter = SCPFileTransferAdapter(
        SCPFileTransferSettings(host="localhost", username="demo"),
        connection=conn,
        asyncssh_module=_FakeAsyncSSH(conn),
    )
    await adapter.init()
    # _run_command wraps OSError in LifecycleError → health returns False
    assert await adapter.health() is False


@pytest.mark.asyncio
async def test_scp_run_command_nonzero_exit_raises() -> None:
    """_run_command raises LifecycleError on non-zero exit status (lines 165-171)."""

    class NonZeroConn(_FakeSSHConnection):
        async def run(self, command: str, *, check: bool = False) -> _FakeSSHResult:
            return _FakeSSHResult(exit_status=1, stderr="permission denied")

    conn = NonZeroConn()
    adapter = SCPFileTransferAdapter(
        SCPFileTransferSettings(host="localhost", username="demo"),
        connection=conn,
        asyncssh_module=_FakeAsyncSSH(conn),
    )
    await adapter.init()
    with pytest.raises(LifecycleError, match="scp-command-failed"):
        await adapter._run_command("ls -1 .")


def test_scp_resolve_remote_path_absolute() -> None:
    """_resolve_remote_path returns normalized absolute path (line 177)."""
    adapter = SCPFileTransferAdapter(
        SCPFileTransferSettings(host="localhost", username="demo")
    )
    result = adapter._resolve_remote_path("/absolute/path/../file.txt")
    assert result == "/absolute/file.txt"


def test_scp_ensure_connection_raises_when_not_initialized() -> None:
    """_ensure_connection raises LifecycleError when conn is None (line 183)."""
    adapter = SCPFileTransferAdapter(
        SCPFileTransferSettings(host="localhost", username="demo")
    )
    with pytest.raises(LifecycleError, match="scp-connection-not-initialized"):
        adapter._ensure_connection()


def test_scp_ensure_asyncssh_raises_when_not_available() -> None:
    """_ensure_asyncssh raises LifecycleError when asyncssh is None (line 188)."""
    conn = _FakeSSHConnection()
    adapter = SCPFileTransferAdapter(
        SCPFileTransferSettings(host="localhost", username="demo"),
        connection=conn,
    )
    with pytest.raises(LifecycleError, match="scp-asyncssh-not-available"):
        adapter._ensure_asyncssh()
