"""Oneiric FastMCP server package.

Exposes ``build_mcp_server()`` and the substrate + scheduler tool surface.
Replaces the legacy aiohttp SubstrateHTTPServer and SchedulerHTTPServer.
"""
from __future__ import annotations

# T1 ships the ``models`` submodule only. The ``server`` submodule (which
# defines ``build_mcp_server``) is added by a later task; the eager
# ``from oneiric.mcp.server import build_mcp_server`` import is deferred
# until that task lands so importing this package does not require the
# server module to exist.
