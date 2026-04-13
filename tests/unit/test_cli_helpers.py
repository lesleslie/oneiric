"""Tests for pure helper functions in oneiric.cli."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from typer import BadParameter

from oneiric.cli import (
    _activity_counts_from_mapping,
    _build_lifecycle_options,
    _build_workflow_node,
    _build_workflow_summary,
    _candidate_summary,
    _coerce_domain,
    _event_results_payload,
    _extract_notification_metadata,
    _format_activity_summary,
    _format_remote_budget_line,
    _format_swap_summary,
    _format_workflow_node,
    _http_server_enabled,
    _lifecycle_counts_from_mapping,
    _normalize_domain,
    _parse_csv,
    _parse_dependency_list,
    _percentile,
    _resolve_http_port,
    _scrub_sensitive_data,
    _set_timestamps,
    _swap_latency_summary,
    DOMAINS,
)
from oneiric.core.lifecycle import LifecycleSafetyOptions, LifecycleStatus
from oneiric.core.resolution import Candidate, CandidateSource
from oneiric.runtime.events import HandlerResult


# ---------------------------------------------------------------------------
# _percentile
# ---------------------------------------------------------------------------

class TestPercentile:
    def test_empty_list_returns_none(self) -> None:
        assert _percentile([], 0.5) is None

    def test_single_element(self) -> None:
        assert _percentile([42.0], 0.5) == 42.0

    def test_median_odd(self) -> None:
        assert _percentile([1.0, 2.0, 3.0], 0.5) == 2.0

    def test_median_even_interpolates(self) -> None:
        result = _percentile([1.0, 2.0, 3.0, 4.0], 0.5)
        assert result == pytest.approx(2.5)

    def test_p95(self) -> None:
        data = list(range(1, 101))
        assert _percentile(data, 0.95) == pytest.approx(95.05, abs=0.01)

    def test_p99(self) -> None:
        data = list(range(1, 101))
        assert _percentile(data, 0.99) == pytest.approx(99.01, abs=0.01)

    def test_p0_and_p100(self) -> None:
        data = [10.0, 20.0, 30.0]
        assert _percentile(data, 0.0) == 10.0
        assert _percentile(data, 1.0) == 30.0

    def test_preserves_order(self) -> None:
        data = [5.0, 1.0, 3.0]
        _percentile(data, 0.5)  # _percentile does NOT sort in place
        assert data == [5.0, 1.0, 3.0]


# ---------------------------------------------------------------------------
# _swap_latency_summary
# ---------------------------------------------------------------------------

class TestSwapLatencySummary:
    def _make_status(
        self,
        durations: list[float] | None = None,
        successes: int = 0,
        failures: int = 0,
    ) -> LifecycleStatus:
        return LifecycleStatus(
            domain="adapter",
            key="test",
            recent_swap_durations_ms=durations or [],
            successful_swaps=successes,
            failed_swaps=failures,
        )

    def test_empty_input(self) -> None:
        summary = _swap_latency_summary([])
        assert summary["samples"] == 0
        assert summary["p50"] is None
        assert summary["p95"] is None
        assert summary["p99"] is None
        assert summary["success_rate"] == 100.0

    def test_single_status(self) -> None:
        status = self._make_status(durations=[10.0, 20.0, 30.0], successes=3)
        summary = _swap_latency_summary([status])
        assert summary["samples"] == 3
        assert summary["success_rate"] == 100.0
        assert summary["p50"] == 20.0

    def test_multiple_statuses(self) -> None:
        s1 = self._make_status(durations=[10.0], successes=2, failures=1)
        s2 = self._make_status(durations=[20.0, 30.0], successes=3, failures=0)
        summary = _swap_latency_summary([s1, s2])
        assert summary["samples"] == 3
        assert summary["success_rate"] == pytest.approx(83.33, abs=0.01)
        assert summary["p95"] is not None


# ---------------------------------------------------------------------------
# _format_swap_summary
# ---------------------------------------------------------------------------

class TestFormatSwapSummary:
    def test_no_samples(self) -> None:
        assert _format_swap_summary({"samples": 0}) == "Swap latency: no samples recorded yet."

    def test_empty_summary(self) -> None:
        assert _format_swap_summary({}) == "Swap latency: no samples recorded yet."

    def test_with_samples(self) -> None:
        summary = {
            "samples": 100,
            "p50": 10.0,
            "p95": 50.0,
            "p99": 90.0,
            "success_rate": 95.5,
        }
        text = _format_swap_summary(summary)
        assert "Swap latency (last 100):" in text
        assert "p50=10.0ms" in text
        assert "p95=50.0ms" in text
        assert "p99=90.0ms" in text
        assert "success_rate=95.5%" in text

    def test_partial_percentiles(self) -> None:
        summary = {"samples": 5, "p50": 12.3, "success_rate": 80.0}
        text = _format_swap_summary(summary)
        assert "p50=12.3ms" in text
        assert "p95" not in text


# ---------------------------------------------------------------------------
# _build_lifecycle_options
# ---------------------------------------------------------------------------

class TestBuildLifecycleOptions:
    def test_none_returns_defaults(self) -> None:
        opts = _build_lifecycle_options(None)
        assert opts.activation_timeout == 30.0
        assert opts.health_timeout == 5.0
        assert opts.shield_tasks is True

    def test_extracts_from_object(self) -> None:
        config = SimpleNamespace(
            activation_timeout=60, health_timeout=10, cleanup_timeout=20,
            hook_timeout=8, shield_tasks=False,
        )
        opts = _build_lifecycle_options(config)
        assert opts.activation_timeout == 60
        assert opts.shield_tasks is False

    def test_missing_attrs_use_defaults(self) -> None:
        config = SimpleNamespace(activation_timeout=100)
        opts = _build_lifecycle_options(config)
        assert opts.activation_timeout == 100
        assert opts.health_timeout == 5.0

    def test_none_values_zeroed(self) -> None:
        config = SimpleNamespace(activation_timeout=None)
        opts = _build_lifecycle_options(config)
        assert opts.activation_timeout == 0


# ---------------------------------------------------------------------------
# _normalize_domain / _coerce_domain
# ---------------------------------------------------------------------------

class TestDomainHelpers:
    def test_normalize_valid(self) -> None:
        for domain in DOMAINS:
            assert _normalize_domain(domain.upper()) == domain

    def test_normalize_invalid_raises(self) -> None:
        with pytest.raises(BadParameter, match="Domain must be one of"):
            _normalize_domain("bogus")

    def test_coerce_none(self) -> None:
        assert _coerce_domain(None) is None

    def test_coerce_valid(self) -> None:
        assert _coerce_domain("Adapter") == "adapter"

    def test_coerce_invalid_raises(self) -> None:
        with pytest.raises(BadParameter):
            _coerce_domain("nonexistent")


# ---------------------------------------------------------------------------
# _parse_csv
# ---------------------------------------------------------------------------

class TestParseCsv:
    def test_none(self) -> None:
        assert _parse_csv(None) == []

    def test_empty_string(self) -> None:
        assert _parse_csv("") == []

    def test_single_item(self) -> None:
        assert _parse_csv("foo") == ["foo"]

    def test_multiple_items(self) -> None:
        assert _parse_csv("a,b,c") == ["a", "b", "c"]

    def test_whitespace_stripped(self) -> None:
        assert _parse_csv(" a , b , c ") == ["a", "b", "c"]

    def test_empty_segments_filtered(self) -> None:
        assert _parse_csv("a,,b,") == ["a", "b"]


# ---------------------------------------------------------------------------
# _parse_dependency_list
# ---------------------------------------------------------------------------

class TestParseDependencyList:
    def test_none(self) -> None:
        assert _parse_dependency_list(None) == []

    def test_empty_list(self) -> None:
        assert _parse_dependency_list([]) == []

    def test_string_returns_wrapped(self) -> None:
        assert _parse_dependency_list("foo") == ["foo"]

    def test_list_passthrough(self) -> None:
        assert _parse_dependency_list(["a", "b"]) == ["a", "b"]

    def test_tuple_passthrough(self) -> None:
        assert _parse_dependency_list(("x", "y")) == ["x", "y"]

    def test_bytes_not_treated_as_sequence(self) -> None:
        # bytes is explicitly excluded from Sequence check
        result = _parse_dependency_list(b"foo")
        assert result == [b"foo"]


# ---------------------------------------------------------------------------
# _build_workflow_node
# ---------------------------------------------------------------------------

class TestBuildWorkflowNode:
    def test_basic_node(self) -> None:
        node = _build_workflow_node({"id": "t1", "task": "my_task"})
        assert node is not None
        assert node["id"] == "t1"
        assert node["task"] == "my_task"
        assert node["depends_on"] == []

    def test_node_with_key(self) -> None:
        node = _build_workflow_node({"key": "k1", "task": "job"})
        assert node is not None
        assert node["id"] == "k1"

    def test_node_with_dependencies(self) -> None:
        node = _build_workflow_node({"id": "t2", "depends_on": ["t1"]})
        assert node["depends_on"] == ["t1"]

    def test_node_without_id_returns_none(self) -> None:
        assert _build_workflow_node({"task": "orphan"}) is None

    def test_node_with_optional_fields(self) -> None:
        node = _build_workflow_node({
            "id": "t3", "payload": {"k": "v"}, "checkpoint": "cp1",
            "retry_policy": {"max": 3},
        })
        assert node["payload"] == {"k": "v"}
        assert node["checkpoint"] == "cp1"
        assert node["retry_policy"] == {"max": 3}

    def test_node_id_coerced_to_string(self) -> None:
        node = _build_workflow_node({"id": 42, "task": "x"})
        assert node["id"] == "42"

    def test_depends_on_string_wrapped(self) -> None:
        node = _build_workflow_node({"id": "t4", "depends_on": "prev"})
        assert node["depends_on"] == ["prev"]


# ---------------------------------------------------------------------------
# _build_workflow_summary
# ---------------------------------------------------------------------------

class TestBuildWorkflowSummary:
    def test_empty_dag(self) -> None:
        summary = _build_workflow_summary("wf1", {}, None, None)
        assert summary["node_count"] == 0
        assert summary["edge_count"] == 0
        assert summary["entry_nodes"] == []

    def test_with_nodes(self) -> None:
        dag = {
            "nodes": [
                {"id": "a", "task": "t1"},
                {"id": "b", "task": "t2", "depends_on": ["a"]},
            ]
        }
        summary = _build_workflow_summary("wf1", dag, None, None)
        assert summary["node_count"] == 2
        assert summary["edge_count"] == 1
        assert summary["entry_nodes"] == ["a"]

    def test_tasks_alias(self) -> None:
        dag = {"tasks": [{"id": "x", "task": "t"}]}
        summary = _build_workflow_summary("wf1", dag, None, None)
        assert summary["node_count"] == 1

    def test_queue_category(self) -> None:
        dag = {"nodes": [{"id": "a", "task": "t"}], "queue_category": "urgent"}
        summary = _build_workflow_summary("wf1", dag, None, None)
        assert summary["queue_category"] == "urgent"

    def test_default_queue_fallback(self) -> None:
        dag = {"nodes": [{"id": "a", "task": "t"}]}
        summary = _build_workflow_summary("wf1", dag, None, "default_q")
        assert summary["queue_category"] == "default_q"

    def test_last_run_attached_when_matching(self) -> None:
        last_run = {"workflow": "wf1", "status": "completed"}
        dag = {"nodes": [{"id": "a", "task": "t"}]}
        summary = _build_workflow_summary("wf1", dag, last_run, None)
        assert summary["last_run"] == last_run

    def test_last_run_ignored_when_not_matching(self) -> None:
        last_run = {"workflow": "other", "status": "completed"}
        dag = {"nodes": [{"id": "a", "task": "t"}]}
        summary = _build_workflow_summary("wf1", dag, last_run, None)
        assert "last_run" not in summary

    def test_non_mapping_entries_skipped(self) -> None:
        dag = {"nodes": [{"id": "ok", "task": "t"}, "not_a_dict", 42]}
        summary = _build_workflow_summary("wf1", dag, None, None)
        assert summary["node_count"] == 1


# ---------------------------------------------------------------------------
# _format_workflow_node
# ---------------------------------------------------------------------------

class TestFormatWorkflowNode:
    def test_root_node(self) -> None:
        text = _format_workflow_node({"id": "a", "task": "t1"})
        assert "depends_on=root" in text
        assert "task=t1" in text

    def test_node_with_deps(self) -> None:
        text = _format_workflow_node({"id": "b", "task": "t2", "depends_on": ["a"]})
        assert "depends_on=a" in text

    def test_node_with_retry(self) -> None:
        text = _format_workflow_node({"id": "c", "task": "t3", "retry_policy": "exponential"})
        assert "retry=exponential" in text

    def test_node_with_payload(self) -> None:
        text = _format_workflow_node({"id": "d", "task": "t4", "payload": {"x": 1}})
        assert "payload={'x': 1}" in text

    def test_node_with_checkpoint(self) -> None:
        text = _format_workflow_node({"id": "e", "task": "t5", "checkpoint": "cp"})
        assert "checkpoint=cp" in text


# ---------------------------------------------------------------------------
# _format_activity_summary
# ---------------------------------------------------------------------------

class TestFormatActivitySummary:
    def test_zero_counts(self) -> None:
        assert _format_activity_summary({}) == "Activity state: paused=0 draining=0"

    def test_with_counts(self) -> None:
        assert _format_activity_summary({"paused": 3, "draining": 1}) == "Activity state: paused=3 draining=1"


# ---------------------------------------------------------------------------
# _activity_counts_from_mapping
# ---------------------------------------------------------------------------

class TestActivityCountsFromMapping:
    def test_empty(self) -> None:
        assert _activity_counts_from_mapping({}) == {"paused": 0, "draining": 0}

    def test_counts(self) -> None:
        mapping = {
            "domain": {
                "key1": {"paused": True},
                "key2": {"draining": True},
                "key3": {"paused": True, "draining": True},
            }
        }
        assert _activity_counts_from_mapping(mapping) == {"paused": 2, "draining": 2}

    def test_nested_domains(self) -> None:
        mapping = {
            "d1": {"k1": {"paused": True}},
            "d2": {"k2": {"draining": True}},
        }
        assert _activity_counts_from_mapping(mapping) == {"paused": 1, "draining": 1}


# ---------------------------------------------------------------------------
# _lifecycle_counts_from_mapping
# ---------------------------------------------------------------------------

class TestLifecycleCountsFromMapping:
    def test_empty(self) -> None:
        assert _lifecycle_counts_from_mapping({}) == {}

    def test_groups_by_state(self) -> None:
        mapping = {
            "adapter": {
                "cache": {"state": "active"},
                "storage": {"state": "activating"},
            },
            "service": {
                "auth": {"state": "active"},
            },
        }
        assert _lifecycle_counts_from_mapping(mapping) == {"active": 2, "activating": 1}

    def test_missing_state_defaults_to_unknown(self) -> None:
        mapping = {"d": {"k": {"other": True}}}
        assert _lifecycle_counts_from_mapping(mapping) == {"unknown": 1}


# ---------------------------------------------------------------------------
# _format_remote_budget_line
# ---------------------------------------------------------------------------

class TestFormatRemoteBudgetLine:
    def _make_config(self, budget_ms: float | None = None) -> SimpleNamespace:
        return SimpleNamespace(latency_budget_ms=budget_ms)

    def test_no_budget_no_sync(self) -> None:
        text = _format_remote_budget_line(self._make_config(None), None)
        assert "budget=n/a" in text
        assert "no syncs yet" in text

    def test_budget_no_sync(self) -> None:
        text = _format_remote_budget_line(self._make_config(1000.0), None)
        assert "budget=1000ms" in text
        assert "no syncs yet" in text

    def test_within_budget(self) -> None:
        text = _format_remote_budget_line(self._make_config(1000.0), 500.0)
        assert "last_duration=500.0ms" in text
        assert "(OK)" in text

    def test_budget_exceeded(self) -> None:
        text = _format_remote_budget_line(self._make_config(100.0), 200.0)
        assert "(EXCEEDED)" in text

    def test_zero_budget_means_unlimited(self) -> None:
        text = _format_remote_budget_line(self._make_config(0), 9999.0)
        assert "(OK)" in text

    def test_no_budget_duration_ok(self) -> None:
        text = _format_remote_budget_line(self._make_config(None), 42.0)
        assert "(OK)" in text


# ---------------------------------------------------------------------------
# _resolve_http_port
# ---------------------------------------------------------------------------

class TestResolveHttpPort:
    def test_explicit_port(self) -> None:
        assert _resolve_http_port(9090) == 9090

    def test_env_port(self) -> None:
        with patch.dict("os.environ", {"PORT": "3000"}):
            assert _resolve_http_port(None) == 3000

    def test_invalid_env_port_falls_through(self) -> None:
        with patch.dict("os.environ", {"PORT": "abc"}):
            assert _resolve_http_port(None) == 8080

    def test_default_fallback(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            assert _resolve_http_port(None) == 8080

    def test_env_port_overrides_none(self) -> None:
        with patch.dict("os.environ", {"PORT": "5555"}):
            assert _resolve_http_port(None) == 5555


# ---------------------------------------------------------------------------
# _scrub_sensitive_data
# ---------------------------------------------------------------------------

class TestScrubSensitiveData:
    def test_clean_value(self) -> None:
        assert _scrub_sensitive_data("hello world") == "hello world"

    def test_secret(self) -> None:
        assert _scrub_sensitive_data("my-secret-value") == "***"

    def test_token(self) -> None:
        assert _scrub_sensitive_data("abc123TOKENxyz") == "***"

    def test_password(self) -> None:
        assert _scrub_sensitive_data("PASSWORD") == "***"

    def test_key(self) -> None:
        assert _scrub_sensitive_data("API-KEY") == "***"

    def test_case_insensitive(self) -> None:
        assert _scrub_sensitive_data("SecretKey") == "***"

    def test_empty_string(self) -> None:
        assert _scrub_sensitive_data("") == ""


# ---------------------------------------------------------------------------
# _event_results_payload
# ---------------------------------------------------------------------------

class TestEventResultsPayload:
    def test_empty(self) -> None:
        assert _event_results_payload([]) == []

    def test_single_success(self) -> None:
        results = [HandlerResult(
            handler="h1", success=True, duration=0.5, value="ok",
        )]
        payload = _event_results_payload(results)
        assert payload[0]["handler"] == "h1"
        assert payload[0]["success"] is True
        assert payload[0]["duration_ms"] == 500.0
        assert payload[0]["value"] == "ok"

    def test_single_failure(self) -> None:
        results = [HandlerResult(
            handler="h2", success=False, duration=1.0, error="boom", attempts=3,
        )]
        payload = _event_results_payload(results)
        assert payload[0]["error"] == "boom"
        assert payload[0]["attempts"] == 3

    def test_multiple(self) -> None:
        results = [
            HandlerResult(handler="a", success=True, duration=0.1),
            HandlerResult(handler="b", success=False, duration=0.2, error="err"),
        ]
        payload = _event_results_payload(results)
        assert len(payload) == 2


# ---------------------------------------------------------------------------
# _set_timestamps
# ---------------------------------------------------------------------------

class TestSetTimestamps:
    def test_sets_issued_at(self) -> None:
        d: dict = {}
        _set_timestamps(d, "2025-01-01T00:00:00Z", None, None)
        assert d["signed_at"] == "2025-01-01T00:00:00Z"

    def test_auto_signs_when_missing(self) -> None:
        d: dict = {}
        _set_timestamps(d, None, None, None)
        assert "signed_at" in d
        # Should be a valid ISO timestamp
        datetime.fromisoformat(d["signed_at"])

    def test_does_not_overwrite_existing_signed_at(self) -> None:
        d = {"signed_at": "2024-01-01T00:00:00Z"}
        _set_timestamps(d, "2025-06-01T00:00:00Z", None, None)
        assert d["signed_at"] == "2025-06-01T00:00:00Z"

    def test_expires_in(self) -> None:
        d: dict = {}
        _set_timestamps(d, None, None, 3600)
        assert "expires_at" in d
        expires = datetime.fromisoformat(d["expires_at"])
        assert (expires - datetime.now(UTC)) < timedelta(seconds=3610)
        assert (expires - datetime.now(UTC)) > timedelta(seconds=3590)

    def test_expires_at_direct(self) -> None:
        d: dict = {}
        _set_timestamps(d, None, "2026-12-31T00:00:00Z", None)
        assert d["expires_at"] == "2026-12-31T00:00:00Z"

    def test_expires_in_takes_priority_over_expires_at(self) -> None:
        d: dict = {}
        _set_timestamps(d, None, "2026-01-01T00:00:00Z", 60)
        assert "expires_at" in d
        # Should use expires_in (60s from now), not the direct expires_at
        expires = datetime.fromisoformat(d["expires_at"])
        assert (expires - datetime.now(UTC)) < timedelta(seconds=120)


# ---------------------------------------------------------------------------
# _candidate_summary
# ---------------------------------------------------------------------------

class TestCandidateSummary:
    def test_basic_summary(self) -> None:
        candidate = Candidate(
            domain="adapter",
            key="cache",
            provider="redis",
            priority=10,
            stack_level=1,
            factory=lambda: None,
            source=CandidateSource.REMOTE_MANIFEST,
            metadata={"version": "2.0"},
        )
        summary = _candidate_summary(candidate)
        assert summary["provider"] == "redis"
        assert summary["priority"] == 10
        assert summary["stack_level"] == 1
        assert summary["source"] == "remote_manifest"
        assert summary["metadata"] == {"version": "2.0"}

    def test_none_values(self) -> None:
        candidate = Candidate(
            domain="adapter",
            key="x",
            factory=lambda: None,
        )
        summary = _candidate_summary(candidate)
        assert summary["provider"] is None
        assert summary["priority"] is None


# ---------------------------------------------------------------------------
# _http_server_enabled
# ---------------------------------------------------------------------------

class TestHttpServerEnabled:
    def _make_settings(self, profile_name: str | None = "production") -> SimpleNamespace:
        profile = SimpleNamespace(name=profile_name)
        return SimpleNamespace(profile=profile)

    def test_no_http_flag(self) -> None:
        assert _http_server_enabled(self._make_settings(), None, True) is False

    def test_explicit_port(self) -> None:
        assert _http_server_enabled(self._make_settings(), 3000, False) is True

    def test_port_overrides_no_http(self) -> None:
        # Even if --no-http is set, explicit port wins... actually no:
        # no_http_flag is checked first
        assert _http_server_enabled(self._make_settings(), 3000, True) is False

    def test_env_port(self) -> None:
        with patch.dict("os.environ", {"PORT": "1"}):
            assert _http_server_enabled(self._make_settings(), None, False) is True

    def test_serverless_profile(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            assert _http_server_enabled(
                self._make_settings("serverless"), None, False
            ) is True

    def test_non_serverless_no_port(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            assert _http_server_enabled(
                self._make_settings("production"), None, False
            ) is False


# ---------------------------------------------------------------------------
# _extract_notification_metadata
# ---------------------------------------------------------------------------

class TestExtractNotificationMetadata:
    def test_no_notification_key(self) -> None:
        candidate = Candidate(
            domain="adapter", key="x", factory=lambda: None,
            metadata={},
        )
        assert _extract_notification_metadata(candidate) is None

    def test_with_notification_config(self) -> None:
        candidate = Candidate(
            domain="adapter", key="x", factory=lambda: None,
            metadata={"notifications": {"channel": "slack", "target": "#ops"}},
        )
        result = _extract_notification_metadata(candidate)
        assert result is not None
        assert result["channel"] == "slack"
        assert result["target"] == "#ops"

    def test_notification_is_string_skipped(self) -> None:
        candidate = Candidate(
            domain="adapter", key="x", factory=lambda: None,
            metadata={"notifications": "yes"},
        )
        assert _extract_notification_metadata(candidate) is None

    def test_default_include_context(self) -> None:
        candidate = Candidate(
            domain="adapter", key="x", factory=lambda: None,
            metadata={"notifications": {"channel": "email"}},
        )
        result = _extract_notification_metadata(candidate)
        assert result["include_context"] is True

    def test_extra_payload_non_dict(self) -> None:
        candidate = Candidate(
            domain="adapter", key="x", factory=lambda: None,
            metadata={"notifications": {"extra_payload": "not_a_dict"}},
        )
        result = _extract_notification_metadata(candidate)
        assert result["extra_payload"] is None
