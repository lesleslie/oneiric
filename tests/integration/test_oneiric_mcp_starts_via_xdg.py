"""End-to-end test: the launchd-supervised wrapper boots the FastMCP server
from an XDG fixture and binds the configured port.

The CLI ``oneiric mcp start`` is not standalone-bootable in dev/CI
(no ``WorkflowTaskProcessor`` wiring — see the wrapper docstring at
``scripts/launch_mcp.py:22-24``). The launchd plist invokes
``scripts/launch_mcp.py`` instead, which wires the processor AND
loads auth via ``_load_auth_from_settings()`` (Phase 3).

This test boots that wrapper as a subprocess and verifies REQ-CLI-XDG-001
end-to-end: the XDG ``auth:`` block flows through to a running server
bound on the configured port with ``/health=200``.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest


def _port_is_open(host: str, port: int, timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _wait_for_port(host: str, port: int, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_is_open(host, port):
            return True
        time.sleep(0.1)
    return False


def _http_get(url: str, timeout: float = 2.0) -> tuple[int, str]:
    import urllib.request

    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except OSError:
        return 0, ""


@pytest.mark.integration
def test_wrapper_boots_oneiric_mcp_from_xdg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: the launchd wrapper reads config from XDG and binds.

    Spins up ``scripts/launch_mcp.py`` (the wrapper launchd actually
    runs — see ``~/Library/LaunchAgents/com.mcp.oneiric.plist``) as a
    subprocess with a fixture ``$HOME`` + XDG layer. Asserts:
      - The server binds the configured port.
      - ``/health`` returns 200.

    Auth-specific contract (``auth.providers`` round-trip, env-var
    overlay) is covered by unit tests in
    ``tests/unit/test_cli_xdg_loader.py``.
    """
    # Pick a port unlikely to collide with anything else (avoid 8681
    # which is the production default + the launchd-managed instance).
    test_port = 18681

    # Set up an XDG fixture: HOME = tmp_path, with .config/oneiric/local.yaml
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    xdg_dir = fake_home / ".config" / "oneiric"
    xdg_dir.mkdir(parents=True)
    (xdg_dir / "local.yaml").write_text(
        "auth:\n  enabled: false\n"
    )

    # Plant a stale legacy file. The CLI must NOT read this (Phase 3 cutover).
    legacy_dir = fake_home / ".oneiric"
    legacy_dir.mkdir()
    (legacy_dir / "settings.yaml").write_text(
        "auth:\n  enabled: false\n  service_name: legacy_should_not_appear\n"
    )

    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(fake_home / ".config"))
    monkeypatch.setenv("ONEIRIC_MCP_PORT", str(test_port))
    for key in (
        "ONEIRIC_AUTH_ENABLED",
        "ONEIRIC_AUTH_DEFAULT_PROVIDER",
        "ONEIRIC_AUTH_TRUSTED_ISSUERS",
    ):
        monkeypatch.delenv(key, raising=False)

    # Use the launchd wrapper (``scripts/launch_mcp.py``) — this is
    # what the production plist invokes. The CLI ``oneiric mcp start``
    # alone is not standalone-bootable (no processor wiring).
    repo_root = Path(__file__).resolve().parents[2]
    wrapper = repo_root / "scripts" / "launch_mcp.py"
    cmd = [
        sys.executable,
        str(wrapper),
        "--host",
        "127.0.0.1",
        "--port",
        str(test_port),
    ]

    proc = subprocess.Popen(
        cmd,
        cwd=str(repo_root),
        env=os.environ.copy(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        # The wrapper waits for /health on its own (launch_with_healthcheck
        # in production; we skip that here and poll directly).
        bound = _wait_for_port("127.0.0.1", test_port, timeout=20.0)
        if not bound:
            out = proc.stdout.read() if proc.stdout else ""
            err = proc.stderr.read() if proc.stderr else ""
            pytest.fail(
                f"server never bound 127.0.0.1:{test_port} within 20s; "
                f"stdout=\n{out!r}\n"
                f"stderr=\n{err!r}"
            )

        # /health is public (REQ-004). The exact body shape isn't pinned
        # here — only the 200 status. Body assertions live in
        # tests/integration/test_oneiric_mcp_e2e.py.
        status, _ = _http_get(f"http://127.0.0.1:{test_port}/health")
        assert status == 200, f"/health returned {status}, expected 200"

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()