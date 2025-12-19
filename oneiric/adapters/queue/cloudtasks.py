"""Google Cloud Tasks queue adapter."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import AnyHttpUrl, BaseModel, Field

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.client_mixins import EnsureClientMixin
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class CloudTasksQueueSettings(BaseModel):
    """Settings for the Cloud Tasks adapter."""

    project_id: str
    location: str
    queue: str
    http_target_url: AnyHttpUrl = Field(
        description="Target URL invoked when the task executes."
    )
    http_method: str = Field(default="POST")
    service_account_email: str | None = None
    oidc_audience: str | None = None
    default_headers: dict[str, str] = Field(default_factory=dict)
    dispatch_deadline_seconds: int | None = Field(default=None, ge=1)
    schedule_offset_seconds: int = Field(
        default=0,
        ge=0,
        description="Optional offset applied to every task schedule time.",
    )


class CloudTasksQueueAdapter(EnsureClientMixin):
    """Adapter that enqueues HTTP tasks against Cloud Tasks queues."""

    metadata = AdapterMetadata(
        category="queue",
        provider="cloudtasks",
        factory="oneiric.adapters.queue.cloudtasks:CloudTasksQueueAdapter",
        capabilities=["queue", "scheduler"],
        stack_level=40,
        priority=400,
        source=CandidateSource.LOCAL_PKG,
        owner="Platform Core",
        requires_secrets=True,
        settings_model=CloudTasksQueueSettings,
    )

    def __init__(
        self,
        settings: CloudTasksQueueSettings,
        *,
        client: Any | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._owns_client = client is None
        self._queue_path: str | None = None
        self._logger = get_logger("adapter.queue.cloudtasks").bind(
            domain="adapter",
            key="queue",
            provider="cloudtasks",
        )

    async def init(self) -> None:
        if self._client is None:
            try:
                from google.cloud import tasks_v2
            except ModuleNotFoundError as exc:  # pragma: no cover - dependency guard
                raise LifecycleError("google-cloud-tasks-missing") from exc
            self._client = tasks_v2.CloudTasksAsyncClient()
            self._owns_client = True
        self._queue_path = self._client.queue_path(
            self._settings.project_id,
            self._settings.location,
            self._settings.queue,
        )
        self._logger.info("cloudtasks-adapter-init", queue=self._queue_path)

    async def cleanup(self) -> None:
        if self._client and self._owns_client:
            close = getattr(self._client, "close", None)
            if close:
                await close()
        self._client = None
        self._logger.info("cloudtasks-adapter-cleanup")

    async def health(self) -> bool:
        client = self._ensure_client("cloudtasks-client-not-initialized")
        try:
            queue_path = self._ensure_queue_path()
            await client.get_queue(name=queue_path)
            return True
        except Exception as exc:  # pragma: no cover - upstream exceptions
            self._logger.warning("cloudtasks-health-failed", error=str(exc))
            return False

    async def enqueue(self, data: Mapping[str, Any]) -> str:
        client = self._ensure_client("cloudtasks-client-not-initialized")
        queue_path = self._ensure_queue_path()
        payload = self._build_task_payload(data)
        response = await client.create_task(parent=queue_path, task=payload)
        return getattr(response, "name", "cloudtasks-task")

    async def read(
        self, **_: Any
    ) -> list[dict[str, Any]]:  # pragma: no cover - explicit not supported
        raise LifecycleError("cloudtasks-read-not-supported")

    async def ack(
        self, *_: Any, **__: Any
    ) -> int:  # pragma: no cover - explicit not supported
        raise LifecycleError("cloudtasks-ack-not-supported")

    async def pending(self, **_: Any) -> list[dict[str, Any]]:
        queue_path = self._ensure_queue_path()
        return [{"queue": queue_path}]

    def _build_task_payload(self, data: Mapping[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        headers.update(self._settings.default_headers)

        http_request: dict[str, Any] = {
            "http_method": self._settings.http_method,
            "url": str(self._settings.http_target_url),
            "headers": headers,
            "body": json.dumps(data).encode("utf-8"),
        }
        if self._settings.service_account_email:
            http_request["oidc_token"] = {
                "service_account_email": self._settings.service_account_email,
                "audience": self._settings.oidc_audience
                or str(self._settings.http_target_url),
            }

        task: dict[str, Any] = {"http_request": http_request}

        if self._settings.dispatch_deadline_seconds:
            task["dispatch_deadline"] = {
                "seconds": self._settings.dispatch_deadline_seconds,
            }

        total_offset = self._settings.schedule_offset_seconds
        if total_offset > 0:
            execute_at = datetime.now(UTC) + timedelta(seconds=total_offset)
            task["schedule_time"] = {
                "seconds": int(execute_at.timestamp()),
                "nanos": execute_at.microsecond * 1000,
            }

        return task

    def _ensure_queue_path(self) -> str:
        if not self._queue_path:
            raise LifecycleError("cloudtasks-queue-path-missing")
        return self._queue_path
