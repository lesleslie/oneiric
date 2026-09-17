from __future__ import annotations

from oneiric.mcp.health import HealthFeedState, aggregate_health


def test_initial_feed_is_not_healthy() -> None:
    feed = HealthFeedState(name="settings")
    assert feed.is_healthy() is False


def test_feed_becomes_healthy_after_success() -> None:
    feed = HealthFeedState(name="settings")
    feed.record_success(entities_count=3)
    assert feed.is_healthy() is True
    assert feed.entities_count == 3
    assert feed.errors_total == 0
    assert feed.cycles_total == 1
    assert feed.last_updated_timestamp is not None


def test_feed_unhealthy_after_error() -> None:
    feed = HealthFeedState(name="settings")
    feed.record_success(entities_count=3)
    feed.record_error()
    assert feed.is_healthy() is False
    assert feed.errors_total == 1


def test_aggregate_health_all_healthy() -> None:
    feeds = {
        "settings": HealthFeedState(name="settings"),
        "context": HealthFeedState(name="context"),
    }
    feeds["settings"].record_success(entities_count=1)
    feeds["context"].record_success(entities_count=2)
    status, body = aggregate_health(feeds)
    assert status == 200
    assert body["status"] == "healthy"
    assert body["cycles_total"] == 2
    assert body["errors_total"] == 0


def test_aggregate_health_degraded_when_any_feed_errors() -> None:
    feeds = {
        "settings": HealthFeedState(name="settings"),
        "context": HealthFeedState(name="context"),
    }
    feeds["settings"].record_success(entities_count=1)
    feeds["context"].record_success(entities_count=2)
    feeds["context"].record_error()
    status, body = aggregate_health(feeds)
    assert status == 503
    assert body["status"] == "degraded"


def test_feed_as_dict_shape() -> None:
    feed = HealthFeedState(name="settings")
    feed.record_success(entities_count=1)
    d = feed.as_dict()
    assert set(d.keys()) == {
        "name", "entities_count", "last_updated_timestamp",
        "errors_total", "cycles_total", "healthy",
    }
    assert d["healthy"] is True
