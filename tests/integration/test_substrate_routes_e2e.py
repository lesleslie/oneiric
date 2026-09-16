"""End-to-end integration tests for the Oneiric substrate HTTP routes.

Boots a real :class:`SubstrateHTTPServer` against a temporary substrate
directory, then issues HTTP requests against the running server via
:mod:`httpx2`. The tests assert both the response payload shape and the
``HealthFeedState`` semantics — a degraded feed (errors_total > 0)
forces ``/health`` to return ``503``.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

httpx2 = pytest.importorskip("httpx2")  # project-standard HTTP client

from oneiric.http import SubstrateHTTPServer  # noqa: E402
from oneiric.http.routes.substrate import HealthFeedState  # noqa: E402


# ---------------------------------------------------------------------------
# Test scaffolding: ephemeral substrate directory + ephemeral TCP port
# ---------------------------------------------------------------------------


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def substrate_dir(tmp_path: Path) -> Path:
    """An empty directory for the SubstrateStore to populate."""
    root = tmp_path / "substrate"
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture
def server_kwargs(substrate_dir: Path) -> dict[str, object]:
    return {
        "host": "127.0.0.1",
        "port": _find_free_port(),
        "substrate_root": substrate_dir,
    }


class _LoopThread:
    """Run the aiohttp server on a private event loop in a daemon thread."""

    def __init__(self, server: SubstrateHTTPServer) -> None:
        self._server = server
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._stopped = threading.Event()

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name="substrate-http-test", daemon=True
        )
        self._thread.start()
        if not self._ready.wait(timeout=10.0):
            raise RuntimeError("aiohttp loop_thread failed to become ready")

    def _run(self) -> None:
        import asyncio

        async def _serve() -> None:
            try:
                await self._server.start()
                self._ready.set()
                while not self._stopped.is_set():
                    await asyncio.sleep(0.05)
            finally:
                await self._server.stop()

        asyncio.run(_serve())

    def stop(self) -> None:
        self._stopped.set()
        if self._thread is not None:
            self._thread.join(timeout=10.0)


@contextmanager
def running_server(
    server_kwargs: dict[str, object],
) -> Iterator[SubstrateHTTPServer]:
    """Start the server on its own thread; tear it down on exit.

    Yields the live server instance so tests can poke at its feeds.
    """
    server = SubstrateHTTPServer(**server_kwargs)  # type: ignore[arg-type]
    server.build_app()

    loop_thread = _LoopThread(server)
    loop_thread.start()
    try:
        deadline = time.monotonic() + 5.0
        host = str(server_kwargs["host"])
        port = int(server_kwargs["port"])  # type: ignore[arg-type]
        while time.monotonic() < deadline:
            try:
                with socket.create_connection((host, port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.05)
        else:
            raise RuntimeError("SubstrateHTTPServer did not start in time")
        yield server
    finally:
        loop_thread.stop()


def _base_url(server_kwargs: dict[str, object]) -> str:
    host = str(server_kwargs["host"])
    port = int(server_kwargs["port"])  # type: ignore[arg-type]
    return f"http://{host}:{port}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_substrate_settings_returns_200_with_non_empty_payload(
    server_kwargs: dict[str, object],
) -> None:
    with running_server(server_kwargs):
        response = httpx2.get(f"{_base_url(server_kwargs)}/substrate/settings")
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, dict)
        # Non-empty payload contract.
        assert "current" in body
        assert "history" in body
        assert "history_total" in body
        assert "settings_version" in body
        assert isinstance(body["history"], list)


def test_substrate_context_returns_200(
    server_kwargs: dict[str, object],
) -> None:
    with running_server(server_kwargs):
        response = httpx2.get(f"{_base_url(server_kwargs)}/substrate/context")
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, dict)
        assert "tenants" in body
        assert "tenant_total" in body
        assert isinstance(body["tenants"], list)


def test_substrate_progress_returns_200(
    server_kwargs: dict[str, object],
) -> None:
    with running_server(server_kwargs):
        response = httpx2.get(f"{_base_url(server_kwargs)}/substrate/progress")
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, dict)
        assert "workflows" in body
        assert "workflow_total" in body
        assert isinstance(body["workflows"], list)


def test_health_returns_200_when_all_routes_healthy(
    server_kwargs: dict[str, object],
) -> None:
    with running_server(server_kwargs) as server:
        # Touch each route at least once so they leave cycles >= 1 + errors == 0.
        for path in ("/substrate/settings", "/substrate/context", "/substrate/progress"):
            r = httpx2.get(f"{_base_url(server_kwargs)}{path}")
            assert r.status_code == 200

        response = httpx2.get(f"{_base_url(server_kwargs)}/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "healthy"
        assert set(body["routes"]) == {"settings", "context", "progress"}
        for name, feed in body["routes"].items():
            assert feed["cycles_total"] >= 1
            assert feed["errors_total"] == 0
            assert feed["healthy"] is True
            assert name in {"settings", "context", "progress"}


def test_health_returns_503_when_route_degraded(
    server_kwargs: dict[str, object],
) -> None:
    with running_server(server_kwargs) as server:
        # Baseline healthy cycles on all three feeds.
        for path in ("/substrate/settings", "/substrate/context", "/substrate/progress"):
            r = httpx2.get(f"{_base_url(server_kwargs)}{path}")
            assert r.status_code == 200

        # Force the settings feed into degraded state.
        settings_feed: HealthFeedState = server.feeds["settings"]
        settings_feed.record_error()
        settings_feed.record_error()
        assert settings_feed.is_healthy() is False

        response = httpx2.get(f"{_base_url(server_kwargs)}/health")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "degraded"
        assert body["routes"]["settings"]["errors_total"] >= 2
        assert body["routes"]["settings"]["healthy"] is False
        assert body["routes"]["context"]["healthy"] is True
        assert body["routes"]["progress"]["healthy"] is True


def test_health_unhealthy_until_first_successful_cycle() -> None:
    """A route that has never been called reports degraded until it is hit."""
    feed = HealthFeedState(name="settings")
    assert feed.is_healthy() is False
    feed.record_success(entities_count=1)
    assert feed.is_healthy() is True