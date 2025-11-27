"""Oneiric command line utilities."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import typer

from oneiric import plugins
from oneiric.adapters import AdapterBridge
from oneiric.adapters.metadata import AdapterMetadata, register_adapter_metadata
from oneiric.actions import ActionBridge, register_builtin_actions
from oneiric.core.config import (
    OneiricSettings,
    SecretsHook,
    domain_activity_path,
    lifecycle_snapshot_path,
    load_settings,
    resolver_settings_from_config,
    runtime_health_path,
)
from oneiric.core.lifecycle import LifecycleError, LifecycleManager, LifecycleSafetyOptions, LifecycleStatus
from oneiric.core.logging import configure_logging, get_logger
from oneiric.core.resolution import Candidate, Resolver
from oneiric.domains import EventBridge, ServiceBridge, TaskBridge, WorkflowBridge
from oneiric.remote import load_remote_telemetry, remote_sync_loop, sync_remote_manifest
from oneiric.runtime.activity import DomainActivityStore
from oneiric.runtime.health import load_runtime_health
from oneiric.runtime.orchestrator import RuntimeOrchestrator

logger = get_logger("cli")


DOMAINS = ("adapter", "service", "task", "event", "workflow", "action")
DEFAULT_REMOTE_REFRESH_INTERVAL = 300.0

app = typer.Typer(help="Oneiric runtime management CLI.")


@dataclass
class CLIState:
    settings: OneiricSettings
    resolver: Resolver
    lifecycle: LifecycleManager
    bridges: Dict[
        str,
        AdapterBridge | ServiceBridge | TaskBridge | EventBridge | WorkflowBridge | ActionBridge,
    ]
    plugin_report: plugins.PluginRegistrationReport


def _build_lifecycle_options(config: Optional[object]) -> LifecycleSafetyOptions:
    if not config:
        return LifecycleSafetyOptions()
    return LifecycleSafetyOptions(
        activation_timeout=getattr(config, "activation_timeout", 30.0) or 0,
        health_timeout=getattr(config, "health_timeout", 5.0) or 0,
        cleanup_timeout=getattr(config, "cleanup_timeout", 10.0) or 0,
        hook_timeout=getattr(config, "hook_timeout", 5.0) or 0,
        shield_tasks=bool(getattr(config, "shield_tasks", True)),
    )


def _swap_latency_summary(statuses: Iterable[LifecycleStatus]) -> Dict[str, Any]:
    durations: List[float] = []
    successes = 0
    failures = 0
    for status in statuses:
        durations.extend(status.recent_swap_durations_ms)
        successes += status.successful_swaps
        failures += status.failed_swaps
    durations.sort()
    total = successes + failures
    return {
        "samples": len(durations),
        "p50": _percentile(durations, 0.5),
        "p95": _percentile(durations, 0.95),
        "p99": _percentile(durations, 0.99),
        "success_rate": 100.0 if total == 0 else (successes / total) * 100.0,
    }


def _percentile(data: List[float], percentile: float) -> Optional[float]:
    if not data:
        return None
    k = (len(data) - 1) * percentile
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return data[int(k)]
    d0 = data[f] * (c - k)
    d1 = data[c] * (k - f)
    return d0 + d1


def _format_swap_summary(summary: Dict[str, Any]) -> str:
    samples = summary.get("samples", 0)
    if not samples:
        return "Swap latency: no samples recorded yet."
    p50 = summary.get("p50")
    p95 = summary.get("p95")
    p99 = summary.get("p99")
    parts = [f"Swap latency (last {samples}):"]
    if p50 is not None:
        parts.append(f"p50={p50:.1f}ms")
    if p95 is not None:
        parts.append(f"p95={p95:.1f}ms")
    if p99 is not None:
        parts.append(f"p99={p99:.1f}ms")
    parts.append(f"success_rate={summary.get('success_rate', 0):.1f}%")
    return " ".join(parts)


def _activity_summary_for_bridge(bridge) -> Dict[str, int]:
    snapshot_fn = getattr(bridge, "activity_snapshot", None)
    if not callable(snapshot_fn):
        return {"paused": 0, "draining": 0}
    snapshot = snapshot_fn()
    paused = sum(1 for state in snapshot.values() if getattr(state, "paused", False))
    draining = sum(1 for state in snapshot.values() if getattr(state, "draining", False))
    return {"paused": paused, "draining": draining}


def _format_activity_summary(summary: Dict[str, int]) -> str:
    return (
        "Activity state: paused={paused} draining={draining}".format(
            paused=summary.get("paused", 0),
            draining=summary.get("draining", 0),
        )
    )


def _activity_counts_from_mapping(activity_state: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    paused = 0
    draining = 0
    for entries in activity_state.values():
        for state in entries.values():
            if state.get("paused"):
                paused += 1
            if state.get("draining"):
                draining += 1
    return {"paused": paused, "draining": draining}


def _format_remote_budget_line(remote_config, last_duration: Optional[float]) -> str:
    budget = getattr(remote_config, "latency_budget_ms", 0) or 0
    budget_text = f"{budget:.0f}ms" if budget else "n/a"
    if last_duration is None:
        return f"Remote latency budget={budget_text} (no syncs yet)"
    duration_text = f"{last_duration:.1f}ms"
    status = "OK" if not budget or last_duration <= budget else "EXCEEDED"
    return f"Remote latency budget={budget_text}; last_duration={duration_text} ({status})"


def _parse_payload(raw: Optional[str]) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"Invalid JSON payload: {exc}")
    if not isinstance(data, dict):
        raise typer.BadParameter("Payload JSON must be an object")
    return data


async def _invoke_action(handle, payload: Dict[str, Any]) -> Any:
    executor = getattr(handle.instance, "execute", None)
    if not callable(executor):
        raise LifecycleError("Selected action does not expose 'execute'")
    result = executor(payload)
    if inspect.isawaitable(result):
        result = await result
    return result


async def _action_invoke_runner(
    bridge: ActionBridge,
    key: str,
    payload: Dict[str, Any],
    *,
    provider: Optional[str],
) -> Any:
    handle = await bridge.use(key, provider=provider)
    return await _invoke_action(handle, payload)


@dataclass
class DemoCLIAdapter:
    message: str

    def handle(self) -> str:
        return self.message


@dataclass
class DemoCLIService:
    name: str = "cli-service"

    def status(self) -> str:
        return f"{self.name}-ok"


@dataclass
class DemoCLITask:
    name: str = "cli-task"

    async def run(self) -> str:
        return f"{self.name}-run"


@dataclass
class DemoCLIWorkflow:
    name: str = "cli-workflow"

    def execute(self) -> str:
        return f"{self.name}-complete"


@dataclass
class DemoCLIEventHandler:
    name: str = "cli-event"

    def handle(self, payload: dict) -> dict:
        return {"name": self.name, "payload": payload}


@dataclass
class DemoCLIAction:
    name: str = "cli-action"

    async def execute(self, payload: Optional[dict] = None) -> dict:
        return {"name": self.name, "payload": payload or {}}


def _initialize_state(
    config_path: Optional[str],
    imports: Iterable[str],
    demo: bool,
) -> CLIState:
    settings = load_settings(config_path)
    configure_logging(settings.logging)
    resolver = Resolver(settings=resolver_settings_from_config(settings))
    _import_modules(imports)
    plugin_report = plugins.register_entrypoint_plugins(resolver, settings.plugins)
    register_builtin_actions(resolver)
    if demo:
        register_adapter_metadata(
            resolver,
            package_name="oneiric.cli.demo",
            package_path=str(Path(__file__).parent),
            adapters=[
                AdapterMetadata(
                    category="demo",
                    provider="cli",
                    stack_level=5,
                    factory=lambda: DemoCLIAdapter("hello from CLI"),
                    description="CLI demo adapter",
                )
            ],
        )
        resolver.register(
            Candidate(
                domain="service",
                key="status",
                provider="cli",
                factory=lambda: DemoCLIService(),
                stack_level=5,
            )
        )
        resolver.register(
            Candidate(
                domain="task",
                key="demo-task",
                provider="cli",
                factory=lambda: DemoCLITask(),
                stack_level=5,
            )
        )
        resolver.register(
            Candidate(
                domain="event",
                key="demo.event",
                provider="cli",
                factory=lambda: DemoCLIEventHandler(),
                stack_level=5,
            )
        )
        resolver.register(
            Candidate(
                domain="workflow",
                key="demo-workflow",
                provider="cli",
                factory=lambda: DemoCLIWorkflow(),
                stack_level=5,
            )
        )
        resolver.register(
            Candidate(
                domain="action",
                key="demo-action",
                provider="cli",
                factory=lambda: DemoCLIAction(),
                stack_level=5,
            )
        )
    lifecycle = LifecycleManager(
        resolver,
        status_snapshot_path=str(lifecycle_snapshot_path(settings)),
        safety=_build_lifecycle_options(settings.lifecycle),
    )
    activity_store = DomainActivityStore(domain_activity_path(settings))
    bridges: Dict[
        str,
        AdapterBridge | ServiceBridge | TaskBridge | EventBridge | WorkflowBridge | ActionBridge,
    ] = {
        "adapter": AdapterBridge(resolver, lifecycle, settings.adapters, activity_store=activity_store),
        "service": ServiceBridge(resolver, lifecycle, settings.services, activity_store=activity_store),
        "task": TaskBridge(resolver, lifecycle, settings.tasks, activity_store=activity_store),
        "event": EventBridge(resolver, lifecycle, settings.events, activity_store=activity_store),
        "workflow": WorkflowBridge(resolver, lifecycle, settings.workflows, activity_store=activity_store),
        "action": ActionBridge(resolver, lifecycle, settings.actions, activity_store=activity_store),
    }

    return CLIState(
        settings=settings,
        resolver=resolver,
        lifecycle=lifecycle,
        bridges=bridges,
        plugin_report=plugin_report,
    )


def _state(ctx: typer.Context) -> CLIState:
    state = ctx.obj
    if not isinstance(state, CLIState):
        raise RuntimeError("CLI state not initialized")
    return state


def _normalize_domain(value: str) -> str:
    lowered = value.lower()
    if lowered not in DOMAINS:
        raise typer.BadParameter(f"Domain must be one of {', '.join(DOMAINS)}.")
    return lowered


def _coerce_domain(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return _normalize_domain(value)


def _import_modules(modules: Iterable[str]) -> None:
    for dotted in modules:
        if not dotted:
            continue
        importlib.import_module(dotted)
        logger.info("module-imported", module=dotted)


def _handle_list(bridge, *, include_shadowed: bool) -> None:
    active = bridge.active_candidates()
    shadowed = bridge.shadowed_candidates() if include_shadowed else []
    print(f"Active {bridge.domain}s:")
    _print_candidates(active)
    if include_shadowed:
        print(f"\nShadowed {bridge.domain}s:")
        _print_candidates(shadowed)


def _print_candidates(candidates) -> None:
    if not candidates:
        print("  (none)")
        return
    for cand in candidates:
        print(
            f"  - {cand.key}/{cand.provider} "
            f"(priority={cand.priority} stack={cand.stack_level} source={cand.source.value})"
        )


def _handle_explain(resolver: Resolver, domain: str, key: str) -> None:
    explanation = resolver.explain(domain, key)
    print(json.dumps(explanation.as_dict(), indent=2))


async def _handle_swap(
    lifecycle: LifecycleManager,
    domain: str,
    key: str,
    *,
    provider: Optional[str],
    force: bool,
) -> None:
    instance = await lifecycle.swap(domain, key, provider=provider, force=force)
    print(f"Swapped {domain}:{key} -> {provider or 'auto'}; instance={instance!r}")


async def _handle_remote_sync(
    resolver: Resolver,
    settings: OneiricSettings,
    lifecycle: LifecycleManager,
    *,
    manifest_override: Optional[str],
    watch: bool,
    refresh_interval: Optional[float],
) -> None:
    secrets = SecretsHook(lifecycle, settings.secrets)
    if watch:
        await sync_remote_manifest(
            resolver,
            settings.remote,
            secrets=secrets,
            manifest_url=manifest_override,
        )
        interval_override = refresh_interval
        config_interval = settings.remote.refresh_interval
        if interval_override is None and not config_interval:
            interval_override = DEFAULT_REMOTE_REFRESH_INTERVAL
            logger.info(
                "remote-refresh-interval-defaulted",
                interval=interval_override,
            )
        await remote_sync_loop(
            resolver,
            settings.remote,
            secrets=secrets,
            manifest_url=manifest_override,
            interval_override=interval_override,
        )
    else:
        result = await sync_remote_manifest(
            resolver,
            settings.remote,
            secrets=secrets,
            manifest_url=manifest_override,
        )
        if not result:
            print("Remote sync skipped.")
        else:
            print(f"Remote sync complete: {result.registered} candidates from {result.manifest.source}.")


async def _handle_orchestrate(
    settings: OneiricSettings,
    resolver: Resolver,
    lifecycle: LifecycleManager,
    *,
    manifest_override: Optional[str],
    refresh_interval: Optional[float],
    disable_remote: bool,
) -> None:
    secrets = SecretsHook(lifecycle, settings.secrets)
    orchestrator = RuntimeOrchestrator(
        settings,
        resolver,
        lifecycle,
        secrets,
        health_path=str(runtime_health_path(settings)),
    )
    try:
        await orchestrator.start(
            manifest_url=manifest_override,
            refresh_interval_override=refresh_interval,
            enable_remote=not disable_remote,
        )
        logger.info(
            "orchestrator-running",
            remote_enabled=not disable_remote,
            refresh_interval=refresh_interval or settings.remote.refresh_interval,
        )
        await _wait_forever()
    except KeyboardInterrupt:
        logger.info("orchestrator-shutdown-requested")
    finally:
        await orchestrator.stop()
        logger.info("orchestrator-stopped")


async def _wait_forever() -> None:
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:  # pragma: no cover - cooperative shutdown
        pass


def _handle_remote_status(settings: OneiricSettings, *, as_json: bool) -> None:
    telemetry = load_remote_telemetry(settings.remote.cache_dir)
    payload = telemetry.as_dict()
    if as_json:
        print(json.dumps(payload, indent=2))
        return
    print(f"Cache dir: {settings.remote.cache_dir}")
    manifest_url = settings.remote.manifest_url or "not configured"
    print(f"Manifest URL: {manifest_url}")
    print("  " + _format_remote_budget_line(settings.remote, payload.get("last_duration_ms")))
    if not telemetry.last_success_at and not telemetry.last_failure_at:
        print("  No remote refresh telemetry recorded yet.")
        return
    if telemetry.last_success_at:
        duration = telemetry.last_duration_ms
        digest = telemetry.last_digest_checks
        metric_parts = [f"registered={telemetry.last_registered or 0}"]
        if duration is not None:
            metric_parts.append(f"duration_ms={duration:.2f}")
        if digest is not None:
            metric_parts.append(f"digest_checks={digest}")
        metrics = " ".join(metric_parts)
        print(
            f"Last success: {telemetry.last_success_at} from {telemetry.last_source or 'unknown'}; "
            f"{metrics}"
        )
        per_domain = telemetry.last_per_domain or {}
        if per_domain:
            print("Per-domain registrations:")
            for domain, count in per_domain.items():
                print(f"  - {domain}: {count}")
        if telemetry.last_skipped:
            print(f"Skipped entries: {telemetry.last_skipped}")
    if telemetry.last_failure_at:
        print(
            "Last failure: "
            f"{telemetry.last_failure_at} (error={telemetry.last_error or 'unknown'}; "
            f"consecutive_failures={telemetry.consecutive_failures})"
        )


def _handle_status(
    bridge,
    lifecycle: LifecycleManager,
    *,
    domain: str,
    key: Optional[str],
    as_json: bool,
    settings: OneiricSettings,
    include_shadowed: bool,
) -> None:
    keys = _status_keys(bridge, key)
    shadowed_map: Dict[str, list[Candidate]] = {}
    for cand in bridge.shadowed_candidates():
        shadowed_map.setdefault(cand.key, []).append(cand)
    records = []
    for item in keys:
        records.append(
            _build_status_record(
                bridge,
                lifecycle,
                key=item,
                shadowed=len(shadowed_map.get(item, [])),
                shadowed_details=shadowed_map.get(item, []),
                include_shadowed=include_shadowed,
            )
        )
    domain_statuses = [status for status in lifecycle.all_statuses() if status.domain == domain]
    swap_summary = _swap_latency_summary(domain_statuses)
    activity_summary = _activity_summary_for_bridge(bridge)
    payload: Dict[str, Any] = {
        "domain": domain,
        "status": records,
        "summary": {
            "swap": swap_summary,
            "activity": activity_summary,
        },
    }
    remote_telemetry = load_remote_telemetry(settings.remote.cache_dir).as_dict()
    per_domain_counts = remote_telemetry.get("last_per_domain") or {}
    payload["remote_telemetry"] = remote_telemetry
    if as_json:
        print(json.dumps(payload, indent=2))
        return
    print(f"Domain: {domain}")
    print(_format_swap_summary(swap_summary))
    print(_format_activity_summary(activity_summary))
    if per_domain_counts.get(domain):
        print(
            f"Remote summary: last sync registered {per_domain_counts[domain]} {domain}(s)"
        )
    if not records:
        print("  (no keys)")
    for record in records:
        _print_status_record(record)
    if domain == "adapter":
        _print_remote_summary(payload["remote_telemetry"], settings.remote.cache_dir, settings.remote)


def _handle_health(
    lifecycle: LifecycleManager,
    *,
    domain: Optional[str],
    key: Optional[str],
    as_json: bool,
    probe: bool,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    statuses = lifecycle.all_statuses()
    if domain:
        statuses = [status for status in statuses if status.domain == domain]
    if key:
        statuses = [status for status in statuses if status.key == key]
    summary = _swap_latency_summary(statuses)
    payload = [status.as_dict() for status in statuses]
    if probe and payload:
        probe_results = asyncio.run(_probe_lifecycle_entries(lifecycle, payload))
        for entry in payload:
            entry["probe_result"] = probe_results.get((entry["domain"], entry["key"]))
    if as_json:
        return payload, summary
    if not payload:
        print("No lifecycle statuses recorded yet.")
        return payload, summary
    for entry in payload:
        state = entry["state"]
        current = entry.get("current_provider")
        pending = entry.get("pending_provider") or "none"
        print(
            f"{entry['domain']}:{entry['key']} state={state} current={current or 'n/a'} "
            f"pending={pending}"
        )
        if entry.get("last_health_at"):
            print(f"  last_health={entry['last_health_at']}")
        if entry.get("last_activated_at"):
            print(f"  last_activated={entry['last_activated_at']}")
        if entry.get("last_error"):
            print(f"  last_error={entry['last_error']}")
        if entry.get("probe_result") is not None:
            print(f"  probe_result={entry['probe_result']}")
    return payload, summary


def _status_keys(bridge, key: Optional[str]) -> list[str]:
    if key:
        return [key]
    keys = set(bridge.settings.selections.keys())
    for cand in bridge.active_candidates():
        keys.add(cand.key)
    return sorted(keys)


def _build_status_record(
    bridge,
    lifecycle: LifecycleManager,
    *,
    key: str,
    shadowed: int,
    shadowed_details: Optional[list[Candidate]] = None,
    include_shadowed: bool = False,
) -> Dict[str, Any]:
    candidate = bridge.resolver.resolve(bridge.domain, key)
    configured = bridge.settings.selections.get(key)
    instance = lifecycle.get_instance(bridge.domain, key)
    lifecycle_status = lifecycle.get_status(bridge.domain, key)
    activity = bridge.activity_state(key)
    record: Dict[str, Any] = {
        "key": key,
        "configured_provider": configured,
        "shadowed": shadowed,
        "activity": {
            "paused": activity.paused,
            "draining": activity.draining,
            "note": activity.note,
        },
    }
    if not candidate:
        record.update({
            "state": "unresolved",
            "message": "No registered candidate",
            "instance_state": "absent",
        })
        if lifecycle_status:
            record["lifecycle"] = lifecycle_status.as_dict()
        return record
    record.update(
        {
            "state": "active",
            "provider": candidate.provider,
            "source": candidate.source.value,
            "priority": candidate.priority,
            "stack_level": candidate.stack_level,
            "metadata": candidate.metadata,
            "registered_at": candidate.registered_at.isoformat(),
            "selection_applied": bool(configured and configured == candidate.provider),
            "instance_state": "ready" if instance else "pending",
            "instance_type": type(instance).__name__ if instance else None,
        }
    )
    if lifecycle_status:
        record["lifecycle"] = lifecycle_status.as_dict()
    if include_shadowed and shadowed_details:
        record["shadowed_details"] = [_candidate_summary(cand) for cand in shadowed_details]
    return record


def _print_status_record(record: Dict[str, Any]) -> None:
    key = record["key"]
    state = record["state"]
    configured = record.get("configured_provider")
    provider = record.get("provider") or "n/a"
    selection_note = " (selection)" if record.get("selection_applied") else ""
    print(
        f"- {key}: state={state} provider={provider} "
        f"configured={configured or 'auto'} shadowed={record['shadowed']}" + selection_note
    )
    if state == "unresolved":
        print(f"    reason: {record.get('message')}")
        return
    print(
        f"    source={record['source']} priority={record['priority']} "
        f"stack={record['stack_level']} instance={record['instance_state']}"
    )
    if record.get("instance_type"):
        print(f"    instance_type={record['instance_type']}")
    lifecycle_info = record.get("lifecycle")
    if lifecycle_info:
        print(
            f"    lifecycle={lifecycle_info['state']} current={lifecycle_info['current_provider'] or 'n/a'} "
            f"pending={lifecycle_info['pending_provider'] or 'none'}"
        )
        if lifecycle_info.get("last_health_at"):
            print(f"    last_health={lifecycle_info['last_health_at']}")
        if lifecycle_info.get("last_error"):
            print(f"    last_error={lifecycle_info['last_error']}")
    activity = record.get("activity") or {}
    print(
        f"    activity paused={activity.get('paused', False)} draining={activity.get('draining', False)}"
        + (f" note={activity.get('note')}" if activity.get("note") else "")
    )
    if record.get("shadowed_details"):
        print("    shadowed_candidates:")
        for detail in record["shadowed_details"]:
            print(
                f"      - provider={detail['provider']} priority={detail['priority']} "
                f"stack={detail['stack_level']} source={detail['source']}"
            )


def _activity_summary(bridges: Dict[str, AdapterBridge | ServiceBridge | TaskBridge | EventBridge | WorkflowBridge]) -> Dict[str, Any]:
    report: Dict[str, Any] = {"domains": {}, "totals": {"paused": 0, "draining": 0, "note_only": 0}}
    for domain, bridge in bridges.items():
        snapshot = bridge.activity_snapshot()
        rows = []
        counts = {"paused": 0, "draining": 0, "note_only": 0}
        for key, state in sorted(snapshot.items()):
            if not state.paused and not state.draining and not state.note:
                continue
            if state.paused:
                counts["paused"] += 1
            if state.draining:
                counts["draining"] += 1
            if state.note and not state.paused and not state.draining:
                counts["note_only"] += 1
            rows.append(
                {
                    "key": key,
                    "paused": state.paused,
                    "draining": state.draining,
                    "note": state.note,
                }
            )
        if rows:
            report["domains"][domain] = {
                "counts": counts,
                "entries": rows,
            }
            report["totals"]["paused"] += counts["paused"]
            report["totals"]["draining"] += counts["draining"]
            report["totals"]["note_only"] += counts["note_only"]
    return report


def _print_activity_report(report: Dict[str, Any]) -> None:
    domains: Dict[str, Any] = report.get("domains") or {}
    if not domains:
        print("No paused or draining keys recorded.")
        return
    totals = report.get("totals", {})
    print(
        "Total activity: paused={paused} draining={draining} note-only={notes}".format(
            paused=totals.get("paused", 0),
            draining=totals.get("draining", 0),
            notes=totals.get("note_only", 0),
        )
    )
    for domain in sorted(domains.keys()):
        counts = domains[domain].get("counts", {})
        print(
            f"{domain} activity: paused={counts.get('paused', 0)} "
            f"draining={counts.get('draining', 0)} note-only={counts.get('note_only', 0)}"
        )
        for entry in domains[domain].get("entries", []):
            status_bits = []
            if entry["paused"]:
                status_bits.append("paused")
            if entry["draining"]:
                status_bits.append("draining")
            status = ", ".join(status_bits) or "note-only"
            note = entry.get("note")
            note_part = f" note={note}" if note else ""
            print(f"  - {entry['key']}: {status}{note_part}")


def _print_remote_summary(telemetry: Dict[str, Any], cache_dir: str, remote_config) -> None:
    print(f"Remote telemetry cache: {cache_dir}")
    last_success = telemetry.get("last_success_at")
    last_failure = telemetry.get("last_failure_at")
    if not last_success and not last_failure:
        print("  No remote refresh telemetry yet.")
        return
    print("  " + _format_remote_budget_line(remote_config, telemetry.get("last_duration_ms")))
    if last_success:
        print(
            f"  Last success {last_success} (source={telemetry.get('last_source') or 'unknown'}, "
            f"registered={telemetry.get('last_registered') or 0})"
        )
    if last_failure:
        print(
            f"  Last failure {last_failure} (error={telemetry.get('last_error') or 'unknown'}, "
            f"consecutive={telemetry.get('consecutive_failures') or 0})"
        )


def _print_runtime_health(snapshot: Dict[str, Any], cache_dir: str, remote_config) -> None:
    print(f"Runtime health cache: {cache_dir}")
    watchers = "running" if snapshot.get("watchers_running") else "stopped"
    remote = "enabled" if snapshot.get("remote_enabled") else "disabled"
    pid = snapshot.get("orchestrator_pid") or "n/a"
    print(f"  watchers={watchers} remote={remote} orchestrator_pid={pid}")
    if snapshot.get("last_remote_duration_ms") is not None:
        print("  " + _format_remote_budget_line(remote_config, snapshot.get("last_remote_duration_ms")))
    if snapshot.get("last_remote_sync_at"):
        print(f"  last_remote_sync={snapshot['last_remote_sync_at']}")
    if snapshot.get("last_remote_error"):
        print(f"  last_remote_error={snapshot['last_remote_error']}")
    if snapshot.get("last_remote_registered") is not None:
        print(f"  last_remote_registered={snapshot['last_remote_registered']}")
    duration = snapshot.get("last_remote_duration_ms")
    if duration is not None:
        budget = getattr(remote_config, "latency_budget_ms", None) or 0
        budget_text = f"{budget:.0f}ms" if budget else "n/a"
        warning = " ⚠ exceeds budget" if budget and duration > budget else ""
        print(f"  last_remote_duration={duration:.1f}ms (budget={budget_text}){warning}")
    per_domain = snapshot.get("last_remote_per_domain") or {}
    if per_domain:
        print("  last_remote_per_domain:")
        for domain, count in per_domain.items():
            print(f"    - {domain}: {count}")
    if snapshot.get("last_remote_skipped"):
        print(f"  last_remote_skipped={snapshot['last_remote_skipped']}")
    activity = snapshot.get("activity_state") or {}
    if activity:
        summary = _activity_counts_from_mapping(activity)
        print(
            "  activity-summary: paused={paused} draining={draining}".format(
                paused=summary.get("paused", 0),
                draining=summary.get("draining", 0),
            )
        )
        print("  domain_activity:")
        for domain, entries in activity.items():
            for key, state in entries.items():
                status = []
                if state.get("paused"):
                    status.append("paused")
                if state.get("draining"):
                    status.append("draining")
                note = state.get("note")
                status_str = ",".join(status) if status else "note"
                suffix = f" note={note}" if note else ""
                print(f"    - {domain}:{key} {status_str}{suffix}")


async def _probe_lifecycle_entries(lifecycle: LifecycleManager, entries: list[Dict[str, Any]]) -> Dict[tuple[str, str], Optional[bool]]:
    results: Dict[tuple[str, str], Optional[bool]] = {}
    for entry in entries:
        domain = entry.get("domain")
        key = entry.get("key")
        if not domain or not key:
            continue
        result = await lifecycle.probe_instance_health(domain, key)
        results[(domain, key)] = result
    return results


def _candidate_summary(candidate: Candidate) -> Dict[str, Any]:
    return {
        "provider": candidate.provider,
        "priority": candidate.priority,
        "stack_level": candidate.stack_level,
        "source": candidate.source.value,
        "metadata": candidate.metadata,
    }


@app.callback(invoke_without_command=True)
def cli_root(
    ctx: typer.Context,
    config: Optional[str] = typer.Option(
        None,
        "--config",
        help="Path to settings file.",
        metavar="PATH",
    ),
    imports: Optional[List[str]] = typer.Option(
        None,
        "--import",
        metavar="MODULE",
        help="Module(s) to import for adapter registration side-effects.",
        show_default=False,
    ),
    demo: bool = typer.Option(False, "--demo", help="Register built-in demo providers."),
) -> None:
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()
    ctx.obj = _initialize_state(config, imports or [], demo)


@app.command("list")
def list_command(
    ctx: typer.Context,
    domain: str = typer.Option("adapter", "--domain", help="Domain to list.", case_sensitive=False),
    shadowed: bool = typer.Option(False, "--shadowed", help="Include shadowed candidates."),
) -> None:
    state = _state(ctx)
    domain = _normalize_domain(domain)
    _handle_list(state.bridges[domain], include_shadowed=shadowed)


@app.command("plugins")
def plugins_command(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Emit plugin diagnostics as JSON."),
) -> None:
    state = _state(ctx)
    report = state.plugin_report or plugins.PluginRegistrationReport.empty()
    if json_output:
        print(json.dumps(report.as_dict(), indent=2))
        return
    if not report.groups:
        print("No plugin entry-point groups configured.")
        return
    print(f"Entry-point groups loaded: {', '.join(report.groups)}")
    print(f"Registered plugin candidates: {report.registered}")
    if report.entries:
        print("Registered payloads:")
        for entry in report.entries:
            print(
                f"  - [{entry.group}] {entry.entry_point}: {entry.registered_candidates} "
                f"({entry.payload_type})"
            )
    if report.errors:
        print("Plugin load issues:")
        for error in report.errors:
            print(f"  - [{error.group}] {error.entry_point}: {error.reason}")


@app.command("action-invoke")
def action_invoke(
    ctx: typer.Context,
    key: str = typer.Argument(..., help="Action key to invoke (e.g., compression.encode)."),
    payload: Optional[str] = typer.Option(
        None,
        "--payload",
        help="JSON payload passed to the action (defaults to {}).",
    ),
    provider: Optional[str] = typer.Option(None, "--provider", help="Override provider selection."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON result."),
) -> None:
    state = _state(ctx)
    bridge = state.bridges.get("action")
    if not bridge:
        raise typer.BadParameter("Actions domain is not initialized")
    payload_map = _parse_payload(payload)
    result = asyncio.run(
        _action_invoke_runner(bridge, key, payload_map, provider=provider)
    )
    if json_output:
        typer.echo(json.dumps(result, indent=2, sort_keys=True))
    else:
        typer.echo(result)


@app.command()
def explain(
    ctx: typer.Context,
    key: str = typer.Argument(..., help="Domain key (category/service_id/etc)."),
    domain: str = typer.Option("adapter", "--domain", help="Domain to inspect.", case_sensitive=False),
) -> None:
    state = _state(ctx)
    domain = _normalize_domain(domain)
    _handle_explain(state.resolver, domain, key)


@app.command()
def swap(
    ctx: typer.Context,
    key: str = typer.Argument(..., help="Domain key (category/service_id/etc)."),
    domain: str = typer.Option("adapter", "--domain", help="Domain to target.", case_sensitive=False),
    provider: Optional[str] = typer.Option(None, "--provider", help="Provider to target (optional)."),
    force: bool = typer.Option(False, "--force", help="Force swap even if health fails."),
) -> None:
    state = _state(ctx)
    domain = _normalize_domain(domain)
    asyncio.run(_handle_swap(state.lifecycle, domain, key, provider=provider, force=force))


@app.command("pause")
def pause_command(
    ctx: typer.Context,
    key: str = typer.Argument(..., help="Domain key to pause/resume."),
    domain: str = typer.Option("adapter", "--domain", help="Domain to target.", case_sensitive=False),
    note: Optional[str] = typer.Option(None, "--note", help="Optional note to attach to the pause state."),
    resume: bool = typer.Option(False, "--resume", help="Resume (unpause) the target."),
) -> None:
    state = _state(ctx)
    domain = _normalize_domain(domain)
    bridge = state.bridges[domain]
    activity = bridge.set_paused(key, paused=not resume, note=note)
    typer.echo(
        f"{'Resumed' if resume else 'Paused'} {domain}:{key} "
        f"(note={activity.note or 'none'})"
    )


@app.command("drain")
def drain_command(
    ctx: typer.Context,
    key: str = typer.Argument(..., help="Domain key to mark draining."),
    domain: str = typer.Option("adapter", "--domain", help="Domain to target.", case_sensitive=False),
    note: Optional[str] = typer.Option(None, "--note", help="Optional note to attach to the draining state."),
    clear: bool = typer.Option(False, "--clear", help="Clear draining state."),
) -> None:
    state = _state(ctx)
    domain = _normalize_domain(domain)
    bridge = state.bridges[domain]
    activity = bridge.set_draining(key, draining=not clear, note=note)
    typer.echo(
        f"{'Cleared' if clear else 'Marked'} draining for {domain}:{key} "
        f"(note={activity.note or 'none'})"
    )


@app.command("remote-sync")
def remote_sync_command(
    ctx: typer.Context,
    manifest: Optional[str] = typer.Option(None, "--manifest", help="Override manifest URL/path.", metavar="URI"),
    watch: bool = typer.Option(False, "--watch", help="Keep refreshing manifests using settings."),
    refresh_interval: Optional[float] = typer.Option(
        None,
        "--refresh-interval",
        help="Override refresh interval (seconds) when running with --watch.",
        metavar="SECONDS",
    ),
) -> None:
    state = _state(ctx)
    asyncio.run(
        _handle_remote_sync(
            state.resolver,
            state.settings,
            state.lifecycle,
            manifest_override=manifest,
            watch=watch,
            refresh_interval=refresh_interval,
        )
    )


@app.command()
def orchestrate(
    ctx: typer.Context,
    manifest: Optional[str] = typer.Option(None, "--manifest", help="Override manifest URL/path.", metavar="URI"),
    refresh_interval: Optional[float] = typer.Option(
        None,
        "--refresh-interval",
        help="Override remote refresh interval (seconds) for the orchestrator.",
        metavar="SECONDS",
    ),
    no_remote: bool = typer.Option(False, "--no-remote", help="Disable remote sync/refresh."),
) -> None:
    state = _state(ctx)
    asyncio.run(
        _handle_orchestrate(
            state.settings,
            state.resolver,
            state.lifecycle,
            manifest_override=manifest,
            refresh_interval=refresh_interval,
            disable_remote=no_remote,
        )
    )


@app.command()
def status(
    ctx: typer.Context,
    domain: str = typer.Option("adapter", "--domain", help="Domain to inspect.", case_sensitive=False),
    key: Optional[str] = typer.Option(None, "--key", help="Domain key to inspect (optional)."),
    json_output: bool = typer.Option(False, "--json", help="Emit status payload as JSON."),
    show_shadowed: bool = typer.Option(False, "--shadowed", help="Include details for shadowed candidates."),
) -> None:
    state = _state(ctx)
    domain = _normalize_domain(domain)
    _handle_status(
        state.bridges[domain],
        state.lifecycle,
        domain=domain,
        key=key,
        as_json=json_output,
        settings=state.settings,
        include_shadowed=show_shadowed,
    )


@app.command("activity")
def activity_command(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Emit activity summary as JSON."),
) -> None:
    state = _state(ctx)
    report = _activity_summary(state.bridges)
    if json_output:
        print(json.dumps(report, indent=2))
        return
    _print_activity_report(report)


@app.command()
def health(
    ctx: typer.Context,
    domain: Optional[str] = typer.Option(None, "--domain", help="Filter to a single domain.", case_sensitive=False),
    key: Optional[str] = typer.Option(None, "--key", help="Filter to a specific key."),
    json_output: bool = typer.Option(False, "--json", help="Emit health payload as JSON."),
    probe: bool = typer.Option(False, "--probe", help="Run live health probes for active instances."),
) -> None:
    state = _state(ctx)
    domain = _coerce_domain(domain)
    lifecycle_payload, lifecycle_summary = _handle_health(
        state.lifecycle,
        domain=domain,
        key=key,
        as_json=json_output,
        probe=probe,
    )
    runtime_snapshot = load_runtime_health(runtime_health_path(state.settings)).as_dict()
    if json_output:
        print(
            json.dumps(
                {
                    "lifecycle": lifecycle_payload,
                    "lifecycle_summary": lifecycle_summary,
                    "runtime": runtime_snapshot,
                },
                indent=2,
            )
        )
        return
    print(_format_swap_summary(lifecycle_summary))
    _print_runtime_health(runtime_snapshot, state.settings.remote.cache_dir, state.settings.remote)


@app.command("remote-status")
def remote_status_command(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Emit telemetry as JSON."),
) -> None:
    state = _state(ctx)
    _handle_remote_status(state.settings, as_json=json_output)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
