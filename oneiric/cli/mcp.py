"""``oneiric mcp`` CLI subcommand — FastMCP server lifecycle (REQ-007).

Mirrors the HTTP CLI's ``start|stop|status|health`` shape so the FastMCP
server can be operated the same way operators already start, stop, probe,
and query the substrate HTTP server.

Auth wiring (REQ-006): settings YAML drives provider configuration; env
vars override at runtime. :func:`_load_auth_from_settings` is the single
canonical path so the operator-facing error messages from
:mod:`oneiric.mcp.config` survive into production. The default
:func:`_build_provider_factories` returns ``{}`` so the CLI can be exercised
standalone; production environments wire their provider constructors
(e.g. JWT, OIDC) in the settings loader before calling ``start``.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import socket
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import typer
from mcp_common.auth.identity import IdentityProviderSpec
from mcp_common.auth.provider import IdentityProvider

from oneiric.cli.base import ExitCode
from oneiric.core.logging import get_logger
from oneiric.mcp.config import (
    OneiricMCPAuthConfig,
    load_auth_config,
    load_yaml_auth_section,
)

logger = get_logger("cli.mcp")

DEFAULT_MCP_PORT = 8681
DEFAULT_PID_FILE = Path(".oneiric_cache") / "mcp.pid"
DEFAULT_SETTINGS_PATH = Path.home() / ".oneiric" / "settings.yaml"


def _resolve_port(port_option: int | None) -> int:
    if port_option is not None:
        return port_option
    env_port = os.getenv("ONEIRIC_MCP_PORT")
    if env_port:
        try:
            return int(env_port)
        except ValueError:
            logger.warning("invalid-mcp-port-env", value=env_port)
    return DEFAULT_MCP_PORT


def _resolve_pid_file(pid_file: str | None, cache_dir: str | None) -> Path:
    if pid_file is not None:
        return Path(pid_file)
    if cache_dir:
        return Path(cache_dir) / "mcp.pid"
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


def _resolve_settings_path(settings_path: Path | None) -> Path:
    if settings_path is not None:
        return settings_path
    env_path = os.getenv("ONEIRIC_SETTINGS_PATH")
    if env_path:
        return Path(env_path)
    return DEFAULT_SETTINGS_PATH


def _load_auth_from_settings(settings_path: Path | None = None) -> OneiricMCPAuthConfig:
    """Load OneiricMCPAuthConfig from YAML + env-var overrides (REQ-006).

    Uses :func:`load_yaml_auth_section` so the operator-facing error
    messages from ``oneiric.mcp.config`` (YAML parse error, wrong-shape
    ``auth:`` section) propagate intact. Env vars
    (``ONEIRIC_AUTH_ENABLED``, ``ONEIRIC_AUTH_DEFAULT_PROVIDER``,
    ``ONEIRIC_AUTH_TRUSTED_ISSUERS``) override YAML values.
    """
    resolved = _resolve_settings_path(settings_path)
    raw = load_yaml_auth_section(resolved)
    return OneiricMCPAuthConfig.from_env(raw)


def _build_provider_factories() -> dict[
    str, Callable[[dict[str, Any]], IdentityProvider]
]:
    """Return the provider factory map wired into ``load_auth_config``.

    Extension point: this stub returns ``{}`` so the ``start`` command
    can be exercised in dev/CI without an operator-supplied provider.
    Production deployments wire their JWT/OIDC/etc. constructors here
    (or, more commonly, hand a pre-populated dict to ``start`` via the
    settings loader). When ``auth.enabled=True`` and this returns
    ``{}``, ``load_auth_config`` raises the documented ``RuntimeError`` —
    by design: opt-in auth must never silently start without providers.
    """
    return {}


def _probe_port(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _is_loopback_host(host: str) -> bool:
    """Return True iff every resolved address for ``host`` is a loopback address.

    Used by :func:`_enforce_public_network_auth_safety` to gate non-loopback
    binds on auth being enabled. Resolves the host via
    :func:`socket.getaddrinfo` so symbolic names (e.g. ``localhost``,
    ``myhost.local``) and dual-stack records are checked against every
    concrete address, not just the textual representation. Returns False on
    resolution failure (defensive — a host we cannot resolve is not safe to
    assume is loopback).
    """
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False
    if not infos:
        return False
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            return False
        ip_text = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_text)
        except ValueError:
            return False
        if not ip.is_loopback:
            return False
    return True


def _enforce_public_network_auth_safety(host: str, auth_enabled: bool) -> None:
    """Refuse to bind a FastMCP server to a non-loopback interface with auth disabled.

    Spec ruling (docs/superpowers/specs/2026-09-16-oneiric-fastmcp-pivot-design.md §8 Q3):
    FastMCP defaults to 127.0.0.1 so the missing-auth-network-exposure finding is
    eliminated by default. Operators who opt in to a public bind MUST also enable
    auth — the BearerTokenMiddleware is the only thing keeping the substrate
    tools from accepting anonymous writes over the network.

    Raises :class:`typer.BadParameter` (so the operator sees a usage-shaped
    error) when both: (a) ``host`` is non-loopback and (b) ``auth_enabled``
    is False. The check intentionally uses the *resolved* auth config
    (``mcp_auth_config.enabled`` post-``load_auth_config``), not the raw
    OneiricMCPAuthConfig — the resolved value drives whether
    ``build_mcp_server`` actually wires :class:`BearerTokenMiddleware`.
    """
    if auth_enabled:
        return
    if _is_loopback_host(host):
        return
    raise typer.BadParameter(
        f"refusing to bind FastMCP to non-loopback interface {host!r} with "
        "auth disabled. The substrate tools (read_settings, write_settings, "
        "schedule_task, etc.) would accept anonymous network writes. "
        "Either bind to a loopback address (127.0.0.1, ::1, localhost) OR "
        "enable auth: set auth.enabled=true in settings.yaml "
        "($ONEIRIC_SETTINGS_PATH) or set env var ONEIRIC_AUTH_ENABLED=1, "
        "and configure at least one provider in auth.providers.<name>.",
        param_hint="--host",
    )


mcp_app = typer.Typer(help="FastMCP server lifecycle (REQ-007).")


@mcp_app.command("start")
def mcp_start(
    host: str = typer.Option(
        "127.0.0.1", "--host", help="Interface for the FastMCP server."
    ),
    port: int | None = typer.Option(
        None,
        "--port",
        metavar="PORT",
        help="TCP port (defaults to $ONEIRIC_MCP_PORT or 8681).",
    ),
    settings_path: Path | None = typer.Option(
        None,
        "--settings",
        metavar="PATH",
        help="Path to oneiric settings.yaml (defaults to $ONEIRIC_SETTINGS_PATH or ~/.oneiric/settings.yaml).",
    ),
    pid_file: Path | None = typer.Option(
        None,
        "--pid-file",
        metavar="PATH",
        help="Path to PID file (defaults to <cache_dir>/mcp.pid).",
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
    """Start the FastMCP server (detached unless ``--foreground``)."""
    from oneiric.mcp.server import build_mcp_server

    resolved_port = _resolve_port(port)
    resolved_pid = _resolve_pid_file(str(pid_file) if pid_file else None, cache_dir)

    existing_pid = _read_pid_file(resolved_pid)
    if existing_pid is not None and _is_pid_alive(existing_pid):
        typer.echo(
            f"MCP server already running on PID {existing_pid} "
            f"(pid file: {resolved_pid})"
        )
        raise typer.Exit(code=ExitCode.ERROR)

    auth_config = _load_auth_from_settings(settings_path)
    provider_factories = _build_provider_factories()
    mcp_auth_config, mcp_providers = load_auth_config(
        auth_config, provider_factories=provider_factories
    )

    # Guard spec §8 Q3: refuse to bind a non-loopback interface when auth is
    # disabled. Runs *after* load_auth_config so the resolved
    # ``mcp_auth_config.enabled`` is what ``build_mcp_server`` will act on;
    # runs *before* both the foreground run_async path and the detached
    # subprocess spawn, so the unauthorized child is never created.
    _enforce_public_network_auth_safety(
        host=host,
        auth_enabled=bool(mcp_auth_config.enabled),
    )
    server = build_mcp_server(
        config=SimpleNamespace(name="oneiric"),
        auth_config=mcp_auth_config,
        providers=mcp_providers,
    )

    if not foreground:
        # Detach via subprocess so the CLI returns immediately.
        import subprocess
        import sys

        cmd = [
            sys.executable,
            "-m",
            "oneiric.cli",
            "mcp",
            "start",
            "--host",
            host,
            "--port",
            str(resolved_port),
            "--foreground",
        ]
        if settings_path is not None:
            cmd.extend(["--settings", str(settings_path)])
        if cache_dir is not None:
            cmd.extend(["--cache-dir", cache_dir])
        if pid_file is not None:
            cmd.extend(["--pid-file", str(pid_file)])

        proc = subprocess.Popen(  # CLI detaches its own server
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
            f"MCP server starting on http://{host}:{resolved_port} "
            f"(pid file: {resolved_pid}, detached pid: {proc.pid})"
        )
        return

    # Foreground path: run the async server loop and write our own PID.
    _write_pid_file(resolved_pid, os.getpid())

    async def _serve_forever() -> None:
        await server.run_async(host=host, port=resolved_port)  # type: ignore[attr-defined]

    try:
        asyncio.run(_serve_forever())
    except KeyboardInterrupt:  # pragma: no cover - cooperative shutdown
        logger.info("mcp-cli-foreground-interrupted")
    finally:
        _clear_pid_file(resolved_pid)


@mcp_app.command("stop")
def mcp_stop(
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
    """Stop the FastMCP server (reads PID file, sends SIGTERM)."""
    resolved_pid = _resolve_pid_file(str(pid_file) if pid_file else None, cache_dir)
    pid = _read_pid_file(resolved_pid)
    if pid is None or not _is_pid_alive(pid):
        typer.echo(f"MCP server is not running (pid file: {resolved_pid})")
        _clear_pid_file(resolved_pid)
        raise typer.Exit(code=ExitCode.ERROR)

    import signal

    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        typer.echo(f"Failed to stop MCP server (pid={pid}): {exc}")
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
        with suppress(OSError):
            os.kill(pid, signal.SIGKILL)

    _clear_pid_file(resolved_pid)
    typer.echo(f"MCP server stopped (pid={pid})")


@mcp_app.command("status")
def mcp_status(
    host: str = typer.Option(
        "127.0.0.1", "--host", help="Interface to probe for live status."
    ),
    port: int | None = typer.Option(
        None,
        "--port",
        metavar="PORT",
        help="Port to probe (defaults to $ONEIRIC_MCP_PORT or 8681).",
    ),
    pid_file: Path | None = typer.Option(
        None, "--pid-file", metavar="PATH", help="Path to PID file."
    ),
    cache_dir: str | None = typer.Option(
        None, "--cache-dir", metavar="PATH", help="Cache directory override."
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit status as JSON."),
) -> None:
    """Show whether the FastMCP server is running."""
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
        typer.echo(f"MCP server is running (PID: {pid}, port: {resolved_port})")
    else:
        typer.echo("MCP server is not running")
        if resolved_pid.exists():
            typer.echo(f"Stale PID file: {resolved_pid}")
    if port_open:
        typer.echo(f"Port {resolved_port} on {host}: reachable")
    else:
        typer.echo(f"Port {resolved_port} on {host}: unreachable")


@mcp_app.command("health")
def mcp_health(
    host: str = typer.Option(
        "127.0.0.1", "--host", help="Interface for the health probe."
    ),
    port: int | None = typer.Option(
        None,
        "--port",
        metavar="PORT",
        help="Port to probe (defaults to $ONEIRIC_MCP_PORT or 8681).",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit health as JSON."),
) -> None:
    """Probe the FastMCP server's /health endpoint."""
    import httpx2 as httpx

    resolved_port = _resolve_port(port)
    url = f"http://{host}:{resolved_port}/health"
    try:
        response = httpx.get(url, timeout=2.0)
    except httpx.HTTPError as exc:
        typer.echo(f"MCP server unreachable at {url}: {exc}")
        raise typer.Exit(code=ExitCode.UNAVAILABLE) from exc

    body: dict[str, object] = {}
    try:
        body = response.json()
    except ValueError, json.JSONDecodeError:
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


__all__ = [
    "IdentityProviderSpec",
    "_build_provider_factories",
    "_clear_pid_file",
    "_enforce_public_network_auth_safety",
    "_is_loopback_host",
    "_is_pid_alive",
    "_load_auth_from_settings",
    "_read_pid_file",
    "_resolve_pid_file",
    "_resolve_port",
    "mcp_app",
]
