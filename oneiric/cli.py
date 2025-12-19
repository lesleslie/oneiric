"""Oneiric command line utilities."""

from __future__ import annotations

import asyncio
import base64
import importlib
import inspect
import json
import math
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import typer
import yaml

from oneiric import plugins
from oneiric.actions import ActionBridge, register_builtin_actions
from oneiric.actions.bootstrap import builtin_action_metadata
from oneiric.actions.metadata import ActionMetadata
from oneiric.adapters import AdapterBridge
from oneiric.adapters.bootstrap import builtin_adapter_metadata
from oneiric.adapters.metadata import AdapterMetadata, register_adapter_metadata
from oneiric.core.config import (
    OneiricSettings,
    SecretsHook,
    apply_profile_with_fallback,
    domain_activity_path,
    lifecycle_snapshot_path,
    load_settings,
    resolver_settings_from_config,
    runtime_health_path,
    runtime_observability_path,
    workflow_checkpoint_path,
)
from oneiric.core.lifecycle import (
    LifecycleError,
    LifecycleManager,
    LifecycleSafetyOptions,
    LifecycleStatus,
)
from oneiric.core.logging import configure_logging, get_logger
from oneiric.core.resolution import Candidate, Resolver
from oneiric.domains import EventBridge, ServiceBridge, TaskBridge, WorkflowBridge
from oneiric.remote import load_remote_telemetry, remote_sync_loop, sync_remote_manifest
from oneiric.remote.models import (
    CapabilityDescriptor,
    RemoteManifest,
    RemoteManifestEntry,
)
from oneiric.remote.security import get_canonical_manifest_for_signing
from oneiric.runtime.activity import DomainActivityStore
from oneiric.runtime.checkpoints import WorkflowCheckpointStore
from oneiric.runtime.events import HandlerResult
from oneiric.runtime.health import load_runtime_health
from oneiric.runtime.load_testing import LoadTestProfile, LoadTestResult, run_load_test
from oneiric.runtime.notifications import NotificationRoute, NotificationRouter
from oneiric.runtime.orchestrator import RuntimeOrchestrator
from oneiric.runtime.scheduler import SchedulerHTTPServer, WorkflowTaskProcessor
from oneiric.runtime.telemetry import load_runtime_telemetry

logger = get_logger("cli")


DOMAINS = ("adapter", "service", "task", "event", "workflow", "action")
DEFAULT_REMOTE_REFRESH_INTERVAL = 300.0

app = typer.Typer(help="Oneiric runtime management CLI.")
manifest_app = typer.Typer(help="Manifest utilities (packaging, inspection).")
secrets_app = typer.Typer(help="Secrets cache + rotation helpers.")
event_app = typer.Typer(help="Event dispatcher helpers.")
workflow_app = typer.Typer(help="Workflow DAG helpers.")
app.add_typer(manifest_app, name="manifest")
app.add_typer(secrets_app, name="secrets")
app.add_typer(event_app, name="event")
app.add_typer(workflow_app, name="workflow")


@dataclass
class CLIState:
    settings: OneiricSettings
    resolver: Resolver
    lifecycle: LifecycleManager
    bridges: dict[
        str,
        AdapterBridge
        | ServiceBridge
        | TaskBridge
        | EventBridge
        | WorkflowBridge
        | ActionBridge,
    ]
    plugin_report: plugins.PluginRegistrationReport
    secrets: SecretsHook
    notification_router: NotificationRouter


def _build_lifecycle_options(config: object | None) -> LifecycleSafetyOptions:
    if not config:
        return LifecycleSafetyOptions()
    return LifecycleSafetyOptions(
        activation_timeout=getattr(config, "activation_timeout", 30.0) or 0,
        health_timeout=getattr(config, "health_timeout", 5.0) or 0,
        cleanup_timeout=getattr(config, "cleanup_timeout", 10.0) or 0,
        hook_timeout=getattr(config, "hook_timeout", 5.0) or 0,
        shield_tasks=bool(getattr(config, "shield_tasks", True)),
    )


def _swap_latency_summary(statuses: Iterable[LifecycleStatus]) -> dict[str, Any]:
    durations: list[float] = []
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


def _percentile(data: list[float], percentile: float) -> float | None:
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


def _format_swap_summary(summary: dict[str, Any]) -> str:
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


def _activity_summary_for_bridge(bridge) -> dict[str, int]:
    snapshot_fn = getattr(bridge, "activity_snapshot", None)
    if not callable(snapshot_fn):
        return {"paused": 0, "draining": 0}
    snapshot = snapshot_fn()
    paused = sum(1 for state in snapshot.values() if getattr(state, "paused", False))
    draining = sum(
        1 for state in snapshot.values() if getattr(state, "draining", False)
    )
    return {"paused": paused, "draining": draining}


def _default_notification_adapter_key(settings: OneiricSettings) -> str | None:
    selections = getattr(settings.adapters, "selections", {}) or {}
    for key in selections:
        if key.startswith("notifications"):
            return key
    return None


def _derive_notification_route(
    state: CLIState,
    *,
    workflow_key: str | None,
    notify_adapter: str | None,
    notify_target: str | None,
    force_send: bool,
) -> NotificationRoute | None:
    should_send = force_send or any(
        value is not None for value in (workflow_key, notify_adapter, notify_target)
    )
    if not should_send:
        return None

    adapter_key = notify_adapter
    adapter_provider: str | None = None
    channel: str | None = None
    target_hint: str | None = None
    title_template: str | None = None
    include_context = True
    extra_payload: dict[str, Any] | None = None

    if workflow_key:
        candidate = state.resolver.resolve("workflow", workflow_key)
        if not candidate:
            raise typer.BadParameter(
                f"Workflow '{workflow_key}' is not registered; cannot derive notification metadata."
            )
        metadata = candidate.metadata.get("notifications")
        if isinstance(metadata, Mapping):
            adapter_key = adapter_key or metadata.get("adapter_provider")
            adapter_key = (
                adapter_key or metadata.get("adapter") or metadata.get("adapter_key")
            )
            adapter_provider = metadata.get("provider")
            channel = metadata.get("channel")
            target_hint = metadata.get("target")
            include_context = bool(metadata.get("include_context", True))
            title_template = metadata.get("title_template") or metadata.get("title")
            raw_payload = metadata.get("extra_payload")
            extra_payload = raw_payload if isinstance(raw_payload, dict) else None
        else:
            channel = None

    target = notify_target or target_hint or channel
    if adapter_key is None and not force_send:
        return None

    return NotificationRoute(
        adapter_key=adapter_key,
        adapter_provider=adapter_provider,
        target=target,
        channel=None if target else channel,
        title_template=title_template,
        include_context=include_context,
        extra_payload=extra_payload,
    )


def _format_activity_summary(summary: dict[str, int]) -> str:
    return "Activity state: paused={paused} draining={draining}".format(
        paused=summary.get("paused", 0),
        draining=summary.get("draining", 0),
    )


def _activity_counts_from_mapping(
    activity_state: dict[str, dict[str, Any]],
) -> dict[str, int]:
    paused = 0
    draining = 0
    for entries in activity_state.values():
        for state in entries.values():
            if state.get("paused"):
                paused += 1
            if state.get("draining"):
                draining += 1
    return {"paused": paused, "draining": draining}


def _lifecycle_counts_from_mapping(
    lifecycle_state: dict[str, dict[str, Any]],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entries in lifecycle_state.values():
        for state in entries.values():
            label = state.get("state") or "unknown"
            counts[label] = counts.get(label, 0) + 1
    return counts


def _format_remote_budget_line(remote_config, last_duration: float | None) -> str:
    budget = getattr(remote_config, "latency_budget_ms", 0) or 0
    budget_text = f"{budget:.0f}ms" if budget else "n/a"
    if last_duration is None:
        return f"Remote latency budget={budget_text} (no syncs yet)"
    duration_text = f"{last_duration:.1f}ms"
    status = "OK" if not budget or last_duration <= budget else "EXCEEDED"
    return (
        f"Remote latency budget={budget_text}; last_duration={duration_text} ({status})"
    )


def _parse_payload(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"Invalid JSON payload: {exc}")
    if not isinstance(data, dict):
        raise typer.BadParameter("Payload JSON must be an object")
    return data


def _parse_csv(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _event_results_payload(results: list[HandlerResult]) -> list[dict[str, Any]]:
    return [
        {
            "handler": result.handler,
            "success": result.success,
            "duration_ms": result.duration * 1000.0,
            "value": result.value,
            "error": result.error,
            "attempts": result.attempts,
        }
        for result in results
    ]


def _load_manifest_from_path(path: Path) -> RemoteManifest:
    """Load manifest JSON/YAML into a RemoteManifest model."""
    text = path.read_text()
    try:
        return RemoteManifest.model_validate_json(text)
    except ValueError:
        loaded = yaml.safe_load(text)
        if not isinstance(loaded, dict):
            raise typer.BadParameter("Manifest must be a JSON or YAML mapping")
        return RemoteManifest.model_validate(loaded)


def _manifest_entry_from_adapter(
    adapter: AdapterMetadata, version: str
) -> RemoteManifestEntry:
    if isinstance(adapter.factory, str):
        factory_str = adapter.factory
    elif callable(adapter.factory):
        factory_str = f"{adapter.factory.__module__}:{adapter.factory.__qualname__}"
    else:
        raise ValueError(f"Unsupported factory type: {type(adapter.factory)}")

    settings_model_str: str | None = None
    if adapter.settings_model:
        if isinstance(adapter.settings_model, str):
            settings_model_str = adapter.settings_model
        else:
            settings_model_str = (
                f"{adapter.settings_model.__module__}:{adapter.settings_model.__name__}"
            )

    capability_descriptors = [
        CapabilityDescriptor(name=name, description=None)
        for name in adapter.capabilities
    ]

    return RemoteManifestEntry(
        domain="adapter",
        key=adapter.category,
        provider=adapter.provider,
        factory=factory_str,
        stack_level=adapter.stack_level or 0,
        priority=adapter.priority,
        version=adapter.version or version,
        capabilities=capability_descriptors,
        owner=adapter.owner,
        requires_secrets=adapter.requires_secrets,
        settings_model=settings_model_str,
        metadata={
            "description": adapter.description or "",
            "source": str(adapter.source),
        },
    )


def _manifest_entry_from_action(
    action: ActionMetadata, version: str
) -> RemoteManifestEntry:
    if isinstance(action.factory, str):
        factory_str = action.factory
    elif callable(action.factory):
        factory_str = f"{action.factory.__module__}:{action.factory.__qualname__}"
    else:
        raise ValueError(f"Unsupported factory type: {type(action.factory)}")

    return RemoteManifestEntry(
        domain="action",
        key=action.action_type,
        provider=action.provider,
        factory=factory_str,
        stack_level=action.stack_level or 0,
        priority=action.priority,
        version=action.version or version,
        side_effect_free=action.extras.get("side_effect_free", False),
        timeout_seconds=action.extras.get("timeout_seconds"),
        metadata={
            "description": action.description or "",
            "source": str(action.source),
        },
    )


async def _invoke_action(handle, payload: dict[str, Any]) -> Any:
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
    payload: dict[str, Any],
    *,
    provider: str | None,
    notification_router: NotificationRouter | None = None,
    notification_route: NotificationRoute | None = None,
) -> Any:
    handle = await bridge.use(key, provider=provider)
    result = await _invoke_action(handle, payload)
    if (
        key == "workflow.notify"
        and notification_router is not None
        and notification_route is not None
    ):
        await notification_router.send(result, notification_route)
    return result


async def _event_emit_runner(
    bridge: EventBridge,
    topic: str,
    payload: dict[str, Any],
    headers: dict[str, Any],
) -> list[HandlerResult]:
    return await bridge.emit(topic, payload, headers=headers)


async def _workflow_run_runner(
    bridge: WorkflowBridge,
    key: str,
    context: dict[str, Any] | None,
):
    return await bridge.execute_dag(key, context=context)


async def _workflow_enqueue_runner(
    bridge: WorkflowBridge,
    key: str,
    *,
    context: dict[str, Any] | None,
    queue_category: str | None,
    provider: str | None,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    return await bridge.enqueue_workflow(
        key,
        context=context,
        queue_category=queue_category,
        provider=provider,
        metadata=metadata,
    )


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

    async def handle(self, envelope) -> dict:
        return {
            "name": self.name,
            "topic": getattr(envelope, "topic", "unknown"),
            "payload": getattr(envelope, "payload", {}),
        }


@dataclass
class DemoCLIAction:
    name: str = "cli-action"

    async def execute(self, payload: dict | None = None) -> dict:
        return {"name": self.name, "payload": payload or {}}


@dataclass
class DemoCLIQueue:
    records: list[dict[str, Any]] = field(default_factory=list)

    async def enqueue(self, payload: dict[str, Any]) -> str:
        self.records.append(payload)
        return f"demo-queue-{len(self.records)}"


def _initialize_state(
    config_path: str | None,
    imports: Iterable[str],
    demo: bool,
    profile: str | None = None,
) -> CLIState:
    settings = load_settings(config_path)
    env_profile = os.getenv("ONEIRIC_PROFILE")
    settings = apply_profile_with_fallback(settings, profile or env_profile)
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
                ),
                AdapterMetadata(
                    category="queue",
                    provider="cli",
                    stack_level=5,
                    factory=DemoCLIQueue,
                    description="CLI demo queue adapter",
                ),
            ],
        )
        resolver.register(
            Candidate(
                domain="service",
                key="status",
                provider="cli",
                factory=DemoCLIService,
                stack_level=5,
            )
        )
        resolver.register(
            Candidate(
                domain="task",
                key="demo-task",
                provider="cli",
                factory=DemoCLITask,
                stack_level=5,
            )
        )
        resolver.register(
            Candidate(
                domain="event",
                key="demo.event",
                provider="cli",
                factory=DemoCLIEventHandler,
                metadata={"topics": ["cli.event"]},
                stack_level=5,
            )
        )
        resolver.register(
            Candidate(
                domain="workflow",
                key="demo-workflow",
                provider="cli",
                factory=DemoCLIWorkflow,
                metadata={
                    "dag": {
                        "nodes": [
                            {"id": "demo-step", "task": "demo-task"},
                        ]
                    },
                    "scheduler": {
                        "queue_category": "queue",
                        "provider": "cli",
                    },
                },
                stack_level=5,
            )
        )
        resolver.register(
            Candidate(
                domain="action",
                key="demo-action",
                provider="cli",
                factory=DemoCLIAction,
                stack_level=5,
            )
        )
    lifecycle = LifecycleManager(
        resolver,
        status_snapshot_path=str(lifecycle_snapshot_path(settings)),
        safety=_build_lifecycle_options(settings.lifecycle),
    )
    activity_store = DomainActivityStore(domain_activity_path(settings))
    checkpoint_path = workflow_checkpoint_path(settings)
    checkpoint_store = (
        WorkflowCheckpointStore(checkpoint_path) if checkpoint_path else None
    )
    adapter_bridge = AdapterBridge(
        resolver, lifecycle, settings.adapters, activity_store=activity_store
    )
    notification_router = NotificationRouter(
        adapter_bridge,
        default_adapter_key=_default_notification_adapter_key(settings),
    )
    task_bridge = TaskBridge(
        resolver, lifecycle, settings.tasks, activity_store=activity_store
    )
    workflow_bridge = WorkflowBridge(
        resolver,
        lifecycle,
        settings.workflows,
        activity_store=activity_store,
        task_bridge=task_bridge,
        checkpoint_store=checkpoint_store,
        queue_bridge=adapter_bridge,
    )
    bridges: dict[
        str,
        AdapterBridge
        | ServiceBridge
        | TaskBridge
        | EventBridge
        | WorkflowBridge
        | ActionBridge,
    ] = {
        "adapter": adapter_bridge,
        "service": ServiceBridge(
            resolver, lifecycle, settings.services, activity_store=activity_store
        ),
        "task": task_bridge,
        "event": EventBridge(
            resolver, lifecycle, settings.events, activity_store=activity_store
        ),
        "workflow": workflow_bridge,
        "action": ActionBridge(
            resolver, lifecycle, settings.actions, activity_store=activity_store
        ),
    }
    secrets = SecretsHook(lifecycle, settings.secrets)

    return CLIState(
        settings=settings,
        resolver=resolver,
        lifecycle=lifecycle,
        bridges=bridges,
        plugin_report=plugin_report,
        secrets=secrets,
        notification_router=notification_router,
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


def _coerce_domain(value: str | None) -> str | None:
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
    provider: str | None,
    force: bool,
) -> None:
    instance = await lifecycle.swap(domain, key, provider=provider, force=force)
    print(f"Swapped {domain}:{key} -> {provider or 'auto'}; instance={instance!r}")


async def _handle_remote_sync(
    resolver: Resolver,
    settings: OneiricSettings,
    lifecycle: LifecycleManager,
    secrets: SecretsHook,
    *,
    manifest_override: str | None,
    watch: bool,
    refresh_interval: float | None,
) -> None:
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
            print(
                f"Remote sync complete: {result.registered} candidates from {result.manifest.source}."
            )


async def _handle_orchestrate(
    settings: OneiricSettings,
    resolver: Resolver,
    lifecycle: LifecycleManager,
    secrets: SecretsHook,
    *,
    manifest_override: str | None,
    refresh_interval: float | None,
    disable_remote: bool,
    workflow_checkpoint_override: str | None,
    disable_workflow_checkpoints: bool,
    http_port: int | None,
    http_host: str,
    enable_http: bool,
    print_dag: bool,
    workflow_filters: Sequence[str],
    inspect_events: bool,
    inspect_json: bool,
) -> None:
    resolved_http_port = _resolve_http_port(http_port) if enable_http else None
    orchestrator = RuntimeOrchestrator(
        settings,
        resolver,
        lifecycle,
        secrets,
        health_path=str(runtime_health_path(settings)),
        workflow_checkpoint_path=workflow_checkpoint_override,
        enable_workflow_checkpoints=not disable_workflow_checkpoints,
    )
    if print_dag or inspect_events:
        telemetry = load_runtime_telemetry(runtime_observability_path(settings))
        payload: dict[str, Any] = {}
        if print_dag:
            payload["workflows"] = _workflow_inspector_summary(
                orchestrator.workflow_bridge,
                workflow_filters,
                telemetry.last_workflow,
            )
        if inspect_events:
            payload["events"] = _event_inspector_summary(
                orchestrator.event_bridge, telemetry.last_event
            )
        _emit_inspector_payload(payload, inspect_json)
        return
    http_server: SchedulerHTTPServer | None = None
    try:
        await orchestrator.start(
            manifest_url=manifest_override,
            refresh_interval_override=refresh_interval,
            enable_remote=not disable_remote,
        )
        if enable_http and resolved_http_port is not None:
            processor = WorkflowTaskProcessor(orchestrator.workflow_bridge)
            http_server = SchedulerHTTPServer(
                processor,
                host=http_host,
                port=resolved_http_port,
            )
            await http_server.start()
        logger.info(
            "orchestrator-running",
            remote_enabled=not disable_remote,
            refresh_interval=refresh_interval or settings.remote.refresh_interval,
            http_enabled=enable_http,
            http_port=resolved_http_port,
        )
        await _wait_forever()
    except KeyboardInterrupt:
        logger.info("orchestrator-shutdown-requested")
    finally:
        if http_server:
            await http_server.stop()
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

    _print_remote_config(settings, payload)

    if not telemetry.last_success_at and not telemetry.last_failure_at:
        print("  No remote refresh telemetry recorded yet.")
        return

    if telemetry.last_success_at:
        _print_remote_success_status(telemetry)

    if telemetry.last_failure_at:
        _print_remote_failure_status(telemetry)


def _resolve_http_port(port_option: int | None) -> int:
    if port_option is not None:
        return port_option
    env_port = os.getenv("PORT")
    if env_port:
        try:
            return int(env_port)
        except ValueError:
            logger.warning("invalid-port-env", value=env_port)
    return 8080


def _print_remote_config(settings: OneiricSettings, payload: dict[str, Any]) -> None:
    """Print remote configuration details."""
    print(f"Cache dir: {settings.remote.cache_dir}")
    manifest_url = settings.remote.manifest_url or "not configured"
    print(f"Manifest URL: {manifest_url}")
    print(
        "  "
        + _format_remote_budget_line(settings.remote, payload.get("last_duration_ms"))
    )


def _print_remote_success_status(telemetry) -> None:
    """Print last successful sync status."""
    metrics = _build_remote_metrics(telemetry)
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


def _print_remote_failure_status(telemetry) -> None:
    """Print last failed sync status."""
    print(
        "Last failure: "
        f"{telemetry.last_failure_at} (error={telemetry.last_error or 'unknown'}; "
        f"consecutive_failures={telemetry.consecutive_failures})"
    )


def _build_remote_metrics(telemetry) -> str:
    """Build metrics string for remote sync."""
    metric_parts = [f"registered={telemetry.last_registered or 0}"]
    if telemetry.last_duration_ms is not None:
        metric_parts.append(f"duration_ms={telemetry.last_duration_ms:.2f}")
    if telemetry.last_digest_checks is not None:
        metric_parts.append(f"digest_checks={telemetry.last_digest_checks}")
    return " ".join(metric_parts)


def _workflow_inspector_summary(
    bridge: WorkflowBridge,
    filters: Sequence[str],
    last_run: dict[str, Any] | None,
) -> dict[str, Any]:
    specs = bridge.dag_specs()
    targets = _workflow_target_keys(filters, specs.keys())
    summary: dict[str, Any] = {}
    missing: list[str] = []
    default_queue = getattr(bridge, "_queue_category", None)
    for key in targets:
        dag_spec = specs.get(key)
        if not dag_spec:
            missing.append(key)
            continue
        summary[key] = _build_workflow_summary(
            key,
            dag_spec,
            last_run if last_run and last_run.get("workflow") == key else None,
            default_queue,
        )
    if not summary and not missing:
        for key, dag_spec in specs.items():
            summary[key] = _build_workflow_summary(
                key,
                dag_spec,
                last_run if last_run and last_run.get("workflow") == key else None,
                default_queue,
            )
    return {"summary": summary, "missing": missing}


def _workflow_target_keys(
    filters: Sequence[str], available: Iterable[str]
) -> list[str]:
    include_all = not filters
    targets: list[str] = []
    seen: set[str] = set()
    for entry in filters:
        lowered = entry.lower()
        if lowered in {"all", "*"}:
            include_all = True
            continue
        if entry not in seen:
            targets.append(entry)
            seen.add(entry)
    if include_all:
        for key in available:
            if key not in seen:
                targets.append(key)
                seen.add(key)
    return targets


def _build_workflow_summary(
    workflow_key: str,
    dag_spec: dict[str, Any],
    last_run: dict[str, Any] | None,
    default_queue: str | None,
) -> dict[str, Any]:
    nodes_raw = dag_spec.get("nodes") or dag_spec.get("tasks") or []
    nodes: list[dict[str, Any]] = []
    edges = 0
    if isinstance(nodes_raw, Sequence):
        for entry in nodes_raw:
            if not isinstance(entry, Mapping):
                continue
            node_id = entry.get("id") or entry.get("key")
            if not node_id:
                continue
            depends = entry.get("depends_on") or []
            if isinstance(depends, Sequence) and not isinstance(depends, (str, bytes)):
                depends_list = list(depends)
            elif depends:
                depends_list = [depends]
            else:
                depends_list = []
            edges += len(depends_list)
            node_entry: dict[str, Any] = {
                "id": str(node_id),
                "task": entry.get("task"),
                "depends_on": depends_list,
            }
            retry_policy = entry.get("retry_policy")
            if retry_policy:
                node_entry["retry_policy"] = retry_policy
            nodes.append(node_entry)
    entry_nodes = [node["id"] for node in nodes if not node["depends_on"]]
    summary: dict[str, Any] = {
        "node_count": len(nodes),
        "edge_count": edges,
        "entry_nodes": entry_nodes,
        "queue_category": dag_spec.get("queue_category") or default_queue,
        "nodes": nodes,
    }
    if last_run and last_run.get("workflow") == workflow_key:
        summary["last_run"] = last_run
    return summary


def _event_inspector_summary(
    bridge: EventBridge, last_event: dict[str, Any] | None
) -> dict[str, Any]:
    return {
        "handlers": bridge.handler_snapshot(),
        "last_event": last_event or {},
    }


def _emit_inspector_payload(payload: dict[str, Any], json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, indent=2))
        return
    workflows = payload.get("workflows")
    events = payload.get("events")
    if workflows is not None:
        _print_workflow_inspector(workflows)
    if workflows is not None and events is not None:
        print("")
    if events is not None:
        _print_event_inspector(events)


def _print_workflow_inspector(data: dict[str, Any]) -> None:
    summary = data.get("summary") or {}
    if not summary:
        print("No workflow DAGs registered.")
    else:
        print("Workflow DAGs:")
        for workflow_key in sorted(summary):
            record = summary[workflow_key]
            queue = record.get("queue_category") or "queue"
            entry_nodes = record.get("entry_nodes") or []
            entry_text = ", ".join(entry_nodes) if entry_nodes else "n/a"
            print(
                f"- {workflow_key}: nodes={record.get('node_count', 0)} edges={record.get('edge_count', 0)} queue={queue} entry={entry_text}"
            )
            for node in record.get("nodes", []):
                depends = node.get("depends_on") or []
                depends_text = ", ".join(depends) if depends else "root"
                retry_policy = node.get("retry_policy")
                retry_text = f" retry={retry_policy}" if retry_policy else ""
                print(
                    f"    · {node.get('id')}: task={node.get('task')} depends_on={depends_text}{retry_text}"
                )
            last_run = record.get("last_run")
            if last_run:
                duration = float(last_run.get("total_duration_ms", 0.0))
                recorded = last_run.get("recorded_at", "n/a")
                print(f"    last_run: duration={duration:.1f}ms recorded_at={recorded}")
    missing = data.get("missing") or []
    if missing:
        print("Missing workflow keys: " + ", ".join(sorted(missing)))


def _print_event_inspector(data: dict[str, Any]) -> None:
    handlers = data.get("handlers") or []
    if not handlers:
        print("No event handlers registered.")
    else:
        print("Event handlers:")
        for handler in handlers:
            topics = handler.get("topics") or ["*"]
            topics_text = ", ".join(topics)
            print(
                f"- {handler.get('name')}: topics={topics_text} priority={handler.get('priority', 0)} max_concurrency={handler.get('max_concurrency', 1)} fanout={handler.get('fanout_policy', 'broadcast')}"
            )
            retry_policy = handler.get("retry_policy")
            if retry_policy:
                print(f"    retry_policy={retry_policy}")
            filters = handler.get("filters") or []
            if filters:
                print("    filters:")
                for clause in filters:
                    parts = [clause.get("path")]
                    if clause.get("equals") is not None:
                        parts.append(f"== {clause['equals']}")
                    if clause.get("any_of"):
                        parts.append(f"in {clause['any_of']}")
                    exists = clause.get("exists")
                    if exists is True:
                        parts.append("exists")
                    elif exists is False:
                        parts.append("missing")
                    print("      - " + " ".join(part for part in parts if part))
    last_event = data.get("last_event") or {}
    if last_event:
        print(
            "Last event: topic={topic} matched={matched} failures={failures} duration={duration:.1f}ms recorded_at={recorded}".format(
                topic=last_event.get("topic", "unknown"),
                matched=last_event.get("matched_handlers", 0),
                failures=last_event.get("failures", 0),
                duration=float(last_event.get("total_duration_ms", 0.0)),
                recorded=last_event.get("recorded_at", "n/a"),
            )
        )


def _handle_status(
    bridge,
    lifecycle: LifecycleManager,
    *,
    domain: str,
    key: str | None,
    as_json: bool,
    settings: OneiricSettings,
    include_shadowed: bool,
) -> None:
    keys = _status_keys(bridge, key)
    shadowed_map: dict[str, list[Candidate]] = {}
    for cand in bridge.shadowed_candidates():
        shadowed_map.setdefault(cand.key, []).append(cand)
    records = [
        _build_status_record(
            bridge,
            lifecycle,
            key=item,
            shadowed=len(shadowed_map.get(item, [])),
            shadowed_details=shadowed_map.get(item, []),
            include_shadowed=include_shadowed,
        )
        for item in keys
    ]
    domain_statuses = [
        status for status in lifecycle.all_statuses() if status.domain == domain
    ]
    swap_summary = _swap_latency_summary(domain_statuses)
    activity_summary = _activity_summary_for_bridge(bridge)
    payload: dict[str, Any] = {
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
        _print_remote_summary(
            payload["remote_telemetry"], settings.remote.cache_dir, settings.remote
        )


def _handle_health(
    lifecycle: LifecycleManager,
    *,
    domain: str | None,
    key: str | None,
    as_json: bool,
    probe: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    statuses = _filter_health_statuses(lifecycle, domain, key)
    summary = _swap_latency_summary(statuses)
    payload = [status.as_dict() for status in statuses]

    if probe and payload:
        _add_probe_results(lifecycle, payload)

    if as_json:
        return payload, summary

    _print_health_statuses(payload)
    return payload, summary


def _filter_health_statuses(
    lifecycle: LifecycleManager, domain: str | None, key: str | None
):
    """Filter lifecycle statuses by domain and key."""
    statuses = lifecycle.all_statuses()
    if domain:
        statuses = [status for status in statuses if status.domain == domain]
    if key:
        statuses = [status for status in statuses if status.key == key]
    return statuses


def _add_probe_results(
    lifecycle: LifecycleManager, payload: list[dict[str, Any]]
) -> None:
    """Add probe results to payload entries."""
    probe_results = asyncio.run(_probe_lifecycle_entries(lifecycle, payload))
    for entry in payload:
        entry["probe_result"] = probe_results.get((entry["domain"], entry["key"]))


def _print_health_statuses(payload: list[dict[str, Any]]) -> None:
    """Print health status entries to console."""
    if not payload:
        print("No lifecycle statuses recorded yet.")
        return

    for entry in payload:
        _print_health_entry(entry)


def _print_health_entry(entry: dict[str, Any]) -> None:
    """Print a single health status entry."""
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


def _status_keys(bridge, key: str | None) -> list[str]:
    if key:
        return [key]
    keys = set(bridge.settings.selections.keys())
    keys.update(cand.key for cand in bridge.active_candidates())
    return sorted(keys)


def _build_status_record(
    bridge,
    lifecycle: LifecycleManager,
    *,
    key: str,
    shadowed: int,
    shadowed_details: list[Candidate] | None = None,
    include_shadowed: bool = False,
) -> dict[str, Any]:
    candidate = bridge.resolver.resolve(bridge.domain, key)
    configured = bridge.settings.selections.get(key)
    instance = lifecycle.get_instance(bridge.domain, key)
    lifecycle_status = lifecycle.get_status(bridge.domain, key)
    activity = bridge.activity_state(key)
    record: dict[str, Any] = {
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
        record.update(
            {
                "state": "unresolved",
                "message": "No registered candidate",
                "instance_state": "absent",
            }
        )
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
        record["shadowed_details"] = [
            _candidate_summary(cand) for cand in shadowed_details
        ]
    return record


def _print_status_record(record: dict[str, Any]) -> None:
    key = record["key"]
    state = record["state"]
    configured = record.get("configured_provider")
    provider = record.get("provider") or "n/a"
    selection_note = " (selection)" if record.get("selection_applied") else ""
    print(
        f"- {key}: state={state} provider={provider} "
        f"configured={configured or 'auto'} shadowed={record['shadowed']}"
        + selection_note
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


def _activity_summary(
    bridges: dict[
        str, AdapterBridge | ServiceBridge | TaskBridge | EventBridge | WorkflowBridge
    ],
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "domains": {},
        "totals": {"paused": 0, "draining": 0, "note_only": 0},
    }
    for domain, bridge in bridges.items():
        domain_report = _build_domain_activity_report(bridge)
        if domain_report:
            report["domains"][domain] = domain_report
            _update_totals(report["totals"], domain_report["counts"])
    return report


def _build_domain_activity_report(bridge) -> dict[str, Any] | None:
    """Build activity report for a single domain."""
    snapshot = bridge.activity_snapshot()
    rows = []
    counts = {"paused": 0, "draining": 0, "note_only": 0}

    for key, state in sorted(snapshot.items()):
        if not (state.paused or state.draining or state.note):
            continue

        _update_state_counts(counts, state)
        rows.append(
            {
                "key": key,
                "paused": state.paused,
                "draining": state.draining,
                "note": state.note,
            }
        )

    if not rows:
        return None

    return {"counts": counts, "entries": rows}


def _update_state_counts(counts: dict[str, int], state) -> None:
    """Update counts based on state flags."""
    if state.paused:
        counts["paused"] += 1
    if state.draining:
        counts["draining"] += 1
    if state.note and not state.paused and not state.draining:
        counts["note_only"] += 1


def _update_totals(totals: dict[str, int], counts: dict[str, int]) -> None:
    """Add domain counts to totals."""
    totals["paused"] += counts["paused"]
    totals["draining"] += counts["draining"]
    totals["note_only"] += counts["note_only"]


def _print_activity_report(report: dict[str, Any]) -> None:
    domains: dict[str, Any] = report.get("domains") or {}
    if not domains:
        print("No paused or draining keys recorded.")
        return

    _print_activity_totals(report.get("totals", {}))
    _print_domain_activity_reports(domains)


def _print_activity_totals(totals: dict[str, int]) -> None:
    """Print overall activity totals."""
    print(
        "Total activity: paused={paused} draining={draining} note-only={notes}".format(
            paused=totals.get("paused", 0),
            draining=totals.get("draining", 0),
            notes=totals.get("note_only", 0),
        )
    )


def _print_domain_activity_reports(domains: dict[str, Any]) -> None:
    """Print per-domain activity reports."""
    for domain in sorted(domains.keys()):
        _print_domain_activity(domain, domains[domain])


def _print_domain_activity(domain: str, domain_data: dict[str, Any]) -> None:
    """Print activity report for a single domain."""
    counts = domain_data.get("counts", {})
    print(
        f"{domain} activity: paused={counts.get('paused', 0)} "
        f"draining={counts.get('draining', 0)} note-only={counts.get('note_only', 0)}"
    )

    for entry in domain_data.get("entries", []):
        _print_activity_entry(entry)


def _print_activity_entry(entry: dict[str, Any]) -> None:
    """Print a single activity entry."""
    status = _format_entry_status(entry)
    note_part = f" note={entry['note']}" if entry.get("note") else ""
    print(f"  - {entry['key']}: {status}{note_part}")


def _print_load_test_result(result: LoadTestResult) -> None:
    print("Load test results")
    print(
        f"tasks={result.total_tasks} concurrency={result.concurrency} duration={result.duration_seconds:.2f}s throughput={result.throughput_per_second:.2f}/s"
    )
    print(
        f"latency_ms avg={result.avg_latency_ms:.2f} p50={result.p50_latency_ms:.2f} p95={result.p95_latency_ms:.2f} p99={result.p99_latency_ms:.2f} errors={result.errors}"
    )


def _format_entry_status(entry: dict[str, Any]) -> str:
    """Format status string from entry flags."""
    status_bits = []
    if entry["paused"]:
        status_bits.append("paused")
    if entry["draining"]:
        status_bits.append("draining")
    return ", ".join(status_bits) or "note-only"


def _print_remote_summary(
    telemetry: dict[str, Any], cache_dir: str, remote_config
) -> None:
    print(f"Remote telemetry cache: {cache_dir}")
    last_success = telemetry.get("last_success_at")
    last_failure = telemetry.get("last_failure_at")
    if not last_success and not last_failure:
        print("  No remote refresh telemetry yet.")
        return
    print(
        "  "
        + _format_remote_budget_line(remote_config, telemetry.get("last_duration_ms"))
    )
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


def _print_runtime_health(
    snapshot: dict[str, Any], cache_dir: str, remote_config
) -> None:
    print(f"Runtime health cache: {cache_dir}")
    _print_runtime_status(snapshot)
    _print_remote_budget_if_present(snapshot, remote_config)
    _print_remote_sync_info(snapshot)
    _print_remote_duration_info(snapshot, remote_config)
    _print_remote_domain_counts(snapshot)
    _print_remote_skipped(snapshot)
    _print_activity_snapshot(snapshot)
    _print_lifecycle_snapshot(snapshot)


def _print_runtime_status(snapshot: dict[str, Any]) -> None:
    """Print runtime status (watchers, remote, orchestrator)."""
    watchers = "running" if snapshot.get("watchers_running") else "stopped"
    remote = "enabled" if snapshot.get("remote_enabled") else "disabled"
    pid = snapshot.get("orchestrator_pid") or "n/a"
    print(f"  watchers={watchers} remote={remote} orchestrator_pid={pid}")


def _print_remote_budget_if_present(snapshot: dict[str, Any], remote_config) -> None:
    """Print remote budget line if duration is present."""
    if snapshot.get("last_remote_duration_ms") is not None:
        print(
            "  "
            + _format_remote_budget_line(
                remote_config, snapshot.get("last_remote_duration_ms")
            )
        )


def _print_remote_sync_info(snapshot: dict[str, Any]) -> None:
    """Print remote sync timestamp, error, and registration count."""
    if snapshot.get("last_remote_sync_at"):
        print(f"  last_remote_sync={snapshot['last_remote_sync_at']}")
    if snapshot.get("last_remote_error"):
        print(f"  last_remote_error={snapshot['last_remote_error']}")
    if snapshot.get("last_remote_registered") is not None:
        print(f"  last_remote_registered={snapshot['last_remote_registered']}")


def _print_remote_duration_info(snapshot: dict[str, Any], remote_config) -> None:
    """Print remote duration with budget comparison."""
    duration = snapshot.get("last_remote_duration_ms")
    if duration is None:
        return

    budget = getattr(remote_config, "latency_budget_ms", None) or 0
    budget_text = f"{budget:.0f}ms" if budget else "n/a"
    warning = " ⚠ exceeds budget" if budget and duration > budget else ""
    print(f"  last_remote_duration={duration:.1f}ms (budget={budget_text}){warning}")


def _print_remote_domain_counts(snapshot: dict[str, Any]) -> None:
    """Print per-domain registration counts."""
    per_domain = snapshot.get("last_remote_per_domain") or {}
    if not per_domain:
        return

    print("  last_remote_per_domain:")
    for domain, count in per_domain.items():
        print(f"    - {domain}: {count}")


def _print_remote_skipped(snapshot: dict[str, Any]) -> None:
    """Print skipped remote count if present."""
    if snapshot.get("last_remote_skipped"):
        print(f"  last_remote_skipped={snapshot['last_remote_skipped']}")


def _print_activity_snapshot(snapshot: dict[str, Any]) -> None:
    """Print persisted pause/drain state."""
    activity = snapshot.get("activity_state") or {}
    if not activity:
        return

    _print_activity_summary(activity)
    _print_domain_activity_details(activity)


def _print_lifecycle_snapshot(snapshot: dict[str, Any]) -> None:
    """Print lifecycle status summary/details."""
    lifecycle_state = snapshot.get("lifecycle_state") or {}
    if not lifecycle_state:
        return

    totals = _lifecycle_counts_from_mapping(lifecycle_state)
    if totals:
        summary = ", ".join(
            f"{state}={count}" for state, count in sorted(totals.items())
        )
        print(f"  lifecycle-summary: {summary}")
    print("  lifecycle_state:")
    for domain, entries in sorted(lifecycle_state.items()):
        for key, state in sorted(entries.items()):
            current = state.get("current_provider") or "n/a"
            pending = state.get("pending_provider") or "none"
            status = state.get("state") or "unknown"
            print(
                f"    - {domain}:{key} state={status} current={current} pending={pending}"
            )
            if state.get("last_health_at"):
                print(f"      last_health={state['last_health_at']}")
            if state.get("last_error"):
                print(f"      last_error={state['last_error']}")


def _profile_metadata(profile) -> dict[str, Any]:
    if not profile:
        return {}
    return {
        "name": getattr(profile, "name", "default") or "default",
        "watchers_enabled": bool(getattr(profile, "watchers_enabled", True)),
        "remote_enabled": bool(getattr(profile, "remote_enabled", True)),
        "inline_manifest_only": bool(getattr(profile, "inline_manifest_only", False)),
        "supervisor_enabled": bool(getattr(profile, "supervisor_enabled", True)),
    }


def _print_profile_summary(metadata: dict[str, Any]) -> None:
    if not metadata:
        return
    watchers = "on" if metadata.get("watchers_enabled") else "off"
    remote = "on" if metadata.get("remote_enabled") else "off"
    inline = "yes" if metadata.get("inline_manifest_only") else "no"
    supervisor = "on" if metadata.get("supervisor_enabled") else "off"
    print(
        "Profile: {name} watchers={watchers} remote={remote} inline-manifest={inline} supervisor={supervisor}".format(
            name=metadata.get("name", "default"),
            watchers=watchers,
            remote=remote,
            inline=inline,
            supervisor=supervisor,
        )
    )


def _secrets_metadata(config, hook: SecretsHook) -> dict[str, Any]:
    provider = config.provider or f"{config.domain}:{config.key}"
    return {
        "provider": provider,
        "cache_ttl_seconds": config.cache_ttl_seconds,
        "refresh_interval": config.refresh_interval,
        "inline_entries": len(config.inline),
        "prefetched": getattr(hook, "prefetched", False),
    }


def _print_secrets_summary(metadata: dict[str, Any]) -> None:
    if not metadata:
        return
    prefetched = "ready" if metadata.get("prefetched") else "pending"
    inline = metadata.get("inline_entries", 0)
    ttl = metadata.get("cache_ttl_seconds")
    ttl_text = f"{ttl:.0f}s" if ttl is not None else "n/a"
    refresh = metadata.get("refresh_interval")
    refresh_text = f"{refresh:.0f}s" if refresh else "off"
    print(
        "Secrets: provider={provider} cache_ttl={ttl} refresh={refresh} inline_entries={inline} status={status}".format(
            provider=metadata.get("provider", "inline"),
            ttl=ttl_text,
            refresh=refresh_text,
            inline=inline,
            status=prefetched,
        )
    )


def _print_activity_summary(activity: dict[str, Any]) -> None:
    """Print activity summary counts."""
    summary = _activity_counts_from_mapping(activity)
    print(
        "  activity-summary: paused={paused} draining={draining}".format(
            paused=summary.get("paused", 0),
            draining=summary.get("draining", 0),
        )
    )


def _print_domain_activity_details(activity: dict[str, Any]) -> None:
    """Print per-domain activity details."""
    print("  domain_activity:")
    for domain, entries in activity.items():
        for key, state in entries.items():
            status_str = _format_activity_status(state)
            note_suffix = _format_activity_note(state)
            print(f"    - {domain}:{key} {status_str}{note_suffix}")


def _format_activity_status(state: dict[str, Any]) -> str:
    """Format activity status flags."""
    status = []
    if state.get("paused"):
        status.append("paused")
    if state.get("draining"):
        status.append("draining")
    return ",".join(status) if status else "note"


def _format_activity_note(state: dict[str, Any]) -> str:
    """Format activity note suffix."""
    note = state.get("note")
    return f" note={note}" if note else ""


async def _probe_lifecycle_entries(
    lifecycle: LifecycleManager, entries: list[dict[str, Any]]
) -> dict[tuple[str, str], bool | None]:
    results: dict[tuple[str, str], bool | None] = {}
    for entry in entries:
        domain = entry.get("domain")
        key = entry.get("key")
        if not domain or not key:
            continue
        result = await lifecycle.probe_instance_health(domain, key)
        results[(domain, key)] = result
    return results


def _candidate_summary(candidate: Candidate) -> dict[str, Any]:
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
    config: str | None = typer.Option(
        None,
        "--config",
        help="Path to settings file.",
        metavar="PATH",
    ),
    imports: list[str] | None = typer.Option(
        None,
        "--import",
        metavar="MODULE",
        help="Module(s) to import for adapter registration side-effects.",
        show_default=False,
    ),
    profile: str | None = typer.Option(
        None,
        "--profile",
        metavar="NAME",
        help="Runtime profile to apply (default, serverless).",
        show_default=False,
        case_sensitive=False,
    ),
    demo: bool = typer.Option(
        False, "--demo", help="Register built-in demo providers."
    ),
) -> None:
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()
    ctx.obj = _initialize_state(config, imports or [], demo, profile)


@app.command("list")
def list_command(
    ctx: typer.Context,
    domain: str = typer.Option(
        "adapter", "--domain", help="Domain to list.", case_sensitive=False
    ),
    shadowed: bool = typer.Option(
        False, "--shadowed", help="Include shadowed candidates."
    ),
) -> None:
    state = _state(ctx)
    domain = _normalize_domain(domain)
    _handle_list(state.bridges[domain], include_shadowed=shadowed)


@app.command("plugins")
def plugins_command(
    ctx: typer.Context,
    json_output: bool = typer.Option(
        False, "--json", help="Emit plugin diagnostics as JSON."
    ),
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
    key: str = typer.Argument(
        ..., help="Action key to invoke (e.g., compression.encode)."
    ),
    payload: str | None = typer.Option(
        None,
        "--payload",
        help="JSON payload passed to the action (defaults to {}).",
    ),
    provider: str | None = typer.Option(
        None, "--provider", help="Override provider selection."
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON result."),
    workflow_key: str | None = typer.Option(
        None,
        "--workflow",
        help="Workflow key (for workflow.notify) that provides notification metadata.",
    ),
    notify_adapter: str | None = typer.Option(
        None,
        "--notify-adapter",
        help="Adapter key to forward workflow.notify payloads to.",
    ),
    notify_target: str | None = typer.Option(
        None,
        "--notify-target",
        help="Override ChatOps target/channel for workflow.notify payloads.",
    ),
    send_notification: bool = typer.Option(
        False,
        "--send-notification/--no-send-notification",
        help="Forward workflow.notify payloads to the resolved ChatOps adapter.",
    ),
) -> None:
    state = _state(ctx)
    bridge = state.bridges.get("action")
    if not bridge:
        raise typer.BadParameter("Actions domain is not initialized")
    payload_map = _parse_payload(payload)
    notification_route = None
    if key == "workflow.notify":
        notification_route = _derive_notification_route(
            state,
            workflow_key=workflow_key,
            notify_adapter=notify_adapter,
            notify_target=notify_target,
            force_send=send_notification,
        )
    result = asyncio.run(
        _action_invoke_runner(
            bridge,
            key,
            payload_map,
            provider=provider,
            notification_router=state.notification_router,
            notification_route=notification_route,
        )
    )
    if json_output:
        typer.echo(json.dumps(result, indent=2, sort_keys=True))
    else:
        typer.echo(result)


@event_app.command("emit")
def event_emit_command(
    ctx: typer.Context,
    topic: str = typer.Argument(..., help="Topic/subject to emit."),
    payload: str | None = typer.Option(
        None,
        "--payload",
        help="JSON payload for the event (defaults to {}).",
    ),
    headers: str | None = typer.Option(
        None,
        "--headers",
        help="Optional JSON headers (defaults to {}).",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit results as JSON."),
) -> None:
    state = _state(ctx)
    bridge = state.bridges.get("event")
    if not bridge:
        raise typer.BadParameter("Event domain is not initialized")
    payload_map = _parse_payload(payload)
    headers_map = _parse_payload(headers)
    results = asyncio.run(
        _event_emit_runner(bridge, topic, payload_map, headers=headers_map)
    )
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "topic": topic,
                    "matched_handlers": len(results),
                    "results": _event_results_payload(results),
                },
                indent=2,
                default=str,
            )
        )
        return
    if not results:
        typer.echo(f"No event handlers matched topic '{topic}'.")
        return
    typer.echo(f"Dispatched to {len(results)} handler(s) for topic '{topic}'.")
    for result in results:
        status = "ok" if result.success else "error"
        suffix = f" attempts={result.attempts}"
        if result.success and result.value is not None:
            suffix += f" value={result.value}"
        elif not result.success and result.error:
            suffix += f" error={result.error}"
        typer.echo(
            f"- {result.handler}: {status} duration={result.duration * 1000:.1f}ms{suffix}"
        )


@app.command()
def explain(
    ctx: typer.Context,
    key: str = typer.Argument(..., help="Domain key (category/service_id/etc)."),
    domain: str = typer.Option(
        "adapter", "--domain", help="Domain to inspect.", case_sensitive=False
    ),
) -> None:
    state = _state(ctx)
    domain = _normalize_domain(domain)
    _handle_explain(state.resolver, domain, key)


@app.command()
def swap(
    ctx: typer.Context,
    key: str = typer.Argument(..., help="Domain key (category/service_id/etc)."),
    domain: str = typer.Option(
        "adapter", "--domain", help="Domain to target.", case_sensitive=False
    ),
    provider: str | None = typer.Option(
        None, "--provider", help="Provider to target (optional)."
    ),
    force: bool = typer.Option(
        False, "--force", help="Force swap even if health fails."
    ),
) -> None:
    state = _state(ctx)
    domain = _normalize_domain(domain)
    asyncio.run(
        _handle_swap(state.lifecycle, domain, key, provider=provider, force=force)
    )


@app.command("pause")
def pause_command(
    ctx: typer.Context,
    key: str = typer.Argument(..., help="Domain key to pause/resume."),
    domain: str = typer.Option(
        "adapter", "--domain", help="Domain to target.", case_sensitive=False
    ),
    note: str | None = typer.Option(
        None, "--note", help="Optional note to attach to the pause state."
    ),
    resume: bool = typer.Option(False, "--resume", help="Resume (unpause) the target."),
) -> None:
    state = _state(ctx)
    domain = _normalize_domain(domain)
    typer.echo(
        f"{'Resumed' if resume else 'Paused'} {domain}:{key} "
        f"(note={(activity := state.bridges[domain].set_paused(key, paused=not resume, note=note)).note or 'none'})"
    )


@app.command("drain")
def drain_command(
    ctx: typer.Context,
    key: str = typer.Argument(..., help="Domain key to mark draining."),
    domain: str = typer.Option(
        "adapter", "--domain", help="Domain to target.", case_sensitive=False
    ),
    note: str | None = typer.Option(
        None, "--note", help="Optional note to attach to the draining state."
    ),
    clear: bool = typer.Option(False, "--clear", help="Clear draining state."),
) -> None:
    state = _state(ctx)
    domain = _normalize_domain(domain)
    typer.echo(
        f"{'Cleared' if clear else 'Marked'} draining for {domain}:{key} "
        f"(note={(activity := state.bridges[domain].set_draining(key, draining=not clear, note=note)).note or 'none'})"
    )


@app.command("remote-sync")
def remote_sync_command(
    ctx: typer.Context,
    manifest: str | None = typer.Option(
        None, "--manifest", help="Override manifest URL/path.", metavar="URI"
    ),
    watch: bool = typer.Option(
        False, "--watch", help="Keep refreshing manifests using settings."
    ),
    refresh_interval: float | None = typer.Option(
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
            state.secrets,
            manifest_override=manifest,
            watch=watch,
            refresh_interval=refresh_interval,
        )
    )


@workflow_app.command("run")
def workflow_run_command(
    ctx: typer.Context,
    key: str = typer.Argument(..., help="Workflow key to execute."),
    context_payload: str | None = typer.Option(
        None,
        "--context",
        help="JSON context passed to DAG nodes (optional).",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit DAG results as JSON."),
) -> None:
    state = _state(ctx)
    bridge = state.bridges.get("workflow")
    if not bridge:
        raise typer.BadParameter("Workflow domain is not initialized")
    context = _parse_payload(context_payload) if context_payload is not None else None
    run_result = asyncio.run(_workflow_run_runner(bridge, key, context=context))
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "workflow": key,
                    "run_id": run_result["run_id"],
                    "results": run_result["results"],
                },
                indent=2,
                default=str,
            )
        )
        return
    results = run_result["results"]
    if not results:
        typer.echo(f"Workflow {key} did not return any DAG results.")
        return
    typer.echo(
        "Workflow {workflow} completed (run_id={run_id}) with {count} node result(s):".format(
            workflow=key,
            run_id=run_result["run_id"],
            count=len(results),
        )
    )
    for node_key, value in results.items():
        typer.echo(f"- {node_key}: {value}")


@workflow_app.command("enqueue")
def workflow_enqueue_command(
    ctx: typer.Context,
    key: str = typer.Argument(..., help="Workflow key to enqueue."),
    queue_category: str | None = typer.Option(
        None,
        "--queue-category",
        "-q",
        help="Adapter category used for queue resolution (defaults to 'queue').",
    ),
    provider: str | None = typer.Option(
        None,
        "--provider",
        "-p",
        help="Queue adapter provider override (optional).",
    ),
    context_payload: str | None = typer.Option(
        None,
        "--context",
        help="JSON context passed to the DAG run when dequeued.",
    ),
    metadata_payload: str | None = typer.Option(
        None,
        "--metadata",
        help="Additional JSON metadata stored with the queue job.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit enqueue metadata as JSON.",
    ),
) -> None:
    state = _state(ctx)
    bridge = state.bridges.get("workflow")
    if not bridge:
        raise typer.BadParameter("Workflow domain is not initialized")
    context = _parse_payload(context_payload) if context_payload else None
    metadata = _parse_payload(metadata_payload) if metadata_payload else None
    result = asyncio.run(
        _workflow_enqueue_runner(
            bridge,
            key,
            context=context,
            queue_category=queue_category,
            provider=provider,
            metadata=metadata,
        )
    )
    if json_output:
        typer.echo(json.dumps(result, indent=2))
        return
    typer.echo(
        "Queued workflow {workflow} (run_id={run_id}) via {queue_provider}".format(
            **result
        )
    )


@app.command()
def orchestrate(
    ctx: typer.Context,
    manifest: str | None = typer.Option(
        None, "--manifest", help="Override manifest URL/path.", metavar="URI"
    ),
    refresh_interval: float | None = typer.Option(
        None,
        "--refresh-interval",
        help="Override remote refresh interval (seconds) for the orchestrator.",
        metavar="SECONDS",
    ),
    no_remote: bool = typer.Option(
        False, "--no-remote", help="Disable remote sync/refresh."
    ),
    workflow_checkpoints: Path | None = typer.Option(
        None,
        "--workflow-checkpoints",
        metavar="PATH",
        help="Path to workflow checkpoint SQLite store (defaults to cache dir).",
    ),
    no_workflow_checkpoints: bool = typer.Option(
        False,
        "--no-workflow-checkpoints",
        help="Disable workflow DAG checkpoint persistence.",
    ),
    http_port: int | None = typer.Option(
        None,
        "--http-port",
        metavar="PORT",
        help="Run the builtin scheduler HTTP server on this port (defaults to $PORT or 8080 when enabled).",
    ),
    http_host: str = typer.Option(
        "0.0.0.0",
        "--http-host",
        help="Interface for the scheduler HTTP server.",
    ),
    no_http: bool = typer.Option(
        False,
        "--no-http",
        help="Disable the builtin scheduler HTTP server (Cloud Tasks callbacks).",
    ),
    print_dag: bool = typer.Option(
        False,
        "--print-dag",
        help="Print workflow DAG summary and exit.",
    ),
    workflow_filter: list[str] | None = typer.Option(
        None,
        "--workflow",
        metavar="KEY",
        help="Filter --print-dag output to specific workflow key(s).",
    ),
    events_inspector: bool = typer.Option(
        False,
        "--events",
        help="Print registered event handlers and exit.",
    ),
    inspect_json: bool = typer.Option(
        False,
        "--inspect-json",
        help="Emit inspector payloads as JSON (requires --print-dag and/or --events).",
    ),
) -> None:
    state = _state(ctx)
    profile_remote_enabled = getattr(state.settings.profile, "remote_enabled", True)
    disable_remote = no_remote or not profile_remote_enabled
    checkpoint_override = str(workflow_checkpoints) if workflow_checkpoints else None
    asyncio.run(
        _handle_orchestrate(
            state.settings,
            state.resolver,
            state.lifecycle,
            state.secrets,
            manifest_override=manifest,
            refresh_interval=refresh_interval,
            disable_remote=disable_remote,
            workflow_checkpoint_override=checkpoint_override,
            disable_workflow_checkpoints=no_workflow_checkpoints,
            http_port=http_port,
            http_host=http_host,
            enable_http=_http_server_enabled(state.settings, http_port, no_http),
            print_dag=print_dag,
            workflow_filters=tuple(workflow_filter or ()),
            inspect_events=events_inspector,
            inspect_json=inspect_json,
        )
    )


def _http_server_enabled(
    settings: OneiricSettings, http_port_option: int | None, no_http_flag: bool
) -> bool:
    if no_http_flag:
        return False
    if http_port_option is not None:
        return True
    env_port = os.getenv("PORT")
    if env_port:
        return True
    profile_name = settings.profile.name.lower() if settings.profile.name else ""
    return profile_name == "serverless"


@app.command("supervisor-info")
def supervisor_info(ctx: typer.Context) -> None:
    """Show the current supervisor feature flag + env overrides."""
    state = _state(ctx)
    profile_toggle = getattr(state.settings.profile, "supervisor_enabled", True)
    runtime_toggle = getattr(
        state.settings.runtime_supervisor, "enabled", profile_toggle
    )
    poll_interval = getattr(state.settings.runtime_supervisor, "poll_interval", 2.0)
    env_override = os.getenv("ONEIRIC_RUNTIME_SUPERVISOR__ENABLED")
    print(
        "Supervisor toggles: profile={profile} runtime={runtime} poll_interval={interval:.2f}s".format(
            profile="on" if profile_toggle else "off",
            runtime="on" if runtime_toggle else "off",
            interval=poll_interval,
        )
    )
    if env_override is not None:
        print(f"Env override: ONEIRIC_RUNTIME_SUPERVISOR__ENABLED={env_override}")


@app.command()
def status(
    ctx: typer.Context,
    domain: str = typer.Option(
        "adapter", "--domain", help="Domain to inspect.", case_sensitive=False
    ),
    key: str | None = typer.Option(
        None, "--key", help="Domain key to inspect (optional)."
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit status payload as JSON."
    ),
    show_shadowed: bool = typer.Option(
        False, "--shadowed", help="Include details for shadowed candidates."
    ),
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
    json_output: bool = typer.Option(
        False, "--json", help="Emit activity summary as JSON."
    ),
) -> None:
    state = _state(ctx)
    report = _activity_summary(state.bridges)
    if json_output:
        print(json.dumps(report, indent=2))
        return
    _print_activity_report(report)


@app.command("load-test")
def load_test_command(
    total_tasks: int = typer.Option(
        1000, "--total", "-t", help="Total tasks to execute."
    ),
    concurrency: int = typer.Option(
        50, "--concurrency", "-c", help="Maximum concurrent tasks."
    ),
    warmup_tasks: int = typer.Option(
        0, "--warmup", help="Warmup tasks to run before measuring."
    ),
    sleep_ms: float = typer.Option(
        0.0, "--sleep-ms", help="Sleep duration per task (ms)."
    ),
    payload_bytes: int = typer.Option(
        0, "--payload-bytes", help="Payload bytes hashed per task."
    ),
    timeout_seconds: float | None = typer.Option(
        None, "--timeout", help="Cancel the run after this many seconds."
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit load test result as JSON."
    ),
) -> None:
    profile = LoadTestProfile(
        total_tasks=total_tasks,
        concurrency=concurrency,
        warmup_tasks=warmup_tasks,
        sleep_ms=sleep_ms,
        payload_bytes=payload_bytes,
        timeout_seconds=timeout_seconds,
    )
    result = asyncio.run(run_load_test(profile))
    if json_output:
        print(result.model_dump_json(indent=2))
        return
    _print_load_test_result(result)


@app.command()
def health(
    ctx: typer.Context,
    domain: str | None = typer.Option(
        None, "--domain", help="Filter to a single domain.", case_sensitive=False
    ),
    key: str | None = typer.Option(None, "--key", help="Filter to a specific key."),
    json_output: bool = typer.Option(
        False, "--json", help="Emit health payload as JSON."
    ),
    probe: bool = typer.Option(
        False, "--probe", help="Run live health probes for active instances."
    ),
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
    runtime_snapshot = load_runtime_health(
        runtime_health_path(state.settings)
    ).as_dict()
    profile_metadata = _profile_metadata(state.settings.profile)
    secrets_metadata = _secrets_metadata(state.settings.secrets, state.secrets)
    if json_output:
        print(
            json.dumps(
                {
                    "lifecycle": lifecycle_payload,
                    "lifecycle_summary": lifecycle_summary,
                    "runtime": runtime_snapshot,
                    "profile": profile_metadata,
                    "secrets": secrets_metadata,
                },
                indent=2,
            )
        )
        return
    print(_format_swap_summary(lifecycle_summary))
    _print_runtime_health(
        runtime_snapshot, state.settings.remote.cache_dir, state.settings.remote
    )
    _print_profile_summary(profile_metadata)
    _print_secrets_summary(secrets_metadata)


@app.command("remote-status")
def remote_status_command(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Emit telemetry as JSON."),
) -> None:
    state = _state(ctx)
    _handle_remote_status(state.settings, as_json=json_output)


@manifest_app.command("pack")
def manifest_pack(
    input_path: Path = typer.Option(
        Path("docs/sample_remote_manifest.yaml"),
        "--input",
        "-i",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Path to manifest YAML/JSON file.",
    ),
    output_path: Path = typer.Option(
        Path("build/manifest.json"),
        "--output",
        "-o",
        file_okay=True,
        dir_okay=False,
        writable=True,
        help="Destination JSON file (use '-' for stdout).",
    ),
    pretty: bool = typer.Option(True, "--pretty/--compact", help="Format JSON output."),
    stdout: bool = typer.Option(
        False, "--stdout", help="Write JSON to stdout regardless of output path."
    ),
) -> None:
    """Package a manifest file into canonical JSON for serverless builds."""
    manifest = _load_manifest_from_path(input_path)
    if stdout or str(output_path) == "-":
        typer.echo(payload := manifest.model_dump_json(indent=2 if pretty else None))
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        payload := manifest.model_dump_json(indent=2 if pretty else None)
    )
    typer.echo(f"Packed manifest {input_path} -> {output_path}")


@manifest_app.command("export")
def manifest_export(
    output_path: Path = typer.Option(
        Path("build/manifest.yaml"),
        "--output",
        "-o",
        file_okay=True,
        dir_okay=False,
        writable=True,
        help="Destination manifest file (use '-' for stdout).",
    ),
    version: str = typer.Option(
        ..., "--version", help="Default version for entries (semantic versioning)."
    ),
    source: str = typer.Option(
        "oneiric-production", "--source", help="Manifest source identifier."
    ),
    format: str = typer.Option(
        "yaml", "--format", help="Output format (yaml or json)."
    ),
    no_adapters: bool = typer.Option(
        False, "--no-adapters", help="Exclude adapter entries."
    ),
    no_actions: bool = typer.Option(
        False, "--no-actions", help="Exclude action entries."
    ),
    pretty: bool = typer.Option(
        True, "--pretty/--compact", help="Pretty-print the output."
    ),
    stdout: bool = typer.Option(
        False, "--stdout", help="Write output to stdout regardless of output path."
    ),
) -> None:
    """Export builtin registry metadata as a remote manifest."""
    normalized_format = format.lower()
    if normalized_format not in {"yaml", "json"}:
        raise typer.BadParameter("Format must be 'yaml' or 'json'.")

    entries: list[RemoteManifestEntry] = []
    if not no_adapters:
        for adapter_meta in builtin_adapter_metadata():
            entries.append(_manifest_entry_from_adapter(adapter_meta, version))
    if not no_actions:
        for action_meta in builtin_action_metadata():
            entries.append(_manifest_entry_from_action(action_meta, version))

    manifest = RemoteManifest(source=source, entries=entries)
    payload = manifest.model_dump(exclude_none=True)

    if normalized_format == "json":
        rendered = json.dumps(payload, indent=2 if pretty else None)
    else:
        rendered = yaml.safe_dump(
            payload,
            sort_keys=False,
            default_flow_style=False,
            allow_unicode=False,
        )

    if stdout or str(output_path) == "-":
        typer.echo(rendered)
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered)
    typer.echo(f"Exported manifest -> {output_path}")


@manifest_app.command("sign")
def manifest_sign(
    input_path: Path = typer.Option(
        ...,
        "--input",
        "-i",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Path to manifest YAML/JSON file.",
    ),
    private_key: Path = typer.Option(
        ...,
        "--private-key",
        "-k",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Path to ED25519 private key (PEM or raw bytes).",
    ),
    output_path: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        file_okay=True,
        dir_okay=False,
        writable=True,
        help="Destination for signed manifest (defaults to in-place).",
    ),
    stdout: bool = typer.Option(
        False, "--stdout", help="Write signed manifest to stdout."
    ),
    key_id: str | None = typer.Option(
        None, "--key-id", help="Optional key identifier stored with signatures."
    ),
    issued_at: str | None = typer.Option(
        None,
        "--issued-at",
        help="Override signed_at timestamp (ISO-8601).",
    ),
    expires_at: str | None = typer.Option(
        None,
        "--expires-at",
        help="Set expires_at timestamp (ISO-8601).",
    ),
    expires_in: int | None = typer.Option(
        None,
        "--expires-in",
        help="Set expires_at to now + seconds.",
    ),
    append: bool = typer.Option(
        False,
        "--append",
        help="Append signature to signatures list instead of overwriting.",
    ),
) -> None:
    """Sign a manifest with an ED25519 private key."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    manifest = _load_manifest_from_path(input_path)
    manifest_dict = manifest.model_dump(exclude_none=True)
    canonical = get_canonical_manifest_for_signing(manifest_dict)

    key_bytes = private_key.read_bytes()
    if len(key_bytes) == 32:
        signing_key = Ed25519PrivateKey.from_private_bytes(key_bytes)
    else:
        signing_key = serialization.load_pem_private_key(key_bytes, password=None)
        if not isinstance(signing_key, Ed25519PrivateKey):
            raise typer.BadParameter("Private key must be ED25519.")

    signature = base64.b64encode(signing_key.sign(canonical.encode("utf-8"))).decode(
        "ascii"
    )
    signature_entry = {"signature": signature, "algorithm": "ed25519"}
    if key_id:
        signature_entry["key_id"] = key_id

    if issued_at:
        manifest_dict["signed_at"] = issued_at
    elif not manifest_dict.get("signed_at"):
        manifest_dict["signed_at"] = datetime.now(UTC).isoformat()

    if expires_in is not None:
        manifest_dict["expires_at"] = (
            datetime.now(UTC) + timedelta(seconds=expires_in)
        ).isoformat()
    elif expires_at:
        manifest_dict["expires_at"] = expires_at

    use_signatures = append or bool(manifest_dict.get("signatures"))
    if use_signatures:
        signatures = list(manifest_dict.get("signatures") or [])
        signatures.append(signature_entry)
        manifest_dict["signatures"] = signatures
        manifest_dict.pop("signature", None)
        manifest_dict.pop("signature_algorithm", None)
    else:
        manifest_dict["signature"] = signature
        manifest_dict["signature_algorithm"] = "ed25519"

    target = output_path or input_path
    if target.suffix.lower() == ".json":
        rendered = json.dumps(manifest_dict, indent=2)
    else:
        rendered = yaml.safe_dump(
            manifest_dict,
            sort_keys=False,
            default_flow_style=False,
            allow_unicode=False,
        )

    if stdout:
        typer.echo(rendered)
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered)
    typer.echo(f"Signed manifest -> {target}")


@secrets_app.command("rotate")
def secrets_rotate_command(
    ctx: typer.Context,
    keys: str | None = typer.Option(
        None,
        "--keys",
        help="Comma-separated secret IDs to invalidate.",
        metavar="ID1,ID2",
    ),
    provider: str | None = typer.Option(
        None,
        "--provider",
        help="Override secrets provider identifier when clearing cache.",
    ),
    all_keys: bool = typer.Option(
        False, "--all", help="Invalidate the entire cache for the configured provider."
    ),
    provider_cache: bool = typer.Option(
        True,
        "--provider-cache/--no-provider-cache",
        help="Also invalidate the provider adapter cache when available.",
    ),
) -> None:
    state = _state(ctx)
    parsed_keys = _parse_csv(keys)
    if not all_keys and not parsed_keys:
        raise typer.BadParameter("Specify --keys or --all when rotating secrets.")
    removed = asyncio.run(
        state.secrets.rotate(
            keys=None if all_keys else parsed_keys,
            provider=provider,
            include_provider_cache=provider_cache,
        )
    )
    typer.echo(f"Invalidated {removed} cached secret value(s).")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
