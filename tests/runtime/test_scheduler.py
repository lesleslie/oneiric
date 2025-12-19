"""Tests for the scheduler HTTP helpers."""

from __future__ import annotations

import socket
from typing import Any

import aiohttp
import pytest

from oneiric.runtime.scheduler import SchedulerHTTPServer, WorkflowTaskProcessor


class FakeWorkflowBridge:
    """Fake bridge recording execute calls."""

    def __init__(self) -> None:
        self.calls: list[
            tuple[
                str,
                dict[str, Any] | None,
                dict[str, Any] | None,
                str | None,
            ]
        ] = []

    async def execute_dag(
        self,
        workflow_key: str,
        *,
        context: dict[str, Any] | None,
        checkpoint: dict[str, Any] | None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append((workflow_key, context, checkpoint, run_id))
        return {
            "run_id": run_id or "generated-run-id",
            "results": {
                "workflow": workflow_key,
                "context": context or {},
                "checkpoint": checkpoint or {},
            },
        }


@pytest.fixture()
def unused_tcp_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    _, port = sock.getsockname()
    sock.close()
    return port


@pytest.mark.asyncio
async def test_workflow_task_processor_executes_workflow():
    bridge = FakeWorkflowBridge()
    processor = WorkflowTaskProcessor(bridge)  # type: ignore[arg-type]
    payload = {
        "workflow": "demo",
        "run_id": "abc123",
        "context": {"tenant": "demo"},
        "checkpoint": {"step": "extract"},
    }

    result = await processor.process(payload)

    assert result["workflow"] == "demo"
    assert result["run_id"] == "abc123"
    assert bridge.calls == [
        ("demo", {"tenant": "demo"}, {"step": "extract"}, "abc123"),
    ]


@pytest.mark.asyncio
async def test_scheduler_http_server_handles_request(unused_tcp_port: int):
    bridge = FakeWorkflowBridge()
    processor = WorkflowTaskProcessor(bridge)  # type: ignore[arg-type]
    server = SchedulerHTTPServer(
        processor,
        host="127.0.0.1",
        port=unused_tcp_port,
    )
    await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            resp = await session.post(
                f"http://127.0.0.1:{unused_tcp_port}/tasks/workflow",
                json={"workflow": "demo", "context": {"tenant": "cloud"}},
            )
            assert resp.status == 200
            payload = await resp.json()
            assert payload["status"] == "completed"
            assert payload["result"]["results"]["workflow"] == "demo"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_scheduler_http_server_validates_payload(unused_tcp_port: int):
    bridge = FakeWorkflowBridge()
    processor = WorkflowTaskProcessor(bridge)  # type: ignore[arg-type]
    server = SchedulerHTTPServer(
        processor,
        host="127.0.0.1",
        port=unused_tcp_port,
    )
    await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            resp = await session.post(
                f"http://127.0.0.1:{unused_tcp_port}/tasks/workflow",
                json={"invalid": True},
            )
            assert resp.status == 400
    finally:
        await server.stop()
