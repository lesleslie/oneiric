"""SubstrateHTTP server for Oneiric.

Wires the substrate HTTP routes onto an :class:`aiohttp.web.Application`
plus a per-feed health aggregator at ``/health``. The server is the
target of the new ``oneiric http start|stop|status|health`` CLI
subcommand and is independently runnable for tests.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from oneiric.core.logging import get_logger
from oneiric.http.routes.substrate import (
    DEFAULT_SUBSTRATE_DIR,
    HealthFeedState,
    SubstrateStore,
    aggregate_health,
    register_substrate_routes,
)

if TYPE_CHECKING:
    from aiohttp import web


logger = get_logger("oneiric.http.server")


@dataclass
class SubstrateHTTPServer:
    """Minimal aiohttp-backed HTTP server for Oneiric substrate state.

    Args:
        host: Interface to bind (``"0.0.0.0"`` by default).
        port: TCP port (``8081`` by default; ``$PORT`` env var overrides).
        substrate_root: Directory holding the JSON substrate files.
            Defaults to ``~/.oneiric/substrate/``.

    Use :meth:`build_app` to construct the underlying aiohttp ``Application``
    (also exposed for tests). Use :meth:`start` / :meth:`stop` for a
    standalone run loop.
    """

    host: str = "0.0.0.0"
    port: int = 8081
    substrate_root: Path | None = None

    _app: "web.Application | None" = None
    _feeds: dict[str, HealthFeedState] | None = None
    _runner: "web.AppRunner | None" = None
    _site: "web.TCPSite | None" = None

    def build_app(self) -> "web.Application":
        """Build a fresh :class:`aiohttp.web.Application` with substrate routes."""
        from aiohttp import web

        store = SubstrateStore(
            root=self.substrate_root
            if self.substrate_root is not None
            else DEFAULT_SUBSTRATE_DIR
        )
        app = web.Application()
        feeds = register_substrate_routes(app, store=store)
        app.router.add_get("/health", self._make_health_handler(feeds))
        app.router.add_get("/", self._make_index_handler(feeds))
        self._app = app
        self._feeds = feeds
        return app

    def _make_health_handler(
        self, feeds: dict[str, HealthFeedState]
    ):
        from aiohttp import web

        async def handle(_request: web.Request) -> web.Response:
            status, body = aggregate_health(feeds)
            return web.json_response(body, status=status, dumps=_safe_dumps)

        return handle

    def _make_index_handler(self, feeds: dict[str, HealthFeedState]):
        from aiohttp import web

        async def handle(_request: web.Request) -> web.Response:
            status, body = aggregate_health(feeds)
            payload = {
                "service": "oneiric-http",
                "routes": sorted(feeds.keys()),
                "health_status": body["status"],
            }
            return web.json_response(payload, status=200, dumps=_safe_dumps)

        return handle

    @property
    def feeds(self) -> dict[str, HealthFeedState]:
        if self._feeds is None:
            raise RuntimeError(
                "SubstrateHTTPServer.feeds accessed before build_app(); "
                "call build_app() first."
            )
        return self._feeds

    async def start(self) -> None:
        from aiohttp import web

        if self._app is None:
            self.build_app()
        assert self._app is not None
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()
        logger.info(
            "substrate-http-started", host=self.host, port=self.port
        )

    async def stop(self) -> None:
        if self._site is not None:
            await self._site.stop()
            self._site = None
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
        logger.info("substrate-http-stopped")

    def list_routes(self) -> Iterable[str]:
        """Public routes the server exposes (for ``oneiric http status``)."""
        return (
            "GET /substrate/settings",
            "GET /substrate/context",
            "GET /substrate/progress",
            "POST /substrate/settings",
            "POST /substrate/context",
            "POST /substrate/progress",
            "GET /health",
        )


def _safe_dumps(payload: Any) -> str:
    import json

    return json.dumps(payload, default=str)


__all__ = ["SubstrateHTTPServer"]