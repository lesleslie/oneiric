"""Tests for OTelMetrics."""

from __future__ import annotations

import pytest
from oneiric.adapters.observability.monitoring import OTelMetrics


def test_record_query_metrics():
    """Test recording query metrics."""
    metrics = OTelMetrics()

    metrics.record_query("test_method", 50.0)
    metrics.record_query("test_method", 100.0)
    metrics.record_query("test_method", 150.0)

    summary = metrics.get_metrics_summary()

    assert summary["query_counts"]["test_method"] == 3
    assert summary["query_times_p50"]["test_method"] == 100.0
    assert summary["query_times_p95"]["test_method"] == 150.0


def test_record_index_usage():
    """Test recording index usage."""
    metrics = OTelMetrics()

    metrics.record_index_usage("ivfflat")
    metrics.record_index_usage("ivfflat")
    metrics.record_index_usage("btree")

    summary = metrics.get_metrics_summary()

    assert summary["index_usage"]["ivfflat"] == 2
    assert summary["index_usage"]["btree"] == 1


def test_reset_metrics():
    """Test resetting metrics."""
    metrics = OTelMetrics()

    metrics.record_query("test_method", 50.0)
    metrics.record_index_usage("ivfflat")

    metrics.reset()

    summary = metrics.get_metrics_summary()

    assert summary["query_counts"] == {}
    assert summary["index_usage"] == {}
