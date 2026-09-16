"""Oneiric HTTP server package.

Exposes a thin :class:`SubstrateHTTPServer` built on :mod:`aiohttp` for
serving Oneiric state (settings, context, progress) over HTTP. Wired
into the CLI via ``oneiric http start|stop|status|health``.
"""

from __future__ import annotations

from oneiric.http.server import SubstrateHTTPServer

__all__ = ["SubstrateHTTPServer"]