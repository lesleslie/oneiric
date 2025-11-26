from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from oneiric.adapters import AdapterMetadata, register_adapter_metadata
from oneiric.core.config import (
    SecretsHook,
    lifecycle_snapshot_path,
    load_settings,
    resolver_settings_from_config,
    runtime_health_path,
)
from oneiric.core.lifecycle import LifecycleManager
from oneiric.core.logging import configure_logging
from oneiric.core.resolution import Candidate, Resolver
from oneiric.core.runtime import run_sync
from oneiric.remote import sync_remote_manifest
from oneiric.runtime.orchestrator import RuntimeOrchestrator


@dataclass
class DemoAdapter:
    greeting: str

    def handle(self) -> str:
        return self.greeting


async def _async_main() -> None:
    configure_logging()
    settings = load_settings()
    resolver = Resolver(settings=resolver_settings_from_config(settings))
    register_adapter_metadata(
        resolver,
        package_name="oneiric.demo",
        package_path=str(Path(__file__).parent),
        adapters=[
            AdapterMetadata(
                category="demo",
                provider="builtin",
                stack_level=1,
                factory=lambda: DemoAdapter("hello from resolver"),
                description="Demo adapter registered via metadata helper.",
            )
        ],
    )
    lifecycle = LifecycleManager(
        resolver,
        status_snapshot_path=str(lifecycle_snapshot_path(settings)),
    )
    secrets = SecretsHook(lifecycle, settings.secrets)
    remote_result = await sync_remote_manifest(
        resolver,
        settings.remote,
        secrets=secrets,
    )
    orchestrator = RuntimeOrchestrator(
        settings,
        resolver,
        lifecycle,
        secrets,
        health_path=str(runtime_health_path(settings)),
    )
    async with orchestrator:
        adapter_handle = await orchestrator.adapter_bridge.use("demo")
        print(adapter_handle.instance.handle())

        if remote_result:
            remote_adapter = next(
                (entry.key for entry in remote_result.manifest.entries if entry.domain == "adapter"),
                None,
            )
            if remote_adapter:
                remote_handle = await orchestrator.adapter_bridge.use(remote_adapter)
                describe = getattr(remote_handle.instance, "describe", None)
                if callable(describe):
                    print(describe())

        resolver.register(
            Candidate(
                domain="service",
                key="status",
                provider="builtin",
                stack_level=1,
                factory=lambda: DemoService(),
            )
        )
        service_handle = await orchestrator.service_bridge.use("status")
        print(service_handle.instance.status())

        resolver.register(
            Candidate(
                domain="task",
                key="demo-task",
                provider="builtin",
                stack_level=1,
                factory=lambda: DemoTask(),
            )
        )
        task_handle = await orchestrator.task_bridge.use("demo-task")
        print(await task_handle.instance.run())

        resolver.register(
            Candidate(
                domain="event",
                key="demo.event",
                provider="builtin",
                stack_level=1,
                factory=lambda: DemoEventHandler(),
            )
        )
        event_handle = await orchestrator.event_bridge.use("demo.event")
        print(event_handle.instance.handle({"hello": "world"}))

        resolver.register(
            Candidate(
                domain="workflow",
                key="demo-workflow",
                provider="builtin",
                stack_level=1,
                factory=lambda: DemoWorkflow(),
            )
        )
        workflow_handle = await orchestrator.workflow_bridge.use("demo-workflow")
        print(workflow_handle.instance.execute())


@dataclass
class DemoService:
    def status(self) -> str:
        return "service-ok"


@dataclass
class DemoTask:
    async def run(self) -> str:
        return "task-run"


@dataclass
class DemoEventHandler:
    def handle(self, payload: dict) -> dict:
        return {"received": payload}


@dataclass
class DemoWorkflow:
    def execute(self) -> str:
        return "workflow-ok"


def main() -> None:
    run_sync(_async_main)


if __name__ == "__main__":
    main()
