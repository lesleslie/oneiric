from types import SimpleNamespace

import pytest

from oneiric.adapters.queue.cloudtasks import (
    CloudTasksQueueAdapter,
    CloudTasksQueueSettings,
)


class _FakeTasksClient:
    def __init__(self) -> None:
        self.created: list[tuple[str, dict]] = []
        self.last_queue: str | None = None

    def queue_path(self, project_id: str, location: str, queue: str) -> str:
        return f"projects/{project_id}/locations/{location}/queues/{queue}"

    async def create_task(self, parent: str, task: dict) -> SimpleNamespace:
        self.created.append((parent, task))
        return SimpleNamespace(name=f"{parent}/tasks/task-1")

    async def get_queue(self, name: str) -> dict:
        self.last_queue = name
        return {"name": name}

    async def close(self) -> None:  # pragma: no cover - defensive close path
        pass


@pytest.mark.asyncio
async def test_cloudtasks_enqueue_builds_payload() -> None:
    client = _FakeTasksClient()
    adapter = CloudTasksQueueAdapter(
        settings=CloudTasksQueueSettings(
            project_id="demo",
            location="us-central1",
            queue="orchestrator",
            http_target_url="https://example.com/run",
        ),
        client=client,
    )

    await adapter.init()
    task_name = await adapter.enqueue({"dag": "compile"})

    assert task_name.endswith("task-1")
    assert len(client.created) == 1
    payload = client.created[0][1]
    assert payload["http_request"]["url"] == "https://example.com/run"
    assert payload["http_request"]["headers"]["Content-Type"] == "application/json"


@pytest.mark.asyncio
async def test_cloudtasks_health_calls_get_queue() -> None:
    client = _FakeTasksClient()
    adapter = CloudTasksQueueAdapter(
        settings=CloudTasksQueueSettings(
            project_id="demo",
            location="us-central1",
            queue="orchestrator",
            http_target_url="https://example.com/run",
        ),
        client=client,
    )

    await adapter.init()
    healthy = await adapter.health()

    assert healthy is True
    assert client.last_queue is not None
