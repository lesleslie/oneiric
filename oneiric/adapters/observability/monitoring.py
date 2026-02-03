from __future__ import annotations

from collections import defaultdict
from typing import Any


class OTelMetrics:
    def __init__(self) -> None:
        self._query_counts: dict[str, int] = defaultdict(int)
        self._query_times: dict[str, list[float]] = defaultdict(list)
        self._index_usage: dict[str, int] = defaultdict(int)

    def record_query(self, method: str, duration_ms: float) -> None:
        self._query_counts[method] += 1
        self._query_times[method].append(duration_ms)

    def record_index_usage(self, index_type: str) -> None:
        self._index_usage[index_type] += 1

    def get_metrics_summary(self) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "query_counts": self._query_counts.copy(),
            "index_usage": self._index_usage.copy(),
            "query_times_p50": {},
            "query_times_p95": {},
        }

        for method, times in self._query_times.items():
            if times:
                sorted_times = sorted(times)
                summary["query_times_p50"][method] = int(
                    sorted_times[len(sorted_times) // 2]
                )
                summary["query_times_p95"][method] = int(
                    sorted_times[int(len(sorted_times) * 0.95)]
                )

        return summary

    def reset(self) -> None:
        self._query_counts.clear()
        self._query_times.clear()
        self._index_usage.clear()
