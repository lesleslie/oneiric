"""Oneiric command line utilities."""

from __future__ import annotations

import asyncio
import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import typer

from oneiric.adapters import AdapterBridge
from oneiric.adapters.metadata import AdapterMetadata, register_adapter_metadata
from oneiric.core.config import (
    OneiricSettings,
    SecretsHook,
    domain_activity_path,
    lifecycle_snapshot_path,
    load_settings,
    resolver_settings_from_config,
    runtime_health_path,
)
from oneiric.core.lifecycle import LifecycleManager
from oneiric.core.logging import configure_logging, get_logger
from oneiric.core.resolution import Candidate, Resolver
from oneiric.domains import EventBridge, ServiceBridge, TaskBridge, WorkflowBridge
from oneiric.remote import load_remote_telemetry, remote_sync_loop, sync_remote_manifest
from oneiric.runtime.activity import DomainActivityStore
from oneiric.runtime.health import load_runtime_health
from oneiric.runtime.orchestrator import RuntimeOrchestrator

logger = get_logger("cli")


DOMAINS = ("adapter", "service", "task", "event", "workflow")
DEFAULT_REMOTE_REFRESH_INTERVAL = 300.0

app = typer.Typer(help="Oneiric runtime management CLI.")


@dataclass
class CLIState:
    settings: OneiricSettings
    resolver: Resolver
    lifecycle: LifecycleManager
    bridges: Dict[str, AdapterBridge | ServiceBridge | TaskBridge | EventBridge | WorkflowBridge]


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


def _initialize_state(
    config_path: Optional[str],
    imports: Iterable[str],
    demo: bool,
) -> CLIState:
    settings = load_settings(config_path)
    resolver = Resolver(settings=resolver_settings_from_config(settings))
    _import_modules(imports)
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
    lifecycle = LifecycleManager(
        resolver,
        status_snapshot_path=str(lifecycle_snapshot_path(settings)),
    )
    activity_store = DomainActivityStore(domain_activity_path(settings))
    bridges: Dict[str, AdapterBridge | ServiceBridge | TaskBridge | EventBridge | WorkflowBridge] = {
        "adapter": AdapterBridge(resolver, lifecycle, settings.adapters, activity_store=activity_store),
        "service": ServiceBridge(resolver, lifecycle, settings.services, activity_store=activity_store),
        "task": TaskBridge(resolver, lifecycle, settings.tasks, activity_store=activity_store),
        "event": EventBridge(resolver, lifecycle, settings.events, activity_store=activity_store),
        "workflow": WorkflowBridge(resolver, lifecycle, settings.workflows, activity_store=activity_store),
    }

    return CLIState(
        settings=settings,
        resolver=resolver,
        lifecycle=lifecycle,
        bridges=bridges,
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
    if not telemetry.last_success_at and not telemetry.last_failure_at:
        print("No remote refresh telemetry recorded yet.")
        print(f"Cache dir: {settings.remote.cache_dir}")
        return
    print(f"Cache dir: {settings.remote.cache_dir}")
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
    payload: Dict[str, Any] = {"domain": domain, "status": records}
    remote_telemetry = load_remote_telemetry(settings.remote.cache_dir).as_dict()
    per_domain_counts = remote_telemetry.get("last_per_domain") or {}
    payload["remote_telemetry"] = remote_telemetry
    if as_json:
        print(json.dumps(payload, indent=2))
        return
    print(f"Domain: {domain}")
    if per_domain_counts.get(domain):
        print(
            f"Remote summary: last sync registered {per_domain_counts[domain]} {domain}(s)"
        )
    if not records:
        print("  (no keys)")
    for record in records:
        _print_status_record(record)
    if domain == "adapter":
        _print_remote_summary(payload["remote_telemetry"], settings.remote.cache_dir)


def _handle_health(
    lifecycle: LifecycleManager,
    *,
    domain: Optional[str],
    key: Optional[str],
    as_json: bool,
    probe: bool,
) -> Dict[str, Any]:
    statuses = lifecycle.all_statuses()
    if domain:
        statuses = [status for status in statuses if status.domain == domain]
    if key:
        statuses = [status for status in statuses if status.key == key]
    payload = [status.as_dict() for status in statuses]
    if probe and payload:
        probe_results = asyncio.run(_probe_lifecycle_entries(lifecycle, payload))
        for entry in payload:
            entry["probe_result"] = probe_results.get((entry["domain"], entry["key"]))
    if as_json:
        return payload
    if not payload:
        print("No lifecycle statuses recorded yet.")
        return payload
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
    return payload


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


def _activity_summary(bridges: Dict[str, AdapterBridge | ServiceBridge | TaskBridge | EventBridge | WorkflowBridge]) -> Dict[str, List[Dict[str, Any]]]:
    summary: Dict[str, List[Dict[str, Any]]] = {}
    for domain, bridge in bridges.items():
        snapshot = bridge.activity_snapshot()
        rows = []
        for key, state in sorted(snapshot.items()):
            if not state.paused and not state.draining and not state.note:
                continue
            rows.append(
                {
                    "key": key,
                    "paused": state.paused,
                    "draining": state.draining,
                    "note": state.note,
                }
            )
        if rows:
            summary[domain] = rows
    return summary


def _print_activity_report(report: Dict[str, List[Dict[str, Any]]]) -> None:
    if not report:
        print("No paused or draining keys recorded.")
        return
    for domain in sorted(report.keys()):
        print(f"{domain} activity:")
        for entry in report[domain]:
            status_bits = []
            if entry["paused"]:
                status_bits.append("paused")
            if entry["draining"]:
                status_bits.append("draining")
            status = ", ".join(status_bits) or "note-only"
            note = entry.get("note")
            note_part = f" note={note}" if note else ""
            print(f"  - {entry['key']}: {status}{note_part}")


def _print_remote_summary(telemetry: Dict[str, Any], cache_dir: str) -> None:
    print(f"Remote telemetry cache: {cache_dir}")
    last_success = telemetry.get("last_success_at")
    last_failure = telemetry.get("last_failure_at")
    if not last_success and not last_failure:
        print("  No remote refresh telemetry yet.")
        return
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


def _print_runtime_health(snapshot: Dict[str, Any], cache_dir: str) -> None:
    print(f"Runtime health cache: {cache_dir}")
    watchers = "running" if snapshot.get("watchers_running") else "stopped"
    remote = "enabled" if snapshot.get("remote_enabled") else "disabled"
    pid = snapshot.get("orchestrator_pid") or "n/a"
    print(f"  watchers={watchers} remote={remote} orchestrator_pid={pid}")
    if snapshot.get("last_remote_sync_at"):
        print(f"  last_remote_sync={snapshot['last_remote_sync_at']}")
    if snapshot.get("last_remote_error"):
        print(f"  last_remote_error={snapshot['last_remote_error']}")
    if snapshot.get("last_remote_registered") is not None:
        print(f"  last_remote_registered={snapshot['last_remote_registered']}")
    per_domain = snapshot.get("last_remote_per_domain") or {}
    if per_domain:
        print("  last_remote_per_domain:")
        for domain, count in per_domain.items():
            print(f"    - {domain}: {count}")
    if snapshot.get("last_remote_skipped"):
        print(f"  last_remote_skipped={snapshot['last_remote_skipped']}")
    activity = snapshot.get("activity_state") or {}
    if activity:
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
    lifecycle_payload = _handle_health(
        state.lifecycle,
        domain=domain,
        key=key,
        as_json=json_output,
        probe=probe,
    )
    runtime_snapshot = load_runtime_health(runtime_health_path(state.settings)).as_dict()
    if json_output:
        print(json.dumps({"lifecycle": lifecycle_payload, "runtime": runtime_snapshot}, indent=2))
        return
    _print_runtime_health(runtime_snapshot, state.settings.remote.cache_dir)


@app.command("remote-status")
def remote_status_command(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Emit telemetry as JSON."),
) -> None:
    state = _state(ctx)
    _handle_remote_status(state.settings, as_json=json_output)


def main() -> None:
    configure_logging()
    app()


if __name__ == "__main__":
    main()
