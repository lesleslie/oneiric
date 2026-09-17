"""Oneiric FastMCP server package.

Exposes ``build_mcp_server()`` and the substrate + scheduler tool surface.
Replaces the legacy aiohttp SubstrateHTTPServer and SchedulerHTTPServer.
"""
from __future__ import annotations

from oneiric.mcp.server import build_mcp_server

__all__ = ["build_mcp_server"]