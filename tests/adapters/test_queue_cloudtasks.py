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


# ---------------------------------------------------------------------------
# Tests — coverage gaps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cloudtasks_cleanup() -> None:
    """cleanup() awaits close() and nils _client (lines 82-87)."""
    client = _FakeTasksClient()
    adapter = CloudTasksQueueAdapter(
        settings=CloudTasksQueueSettings(
            project_id="p", location="us-central1", queue="q",
            http_target_url="https://example.com/run",
        ),
        client=client,
    )
    await adapter.init()
    adapter._owns_client = True  # force cleanup to run close()
    await adapter.cleanup()
    assert adapter._client is None


@pytest.mark.asyncio
async def test_cloudtasks_pending() -> None:
    """pending() returns queue path info (lines 117-118)."""
    client = _FakeTasksClient()
    adapter = CloudTasksQueueAdapter(
        settings=CloudTasksQueueSettings(
            project_id="p", location="us-central1", queue="q",
            http_target_url="https://example.com/run",
        ),
        client=client,
    )
    await adapter.init()
    result = await adapter.pending()
    assert len(result) == 1 and "queue" in result[0]


@pytest.mark.asyncio
async def test_cloudtasks_ensure_queue_path_raises() -> None:
    """_ensure_queue_path raises LifecycleError when queue_path is not set (line 156)."""
    from oneiric.core.lifecycle import LifecycleError

    adapter = CloudTasksQueueAdapter(
        settings=CloudTasksQueueSettings(
            project_id="p", location="l", queue="q",
            http_target_url="https://example.com/run",
        ),
        client=_FakeTasksClient(),
    )
    with pytest.raises(LifecycleError, match="cloudtasks-queue-path-missing"):
        adapter._ensure_queue_path()


@pytest.mark.asyncio
async def test_cloudtasks_task_payload_with_service_account() -> None:
    """_build_task_payload includes oidc_token when service_account_email is set (line 131)."""
    client = _FakeTasksClient()
    adapter = CloudTasksQueueAdapter(
        settings=CloudTasksQueueSettings(
            project_id="p", location="l", queue="q",
            http_target_url="https://example.com/run",
            service_account_email="sa@proj.iam.gserviceaccount.com",
        ),
        client=client,
    )
    payload = adapter._build_task_payload({"k": "v"})
    assert "oidc_token" in payload["http_request"]
    assert payload["http_request"]["oidc_token"]["service_account_email"] == "sa@proj.iam.gserviceaccount.com"


@pytest.mark.asyncio
async def test_cloudtasks_task_payload_with_dispatch_deadline() -> None:
    """_build_task_payload includes dispatch_deadline when set (line 140)."""
    adapter = CloudTasksQueueAdapter(
        settings=CloudTasksQueueSettings(
            project_id="p", location="l", queue="q",
            http_target_url="https://example.com/run",
            dispatch_deadline_seconds=30,
        ),
        client=_FakeTasksClient(),
    )
    payload = adapter._build_task_payload({"k": "v"})
    assert payload["dispatch_deadline"]["seconds"] == 30


@pytest.mark.asyncio
async def test_cloudtasks_task_payload_with_schedule_offset() -> None:
    """_build_task_payload includes schedule_time when schedule_offset_seconds > 0 (lines 146-147)."""
    adapter = CloudTasksQueueAdapter(
        settings=CloudTasksQueueSettings(
            project_id="p", location="l", queue="q",
            http_target_url="https://example.com/run",
            schedule_offset_seconds=60,
        ),
        client=_FakeTasksClient(),
    )
    payload = adapter._build_task_payload({"k": "v"})
    assert "schedule_time" in payload
    assert payload["schedule_time"]["seconds"] > 0


@pytest.mark.asyncio
async def test_cloudtasks_init_creates_client_from_sdk(monkeypatch) -> None:
    """init() creates CloudTasksAsyncClient from google.cloud.tasks_v2 when client is None (lines 68-73)."""
    import sys
    import types

    created: list[object] = []

    class FakeClient(_FakeTasksClient):
        pass

    fake_client_instance = FakeClient()

    class FakeCloudTasksAsyncClient:
        def __init__(self) -> None:
            created.append(self)

        def queue_path(self, project_id: str, location: str, queue: str) -> str:
            return f"projects/{project_id}/locations/{location}/queues/{queue}"

        async def get_queue(self, name: str) -> dict:
            return {"name": name}

        async def close(self) -> None:
            pass

    fake_tasks_v2 = types.ModuleType("tasks_v2")
    fake_tasks_v2.CloudTasksAsyncClient = FakeCloudTasksAsyncClient  # type: ignore[attr-defined]

    fake_google_cloud = types.ModuleType("google.cloud")
    fake_google_cloud.tasks_v2 = fake_tasks_v2  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "google", types.ModuleType("google"))
    monkeypatch.setitem(sys.modules, "google.cloud", fake_google_cloud)
    monkeypatch.setitem(sys.modules, "google.cloud.tasks_v2", fake_tasks_v2)

    adapter = CloudTasksQueueAdapter(
        settings=CloudTasksQueueSettings(
            project_id="p", location="l", queue="q",
            http_target_url="https://example.com/run",
        ),
        # No client — triggers SDK import
    )
    await adapter.init()
    assert len(created) == 1
    assert adapter._queue_path is not None
