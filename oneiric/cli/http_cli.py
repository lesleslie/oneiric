"""``oneiric http`` CLI subcommand — substrate HTTP server lifecycle.

Mirrors the ``oneiric start|stop|status`` orchestrator commands so the
HTTP substrate server is startable, stoppable, queryable for status, and
probeable for health in the same operator-facing way.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
from pathlib import Path

import typer

from oneiric.cli.base import ExitCode
from oneiric.core.logging import get_logger
from oneiric.http.server import SubstrateHTTPServer

logger = get_logger("cli.http")

DEFAULT_HTTP_PORT = 8081
DEFAULT_PID_FILE = Path(".oneiric_cache") / "http.pid"


def _resolve_port(port_option: int | None) -> int:
    if port_option is not None:
        return port_option
    env_port = os.getenv("ONEIRIC_HTTP_PORT")
    if env_port:
        try:
            return int(env_port)
        except ValueError:
            logger.warning("invalid-http-port-env", value=env_port)
    return DEFAULT_HTTP_PORT


def _resolve_pid_file(pid_file: str | None, cache_dir: str | None) -> Path:
    if pid_file is not None:
        return Path(pid_file)
    if cache_dir:
        return Path(cache_dir) / "http.pid"
    return DEFAULT_PID_FILE


def _is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _write_pid_file(path: Path, pid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{pid}\n")


def _read_pid_file(path: Path) -> int | None:
    try:
        text = path.read_text().strip()
    except FileNotFoundError:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _clear_pid_file(path: Path) -> None:
    path.unlink(missing_ok=True)


http_app = typer.Typer(help="Substrate HTTP server lifecycle.")


@http_app.command("start")
def http_start(
    host: str = typer.Option(
        "0.0.0.0", "--host", help="Interface for the substrate HTTP server."
    ),
    port: int | None = typer.Option(
        None,
        "--port",
        metavar="PORT",
        help="TCP port (defaults to $ONEIRIC_HTTP_PORT or 8081).",
    ),
    substrate_root: Path | None = typer.Option(
        None,
        "--substrate-root",
        metavar="PATH",
        help="Directory holding substrate JSON files (defaults to ~/.oneiric/substrate).",
    ),
    pid_file: Path | None = typer.Option(
        None,
        "--pid-file",
        metavar="PATH",
        help="Path to PID file (defaults to <cache_dir>/http.pid).",
    ),
    foreground: bool = typer.Option(
        False,
        "--foreground",
        help="Run in the foreground (do not detach). Default is detached background.",
    ),
    cache_dir: str | None = typer.Option(
        None,
        "--cache-dir",
        metavar="PATH",
        help="Override Oneiric cache directory for PID file placement.",
    ),
) -> None:
    """Start the substrate HTTP server (detached unless ``--foreground``)."""
    resolved_port = _resolve_port(port)
    resolved_pid = _resolve_pid_file(str(pid_file) if pid_file else None, cache_dir)

    existing_pid = _read_pid_file(resolved_pid)
    if existing_pid is not None and _is_pid_alive(existing_pid):
        typer.echo(
            f"HTTP server already running on PID {existing_pid} "
            f"(pid file: {resolved_pid})"
        )
        raise typer.Exit(code=ExitCode.ERROR)

    if not foreground:
        # Detach via subprocess so the CLI returns immediately.
        import subprocess
        import sys

        cmd = [
            sys.executable,
            "-m",
            "oneiric.cli",
            "http",
            "start",
            "--host",
            host,
            "--port",
            str(resolved_port),
            "--foreground",
        ]
        if substrate_root is not None:
            cmd.extend(["--substrate-root", str(substrate_root)])
        if cache_dir is not None:
            cmd.extend(["--cache-dir", cache_dir])
        if pid_file is not None:
            cmd.extend(["--pid-file", str(pid_file)])

        proc = subprocess.Popen(  # noqa: S603  # CLI detaches its own server
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        # Wait briefly for the child to write its PID file.
        for _ in range(50):
            if resolved_pid.exists():
                break
            import time

            time.sleep(0.1)
        typer.echo(
            f"HTTP server starting on http://{host}:{resolved_port} "
            f"(pid file: {resolved_pid}, detached pid: {proc.pid})"
        )
        return

    # Foreground path: run the async server loop and write our own PID.
    _write_pid_file(resolved_pid, os.getpid())
    try:
        server = SubstrateHTTPServer(
            host=host,
            port=resolved_port,
            substrate_root=substrate_root,
        )
        asyncio.run(_serve_forever(server))
    finally:
        _clear_pid_file(resolved_pid)


async def _serve_forever(server: SubstrateHTTPServer) -> None:
    await server.start()
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:  # pragma: no cover - cooperative shutdown
        pass
    finally:
        await server.stop()


@http_app.command("stop")
def http_stop(
    pid_file: Path | None = typer.Option(
        None, "--pid-file", metavar="PATH", help="Path to PID file."
    ),
    cache_dir: str | None = typer.Option(
        None, "--cache-dir", metavar="PATH", help="Cache directory override."
    ),
    timeout_seconds: float = typer.Option(
        5.0,
        "--timeout",
        metavar="SECONDS",
        help="Seconds to wait for graceful shutdown before SIGKILL.",
    ),
) -> None:
    """Stop the substrate HTTP server (reads PID file, sends SIGTERM)."""
    resolved_pid = _resolve_pid_file(str(pid_file) if pid_file else None, cache_dir)
    pid = _read_pid_file(resolved_pid)
    if pid is None or not _is_pid_alive(pid):
        typer.echo(f"HTTP server is not running (pid file: {resolved_pid})")
        _clear_pid_file(resolved_pid)
        raise typer.Exit(code=ExitCode.ERROR)

    import signal

    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        typer.echo(f"Failed to stop HTTP server (pid={pid}): {exc}")
        _clear_pid_file(resolved_pid)
        raise typer.Exit(code=ExitCode.ERROR) from exc

    # Wait up to timeout_seconds for the process to exit.
    import time

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _is_pid_alive(pid):
            break
        time.sleep(0.1)
    else:
        # Still alive after timeout — escalate.
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass

    _clear_pid_file(resolved_pid)
    typer.echo(f"HTTP server stopped (pid={pid})")


@http_app.command("status")
def http_status(
    host: str = typer.Option(
        "127.0.0.1", "--host", help="Interface to probe for live status."
    ),
    port: int | None = typer.Option(
        None,
        "--port",
        metavar="PORT",
        help="Port to probe (defaults to $ONEIRIC_HTTP_PORT or 8081).",
    ),
    pid_file: Path | None = typer.Option(
        None, "--pid-file", metavar="PATH", help="Path to PID file."
    ),
    cache_dir: str | None = typer.Option(
        None, "--cache-dir", metavar="PATH", help="Cache directory override."
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit status as JSON."
    ),
) -> None:
    """Show whether the substrate HTTP server is running."""
    resolved_port = _resolve_port(port)
    resolved_pid = _resolve_pid_file(str(pid_file) if pid_file else None, cache_dir)
    pid = _read_pid_file(resolved_pid)
    pid_alive = pid is not None and _is_pid_alive(pid)
    port_open = _probe_port(host, resolved_port)

    payload = {
        "running": pid_alive,
        "pid": pid,
        "pid_file": str(resolved_pid),
        "pid_file_exists": resolved_pid.exists(),
        "host": host,
        "port": resolved_port,
        "port_reachable": port_open,
    }

    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return

    if pid_alive:
        typer.echo(f"HTTP server is running (PID: {pid}, port: {resolved_port})")
    else:
        typer.echo("HTTP server is not running")
        if resolved_pid.exists():
            typer.echo(f"Stale PID file: {resolved_pid}")
    if port_open:
        typer.echo(f"Port {resolved_port} on {host}: reachable")
    else:
        typer.echo(f"Port {resolved_port} on {host}: unreachable")


@http_app.command("health")
def http_health(
    host: str = typer.Option(
        "127.0.0.1", "--host", help="Interface for the health probe."
    ),
    port: int | None = typer.Option(
        None,
        "--port",
        metavar="PORT",
        help="Port to probe (defaults to $ONEIRIC_HTTP_PORT or 8081).",
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit health as JSON."
    ),
) -> None:
    """Probe the substrate HTTP server's /health endpoint."""
    import httpx2 as httpx

    resolved_port = _resolve_port(port)
    url = f"http://{host}:{resolved_port}/health"
    try:
        response = httpx.get(url, timeout=2.0)
    except httpx.HTTPError as exc:
        typer.echo(f"HTTP server unreachable at {url}: {exc}")
        raise typer.Exit(code=ExitCode.UNAVAILABLE) from exc

    body: dict[str, object] = {}
    try:
        body = response.json()
    except (ValueError, json.JSONDecodeError):
        body = {"raw": response.text}

    if json_output:
        typer.echo(
            json.dumps(
                {
                    "url": url,
                    "status_code": response.status_code,
                    "body": body,
                },
                indent=2,
            )
        )
    else:
        typer.echo(f"GET {url} -> {response.status_code}")
        typer.echo(json.dumps(body, indent=2))

    if response.status_code != 200:
        raise typer.Exit(code=ExitCode.UNAVAILABLE)


def _probe_port(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


__all__ = ["http_app"]