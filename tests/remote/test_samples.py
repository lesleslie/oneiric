"""Tests for remote manifest sample factories."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from oneiric.remote import samples


@dataclass
class DemoEnvelope:
    topic: str | None = None
    payload: dict | None = None


class EmptyEnvelope:
    pass


def test_demo_remote_adapter_describes_note():
    adapter = samples.demo_remote_adapter()

    assert adapter.note == "hello from remote manifest"
    assert adapter.describe() == "hello from remote manifest"


def test_demo_remote_service_status():
    service = samples.demo_remote_service()

    assert service.name == "remote-service"
    assert service.status() == "remote-service-ok"


@pytest.mark.asyncio
async def test_demo_remote_task_run():
    task = samples.demo_remote_task()

    assert task.name == "remote-task"
    assert await task.run() == "remote-task-run"


@pytest.mark.asyncio
async def test_demo_remote_event_handler_payload_defaults():
    handler = samples.demo_remote_event_handler()

    response = await handler.handle(EmptyEnvelope())

    assert response["name"] == "remote-event"
    assert response["topic"] == "unknown"
    assert response["payload"] == {}


@pytest.mark.asyncio
async def test_demo_remote_event_handler_payload_values():
    handler = samples.demo_remote_event_handler()

    response = await handler.handle(DemoEnvelope(topic="alerts", payload={"ok": True}))

    assert response["topic"] == "alerts"
    assert response["payload"] == {"ok": True}


def test_demo_remote_workflow_execute():
    workflow = samples.demo_remote_workflow()

    assert workflow.name == "remote-workflow"
    assert workflow.execute() == "remote-workflow-complete"
