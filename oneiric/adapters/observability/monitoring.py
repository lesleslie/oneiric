"""Performance monitoring for OTel adapter."""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Any


class OTelMetrics:
    """Performance metrics collector for OTel adapter."""

    def __init__(self) -> None:
        """Initialize metrics collector."""
        self._query_counts: dict[str, int] = defaultdict(int)
        self._query_times: dict[str, list[float]] = defaultdict(list)
        self._index_usage: dict[str, int] = defaultdict(int)

    def record_query(self, method: str, duration_ms: float) -> None:
        """Record query execution time.

        Args:
            method: Query method name (e.g., "find_similar_traces")
            duration_ms: Execution time in milliseconds
        """
        self._query_counts[method] += 1
        self._query_times[method].append(duration_ms)

    def record_index_usage(self, index_type: str) -> None:
        """Record index usage statistics.

        Args:
            index_type: Index type (e.g., "ivfflat", "btree")
        """
        self._index_usage[index_type] += 1

    def get_metrics_summary(self) -> dict[str, Any]:
        """Get current metrics summary.

        Returns:
            Dictionary with query counts, timing percentiles, and index usage
        """
        summary = {
            "query_counts": dict(self._query_counts),
            "index_usage": dict(self._index_usage),
            "query_times_p50": {},
            "query_times_p95": {},
        }

        # Calculate percentiles
        for method, times in self._query_times.items():
            if times:
                sorted_times = sorted(times)
                summary["query_times_p50"][method] = sorted_times[len(sorted_times) // 2]
                summary["query_times_p95"][method] = sorted_times[int(len(sorted_times) * 0.95)]

        return summary

    def reset(self) -> None:
        """Reset all metrics."""
        self._query_counts.clear()
        self._query_times.clear()
        self._index_usage.clear()
