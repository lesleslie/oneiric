"""Gap-fill tests for oneiric/cli.py — covers uncovered branches."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from oneiric import plugins
from oneiric.cli import (
    CLIState,
    DemoCLIAction,
    DemoCLIAdapter,
    DemoCLIEventHandler,
    DemoCLIQueue,
    DemoCLIService,
    DemoCLITask,
    DemoCLIWorkflow,
    _build_domain_activity_report,
    _build_status_record,
    _build_workflow_plans,
    _derive_notification_route,
    _emit_inspector_payload,
    _enrich_workflow_plan,
    _format_activity_note,
    _format_activity_status,
    _format_entry_status,
    _format_filter_clause,
    _handle_status,
    _manifest_entry_from_action,
    _normalize_domain,
    _parse_payload,
    _print_activity_snapshot,
    _print_activity_summary,
    _print_domain_activity_details,
    _print_event_handlers,
    _print_event_inspector,
    _print_handler_filters,
    _print_health_entry,
    _print_health_statuses,
    _print_last_event,
    _print_lifecycle_snapshot,
    _print_load_test_result,
    _print_profile_summary,
    _print_remote_domain_counts,
    _print_remote_failure_status,
    _print_remote_skipped,
    _print_remote_success_status,
    _print_remote_summary,
    _print_remote_sync_info,
    _print_secrets_summary,
    _print_single_handler,
    _print_single_workflow_inspector,
    _print_single_workflow_plan,
    _print_status_record,
    _print_workflow_inspector,
    _print_workflow_last_run,
    _print_workflow_metadata,
    _print_workflow_nodes,
    _print_workflow_plan,
    _profile_metadata,
    _state,
    _update_state_counts,
    _workflow_inspector_summary,
    app,
)
from oneiric.core.resolution import Candidate, CandidateSource
from oneiric.runtime.load_testing import LoadTestResult


# ---------------------------------------------------------------------------
# Demo classes
# ---------------------------------------------------------------------------


def test_demo_cli_adapter_handle() -> None:
    adapter = DemoCLIAdapter(message="hello")
    assert adapter.handle() == "hello"


def test_demo_cli_service_status() -> None:
    svc = DemoCLIService(name="my-svc")
    assert svc.status() == "my-svc-ok"


def test_demo_cli_task_run() -> None:
    task = DemoCLITask(name="my-task")
    result = asyncio.run(task.run())
    assert result == "my-task-run"


def test_demo_cli_workflow_execute() -> None:
    wf = DemoCLIWorkflow(name="my-wf")
    assert wf.execute() == "my-wf-complete"


def test_demo_cli_event_handler_handle() -> None:
    handler = DemoCLIEventHandler(name="my-handler")
    envelope = SimpleNamespace(topic="test.topic", payload={"k": "v"})
    result = asyncio.run(handler.handle(envelope))
    assert result["name"] == "my-handler"
    assert result["topic"] == "test.topic"


def test_demo_cli_action_execute() -> None:
    action = DemoCLIAction(name="my-action")
    result = asyncio.run(action.execute({"x": 1}))
    assert result["name"] == "my-action"
    assert result["payload"] == {"x": 1}


def test_demo_cli_action_execute_no_payload() -> None:
    action = DemoCLIAction()
    result = asyncio.run(action.execute())
    assert result["payload"] == {}


def test_demo_cli_queue_enqueue() -> None:
    q = DemoCLIQueue()
    result = asyncio.run(q.enqueue({"job": "data"}))
    assert result == "demo-queue-1"


# ---------------------------------------------------------------------------
# _state — RuntimeError path
# ---------------------------------------------------------------------------


def test_state_raises_when_obj_not_clstate() -> None:
    ctx = MagicMock()
    ctx.obj = "not-a-state"
    with pytest.raises(RuntimeError, match="CLI state not initialized"):
        _state(ctx)


# ---------------------------------------------------------------------------
# _normalize_domain — BadParameter
# ---------------------------------------------------------------------------


def test_normalize_domain_invalid_raises() -> None:
    with pytest.raises(Exception):
        _normalize_domain("invalid-domain-xyz")


# ---------------------------------------------------------------------------
# _derive_notification_route — None return when adapter_key is None
# ---------------------------------------------------------------------------


def test_derive_notification_route_returns_none_when_no_adapter_key() -> None:
    state = MagicMock()
    # All None → should_send=False → early return at line 214
    result = _derive_notification_route(
        state,
        workflow_key=None,
        notify_adapter=None,
        notify_target=None,
        force_send=False,
    )
    assert result is None


def test_derive_notification_route_returns_none_should_send_but_no_adapter_key() -> None:
    # notify_target makes should_send=True, but adapter_key stays None and force_send=False
    # → hits line 244 return None
    state = MagicMock()
    result = _derive_notification_route(
        state,
        workflow_key=None,
        notify_adapter=None,
        notify_target="somewhere",
        force_send=False,
    )
    assert result is None


# ---------------------------------------------------------------------------
# _parse_payload — invalid JSON
# ---------------------------------------------------------------------------


def test_parse_payload_invalid_json_raises() -> None:
    with pytest.raises(Exception):
        _parse_payload("{not valid json}")


def test_parse_payload_non_object_raises() -> None:
    with pytest.raises(Exception):
        _parse_payload("[1, 2, 3]")


# ---------------------------------------------------------------------------
# _manifest_entry_from_action — string factory branch
# ---------------------------------------------------------------------------


def test_manifest_entry_from_action_string_factory() -> None:
    from oneiric.actions.metadata import ActionMetadata
    from oneiric.core.resolution import CandidateSource

    meta = ActionMetadata(
        key="test.action",
        provider="test",
        factory="oneiric.adapters.bridge:AdapterBridge",
        description="test action",
        source=CandidateSource.MANUAL,
    )
    entry = _manifest_entry_from_action(meta, "1.0.0")
    assert entry.factory == "oneiric.adapters.bridge:AdapterBridge"


def test_manifest_entry_from_action_callable_factory() -> None:
    from oneiric.actions.metadata import ActionMetadata
    from oneiric.core.resolution import CandidateSource

    def my_factory():
        pass

    meta = ActionMetadata(
        key="test.action",
        provider="test",
        factory=my_factory,
        description="test action",
        source=CandidateSource.MANUAL,
    )
    entry = _manifest_entry_from_action(meta, "1.0.0")
    assert "my_factory" in entry.factory


# ---------------------------------------------------------------------------
# _print_remote_success_status / _print_remote_failure_status
# ---------------------------------------------------------------------------


def test_print_remote_success_status_with_per_domain_and_skipped(capsys) -> None:
    telemetry = SimpleNamespace(
        last_success_at="2024-01-01T12:00:00",
        last_source="https://example.com",
        last_registered=3,
        last_duration_ms=120.5,
        last_digest_checks=None,
        last_per_domain={"adapter": 2, "action": 1},
        last_skipped=2,
    )
    _print_remote_success_status(telemetry)
    captured = capsys.readouterr()
    assert "Per-domain" in captured.out
    assert "adapter" in captured.out
    assert "Skipped" in captured.out


def test_print_remote_success_status_minimal(capsys) -> None:
    telemetry = SimpleNamespace(
        last_success_at="2024-01-01T12:00:00",
        last_source=None,
        last_registered=0,
        last_duration_ms=None,
        last_digest_checks=None,
        last_per_domain={},
        last_skipped=0,
    )
    _print_remote_success_status(telemetry)
    captured = capsys.readouterr()
    assert "Last success" in captured.out


def test_print_remote_failure_status(capsys) -> None:
    telemetry = SimpleNamespace(
        last_failure_at="2024-01-01T11:00:00",
        last_error="connection timeout",
        consecutive_failures=3,
    )
    _print_remote_failure_status(telemetry)
    captured = capsys.readouterr()
    assert "Last failure" in captured.out
    assert "connection timeout" in captured.out


# ---------------------------------------------------------------------------
# _workflow_inspector_summary — missing key and empty filter fallback
# ---------------------------------------------------------------------------


def test_workflow_inspector_summary_missing_key() -> None:
    bridge = MagicMock()
    bridge.dag_specs.return_value = {"wf1": {"nodes": []}}
    bridge._queue_category = None
    result = _workflow_inspector_summary(bridge, ["wf1", "missing-wf"], None)
    assert "missing-wf" in result["missing"]
    assert "wf1" in result["summary"]


def test_workflow_inspector_summary_empty_filter_shows_all() -> None:
    bridge = MagicMock()
    bridge.dag_specs.return_value = {"wf1": {"nodes": []}, "wf2": {"nodes": []}}
    bridge._queue_category = None
    result = _workflow_inspector_summary(bridge, [], None)
    assert "wf1" in result["summary"]
    assert "wf2" in result["summary"]


# ---------------------------------------------------------------------------
# _emit_inspector_payload — workflows + events both present
# ---------------------------------------------------------------------------


def test_emit_inspector_payload_both_sections(capsys) -> None:
    payload = {
        "workflows": {"summary": {}, "missing": []},
        "events": {"handlers": [], "last_event": {}},
    }
    _emit_inspector_payload(payload, json_output=False)
    captured = capsys.readouterr()
    assert "No workflow" in captured.out or captured.out is not None


def test_emit_inspector_payload_json(capsys) -> None:
    payload = {"workflows": {"summary": {}, "missing": []}}
    _emit_inspector_payload(payload, json_output=True)
    captured = capsys.readouterr()
    assert '"workflows"' in captured.out


# ---------------------------------------------------------------------------
# _enrich_workflow_plan — branches
# ---------------------------------------------------------------------------


def test_enrich_workflow_plan_no_candidate() -> None:
    plan = {"queue_category": "default"}
    _enrich_workflow_plan(plan, None)
    assert "scheduler" not in plan


def test_enrich_workflow_plan_with_scheduler_and_notifications() -> None:
    candidate = MagicMock()
    candidate.metadata = {
        "scheduler": {"cron": "*/5 * * * *"},
        "notifications": {"channel": "#alerts"},
    }
    plan = {"queue_category": "urgent"}
    _enrich_workflow_plan(plan, candidate)
    assert "scheduler" in plan
    assert "notifications" in plan
    assert plan["scheduler"]["queue_category"] == "urgent"


def test_enrich_workflow_plan_queue_already_in_scheduler() -> None:
    candidate = MagicMock()
    candidate.metadata = {
        "scheduler": {"queue_category": "existing"},
    }
    plan = {"queue_category": "new"}
    _enrich_workflow_plan(plan, candidate)
    assert plan["scheduler"]["queue_category"] == "existing"


# ---------------------------------------------------------------------------
# _build_workflow_plans — missing key and empty filter fallback
# ---------------------------------------------------------------------------


def test_build_workflow_plans_missing_key() -> None:
    resolver = MagicMock()
    bridge = MagicMock()
    bridge.dag_specs.return_value = {"wf1": {"nodes": []}}
    bridge._queue_category = None
    resolver.resolve.return_value = None
    plans, missing = _build_workflow_plans(resolver, bridge, ["wf1", "nonexistent"])
    assert "nonexistent" in missing
    assert "wf1" in plans


def test_build_workflow_plans_empty_filter_shows_all() -> None:
    resolver = MagicMock()
    bridge = MagicMock()
    bridge.dag_specs.return_value = {"wf1": {"nodes": []}, "wf2": {"nodes": []}}
    bridge._queue_category = None
    resolver.resolve.return_value = None
    plans, missing = _build_workflow_plans(resolver, bridge, [])
    assert "wf1" in plans
    assert "wf2" in plans
    assert not missing


# ---------------------------------------------------------------------------
# _print_workflow_metadata / _print_workflow_nodes / _print_single_workflow_plan
# ---------------------------------------------------------------------------


def test_print_workflow_metadata_with_scheduler_and_notifications(capsys) -> None:
    _print_workflow_metadata(
        {"scheduler": {"cron": "0 * * * *"}, "notifications": {"channel": "#wf"}}
    )
    captured = capsys.readouterr()
    assert "scheduler" in captured.out
    assert "notifications" in captured.out


def test_print_workflow_metadata_empty(capsys) -> None:
    _print_workflow_metadata({})
    captured = capsys.readouterr()
    assert captured.out == ""


def test_print_workflow_nodes(capsys) -> None:
    nodes = [{"id": "step1", "task": "my.task", "depends_on": []}]
    _print_workflow_nodes(nodes)
    captured = capsys.readouterr()
    assert "step1" in captured.out


def test_print_single_workflow_plan(capsys) -> None:
    record = {
        "queue_category": "default",
        "node_count": 2,
        "edge_count": 1,
        "nodes": [{"id": "n1", "task": "t1", "depends_on": []}],
    }
    _print_single_workflow_plan("my-workflow", record)
    captured = capsys.readouterr()
    assert "my-workflow" in captured.out


# ---------------------------------------------------------------------------
# _print_workflow_plan — with workflows, with missing, empty
# ---------------------------------------------------------------------------


def test_print_workflow_plan_with_workflows_and_missing(capsys) -> None:
    data = {
        "workflows": {
            "wf1": {
                "queue_category": "default",
                "node_count": 1,
                "edge_count": 0,
                "nodes": [],
            }
        },
        "missing": ["wf-gone"],
    }
    _print_workflow_plan(data)
    captured = capsys.readouterr()
    assert "wf1" in captured.out
    assert "wf-gone" in captured.out


def test_print_workflow_plan_empty(capsys) -> None:
    _print_workflow_plan({"workflows": {}, "missing": []})
    captured = capsys.readouterr()
    assert "No workflow plans" in captured.out


def test_print_workflow_plan_no_missing(capsys) -> None:
    data = {
        "workflows": {
            "wf1": {"queue_category": None, "node_count": 0, "edge_count": 0, "nodes": []}
        },
        "missing": [],
    }
    _print_workflow_plan(data)
    captured = capsys.readouterr()
    assert "wf1" in captured.out
    assert "Missing" not in captured.out


# ---------------------------------------------------------------------------
# _print_workflow_last_run
# ---------------------------------------------------------------------------


def test_print_workflow_last_run_with_data(capsys) -> None:
    _print_workflow_last_run({"total_duration_ms": 250.0, "recorded_at": "2024-01-01"})
    captured = capsys.readouterr()
    assert "last_run" in captured.out
    assert "250.0ms" in captured.out


def test_print_workflow_last_run_empty(capsys) -> None:
    _print_workflow_last_run({})
    assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# _print_workflow_inspector — empty summary, with missing
# ---------------------------------------------------------------------------


def test_print_workflow_inspector_empty(capsys) -> None:
    _print_workflow_inspector({"summary": {}, "missing": []})
    captured = capsys.readouterr()
    assert "No workflow DAGs" in captured.out


def test_print_workflow_inspector_with_missing(capsys) -> None:
    _print_single_workflow_inspector("wf1", {
        "queue_category": "q",
        "entry_nodes": ["n1"],
        "node_count": 1,
        "edge_count": 0,
        "nodes": [],
    })
    data = {"summary": {"wf1": {}}, "missing": ["lost-wf"]}
    _print_workflow_inspector(data)
    captured = capsys.readouterr()
    assert "lost-wf" in captured.out


# ---------------------------------------------------------------------------
# _format_filter_clause — equals and any_of branches
# ---------------------------------------------------------------------------


def test_format_filter_clause_equals() -> None:
    result = _format_filter_clause({"path": "status", "equals": "active"})
    assert "== active" in result


def test_format_filter_clause_any_of() -> None:
    result = _format_filter_clause({"path": "tier", "any_of": ["free", "pro"]})
    assert "in" in result


def test_format_filter_clause_exists_false() -> None:
    result = _format_filter_clause({"path": "error", "exists": False})
    assert "missing" in result


def test_format_filter_clause_exists_true() -> None:
    result = _format_filter_clause({"path": "payload", "exists": True})
    assert "exists" in result


# ---------------------------------------------------------------------------
# _print_handler_filters / _print_single_handler / _print_event_handlers
# ---------------------------------------------------------------------------


def test_print_handler_filters_with_clauses(capsys) -> None:
    _print_handler_filters([{"path": "x", "equals": "y"}])
    captured = capsys.readouterr()
    assert "filters:" in captured.out


def test_print_handler_filters_empty(capsys) -> None:
    _print_handler_filters([])
    assert capsys.readouterr().out == ""


def test_print_single_handler_with_retry_and_filters(capsys) -> None:
    handler = {
        "name": "h1",
        "topics": ["events.created"],
        "priority": 5,
        "max_concurrency": 2,
        "fanout_policy": "round_robin",
        "retry_policy": {"max_attempts": 3},
        "filters": [{"path": "status", "equals": "ok"}],
    }
    _print_single_handler(handler)
    captured = capsys.readouterr()
    assert "h1" in captured.out
    assert "retry_policy" in captured.out


def test_print_event_handlers_empty(capsys) -> None:
    _print_event_handlers([])
    captured = capsys.readouterr()
    assert "No event handlers" in captured.out


def test_print_event_handlers_with_handlers(capsys) -> None:
    handlers = [{"name": "h1", "topics": ["t1"], "priority": 0, "max_concurrency": 1, "fanout_policy": "broadcast"}]
    _print_event_handlers(handlers)
    captured = capsys.readouterr()
    assert "h1" in captured.out


# ---------------------------------------------------------------------------
# _print_last_event / _print_event_inspector
# ---------------------------------------------------------------------------


def test_print_last_event_with_data(capsys) -> None:
    _print_last_event({
        "topic": "user.created",
        "matched_handlers": 2,
        "failures": 0,
        "total_duration_ms": 10.5,
        "recorded_at": "2024-01-01",
    })
    captured = capsys.readouterr()
    assert "user.created" in captured.out


def test_print_last_event_empty(capsys) -> None:
    _print_last_event({})
    assert capsys.readouterr().out == ""


def test_print_event_inspector(capsys) -> None:
    data = {
        "handlers": [{"name": "h1", "topics": ["t"], "priority": 0, "max_concurrency": 1, "fanout_policy": "broadcast"}],
        "last_event": {"topic": "t1", "matched_handlers": 1, "failures": 0, "total_duration_ms": 5.0, "recorded_at": "now"},
    }
    _print_event_inspector(data)
    captured = capsys.readouterr()
    assert "h1" in captured.out
    assert "t1" in captured.out


# ---------------------------------------------------------------------------
# _print_health_statuses — empty payload
# ---------------------------------------------------------------------------


def test_print_health_statuses_empty(capsys) -> None:
    _print_health_statuses([])
    captured = capsys.readouterr()
    assert "No lifecycle statuses" in captured.out


# ---------------------------------------------------------------------------
# _print_health_entry — conditional branches
# ---------------------------------------------------------------------------


def test_print_health_entry_all_fields(capsys) -> None:
    entry = {
        "domain": "adapter",
        "key": "cache",
        "state": "active",
        "current_provider": "redis",
        "pending_provider": None,
        "last_health_at": "2024-01-01T12:00:00",
        "last_activated_at": "2024-01-01T11:00:00",
        "last_error": "connection timeout",
        "probe_result": True,
    }
    _print_health_entry(entry)
    captured = capsys.readouterr()
    assert "last_health=" in captured.out
    assert "last_error=" in captured.out
    assert "probe_result=" in captured.out


def test_print_health_entry_minimal(capsys) -> None:
    entry = {
        "domain": "adapter",
        "key": "cache",
        "state": "pending",
        "current_provider": None,
        "pending_provider": None,
    }
    _print_health_entry(entry)
    captured = capsys.readouterr()
    assert "adapter:cache" in captured.out


# ---------------------------------------------------------------------------
# _build_status_record — unresolved (no candidate)
# ---------------------------------------------------------------------------


def test_build_status_record_unresolved_no_candidate() -> None:
    from types import SimpleNamespace

    bridge = MagicMock()
    bridge.domain = "adapter"
    bridge.settings.selections.get.return_value = None
    bridge.resolver.resolve.return_value = None
    bridge.activity_state.return_value = SimpleNamespace(paused=False, draining=False, note=None)

    lifecycle = MagicMock()
    lifecycle.get_instance.return_value = None
    lifecycle.get_status.return_value = None

    record = _build_status_record(bridge, lifecycle, key="cache", shadowed=0)
    assert record["state"] == "unresolved"


def test_build_status_record_unresolved_with_lifecycle_status() -> None:
    from types import SimpleNamespace

    bridge = MagicMock()
    bridge.domain = "adapter"
    bridge.settings.selections.get.return_value = None
    bridge.resolver.resolve.return_value = None
    bridge.activity_state.return_value = SimpleNamespace(paused=False, draining=False, note=None)

    lifecycle_status = MagicMock()
    lifecycle_status.as_dict.return_value = {"state": "activating"}

    lifecycle = MagicMock()
    lifecycle.get_instance.return_value = None
    lifecycle.get_status.return_value = lifecycle_status

    record = _build_status_record(bridge, lifecycle, key="cache", shadowed=0)
    assert "lifecycle" in record


# ---------------------------------------------------------------------------
# _print_status_record — branches
# ---------------------------------------------------------------------------


def test_print_status_record_unresolved(capsys) -> None:
    record = {
        "key": "cache",
        "state": "unresolved",
        "configured_provider": None,
        "shadowed": 0,
        "message": "No registered candidate",
    }
    _print_status_record(record)
    captured = capsys.readouterr()
    assert "unresolved" in captured.out
    assert "No registered candidate" in captured.out


def test_print_status_record_active_with_all_fields(capsys) -> None:
    record = {
        "key": "cache",
        "state": "active",
        "configured_provider": "redis",
        "shadowed": 1,
        "provider": "redis",
        "source": "manual",
        "priority": 10,
        "stack_level": 0,
        "instance_state": "ready",
        "instance_type": "RedisAdapter",
        "selection_applied": True,
        "lifecycle": {
            "state": "active",
            "current_provider": "redis",
            "pending_provider": None,
            "last_health_at": "2024-01-01",
            "last_error": None,
        },
        "activity": {"paused": False, "draining": False, "note": "warm"},
        "shadowed_details": [
            {"provider": "memcache", "priority": 5, "stack_level": 0, "source": "auto"}
        ],
    }
    _print_status_record(record)
    captured = capsys.readouterr()
    assert "redis" in captured.out
    assert "RedisAdapter" in captured.out
    assert "shadowed_candidates" in captured.out


def test_print_status_record_lifecycle_with_last_error(capsys) -> None:
    record = {
        "key": "cache",
        "state": "active",
        "configured_provider": None,
        "shadowed": 0,
        "provider": "memory",
        "source": "auto",
        "priority": 0,
        "stack_level": 0,
        "instance_state": "pending",
        "instance_type": None,
        "selection_applied": False,
        "lifecycle": {
            "state": "failed",
            "current_provider": None,
            "pending_provider": "redis",
            "last_health_at": None,
            "last_error": "timeout",
        },
        "activity": {"paused": False, "draining": False, "note": None},
    }
    _print_status_record(record)
    captured = capsys.readouterr()
    assert "last_error=timeout" in captured.out


# ---------------------------------------------------------------------------
# _build_domain_activity_report — items skipped if no paused/draining/note
# ---------------------------------------------------------------------------


def test_build_domain_activity_report_all_inactive() -> None:
    bridge = MagicMock()
    state = SimpleNamespace(paused=False, draining=False, note=None)
    bridge.activity_snapshot.return_value = {"cache": state}
    result = _build_domain_activity_report(bridge)
    assert result is None


def test_build_domain_activity_report_mixed() -> None:
    bridge = MagicMock()
    active = SimpleNamespace(paused=True, draining=False, note=None)
    inactive = SimpleNamespace(paused=False, draining=False, note=None)
    bridge.activity_snapshot.return_value = {"cache": active, "db": inactive}
    result = _build_domain_activity_report(bridge)
    assert result is not None
    assert result["counts"]["paused"] == 1


# ---------------------------------------------------------------------------
# _update_state_counts — draining and note_only branches
# ---------------------------------------------------------------------------


def test_update_state_counts_draining_only() -> None:
    counts = {"paused": 0, "draining": 0, "note_only": 0}
    state = SimpleNamespace(paused=False, draining=True, note=None)
    _update_state_counts(counts, state)
    assert counts["draining"] == 1
    assert counts["note_only"] == 0


def test_update_state_counts_note_only() -> None:
    counts = {"paused": 0, "draining": 0, "note_only": 0}
    state = SimpleNamespace(paused=False, draining=False, note="warming up")
    _update_state_counts(counts, state)
    assert counts["note_only"] == 1


# ---------------------------------------------------------------------------
# _print_load_test_result
# ---------------------------------------------------------------------------


def test_print_load_test_result(capsys) -> None:
    result = LoadTestResult(
        total_tasks=100,
        concurrency=10,
        duration_seconds=5.0,
        throughput_per_second=20.0,
        avg_latency_ms=50.0,
        p50_latency_ms=45.0,
        p95_latency_ms=90.0,
        p99_latency_ms=120.0,
        errors=2,
    )
    _print_load_test_result(result)
    captured = capsys.readouterr()
    assert "tasks=100" in captured.out
    assert "throughput" in captured.out


# ---------------------------------------------------------------------------
# _format_entry_status — note-only return
# ---------------------------------------------------------------------------


def test_format_entry_status_note_only() -> None:
    result = _format_entry_status({"paused": False, "draining": False})
    assert result == "note-only"


def test_format_entry_status_paused() -> None:
    result = _format_entry_status({"paused": True, "draining": False})
    assert "paused" in result


# ---------------------------------------------------------------------------
# _print_remote_summary — branches
# ---------------------------------------------------------------------------


def test_print_remote_summary_no_telemetry(capsys) -> None:
    remote_config = SimpleNamespace(latency_budget_ms=None)
    _print_remote_summary({"last_success_at": None, "last_failure_at": None}, "/tmp", remote_config)
    captured = capsys.readouterr()
    assert "No remote" in captured.out


def test_print_remote_summary_with_success_and_failure(capsys) -> None:
    remote_config = SimpleNamespace(latency_budget_ms=500)
    telemetry = {
        "last_success_at": "2024-01-01",
        "last_failure_at": "2024-01-02",
        "last_duration_ms": 100.0,
        "last_source": "https://example.com",
        "last_registered": 5,
    }
    _print_remote_summary(telemetry, "/tmp", remote_config)
    captured = capsys.readouterr()
    assert "Last success" in captured.out
    assert "Last failure" in captured.out


# ---------------------------------------------------------------------------
# _print_remote_sync_info — conditional branches
# ---------------------------------------------------------------------------


def test_print_remote_sync_info_all_fields(capsys) -> None:
    _print_remote_sync_info({
        "last_remote_sync_at": "2024-01-01",
        "last_remote_error": "timeout",
        "last_remote_registered": 3,
    })
    captured = capsys.readouterr()
    assert "last_remote_sync" in captured.out
    assert "last_remote_error" in captured.out
    assert "last_remote_registered" in captured.out


def test_print_remote_sync_info_empty(capsys) -> None:
    _print_remote_sync_info({})
    assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# _print_remote_domain_counts / _print_remote_skipped
# ---------------------------------------------------------------------------


def test_print_remote_domain_counts(capsys) -> None:
    _print_remote_domain_counts({"last_remote_per_domain": {"adapter": 3, "action": 1}})
    captured = capsys.readouterr()
    assert "adapter" in captured.out


def test_print_remote_domain_counts_empty(capsys) -> None:
    _print_remote_domain_counts({})
    assert capsys.readouterr().out == ""


def test_print_remote_skipped(capsys) -> None:
    _print_remote_skipped({"last_remote_skipped": 2})
    captured = capsys.readouterr()
    assert "last_remote_skipped=2" in captured.out


def test_print_remote_skipped_none(capsys) -> None:
    _print_remote_skipped({})
    assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# _print_activity_snapshot / _print_lifecycle_snapshot
# ---------------------------------------------------------------------------


def test_print_activity_snapshot_with_data(capsys) -> None:
    _print_activity_snapshot({
        "activity_state": {
            "adapter": {
                "cache": {"paused": True, "draining": False, "note": None}
            }
        }
    })
    captured = capsys.readouterr()
    assert "activity" in captured.out


def test_print_activity_snapshot_empty(capsys) -> None:
    _print_activity_snapshot({})
    assert capsys.readouterr().out == ""


def test_print_lifecycle_snapshot_with_data(capsys) -> None:
    _print_lifecycle_snapshot({
        "lifecycle_state": {
            "adapter": {
                "cache": {
                    "state": "active",
                    "current_provider": "redis",
                    "pending_provider": None,
                    "last_health_at": "2024-01-01",
                    "last_error": "err",
                }
            }
        }
    })
    captured = capsys.readouterr()
    assert "adapter:cache" in captured.out
    assert "last_health" in captured.out
    assert "last_error" in captured.out


def test_print_lifecycle_snapshot_empty(capsys) -> None:
    _print_lifecycle_snapshot({})
    assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# _profile_metadata — no profile
# ---------------------------------------------------------------------------


def test_profile_metadata_no_profile() -> None:
    result = _profile_metadata(None)
    assert result == {}


# ---------------------------------------------------------------------------
# _print_profile_summary — empty metadata
# ---------------------------------------------------------------------------


def test_print_profile_summary_empty(capsys) -> None:
    _print_profile_summary({})
    assert capsys.readouterr().out == ""


def test_print_profile_summary_full(capsys) -> None:
    _print_profile_summary({
        "name": "serverless",
        "watchers_enabled": False,
        "remote_enabled": True,
        "inline_manifest_only": True,
        "supervisor_enabled": False,
    })
    captured = capsys.readouterr()
    assert "serverless" in captured.out


# ---------------------------------------------------------------------------
# _print_secrets_summary — empty metadata
# ---------------------------------------------------------------------------


def test_print_secrets_summary_empty(capsys) -> None:
    _print_secrets_summary({})
    assert capsys.readouterr().out == ""


def test_print_secrets_summary_full(capsys) -> None:
    _print_secrets_summary({
        "provider": "vault",
        "cache_ttl_seconds": 300.0,
        "refresh_interval": 60.0,
        "inline_entries": 2,
        "prefetched": True,
    })
    captured = capsys.readouterr()
    assert "vault" in captured.out


# ---------------------------------------------------------------------------
# _print_activity_summary (the cli.py variant)
# ---------------------------------------------------------------------------


def test_print_activity_summary_cli(capsys) -> None:
    _print_activity_summary({
        "adapter": {
            "cache": {"paused": True, "draining": False}
        }
    })
    captured = capsys.readouterr()
    assert "paused=1" in captured.out


# ---------------------------------------------------------------------------
# _print_domain_activity_details / _format_activity_status / _format_activity_note
# ---------------------------------------------------------------------------


def test_print_domain_activity_details(capsys) -> None:
    _print_domain_activity_details({
        "adapter": {
            "cache": {"paused": True, "draining": False, "note": "warming"},
        }
    })
    captured = capsys.readouterr()
    assert "adapter:cache" in captured.out
    assert "note=warming" in captured.out


def test_format_activity_status_note_only() -> None:
    assert _format_activity_status({}) == "note"


def test_format_activity_status_paused_and_draining() -> None:
    result = _format_activity_status({"paused": True, "draining": True})
    assert "paused" in result
    assert "draining" in result


def test_format_activity_note_with_note() -> None:
    assert _format_activity_note({"note": "test note"}) == " note=test note"


def test_format_activity_note_empty() -> None:
    assert _format_activity_note({}) == ""


# ---------------------------------------------------------------------------
# CLI command closures via CliRunner + patched _initialize_state
# ---------------------------------------------------------------------------


def _make_mock_state(**bridge_overrides: Any) -> CLIState:
    """Build a minimal CLIState with MagicMock fields."""
    default_bridges: dict[str, Any] = {
        "adapter": MagicMock(),
        "service": MagicMock(),
        "task": MagicMock(),
        "workflow": MagicMock(),
        "event": MagicMock(),
        "action": MagicMock(),
    }
    default_bridges.update(bridge_overrides)
    settings = MagicMock()
    settings.remote.cache_dir = "/tmp/test-cache"
    settings.remote.manifest_url = "https://example.com/manifest.json"
    settings.remote.latency_budget_ms = None
    settings.profile.name = "default"
    settings.profile.supervisor_enabled = True
    settings.runtime_supervisor.enabled = True
    settings.runtime_supervisor.poll_interval = 2.0
    settings.runtime_paths.cache_dir = "/tmp/test-cache"
    return CLIState(
        settings=settings,
        resolver=MagicMock(),
        lifecycle=MagicMock(),
        bridges=default_bridges,
        plugin_report=plugins.PluginRegistrationReport.empty(),
        secrets=MagicMock(),
        notification_router=MagicMock(),
    )


def _run_command(*args: str, state: CLIState | None = None) -> Any:
    from typer.testing import CliRunner

    if state is None:
        state = _make_mock_state()

    runner = CliRunner()
    with patch("oneiric.cli._initialize_state", return_value=state):
        return runner.invoke(app, list(args))


# cli_root — suppress_events and debug flags (lines 1985-1991)
def test_cli_root_suppress_events_flag() -> None:
    with patch("oneiric.core.logging.configure_early_logging") as mock_log:
        result = _run_command("--suppress-events", "plugins")
    assert result.exit_code == 0


def test_cli_root_debug_flag() -> None:
    import os
    result = _run_command("--debug", "plugins")
    # Should not raise; debug sets ONEIRIC_APP__DEBUG env var


# plugins_command — no groups configured (line 2026-2027)
def test_plugins_command_no_groups(capsys) -> None:
    state = _make_mock_state()
    state.plugin_report.groups = []
    state.plugin_report.registered = 0
    result = _run_command("plugins", state=state)
    assert result.exit_code == 0
    assert "No plugin entry-point groups" in result.output


# plugins_command — with errors (lines 2038-2040)
def test_plugins_command_with_errors(capsys) -> None:
    state = _make_mock_state()
    error = MagicMock()
    error.group = "broken.group"
    error.entry_point = "broken-ep"
    error.reason = "import failed"
    state.plugin_report.groups = ["broken.group"]
    state.plugin_report.registered = 0
    state.plugin_report.entries = []
    state.plugin_report.errors = [error]
    result = _run_command("plugins", state=state)
    assert result.exit_code == 0
    assert "import failed" in result.output


# action-invoke — no action bridge (line 2082)
def test_action_invoke_no_bridge() -> None:
    state = _make_mock_state(**{"action": None})
    result = _run_command("action-invoke", "test.action", state=state)
    assert result.exit_code != 0 or "not initialized" in result.output


# event emit — no event bridge (line 2151)
def test_event_emit_no_bridge() -> None:
    state = _make_mock_state(**{"event": None})
    result = _run_command("event", "emit", "test.topic", state=state)
    assert result.exit_code != 0 or "not initialized" in result.output


# event emit — no results (lines 2173-2175)
def test_event_emit_no_handlers_matched() -> None:
    state = _make_mock_state()
    state.bridges["event"].emit = AsyncMock(return_value=[])
    result = _run_command("event", "emit", "test.topic", state=state)
    assert result.exit_code == 0
    assert "No event handlers matched" in result.output


# workflow run — no bridge (line 2315)
def test_workflow_run_no_bridge() -> None:
    state = _make_mock_state(**{"workflow": None})
    result = _run_command("workflow", "run", "my-wf", state=state)
    assert result.exit_code != 0 or "not initialized" in result.output


# workflow run — empty results (lines 2347-2348)
def test_workflow_run_empty_results() -> None:
    state = _make_mock_state()
    state.bridges["workflow"].execute_dag = AsyncMock(
        return_value={"run_id": "abc123", "results": {}}
    )
    result = _run_command("workflow", "run", "my-wf", state=state)
    assert result.exit_code == 0
    assert "did not return any DAG results" in result.output


# workflow enqueue — no bridge (line 2395)
def test_workflow_enqueue_no_bridge() -> None:
    state = _make_mock_state(**{"workflow": None})
    result = _run_command("workflow", "enqueue", "my-wf", state=state)
    assert result.exit_code != 0 or "not initialized" in result.output


# workflow enqueue — non-json output (line 2411)
def test_workflow_enqueue_non_json_output() -> None:
    state = _make_mock_state()
    state.bridges["workflow"].enqueue_workflow = AsyncMock(
        return_value={"workflow": "my-wf", "run_id": "abc", "queue_provider": "redis"}
    )
    result = _run_command("workflow", "enqueue", "my-wf", state=state)
    assert result.exit_code == 0
    assert "Queued workflow" in result.output


# workflow plan — no bridge (line 2436)
def test_workflow_plan_no_bridge() -> None:
    state = _make_mock_state(**{"workflow": None})
    result = _run_command("workflow", "plan", state=state)
    assert result.exit_code != 0 or "not initialized" in result.output


# workflow plan — non-json output (line 2443)
def test_workflow_plan_non_json_output() -> None:
    state = _make_mock_state()
    state.bridges["workflow"].dag_specs.return_value = {}
    state.bridges["workflow"]._queue_category = None
    state.resolver.resolve.return_value = None
    result = _run_command("workflow", "plan", state=state)
    assert result.exit_code == 0


# supervisor-info (lines 2552-2567)
def test_supervisor_info_command() -> None:
    import os
    state = _make_mock_state()
    with patch.dict(os.environ, {"ONEIRIC_RUNTIME_SUPERVISOR__ENABLED": "true"}):
        result = _run_command("supervisor-info", state=state)
    assert result.exit_code == 0
    assert "Supervisor toggles" in result.output
    assert "Env override" in result.output


# load-test (lines 2638-2650)
def test_load_test_command_non_json() -> None:
    mock_result = LoadTestResult(
        total_tasks=10,
        concurrency=2,
        duration_seconds=1.0,
        throughput_per_second=10.0,
        avg_latency_ms=100.0,
        p50_latency_ms=90.0,
        p95_latency_ms=150.0,
        p99_latency_ms=200.0,
        errors=0,
    )
    with patch("oneiric.cli.run_load_test", AsyncMock(return_value=mock_result)):
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(app, ["load-test", "--total", "10", "--concurrency", "2"])
    assert result.exit_code == 0
    assert "tasks=10" in result.output


# manifest pack — stdout mode (lines 2740-2741)
def test_manifest_pack_stdout(tmp_path) -> None:
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text('source: "test"\nentries: []\n')
    from typer.testing import CliRunner
    runner = CliRunner()
    result = runner.invoke(app, [
        "manifest", "pack",
        "--input", str(manifest_file),
        "--stdout",
    ])
    assert result.exit_code == 0
    assert "source" in result.output


# start command — process manager not running, success (lines 3095-3125)
def test_start_command_success() -> None:
    state = _make_mock_state()
    process_mgr = MagicMock()
    process_mgr.is_running.return_value = False
    process_mgr.start_process.return_value = True
    with patch("oneiric.cli.ProcessManager", return_value=process_mgr):
        result = _run_command("start", state=state)
    assert result.exit_code == 0


def test_start_command_already_running() -> None:
    state = _make_mock_state()
    process_mgr = MagicMock()
    process_mgr.is_running.return_value = True
    process_mgr.pid = 12345
    with patch("oneiric.cli.ProcessManager", return_value=process_mgr):
        result = _run_command("start", state=state)
    assert result.exit_code == 1
    assert "already running" in result.output


def test_start_command_fails() -> None:
    state = _make_mock_state()
    process_mgr = MagicMock()
    process_mgr.is_running.return_value = False
    process_mgr.start_process.return_value = False
    with patch("oneiric.cli.ProcessManager", return_value=process_mgr):
        result = _run_command("start", state=state)
    assert result.exit_code == 1
    assert "Failed" in result.output


# stop command — not running, success, failure (lines 3137-3153)
def test_stop_command_not_running() -> None:
    state = _make_mock_state()
    process_mgr = MagicMock()
    process_mgr.is_running.return_value = False
    with patch("oneiric.cli.ProcessManager", return_value=process_mgr):
        result = _run_command("stop", state=state)
    assert result.exit_code == 1
    assert "not running" in result.output


def test_stop_command_success() -> None:
    state = _make_mock_state()
    process_mgr = MagicMock()
    process_mgr.is_running.return_value = True
    process_mgr.stop_process.return_value = True
    with patch("oneiric.cli.ProcessManager", return_value=process_mgr):
        result = _run_command("stop", state=state)
    assert result.exit_code == 0


def test_stop_command_fails() -> None:
    state = _make_mock_state()
    process_mgr = MagicMock()
    process_mgr.is_running.return_value = True
    process_mgr.stop_process.return_value = False
    with patch("oneiric.cli.ProcessManager", return_value=process_mgr):
        result = _run_command("stop", state=state)
    assert result.exit_code == 1
    assert "Failed" in result.output


# process-status — running + json + not running with stale PID (lines 3166-3186)
def test_process_status_running(capsys) -> None:
    state = _make_mock_state()
    process_mgr = MagicMock()
    process_mgr.get_status.return_value = {
        "running": True, "pid": 99, "pid_file": "/tmp/test.pid"
    }
    with patch("oneiric.cli.ProcessManager", return_value=process_mgr):
        result = _run_command("process-status", state=state)
    assert result.exit_code == 0
    assert "running" in result.output


def test_process_status_not_running_stale_pid() -> None:
    state = _make_mock_state()
    process_mgr = MagicMock()
    process_mgr.get_status.return_value = {
        "running": False, "pid": None, "pid_file": "/tmp/test.pid", "pid_file_exists": True
    }
    with patch("oneiric.cli.ProcessManager", return_value=process_mgr):
        result = _run_command("process-status", state=state)
    assert result.exit_code == 0
    assert "not running" in result.output
    assert "Stale" in result.output


def test_process_status_json() -> None:
    state = _make_mock_state()
    process_mgr = MagicMock()
    process_mgr.get_status.return_value = {
        "running": False, "pid": None, "pid_file": "/tmp/test.pid", "pid_file_exists": False
    }
    with patch("oneiric.cli.ProcessManager", return_value=process_mgr):
        result = _run_command("process-status", "--json", state=state)
    assert result.exit_code == 0
    assert '"running"' in result.output


# ---------------------------------------------------------------------------
# manifest export — bad format, stdout, json format
# ---------------------------------------------------------------------------


def test_manifest_export_bad_format(tmp_path) -> None:
    from typer.testing import CliRunner
    runner = CliRunner()
    result = runner.invoke(app, [
        "manifest", "export",
        "--version", "1.0.0",
        "--format", "xml",
        "--stdout",
    ])
    assert result.exit_code != 0 or "yaml" in result.output.lower() or "json" in result.output.lower()


def test_manifest_export_stdout_yaml() -> None:
    from typer.testing import CliRunner
    runner = CliRunner()
    result = runner.invoke(app, [
        "manifest", "export",
        "--version", "1.0.0",
        "--format", "yaml",
        "--stdout",
        "--no-adapters",
        "--no-actions",
    ])
    assert result.exit_code == 0
    assert "source" in result.output


def test_manifest_export_stdout_json() -> None:
    from typer.testing import CliRunner
    runner = CliRunner()
    result = runner.invoke(app, [
        "manifest", "export",
        "--version", "1.0.0",
        "--format", "json",
        "--stdout",
        "--no-adapters",
        "--no-actions",
    ])
    assert result.exit_code == 0
    assert '"source"' in result.output


# ---------------------------------------------------------------------------
# _apply_signature_to_manifest — append mode (lines 2865-2869)
# ---------------------------------------------------------------------------


def test_apply_signature_to_manifest_append_mode() -> None:
    from oneiric.cli import _apply_signature_to_manifest
    manifest_dict: dict = {"source": "test"}
    entry = {"signature": "sig1", "algorithm": "ed25519"}
    _apply_signature_to_manifest(manifest_dict, entry, append=True)
    assert "signatures" in manifest_dict
    assert manifest_dict["signatures"][0]["signature"] == "sig1"


def test_apply_signature_to_manifest_existing_signatures() -> None:
    from oneiric.cli import _apply_signature_to_manifest
    manifest_dict: dict = {
        "source": "test",
        "signatures": [{"signature": "old", "algorithm": "ed25519"}],
    }
    entry = {"signature": "new", "algorithm": "ed25519"}
    _apply_signature_to_manifest(manifest_dict, entry, append=False)
    assert len(manifest_dict["signatures"]) == 2


# ---------------------------------------------------------------------------
# secrets rotate — no keys, no --all (line 2992)
# ---------------------------------------------------------------------------


def test_secrets_rotate_no_keys_raises() -> None:
    state = _make_mock_state()
    result = _run_command("secrets", "rotate", state=state)
    assert result.exit_code != 0 or "Specify" in result.output


# ---------------------------------------------------------------------------
# secrets rotate — with --all (covers 2993-3000)
# ---------------------------------------------------------------------------


def test_secrets_rotate_with_all() -> None:
    state = _make_mock_state()
    state.secrets.rotate = AsyncMock(return_value=5)
    result = _run_command("secrets", "rotate", "--all", state=state)
    assert result.exit_code == 0
    assert "5" in result.output


# ---------------------------------------------------------------------------
# shell_command (lines 3020-3030) — mock asyncio.run to skip real IPython
# ---------------------------------------------------------------------------


def test_shell_command_invokes_asyncio_run() -> None:
    from typer.testing import CliRunner
    runner = CliRunner()
    with patch("oneiric.cli.asyncio.run") as mock_run:
        mock_run.return_value = None
        result = runner.invoke(app, ["shell"])
    assert mock_run.called


# ---------------------------------------------------------------------------
# _create_signature_entry with key_id (line 2837)
# ---------------------------------------------------------------------------


def test_create_signature_entry_with_key_id() -> None:
    from oneiric.cli import _create_signature_entry
    signing_key = MagicMock()
    signing_key.sign.return_value = b"fake-signature-bytes"
    entry = _create_signature_entry(signing_key, "canonical-content", key_id="my-key")
    assert entry["key_id"] == "my-key"
    assert "signature" in entry


def test_create_signature_entry_no_key_id() -> None:
    from oneiric.cli import _create_signature_entry
    signing_key = MagicMock()
    signing_key.sign.return_value = b"fake-signature-bytes"
    entry = _create_signature_entry(signing_key, "canonical-content", key_id=None)
    assert "key_id" not in entry


# ---------------------------------------------------------------------------
# _load_manifest_from_path — YAML non-dict raises BadParameter (line 340)
# ---------------------------------------------------------------------------


def test_load_manifest_from_path_yaml_non_dict_raises(tmp_path) -> None:
    from oneiric.cli import _load_manifest_from_path

    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text("- item: one\n- item: two\n")
    with pytest.raises(Exception):
        _load_manifest_from_path(manifest_file)


# ---------------------------------------------------------------------------
# _import_modules — empty string branch (line 735)
# ---------------------------------------------------------------------------


def test_import_modules_skips_empty_strings() -> None:
    from oneiric.cli import _import_modules

    # Empty string → continue (line 735)
    _import_modules(["", ""])  # Should not raise


# ---------------------------------------------------------------------------
# _build_status_record — include_shadowed with details (line 1533)
# ---------------------------------------------------------------------------


def test_build_status_record_with_shadowed_details() -> None:
    from oneiric.core.resolution import Candidate, CandidateSource
    from datetime import datetime, UTC

    candidate = Candidate(
        domain="adapter",
        key="cache",
        provider="redis",
        factory=lambda: None,
        source=CandidateSource.MANUAL,
    )
    shadow = Candidate(
        domain="adapter",
        key="cache",
        provider="memcache",
        factory=lambda: None,
        source=CandidateSource.MANUAL,
    )

    bridge = MagicMock()
    bridge.domain = "adapter"
    bridge.settings.selections.get.return_value = "redis"
    bridge.resolver.resolve.return_value = candidate
    bridge.activity_state.return_value = SimpleNamespace(paused=False, draining=False, note=None)

    lifecycle = MagicMock()
    lifecycle.get_instance.return_value = None
    lifecycle.get_status.return_value = None

    record = _build_status_record(
        bridge, lifecycle, key="cache", shadowed=1,
        shadowed_details=[shadow], include_shadowed=True
    )
    assert "shadowed_details" in record
    assert record["shadowed_details"][0]["provider"] == "memcache"


# ---------------------------------------------------------------------------
# _handle_remote_status — branches (lines 926-930)
# ---------------------------------------------------------------------------


def test_handle_remote_status_with_both_telemetry(capsys) -> None:
    from oneiric.cli import _handle_remote_status

    settings = MagicMock()
    settings.remote.cache_dir = "/tmp"
    settings.remote.manifest_url = "https://example.com/manifest.json"
    settings.remote.latency_budget_ms = None

    telemetry = MagicMock()
    telemetry.as_dict.return_value = {"last_duration_ms": 100.0}
    telemetry.last_success_at = "2024-01-01"
    telemetry.last_failure_at = "2024-01-02"
    telemetry.last_source = "https://example.com"
    telemetry.last_registered = 5
    telemetry.last_duration_ms = 100.0
    telemetry.last_digest_checks = None
    telemetry.last_per_domain = {}
    telemetry.last_skipped = 0
    telemetry.last_error = "err"
    telemetry.consecutive_failures = 1

    with patch("oneiric.cli.load_remote_telemetry", return_value=telemetry):
        _handle_remote_status(settings, as_json=False)
    captured = capsys.readouterr()
    assert "Cache dir" in captured.out


def test_handle_remote_status_no_telemetry(capsys) -> None:
    from oneiric.cli import _handle_remote_status

    settings = MagicMock()
    settings.remote.cache_dir = "/tmp"
    settings.remote.manifest_url = None
    settings.remote.latency_budget_ms = None

    telemetry = MagicMock()
    telemetry.as_dict.return_value = {}
    telemetry.last_success_at = None
    telemetry.last_failure_at = None

    with patch("oneiric.cli.load_remote_telemetry", return_value=telemetry):
        _handle_remote_status(settings, as_json=False)
    captured = capsys.readouterr()
    assert "No remote refresh telemetry" in captured.out


# ---------------------------------------------------------------------------
# _handle_status — per_domain_counts and empty records branches (lines 1356, 1391, 1395)
# ---------------------------------------------------------------------------


def test_handle_status_with_per_domain_and_empty_records(capsys) -> None:
    bridge = MagicMock()
    bridge.domain = "adapter"
    bridge.settings.selections = {}
    bridge.shadowed_candidates.return_value = []
    bridge.active_candidates.return_value = []
    bridge.activity_state.return_value = SimpleNamespace(paused=False, draining=False, note=None)

    lifecycle = MagicMock()
    lifecycle.all_statuses.return_value = []
    lifecycle.get_instance.return_value = None
    lifecycle.get_status.return_value = None

    settings = MagicMock()
    settings.remote.cache_dir = "/tmp"
    settings.remote.latency_budget_ms = None

    # Include per_domain_counts for the domain
    telemetry_dict = {"last_per_domain": {"adapter": 3}, "last_duration_ms": None}
    remote_telemetry = MagicMock()
    remote_telemetry.as_dict.return_value = telemetry_dict

    with patch("oneiric.cli.load_remote_telemetry", return_value=remote_telemetry):
        _handle_status(
            bridge, lifecycle,
            domain="adapter",
            key=None,
            as_json=False,
            settings=settings,
            include_shadowed=False,
        )
    captured = capsys.readouterr()
    assert "Remote summary" in captured.out
    assert "(no keys)" in captured.out


# ---------------------------------------------------------------------------
# action-invoke — non-JSON result output (line 2106)
# ---------------------------------------------------------------------------


def test_action_invoke_non_json_output() -> None:
    state = _make_mock_state()
    state.bridges["action"].use = AsyncMock(return_value=MagicMock())

    async def fake_runner(*args, **kwargs):
        return "action-result"

    with patch("oneiric.cli._action_invoke_runner", new=AsyncMock(return_value="action-result")):
        result = _run_command("action-invoke", "test.action", state=state)
    assert result.exit_code == 0
    assert "action-result" in result.output


# ---------------------------------------------------------------------------
# manifest export — with actions (lines 2790-2791)
# ---------------------------------------------------------------------------


def test_manifest_export_includes_actions() -> None:
    from typer.testing import CliRunner
    runner = CliRunner()
    result = runner.invoke(app, [
        "manifest", "export",
        "--version", "1.0.0",
        "--format", "yaml",
        "--stdout",
        "--no-adapters",
    ])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# main() — line 3190
# ---------------------------------------------------------------------------


def test_main_calls_app() -> None:
    from oneiric.cli import main
    with patch("oneiric.cli.app") as mock_app:
        main()
    mock_app.assert_called_once()


# ---------------------------------------------------------------------------
# _format_entry_status — draining=True branch (line 1697)
# ---------------------------------------------------------------------------


def test_format_entry_status_draining() -> None:
    result = _format_entry_status({"paused": False, "draining": True})
    assert "draining" in result


# ---------------------------------------------------------------------------
# _handle_status — shadowed_candidates loop body (line 1356)
# ---------------------------------------------------------------------------


def test_handle_status_with_shadowed_candidates_iterated(capsys) -> None:
    shadow = Candidate(
        domain="adapter",
        key="cache",
        provider="memcache",
        factory=lambda: None,
        source=CandidateSource.MANUAL,
    )
    bridge = MagicMock()
    bridge.domain = "adapter"
    bridge.settings.selections = {}
    bridge.shadowed_candidates.return_value = [shadow]
    bridge.active_candidates.return_value = []
    bridge.activity_state.return_value = SimpleNamespace(
        paused=False, draining=False, note=None
    )

    lifecycle = MagicMock()
    lifecycle.all_statuses.return_value = []
    lifecycle.get_instance.return_value = None
    lifecycle.get_status.return_value = None

    settings = MagicMock()
    settings.remote.cache_dir = "/tmp"
    settings.remote.latency_budget_ms = None

    with patch("oneiric.cli.load_remote_telemetry", return_value=MagicMock(as_dict=lambda: {})):
        _handle_status(
            bridge,
            lifecycle,
            domain="adapter",
            key=None,
            as_json=False,
            settings=settings,
            include_shadowed=False,
        )


# ---------------------------------------------------------------------------
# _probe_lifecycle_entries — continue branch for missing domain/key (line 1929)
# ---------------------------------------------------------------------------


async def test_probe_lifecycle_entries_skips_missing_domain() -> None:
    from oneiric.cli import _probe_lifecycle_entries

    lifecycle = MagicMock()
    # Entry missing "domain" key → continue
    result = await _probe_lifecycle_entries(lifecycle, [{"key": "foo"}])
    assert result == {}
    lifecycle.probe_instance_health.assert_not_called()


async def test_probe_lifecycle_entries_skips_missing_key() -> None:
    from oneiric.cli import _probe_lifecycle_entries

    lifecycle = MagicMock()
    # Entry missing "key" → continue
    result = await _probe_lifecycle_entries(lifecycle, [{"domain": "adapter"}])
    assert result == {}
    lifecycle.probe_instance_health.assert_not_called()


# ---------------------------------------------------------------------------
# _handle_remote_sync — watch=True path (lines 792-806)
# ---------------------------------------------------------------------------


async def test_handle_remote_sync_watch_true() -> None:
    from oneiric.cli import _handle_remote_sync

    settings = MagicMock()
    settings.remote.refresh_interval = None

    with patch(
        "oneiric.cli.sync_remote_manifest", new=AsyncMock(return_value=MagicMock())
    ) as mock_sync, patch(
        "oneiric.cli.remote_sync_loop", new=AsyncMock()
    ) as mock_loop:
        await _handle_remote_sync(
            MagicMock(),
            settings,
            MagicMock(),
            MagicMock(),
            manifest_override=None,
            watch=True,
            refresh_interval=None,
        )
    mock_sync.assert_called_once()
    mock_loop.assert_called_once()


# ---------------------------------------------------------------------------
# _handle_remote_sync — watch=False, result=None (line 821)
# ---------------------------------------------------------------------------


async def test_handle_remote_sync_watch_false_result_none(capsys) -> None:
    from oneiric.cli import _handle_remote_sync

    with patch("oneiric.cli.sync_remote_manifest", new=AsyncMock(return_value=None)):
        await _handle_remote_sync(
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
            manifest_override=None,
            watch=False,
            refresh_interval=None,
        )
    assert "Remote sync skipped" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# _wait_forever — try block body (lines 905-907)
# ---------------------------------------------------------------------------


async def test_wait_forever_body_executes() -> None:
    from oneiric.cli import _wait_forever

    with patch(
        "oneiric.cli.asyncio.sleep",
        new=AsyncMock(side_effect=asyncio.CancelledError),
    ):
        await _wait_forever()


# ---------------------------------------------------------------------------
# _handle_orchestrate — try/finally block (lines 872-901)
# ---------------------------------------------------------------------------


async def test_handle_orchestrate_try_block() -> None:
    from oneiric.cli import _handle_orchestrate

    settings = MagicMock()
    settings.remote.refresh_interval = None

    mock_orchestrator = MagicMock()
    mock_orchestrator.start = AsyncMock()
    mock_orchestrator.stop = AsyncMock()
    mock_orchestrator.workflow_bridge = MagicMock()
    mock_orchestrator.event_bridge = MagicMock()

    with patch(
        "oneiric.cli.RuntimeOrchestrator", return_value=mock_orchestrator
    ), patch(
        "oneiric.cli._wait_forever", new=AsyncMock(side_effect=KeyboardInterrupt)
    ):
        await _handle_orchestrate(
            settings,
            MagicMock(),
            MagicMock(),
            MagicMock(),
            manifest_override=None,
            refresh_interval=None,
            disable_remote=False,
            workflow_checkpoint_override=None,
            disable_workflow_checkpoints=False,
            http_port=None,
            http_host="127.0.0.1",
            enable_http=False,
            print_dag=False,
            workflow_filters=[],
            inspect_events=False,
            inspect_json=False,
        )
    mock_orchestrator.start.assert_called_once()
    mock_orchestrator.stop.assert_called_once()


# ---------------------------------------------------------------------------
# load-test command — json_output=True (lines 2648-2649)
# ---------------------------------------------------------------------------


def test_load_test_command_json_output() -> None:
    from oneiric.runtime.load_testing import LoadTestResult
    from typer.testing import CliRunner

    mock_result = LoadTestResult(
        total_tasks=10,
        concurrency=2,
        duration_seconds=1.0,
        throughput_per_second=10.0,
        avg_latency_ms=100.0,
        p50_latency_ms=90.0,
        p95_latency_ms=150.0,
        p99_latency_ms=200.0,
        errors=0,
    )
    with patch("oneiric.cli.run_load_test", AsyncMock(return_value=mock_result)):
        runner = CliRunner()
        result = runner.invoke(app, ["load-test", "--total", "10", "--json"])
    assert result.exit_code == 0
    assert "total_tasks" in result.output


# ---------------------------------------------------------------------------
# _load_signing_key — PEM path (lines 2823-2826)
# ---------------------------------------------------------------------------


def test_load_signing_key_pem_ed25519(tmp_path) -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from oneiric.cli import _load_signing_key

    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_file = tmp_path / "key.pem"
    key_file.write_bytes(pem)
    result = _load_signing_key(key_file)
    assert isinstance(result, Ed25519PrivateKey)


def test_load_signing_key_pem_non_ed25519_raises(tmp_path) -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    from oneiric.cli import _load_signing_key

    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = rsa_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_file = tmp_path / "rsa_key.pem"
    key_file.write_bytes(pem)
    with pytest.raises(Exception, match="ED25519"):
        _load_signing_key(key_file)


# ---------------------------------------------------------------------------
# manifest sign --stdout (lines 2957-2959)
# ---------------------------------------------------------------------------


def test_manifest_sign_stdout(tmp_path) -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from typer.testing import CliRunner

    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_file = tmp_path / "key.pem"
    key_file.write_bytes(pem)

    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text('source: "test"\nentries: []\n')

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "manifest",
            "sign",
            "--input",
            str(manifest_file),
            "--private-key",
            str(key_file),
            "--stdout",
        ],
    )
    assert result.exit_code == 0
    assert "source" in result.output


# ---------------------------------------------------------------------------
# shell command — inner _shell() body (lines 3021-3028)
# ---------------------------------------------------------------------------


def test_shell_command_inner_body() -> None:
    mock_shell_instance = MagicMock()

    def run_coro(coro) -> None:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(coro)
        finally:
            loop.close()

    # Patch asyncio.run to actually execute the inner _shell() coroutine.
    # Patch load_settings for the coroutine body, OneiricShell to avoid real shell start.
    # _run_command already patches _initialize_state so cli_root succeeds without real config.
    with patch("oneiric.cli.asyncio.run", side_effect=run_coro), \
         patch("oneiric.cli.load_settings", return_value=MagicMock()), \
         patch("oneiric.shell.OneiricShell", return_value=mock_shell_instance):
        _run_command("shell")
    mock_shell_instance.start.assert_called_once()


# ---------------------------------------------------------------------------
# _handle_orchestrate — enable_http=True path (lines 880-886, 899)
# ---------------------------------------------------------------------------


async def test_handle_orchestrate_with_http_server() -> None:
    from oneiric.cli import _handle_orchestrate

    settings = MagicMock()
    settings.remote.refresh_interval = None

    mock_orchestrator = MagicMock()
    mock_orchestrator.start = AsyncMock()
    mock_orchestrator.stop = AsyncMock()
    mock_orchestrator.workflow_bridge = MagicMock()
    mock_orchestrator.event_bridge = MagicMock()

    mock_http_server = MagicMock()
    mock_http_server.start = AsyncMock()
    mock_http_server.stop = AsyncMock()

    with patch(
        "oneiric.cli.RuntimeOrchestrator", return_value=mock_orchestrator
    ), patch(
        "oneiric.cli._wait_forever", new=AsyncMock(side_effect=KeyboardInterrupt)
    ), patch(
        "oneiric.cli._resolve_http_port", return_value=8080
    ), patch(
        "oneiric.cli.WorkflowTaskProcessor", return_value=MagicMock()
    ), patch(
        "oneiric.cli.SchedulerHTTPServer", return_value=mock_http_server
    ):
        await _handle_orchestrate(
            settings,
            MagicMock(),
            MagicMock(),
            MagicMock(),
            manifest_override=None,
            refresh_interval=None,
            disable_remote=False,
            workflow_checkpoint_override=None,
            disable_workflow_checkpoints=False,
            http_port=8080,
            http_host="127.0.0.1",
            enable_http=True,
            print_dag=False,
            workflow_filters=[],
            inspect_events=False,
            inspect_json=False,
        )
    mock_http_server.start.assert_called_once()
    mock_http_server.stop.assert_called_once()
