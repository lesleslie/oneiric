"""HTTP scheduler helpers for workflow queue integrations."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from oneiric.core.logging import get_logger
from oneiric.domains.workflows import WorkflowBridge

try:  # pragma: no cover - optional dependency guard
    from aiohttp import web
except ModuleNotFoundError:  # pragma: no cover - import deferred until runtime
    web = None  # type: ignore[assignment]


class WorkflowTaskProcessor:
    """Processes workflow tasks delivered via HTTP callbacks."""

    def __init__(self, workflow_bridge: WorkflowBridge) -> None:
        self._workflow_bridge = workflow_bridge
        self._logger = get_logger("runtime.scheduler.processor")

    async def process(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Execute the workflow run described by the payload."""

        workflow_key = payload.get("workflow")
        if not workflow_key or not isinstance(workflow_key, str):
            raise ValueError("workflow-key-missing")
        context = self._coerce_mapping(payload.get("context"))
        checkpoint = self._coerce_mapping(payload.get("checkpoint"))
        metadata = self._coerce_mapping(payload.get("metadata"))
        self._logger.info(
            "workflow-task-start",
            workflow=workflow_key,
            run_id=payload.get("run_id"),
        )
        run_result = await self._workflow_bridge.execute_dag(
            workflow_key,
            context=context,
            checkpoint=checkpoint,
            run_id=payload.get("run_id")
            if isinstance(payload.get("run_id"), str)
            else None,
        )
        resolved_run_id = run_result["run_id"]
        response = {
            "workflow": workflow_key,
            "run_id": resolved_run_id,
            "workflow_provider": payload.get("workflow_provider"),
            "metadata": metadata or {},
            "results": run_result["results"],
            "processed_at": datetime.now(UTC).isoformat(),
        }
        self._logger.info(
            "workflow-task-complete",
            workflow=workflow_key,
            run_id=resolved_run_id,
        )
        return response

    @staticmethod
    def _coerce_mapping(value: Any) -> dict[str, Any] | None:
        if isinstance(value, Mapping):
            return dict(value)
        return None


class SchedulerHTTPServer:
    """Minimal aiohttp server that handles Cloud Tasks HTTP callbacks."""

    def __init__(
        self,
        processor: WorkflowTaskProcessor,
        *,
        host: str = "0.0.0.0",
        port: int = 8080,
    ) -> None:
        if web is None:  # pragma: no cover - optional dependency guard
            raise RuntimeError(
                "aiohttp-not-installed: pip install 'oneiric[http-aiohttp]' "
                "to enable the scheduler HTTP server."
            )
        self._processor = processor
        self._host = host
        self._port = port
        self._logger = get_logger("runtime.scheduler.http")
        self._app = web.Application()
        self._app.router.add_get("/healthz", self._handle_health)
        self._app.router.add_post("/tasks/workflow", self._handle_workflow_task)
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    async def start(self) -> None:
        assert web is not None  # For typing
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self._host, self._port)
        await self._site.start()
        self._logger.info("scheduler-http-started", host=self._host, port=self._port)

    async def stop(self) -> None:
        if self._site:
            await self._site.stop()
            self._site = None
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
        self._logger.info("scheduler-http-stopped")

    async def _handle_health(self, _: web.Request):
        return web.json_response({"status": "ok"})

    async def _handle_workflow_task(self, request: web.Request):
        try:
            payload = await request.json()
        except Exception:
            return web.json_response(
                {"error": "invalid-json"}, status=400, dumps=_safe_dumps
            )
        if not isinstance(payload, Mapping):
            return web.json_response(
                {"error": "payload-must-be-object"}, status=400, dumps=_safe_dumps
            )
        try:
            result = await self._processor.process(payload)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400, dumps=_safe_dumps)
        except Exception as exc:  # pragma: no cover - runtime failures logged
            self._logger.error(
                "scheduler-http-error",
                error=str(exc),
            )
            return web.json_response(
                {"error": "workflow-execution-failed"}, status=500, dumps=_safe_dumps
            )
        return web.json_response(
            {"status": "completed", "result": result}, status=200, dumps=_safe_dumps
        )


def _safe_dumps(payload: Any) -> str:
    """aiohttp json response helper that avoids non-serializable errors."""
    import json

    return json.dumps(payload, default=str)


__all__ = ["SchedulerHTTPServer", "WorkflowTaskProcessor"]
