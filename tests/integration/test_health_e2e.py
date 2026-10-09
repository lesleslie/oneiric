"""End-to-end test for the oneiric MCP health-check enrichment (Phase 1.4).

Per ``docs/plans/2026-10-09-mcp-health-check-enrichment.md`` Phase 1.4
REQ-HC-001/002/003:

* ``GET /health`` returns 200 when the mcp-common aggregator reports
  ``HEALTHY`` or ``WARMING_UP``; 503 when it reports ``DEGRADED`` or
  ``FAILED`` (was the silent-200-degraded bug).
* The body is the canonical mcp-common ``HealthSnapshot`` envelope
  (``status`` + ``checks`` + ``reason_codes``).
* The ``oneiric_get_health`` MCP tool returns the same envelope shape.
* ``HEALTH_FEED_HALFLIFE_SECONDS=60`` is the per-repo default; the
  pre-60s decay window is the soft-rollout safeguard against fresh
  server 503-flicker.
"""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from typing import Any

import pytest
from mcp_common.auth.config import AuthConfig
from mcp_common.health.feed import HealthFeedState
from starlette.testclient import TestClient

from oneiric.mcp.server import (
    _aggregate_health_status,
    _record_feed_error,
    _record_feed_success,
    _register_health_tool,
    _resolve_feeds,
    _resolve_health_halflife,
    build_mcp_server,
)
from fastmcp import FastMCP


class _StubProcessor:
    """Minimal scheduler processor — ``build_mcp_server`` requires one."""

    async def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"run_id": "run-e2e", "results": {"ok": True}}


def _build_mcp(*, feeds: dict[str, HealthFeedState]) -> FastMCP:
    """Build a real FastMCP server wired to the test-supplied feeds.

    Pass ``feeds`` explicitly so each test owns its lifecycle. Auth is
    disabled so we can hit the tool surface without seeding a Principal
    (the latent contextvar-propagation bug surfaces otherwise).
    """
    return build_mcp_server(
        SimpleNamespace(name="oneiric-health-e2e"),
        auth_config=AuthConfig(enabled=False, service_name="oneiric"),
        providers={},
        processor=_StubProcessor(),
        health_feeds=feeds,
    )


def _http_app(mcp: FastMCP):
    return mcp.http_app()


class TestHealthHalflifeDefault:
    """``HEALTH_FEED_HALFLIFE_SECONDS=60`` per Phase 1.4 REQ-HC-002."""

    def test_default_halflife_is_60(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HEALTH_FEED_HALFLIFE_SECONDS", raising=False)
        assert _resolve_health_halflife() == 60.0

    def test_env_override_honored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HEALTH_FEED_HALFLIFE_SECONDS", "300")
        assert _resolve_health_halflife() == 300.0

    def test_garbage_env_falls_back_to_60(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HEALTH_FEED_HALFLIFE_SECONDS", "not-a-number")
        assert _resolve_health_halflife() == 60.0


class TestHealthRouteReturns503OnDegraded:
    """Phase 1.4 REQ-HC-002: /health flips to 503 when any feed is broken.

    Pre-migration the route returned 200 with a degraded envelope; the
    silent-degraded case was the Phase 1 trigger. Post-migration the
    route uses mcp-common's aggregator and returns the correct HTTP
    code per the StatusValue -> http_code mapping.
    """

    def test_200_when_all_feeds_healthy(self) -> None:
        feeds = _resolve_feeds(None)
        for f in feeds.values():
            _record_feed_success(f, entities_count=3)
        client = TestClient(_http_app(_build_mcp(feeds=feeds)))
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        for check in body["checks"].values():
            assert check["status"] == "healthy"
            assert check["healthy"] is True

    def test_200_when_all_feeds_warming_up(self) -> None:
        """Per plan: WARMING_UP returns 200 (warm-but-slow = serving)."""
        feeds = _resolve_feeds(None)
        # Pre-warm only bumps cycles_total + last_updated; entities_count
        # stays at 0 -> WARMING_UP_EMPTY_FEED reason, status=WARMING_UP.
        for f in feeds.values():
            _record_feed_success(f, entities_count=0)
        client = TestClient(_http_app(_build_mcp(feeds=feeds)))
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "warming_up"

    def test_503_when_any_feed_has_recent_error(self) -> None:
        """The Phase 1 silent-200-degraded bug: must be 503 now."""
        feeds = _resolve_feeds(None)
        for f in feeds.values():
            _record_feed_success(f, entities_count=3)
        # settings becomes degraded via record_error (last_error_at=now).
        _record_feed_error(feeds["settings"])
        client = TestClient(_http_app(_build_mcp(feeds=feeds)))
        resp = client.get("/health")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "degraded"
        assert body["checks"]["settings"]["status"] == "degraded"
        assert "error_within_halflife" in body["checks"]["settings"]["reason_codes"]

    def test_503_when_feed_never_populated(self) -> None:
        """HNSW hardening: ingester claims to be running but never cycled.

        This is the case the launch_mcp pre-warm in
        ``scripts/launch_mcp.py`` exists to defeat; the test asserts the
        raw aggregator flag (DEGRADED, 503) when pre-warm is skipped.
        """
        # No pre-warm; defaults have ingester_running=True but
        # cycles_total=0 -> FEED_NEVER_POPULATED -> DEGRADED -> 503.
        feeds = _resolve_feeds(None)
        client = TestClient(_http_app(_build_mcp(feeds=feeds)))
        resp = client.get("/health")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "degraded"

    def test_503_when_ingester_not_running(self) -> None:
        """Producer dead + empty feed = FAILED -> 503."""
        feeds = {
            "settings": HealthFeedState(ingester_running=False),
            "context": HealthFeedState(ingester_running=False),
            "progress": HealthFeedState(ingester_running=False),
            "runtime_registry": HealthFeedState(ingester_running=False),
        }
        client = TestClient(_http_app(_build_mcp(feeds=feeds)))
        resp = client.get("/health")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "failed"
        assert "ingester_not_running" in body["checks"]["settings"]["reason_codes"]


class TestHealthSnapshotShape:
    """The body must be the canonical mcp-common ``HealthSnapshot``.

    The shape is::

        {
          "status": "healthy" | "warming_up" | "degraded" | "failed",
          "checks": {feed_name: {"status": ..., "healthy": bool,
                                  "reason_codes": [str, ...]}},
          "reason_codes": [str, ...],   # worst feed's codes
        }

    All four substrate feeds (settings/context/progress/runtime_registry)
    must appear in ``checks`` so operators can localize failures.
    """

    def test_envelope_has_required_keys(self) -> None:
        feeds = _resolve_feeds(None)
        for f in feeds.values():
            _record_feed_success(f, entities_count=3)
        _status_code, snapshot = _aggregate_health_status(feeds)
        assert set(snapshot.keys()) == {"status", "checks", "reason_codes"}
        assert set(snapshot["checks"].keys()) == {
            "settings",
            "context",
            "progress",
            "runtime_registry",
        }
        for check in snapshot["checks"].values():
            assert set(check.keys()) == {"status", "healthy", "reason_codes"}

    def test_reason_codes_are_string_enum_values(self) -> None:
        feeds = _resolve_feeds(None)
        for f in feeds.values():
            _record_feed_success(f, entities_count=3)
        _status_code, snapshot = _aggregate_health_status(feeds)
        # JSON-encoded reason codes are plain strings (mcp-common uses
        # StrEnum); operators should not see ``ReasonCode.X`` literals.
        for codes in [snapshot["reason_codes"], *(
            c["reason_codes"] for c in snapshot["checks"].values()
        )]:
            for code in codes:
                assert isinstance(code, str)


class TestOneiricGetHealthMcpTool:
    """The ``oneiric_get_health`` MCP tool (Phase 1.4 new tool)."""

    def test_tool_is_registered(self) -> None:
        mcp = _build_mcp(feeds=_resolve_feeds(None))
        tools = asyncio.run(mcp.list_tools())
        names = {t.name for t in tools}
        assert "oneiric_get_health" in names

    def test_tool_returns_snapshot_with_status_and_checks(self) -> None:
        feeds = _resolve_feeds(None)
        for f in feeds.values():
            _record_feed_success(f, entities_count=5)
        mcp = _build_mcp(feeds=feeds)
        tools = asyncio.run(mcp.list_tools())
        health_tool = next(t for t in tools if t.name == "oneiric_get_health")
        result = asyncio.run(health_tool.fn())
        assert result["status"] == "healthy"
        assert "settings" in result["checks"]
        assert "runtime_registry" in result["checks"]
        for check in result["checks"].values():
            assert check["status"] == "healthy"
            assert check["healthy"] is True

    def test_tool_reports_warming_up_for_fresh_server(self) -> None:
        """A freshly-booted oneiric (pre-warm only) returns 200 + WARMING_UP."""
        feeds = _resolve_feeds(None)
        for f in feeds.values():
            _record_feed_success(f, entities_count=0)
        mcp = _build_mcp(feeds=feeds)
        tools = asyncio.run(mcp.list_tools())
        health_tool = next(t for t in tools if t.name == "oneiric_get_health")
        result = asyncio.run(health_tool.fn())
        assert result["status"] == "warming_up"
        for check in result["checks"].values():
            assert check["status"] == "warming_up"
            assert "warming_up_empty_feed" in check["reason_codes"]


class TestHalflifeDecay:
    """An error older than the halflife decayed to HEALTHY.

    Per the mcp-common ``is_healthy`` contract: ``last_error_at`` within
    the halflife window -> DEGRADED; outside -> HEALTHY (decayed). The
    60s default is the soft-rollout safeguard.
    """

    def test_error_within_halflife_is_degraded(self) -> None:
        feeds = _resolve_feeds(None)
        for f in feeds.values():
            _record_feed_success(f, entities_count=3)
        _record_feed_error(feeds["settings"])
        status_code, snapshot = _aggregate_health_status(feeds)
        assert status_code == 503
        assert snapshot["status"] == "degraded"
        assert (
            "error_within_halflife"
            in snapshot["checks"]["settings"]["reason_codes"]
        )

    def test_error_outside_halflife_decays_to_healthy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Forge last_error_at far in the past and assert HEALTHY again."""
        import time

        monkeypatch.setenv("HEALTH_FEED_HALFLIFE_SECONDS", "60")
        feeds = _resolve_feeds(None)
        for f in feeds.values():
            _record_feed_success(f, entities_count=3)
        # settings had an error 10 minutes ago — well past the 60s halflife.
        feeds["settings"].last_error_at = time.time() - 600.0
        feeds["settings"].errors_total = 1
        status_code, snapshot = _aggregate_health_status(feeds)
        assert status_code == 200
        assert snapshot["status"] == "healthy"


class TestHealthMetrics:
    """Phase 1.4 observability: per-feed Prometheus metrics on every /health hit.

    The contract (per the mcp-common convention with ``repo="oneiric"``):

    * ``health_feed_status{repo, feed, status}`` — 1.0 for the current
      status per feed, 0.0 for the other three.
    * ``health_feed_errors_within_window{repo, feed}`` — counter of
      errors since the last success per feed.
    * ``mcp_common_health_halflife_seconds{repo}`` — current halflife.
    """

    def test_metrics_emitted_with_repo_label(self) -> None:
        from prometheus_client import generate_latest

        from oneiric.mcp.server import _health_metrics_registry

        feeds = _resolve_feeds(None)
        for f in feeds.values():
            _record_feed_success(f, entities_count=3)
        client = TestClient(_http_app(_build_mcp(feeds=feeds)))
        # Hit the route to trigger metric emission.
        client.get("/health")
        metrics = generate_latest(_health_metrics_registry).decode()
        # Per-feed, all four substrate feeds must have a status=healthy
        # series with value 1.0 (after a successful cycle).
        for feed_name in ("settings", "context", "progress", "runtime_registry"):
            needle = (
                f'health_feed_status{{feed="{feed_name}",'
                f'repo="oneiric",status="healthy"}} 1.0'
            )
            assert needle in metrics, (
                f"missing metric for {feed_name}: looked for {needle!r}"
            )

    def test_halflife_metric_matches_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from prometheus_client import generate_latest

        from oneiric.mcp.server import _health_metrics_registry

        monkeypatch.setenv("HEALTH_FEED_HALFLIFE_SECONDS", "120")
        feeds = _resolve_feeds(None)
        for f in feeds.values():
            _record_feed_success(f, entities_count=3)
        client = TestClient(_http_app(_build_mcp(feeds=feeds)))
        client.get("/health")
        metrics = generate_latest(_health_metrics_registry).decode()
        assert 'mcp_common_health_halflife_seconds{repo="oneiric"} 120.0' in metrics
