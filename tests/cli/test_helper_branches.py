from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import typer
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from oneiric.actions.metadata import ActionMetadata
from oneiric.adapters.metadata import AdapterMetadata
from oneiric.cli import (
    _action_invoke_runner,
    _activity_counts_from_mapping,
    _activity_summary_for_bridge,
    _add_probe_results,
    _default_notification_adapter_key,
    _apply_signature_to_manifest,
    _derive_notification_route,
    _build_remote_metrics,
    _build_workflow_node,
    _candidate_summary,
    _event_emit_runner,
    _event_results_payload,
    _extract_notification_metadata,
    _format_activity_note,
    _format_activity_status,
    _format_event_result,
    _format_filter_clause,
    _format_remote_budget_line,
    _http_server_enabled,
    _invoke_action,
    _manifest_entry_from_action,
    _manifest_entry_from_adapter,
    _lifecycle_counts_from_mapping,
    _load_signing_key,
    _parse_csv,
    _parse_dependency_list,
    _parse_payload,
    _render_manifest,
    _resolve_http_port,
    _scrub_sensitive_data,
    _set_timestamps,
    _workflow_enqueue_runner,
    _workflow_run_runner,
    _workflow_target_keys,
    _filter_health_statuses,
)
from oneiric.core.config import OneiricSettings
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.resolution import Candidate, CandidateSource
from oneiric.runtime.events import HandlerResult
from oneiric.runtime.notifications import NotificationRoute


def _demo_factory() -> None:
    return None


def test_parsers_and_counts_cover_branches() -> None:
    assert _parse_payload(None) == {}
    assert _parse_csv("a, b,, c") == ["a", "b", "c"]
    assert _activity_counts_from_mapping({"d": {"k": {"paused": True, "draining": False}}}) == {
        "paused": 1,
        "draining": 0,
    }
    assert _lifecycle_counts_from_mapping({"d": {"k": {"state": "ready"}}}) == {
        "ready": 1
    }

    with pytest.raises(typer.BadParameter):
        _parse_payload("[1, 2]")


def test_workflow_helpers_and_filters() -> None:
    assert _parse_dependency_list(["a", "b"]) == ["a", "b"]
    assert _parse_dependency_list("solo") == ["solo"]
    assert _parse_dependency_list(None) == []
    assert _workflow_target_keys(["all", "demo", "demo"], ["alpha", "beta"]) == [
        "demo",
        "alpha",
        "beta",
    ]

    node = _build_workflow_node(
        {
            "id": "step1",
            "task": "tasks.step1",
            "depends_on": "prev",
            "payload": {"a": 1},
            "retry_policy": {"attempts": 2},
        }
    )
    assert node["depends_on"] == ["prev"]
    assert _build_workflow_node({"task": "x"}) is None

    assert _format_filter_clause({"path": "payload.region", "exists": True}) == "payload.region exists"
    assert _format_filter_clause({"path": "payload.region", "exists": False}) == "payload.region missing"


def test_health_probe_and_activity_formatting() -> None:
    class Status:
        def __init__(self, domain, key, state):
            self.domain = domain
            self.key = key
            self.state = state

        def as_dict(self):
            return {"domain": self.domain, "key": self.key, "state": self.state}

    class Lifecycle:
        def __init__(self):
            self.calls = []

        def all_statuses(self):
            return [Status("adapter", "cache", "ready"), Status("task", "job", "paused")]

        async def probe_instance_health(self, domain, key):
            self.calls.append((domain, key))
            return True

    lifecycle = Lifecycle()
    statuses = _filter_health_statuses(lifecycle, "adapter", None)
    assert len(statuses) == 1
    payload = [s.as_dict() for s in statuses]
    _add_probe_results(lifecycle, payload)
    assert payload[0]["probe_result"] is True

    assert _format_activity_status({"paused": True, "draining": False}) == "paused"
    assert _format_activity_status({"paused": False, "draining": False}) == "note"
    assert _format_activity_note({"note": "maintenance"}) == " note=maintenance"


def test_remote_and_event_helpers() -> None:
    class RemoteConfig:
        latency_budget_ms = 50.0

    assert _format_remote_budget_line(RemoteConfig(), None).endswith("(no syncs yet)")
    assert "EXCEEDED" in _format_remote_budget_line(RemoteConfig(), 60.0)
    assert _resolve_http_port(9090) == 9090
    assert _resolve_http_port(None) == 8080
    assert _http_server_enabled(SimpleNamespace(profile=SimpleNamespace(name="serverless")), None, False) is True
    assert _http_server_enabled(SimpleNamespace(profile=SimpleNamespace(name="standard")), None, True) is False
    assert _scrub_sensitive_data("normal") == "normal"
    assert _scrub_sensitive_data("api-token") == "***"

    result = HandlerResult(
        handler="demo",
        success=False,
        duration=0.1,
        error="secret-token",
        attempts=2,
    )
    text = _format_event_result(result)
    assert "error=***" in text


def test_signature_and_runtime_helpers(tmp_path, monkeypatch) -> None:
    private_key = Ed25519PrivateKey.generate()
    pem = private_key.private_bytes_raw()
    key_file = tmp_path / "key.bin"
    key_file.write_bytes(pem)

    loaded = _load_signing_key(key_file)
    assert loaded.sign(b"x")

    manifest = {}
    _set_timestamps(manifest, issued_at=None, expires_at="2026-01-01T00:00:00+00:00", expires_in=None)
    assert "signed_at" in manifest
    assert manifest["expires_at"] == "2026-01-01T00:00:00+00:00"

    signature_entry = {"signature": "abc", "algorithm": "ed25519"}
    _apply_signature_to_manifest(manifest, signature_entry, append=False)
    assert manifest["signature_algorithm"] == "ed25519"

    rendered = _render_manifest(manifest, tmp_path / "manifest.json")
    assert rendered.startswith("{")

    telemetry = SimpleNamespace(last_registered=3, last_duration_ms=1.5, last_digest_checks=2)
    assert _build_remote_metrics(telemetry) == "registered=3 duration_ms=1.50 digest_checks=2"

    candidate = Candidate(
        domain="adapter",
        key="cache",
        provider="redis",
        factory=lambda: object(),
        source=CandidateSource.MANUAL,
        metadata={"hello": "world"},
    )
    summary = _candidate_summary(candidate)
    assert summary["provider"] == "redis"
    assert summary["source"] == CandidateSource.MANUAL.value


def test_cli_notification_and_manifest_helpers() -> None:
    assert _activity_summary_for_bridge(SimpleNamespace()) == {"paused": 0, "draining": 0}

    bridge = SimpleNamespace(
        activity_snapshot=lambda: {
            "a": SimpleNamespace(paused=True, draining=False),
            "b": SimpleNamespace(paused=False, draining=True),
        }
    )
    assert _activity_summary_for_bridge(bridge) == {"paused": 1, "draining": 1}

    settings = SimpleNamespace(
        adapters=SimpleNamespace(selections={"cache": {"provider": "redis"}, "notifications.email": {}})
    )
    assert _default_notification_adapter_key(settings) == "notifications.email"

    candidate = Candidate(
        domain="workflow",
        key="wf",
        provider="demo",
        factory=_demo_factory,
        source=CandidateSource.LOCAL_PKG,
        metadata={
            "notifications": {
                "adapter_provider": "sendgrid",
                "adapter": "notifications.email",
                "provider": "mailgun",
                "channel": "ops",
                "target": "team",
                "include_context": False,
                "title_template": "[{level}] {channel}",
                "extra_payload": {"region": "us"},
            }
        },
    )
    metadata = _extract_notification_metadata(candidate)
    assert metadata and metadata["extra_payload"] == {"region": "us"}
    assert (
        _extract_notification_metadata(
            Candidate(
                domain="workflow",
                key="wf2",
                provider="demo",
                factory=_demo_factory,
                source=CandidateSource.LOCAL_PKG,
                metadata={"notifications": "not-a-mapping"},
            )
        )
        is None
    )

    class Resolver:
        def __init__(self, resolved):
            self.resolved = resolved

        def resolve(self, domain, key):
            assert domain == "workflow"
            return self.resolved if key == "known" else None

    state = SimpleNamespace(resolver=Resolver(candidate))
    assert _derive_notification_route(
        state,
        workflow_key=None,
        notify_adapter=None,
        notify_target=None,
        force_send=False,
    ) is None
    with pytest.raises(typer.BadParameter):
        _derive_notification_route(
            SimpleNamespace(resolver=Resolver(None)),
            workflow_key="missing",
            notify_adapter=None,
            notify_target=None,
            force_send=False,
        )

    route = _derive_notification_route(
        state,
        workflow_key="known",
        notify_adapter=None,
        notify_target=None,
        force_send=False,
    )
    assert route == NotificationRoute(
        adapter_key="sendgrid",
        adapter_provider="mailgun",
        target="team",
        channel=None,
        title_template="[{level}] {channel}",
        include_context=False,
        extra_payload={"region": "us"},
    )

    forced = _derive_notification_route(
        SimpleNamespace(resolver=Resolver(candidate)),
        workflow_key=None,
        notify_adapter=None,
        notify_target=None,
        force_send=True,
    )
    assert forced is not None and forced.adapter_key is None

    adapter = AdapterMetadata(
        category="cache",
        provider="redis",
        factory=_demo_factory,
        capabilities=["kv"],
        stack_level=7,
        priority=9,
        source=CandidateSource.LOCAL_PKG,
        owner="Platform",
        requires_secrets=True,
        settings_model=OneiricSettings,
        description="demo",
    )
    entry = _manifest_entry_from_adapter(adapter, "1.2.3")
    assert entry.factory.endswith(":_demo_factory")
    assert entry.settings_model.endswith(":OneiricSettings")
    assert entry.capability_names == ["kv"]

    adapter_model = AdapterMetadata.model_construct(
        category="cache",
        provider="redis",
        factory="pkg.module:Factory",
        capabilities=[],
        stack_level=None,
        priority=None,
        source=CandidateSource.LOCAL_PKG,
        owner=None,
        requires_secrets=False,
        settings_model="pkg.module:Settings",
    )
    assert (
        _manifest_entry_from_adapter(adapter_model, "1.2.3").settings_model
        == "pkg.module:Settings"
    )

    bad_adapter = AdapterMetadata.model_construct(
        category="cache",
        provider="redis",
        factory=123,
        capabilities=[],
        stack_level=None,
        priority=None,
        source=CandidateSource.LOCAL_PKG,
        owner=None,
        requires_secrets=False,
        settings_model=None,
    )
    with pytest.raises(ValueError):
        _manifest_entry_from_adapter(bad_adapter, "1.2.3")

    action = ActionMetadata(
        key="workflow.notify",
        provider="demo",
        factory=_demo_factory,
        source=CandidateSource.LOCAL_PKG,
        description="demo action",
        stack_level=5,
        priority=11,
        owner="Platform",
        requires_secrets=False,
        side_effect_free=True,
        extras={"timeout_seconds": 30},
    )
    action_entry = _manifest_entry_from_action(action, "9.9.9")
    assert action_entry.factory.endswith(":_demo_factory")
    assert action_entry.side_effect_free is True
    assert action_entry.timeout_seconds == 30

    bad_action = ActionMetadata.model_construct(
        key="workflow.notify",
        provider="demo",
        factory=123,
        source=CandidateSource.LOCAL_PKG,
        extras={},
        side_effect_free=False,
    )
    with pytest.raises(ValueError):
        _manifest_entry_from_action(bad_action, "9.9.9")


@pytest.mark.asyncio
async def test_cli_runner_helpers() -> None:
    class SyncHandle:
        def __init__(self) -> None:
            self.instance = SimpleNamespace(execute=lambda payload: {"sync": payload})

    class AsyncHandle:
        def __init__(self) -> None:
            async def execute(payload):
                return {"async": payload}

            self.instance = SimpleNamespace(execute=execute)

    assert await _invoke_action(SyncHandle(), {"a": 1}) == {"sync": {"a": 1}}
    assert await _invoke_action(AsyncHandle(), {"b": 2}) == {"async": {"b": 2}}
    with pytest.raises(LifecycleError):
        await _invoke_action(SimpleNamespace(instance=SimpleNamespace()), {})

    class Bridge:
        def __init__(self) -> None:
            self.used = []

        async def use(self, key, provider=None):
            self.used.append((key, provider))
            return SyncHandle()

        async def emit(self, topic, payload, headers=None):
            return [{"topic": topic, "payload": payload, "headers": headers}]

        async def execute_dag(self, key, **kwargs):
            return {"workflow": key, **kwargs}

        async def enqueue_workflow(self, key, **kwargs):
            return {"workflow": key, **kwargs}

    class Router:
        def __init__(self) -> None:
            self.calls = []

        async def send(self, result, route):
            self.calls.append((result, route))

    bridge = Bridge()
    router = Router()
    route = NotificationRoute(adapter_key="notifications.email")
    result = await _action_invoke_runner(
        bridge,
        "workflow.notify",
        {"message": "hello"},
        provider="demo",
        notification_router=router,
        notification_route=route,
    )
    assert result == {"sync": {"message": "hello"}}
    assert bridge.used == [("workflow.notify", "demo")]
    assert router.calls and router.calls[0][1] == route

    emitted = await _event_emit_runner(bridge, "topic", {"a": 1}, {"h": "v"})
    assert emitted[0]["topic"] == "topic"

    executed = await _workflow_run_runner(
        bridge,
        "wf",
        {"ctx": 1},
        checkpoint={"step": 1},
        use_checkpoint_store=True,
        resume_from_checkpoint=False,
    )
    assert executed["workflow"] == "wf"

    enqueued = await _workflow_enqueue_runner(
        bridge,
        "wf",
        context={"ctx": 2},
        queue_category="queue",
        provider="demo",
        metadata={"k": "v"},
    )
    assert enqueued["workflow"] == "wf"
