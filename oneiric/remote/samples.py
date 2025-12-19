"""Sample factories used by remote manifest demos."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RemoteDemoAdapter:
    note: str

    def describe(self) -> str:
        return self.note


@dataclass
class RemoteDemoService:
    name: str = "remote-service"

    def status(self) -> str:
        return f"{self.name}-ok"


@dataclass
class RemoteDemoTask:
    name: str = "remote-task"

    async def run(self) -> str:
        return f"{self.name}-run"


@dataclass
class RemoteDemoEventHandler:
    name: str = "remote-event"

    async def handle(self, envelope) -> dict:
        return {
            "name": self.name,
            "topic": getattr(envelope, "topic", "unknown"),
            "payload": getattr(envelope, "payload", {}),
        }


@dataclass
class RemoteDemoWorkflow:
    name: str = "remote-workflow"

    def execute(self) -> str:
        return f"{self.name}-complete"


def demo_remote_adapter() -> RemoteDemoAdapter:
    return RemoteDemoAdapter(note="hello from remote manifest")


def demo_remote_service() -> RemoteDemoService:
    return RemoteDemoService()


def demo_remote_task() -> RemoteDemoTask:
    return RemoteDemoTask()


def demo_remote_event_handler() -> RemoteDemoEventHandler:
    return RemoteDemoEventHandler()


def demo_remote_workflow() -> RemoteDemoWorkflow:
    return RemoteDemoWorkflow()
