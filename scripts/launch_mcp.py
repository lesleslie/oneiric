#!/usr/bin/env python3
"""Launch wrapper for the Oneiric FastMCP server (mcp-common launcher edition).

Phase 2 commit 2.5a of the 2026-09-26-mcp-launcher-standardization plan.

Public invocation from launchd ``com.mcp.oneiric.plist``:

    /Users/les/Projects/oneiric/.venv/bin/python \\
    /Users/les/Projects/oneiric/scripts/launch_mcp.py \\
    /Users/les/.oneiric/settings.yaml \\
    --host 127.0.0.1 --port 8681

The wrapper collapses the prior ad-hoc boot sequence (manual
``Resolver + LifecycleManager + WorkflowBridge + WorkflowTaskProcessor``
wiring, manual ``health_feeds`` warm-up, manual
``run_async(transport='http')``) into a single ``mcp_common.server.launcher
.launch()`` call. The launcher handles ``~/.config/secrets.env`` loading,
``settings`` feed warming (only ``settings`` — ``context`` and ``progress``
populate via tool calls), HTTP transport, and uvicorn
``timeout_graceful_shutdown=30``.

The vendored ``oneiric mcp start`` CLI (oneiric/cli/mcp.py) has a
dormant gap (no ``WorkflowTaskProcessor`` wiring, stdio transport); that
fix lands in Phase 2 commits 2.5b / 2.5c.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Venv bootstrap: the wrapper's shebang (`#!/usr/bin/env python3`) resolves to
# whatever python3 is in launchd's $PATH — typically Homebrew's system python
# (e.g. /usr/local/bin/python3 → /usr/local/Cellar/python@3.14/...). That python
# is the SAME binary as the venv's `.venv/bin/python` (both symlink to the same
# Homebrew cellar file), but the venv's site-packages aren't on sys.path unless
# Python was launched via the venv's binary. Fix: prepend the venv's
# site-packages to sys.path. Idempotent — no-op when the venv is already active
# (sys.prefix is already under `_REPO_ROOT/.venv`).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_VENV_ROOT = _REPO_ROOT / ".venv"
_VENV_SITE_PACKAGES = _VENV_ROOT / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
try:
    _VENV_SITE_PACKAGES_REL = _VENV_SITE_PACKAGES.relative_to(Path(sys.prefix))
    _IN_VENV = True
except ValueError:
    _IN_VENV = False
if not _IN_VENV and _VENV_SITE_PACKAGES.is_dir():
    sys.path.insert(0, str(_VENV_SITE_PACKAGES))

import argparse
import asyncio
import signal
from types import SimpleNamespace

from mcp_common.server import launch


def _install_sigterm_handler() -> None:
    """REQ-014 — SIGTERM exits 0 (not -15) so launchd ``KeepAlive`` does not loop.

    FastMCP / uvicorn complete graceful shutdown but the Python process
    inherits the OS-level SIGTERM default disposition (returncode 128+15 =
    -15). The wrapper installs an explicit handler so incident-response
    scripts that key on returncode=0 distinguish clean shutdowns from
    signals. ``os._exit(0)`` is preferred for lifespan-teardown edge cases
    per the cookbook Trap G notes; ``sys.exit(0)`` is sufficient for the
    common path the wrapper occupies.
    """
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))


def _build_processor():
    """Construct the ``WorkflowTaskProcessor`` the launcher needs.

    Mirrors the production loader the launchd plist references (see
    ``oneiric.mcp.server._resolve_processor`` docstring: *"future
    production loaders will build a processor from a WorkflowBridge when
    processor is not supplied"*). The processor is mandatory —
    ``_register_scheduler_tools`` raises ``RuntimeError("schedule_task
    requires a processor; none supplied.")`` at startup if it is not
    supplied (oneiric/mcp/server.py:300-322).
    """
    from oneiric.core.config import LayerSettings
    from oneiric.core.lifecycle import LifecycleManager
    from oneiric.core.resolution import Resolver
    from oneiric.domains.workflows import WorkflowBridge
    from oneiric.mcp.scheduler import WorkflowTaskProcessor

    layer_settings = LayerSettings()
    resolver = Resolver()
    lifecycle = LifecycleManager(resolver)
    workflow_bridge = WorkflowBridge(
        resolver=resolver,
        lifecycle=lifecycle,
        settings=layer_settings,
    )
    return WorkflowTaskProcessor(workflow_bridge)


def _build_warm_settings_feed():
    """Pre-warm oneiric's ``settings`` HealthFeedState.

    The launcher's ``warm_settings_feed()`` creates an
    ``mcp_common.health.feed.HealthFeedState`` instance — a different class
    from oneiric's own ``oneiric.mcp.health.HealthFeedState``. oneiric's
    ``/health`` route aggregates the oneiric feeds, so the launcher's warm
    has no observable effect on this server. This helper builds the
    equivalent oneiric-shaped feed (cycles_total=1, entities_count=1) so
    the first probe returns 200 instead of 503.

    Per REQ-004, only ``settings`` is pre-warmed. ``context`` and
    ``progress`` start unhealthy and populate via tool calls.
    """
    from oneiric.mcp.health import HealthFeedState

    feed = HealthFeedState(name="settings")
    feed.record_success(entities_count=1)
    return {
        "settings": feed,
        "context": HealthFeedState(name="context"),
        "progress": HealthFeedState(name="progress"),
    }


def build_server(settings_path: Path):
    """Closure factory: bind ``settings_path``; the inner closure takes no args.

    The variadic ``Callable[..., Any]`` contract (REQ-003) lets the
    launcher call ``build_server()`` with no positional args. Two-stage
    capture is the canonical pattern (cookbook Example 4 — crackerjack):
    the factory binds the heavy deps (auth load + processor) so the
    inner closure is a trivial ``return build_mcp_server(...)``.

    The launcher warms only the ``settings`` feed (REQ-004). ``context``
    and ``progress`` start unhealthy and populate via tool calls.
    """
    from oneiric.cli.mcp import _load_auth_from_settings
    from oneiric.mcp.config import load_auth_config
    from oneiric.mcp.server import build_mcp_server

    auth_config = _load_auth_from_settings(settings_path)
    mcp_auth_config, mcp_providers = load_auth_config(
        auth_config, provider_factories={},
    )
    processor = _build_processor()
    health_feeds = _build_warm_settings_feed()

    def _build():
        return build_mcp_server(
            config=SimpleNamespace(name="oneiric"),
            auth_config=mcp_auth_config,
            providers=mcp_providers,
            processor=processor,
            health_feeds=health_feeds,
        )

    return _build


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Launch the Oneiric FastMCP server via mcp-common launcher.",
    )
    parser.add_argument(
        "settings",
        nargs="?",
        default=str(Path.home() / ".oneiric" / "settings.yaml"),
        help="Path to oneiric settings.yaml "
        "(defaults to ~/.oneiric/settings.yaml).",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8681)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    settings_path = Path(args.settings)
    if not settings_path.exists():
        print(f"settings file not found: {settings_path}", file=sys.stderr)
        return 2

    _install_sigterm_handler()

    asyncio.run(
        launch(
            build_server=build_server(settings_path),
            component_name="oneiric",
            secrets_path=Path.home() / ".config" / "secrets.env",
            settings_path=settings_path,
            host=args.host,
            port=args.port,
            timeout_graceful_shutdown=30,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())