#!/usr/bin/env python3
"""Launch wrapper for the Oneiric FastMCP server (mcp-common launcher edition).

Phase 2 commit 2.5a of the 2026-09-26-mcp-launcher-standardization plan.

Public invocation from launchd ``com.mcp.oneiric.plist``:

    /Users/les/Projects/oneiric/.venv/bin/python \\
    /Users/les/Projects/oneiric/scripts/launch_mcp.py \\
    --host 127.0.0.1 --port 8681

The wrapper collapses the prior ad-hoc boot sequence (manual
``Resolver + LifecycleManager + WorkflowBridge + WorkflowTaskProcessor``
wiring, manual ``health_feeds`` warm-up, manual
``run_async(transport='http')``) into a single ``mcp_common.server.launcher
.launch()`` call. The launcher handles ``~/.config/secrets.env`` loading,
HTTP transport, and uvicorn ``timeout_graceful_shutdown=30``.

2026-10-05 (XDG loader migration): the legacy ``~/.oneiric/settings.yaml``
positional argument is dropped. The Oneiric CLI now reads
``OneiricSettings`` via the XDG-compliant ``load_settings()`` loader
(see ``docs/plans/2026-10-05-oneiric-cli-loader-xdg-migration.md``
Phase 4). The launchd plist no longer passes the legacy path. The
launcher's ``settings_path=`` arg is also dropped because oneiric's
``/health`` reports substrate feeds (not the generic ``settings`` feed),
so warming that feed would be a no-op for the visible body — same
reasoning as ``mahavishnu/scripts/launch_mcp.py``.

The vendored ``oneiric mcp start`` CLI (oneiric/cli/mcp.py) has a
dormant gap (no ``WorkflowTaskProcessor`` wiring, stdio transport); that
fix lands in Phase 2 commits 2.5b / 2.5c.
"""

from __future__ import annotations

import site
import sys
from pathlib import Path

# Venv bootstrap: the wrapper's shebang (`#!/usr/bin/env python3`) resolves to
# whatever python3 is in launchd's $PATH — typically Homebrew's system python
# (e.g. /usr/local/bin/python3 → /usr/local/Cellar/python@3.14/...). That python
# is the SAME binary as the venv's `.venv/bin/python` (both symlink to the same
# Homebrew cellar file), but the venv's site-packages aren't on sys.path unless
# Python was launched via the venv's binary. Fix: use `site.addsitedir` (NOT
# just `sys.path.insert`) so `.pth` files in the venv's site-packages get
# processed at runtime — `site.addsitedir` walks the directory and exec's any
# `.pth` it finds (handles both direct-install packages and editable-install
# pointers). A plain `sys.path.insert` misses .pth files because Python's site
# initialization ran before our bootstrap prepend. Idempotent — no-op when the
# venv is already active (sys.prefix is already under `_REPO_ROOT/.venv`).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_VENV_ROOT = _REPO_ROOT / ".venv"
_VENV_SITE_PACKAGES = (
    _VENV_ROOT
    / "lib"
    / f"python{sys.version_info.major}.{sys.version_info.minor}"
    / "site-packages"
)
try:
    _VENV_SITE_PACKAGES.relative_to(Path(sys.prefix))
    _IN_VENV = True
except ValueError:
    _IN_VENV = False
if not _IN_VENV and _VENV_SITE_PACKAGES.is_dir():
    site.addsitedir(str(_VENV_SITE_PACKAGES))

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


def _build_warm_feeds() -> dict[str, HealthFeedState]:
    """Pre-warm every oneiric HealthFeedState with a 'ready to serve' baseline.

    The launcher's ``warm_settings_feed()`` constructs an
    ``mcp_common.health.feed.HealthFeedState`` — a different class
    from oneiric's own ``oneiric.mcp.health.HealthFeedState``, so
    oneiric's ``/health`` aggregator never sees the launcher's warm.
    This helper builds the consumer-shaped feeds directly so the
    aggregator's per-feed ``is_healthy()`` predicate sees a real warm.

    Oneiric's ``HealthFeedState.is_healthy()`` returns False when
    ``cycles_total == 0`` (no cycles = never warmed = degraded). With
    three substrate feeds (settings/context/progress) all keyed into
    the same ``/health`` body, an unwarmed ``context`` or ``progress``
    feed forces the aggregate to 503 even on a freshly-booted server.
    That cascades: ``launch_with_healthcheck.sh`` uses ``curl -fsS``,
    which exits non-zero on 4xx/5xx, the wrapper kills the Python
    process, launchd sees ``KeepAlive.Crashed=true``, and the server
    restart-loops forever (see
    ``feedback-oneiric-mcp-health-feed-warmup``).

    Each feed starts with ``record_success(entities_count=0)`` —
    ``cycles_total=1`` (warmed), ``errors_total=0`` (clean),
    ``entities_count=0`` (no real data yet). Subsequent tool calls
    overwrite with the actual entity count via
    ``feed.record_success(N)``. REQ-004 governs ``/health`` public
    access; this pre-warm is orthogonal — see cookbook Trap K for the
    full rationale.
    """
    from oneiric.mcp.health import HealthFeedState

    feeds = {}
    for name in ("settings", "context", "progress"):
        feed = HealthFeedState(name=name)
        feed.record_success(entities_count=0)
        feeds[name] = feed
    return feeds


def build_server():
    """Closure factory: returns the configured Oneiric FastMCP server.

    ``FastMCPServer.run_async(...)`` satisfies the launcher's duck-typed
    contract (variadic ``Callable[..., Any]`` — REQ-003), so the wrapper
    can be returned directly. The launcher calls ``build_server()`` with
    no args and gets the FastMCP server back.

    The launcher warms only the ``settings`` feed (REQ-004) for the
    generic HealthFeedState. ``context`` and ``progress`` start unhealthy
    and populate via tool calls. Oneiric's own ``/health`` body
    reports substrate feeds, not the launcher-warmed ``settings`` feed
    — so passing a settings file here is intentionally skipped.
    """
    from oneiric.cli.mcp import _load_auth_from_settings
    from oneiric.mcp.config import load_auth_config
    from oneiric.mcp.server import build_mcp_server

    auth_config = _load_auth_from_settings()
    mcp_auth_config, mcp_providers = load_auth_config(
        auth_config,
        provider_factories={},
    )
    processor = _build_processor()
    health_feeds = _build_warm_feeds()

    return build_mcp_server(
        config=SimpleNamespace(name="oneiric"),
        auth_config=mcp_auth_config,
        providers=mcp_providers,
        processor=processor,
        health_feeds=health_feeds,
    )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Launch the Oneiric FastMCP server via mcp-common launcher.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8681)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    _install_sigterm_handler()

    asyncio.run(
        launch(
            build_server=build_server,
            component_name="oneiric",
            secrets_path=Path.home() / ".config" / "secrets.env",
            # No settings_path — oneiric's /health reports substrate
            # feeds (settings, context, progress), not the launcher-warmed
            # generic settings feed. Same reasoning as
            # mahavishnu/scripts/launch_mcp.py.
            host=args.host,
            port=args.port,
            timeout_graceful_shutdown=30,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
