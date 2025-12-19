"""Event dispatch and hook routing action kit."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable, Iterable, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, ValidationError

from oneiric.actions.metadata import ActionMetadata
from oneiric.actions.payloads import normalize_payload
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class EventHookConfig(BaseModel):
    """Configuration for individual webhook/event hooks."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Hook identifier for logging/metrics.")
    url: AnyHttpUrl = Field(description="Hook endpoint URL.")
    method: str = Field(
        default="POST",
        description="HTTP method used when invoking the hook.",
    )
    headers: Mapping[str, str] = Field(
        default_factory=dict,
        description="Optional header overrides.",
    )
    enabled: bool = Field(
        default=True,
        description="When false, the hook is skipped.",
    )
    timeout_seconds: float | None = Field(
        default=None,
        gt=0,
        description="Per-request timeout override.",
    )
    secret: str | None = Field(
        default=None,
        description="Optional shared secret copied into the X-Hook-Secret header.",
    )


class EventDispatchSettings(BaseModel):
    """Settings for event dispatch hooks."""

    default_topic: str = Field(
        default="events.default",
        description="Topic used when payload omits one.",
    )
    default_source: str = Field(
        default="oneiric.runtime",
        description="Source string added to emitted events.",
    )
    max_hooks: int = Field(
        default=10,
        ge=0,
        description="Maximum hooks allowed per invocation.",
    )
    timeout_seconds: float = Field(
        default=5.0,
        gt=0,
        description="Base HTTP timeout when invoking hooks.",
    )
    concurrency: int = Field(
        default=5,
        ge=1,
        description="Concurrency limit for outbound hook requests.",
    )
    dry_run: bool = Field(
        default=True,
        description="When true, hooks are not invoked and responses are simulated.",
    )


class EventDispatchAction:
    """Action kit that emits structured events and optional hooks."""

    metadata = ActionMetadata(
        key="event.dispatch",
        provider="builtin-event-dispatch",
        factory="oneiric.actions.event:EventDispatchAction",
        description="Dispatches structured events and optional webhook hooks with concurrency limits",
        domains=["event", "task", "workflow"],
        capabilities=["dispatch", "emit", "hook"],
        stack_level=40,
        priority=370,
        source=CandidateSource.LOCAL_PKG,
        owner="Platform Core",
        requires_secrets=False,
        side_effect_free=False,
        settings_model=EventDispatchSettings,
    )

    def __init__(
        self,
        settings: EventDispatchSettings | None = None,
        *,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self._settings = settings or EventDispatchSettings()
        self._client_factory = client_factory
        self._logger = get_logger("action.event.dispatch")

    async def execute(self, payload: dict | None = None) -> dict:
        payload = normalize_payload(payload)
        topic = (payload.get("topic") or self._settings.default_topic).strip()
        if not topic:
            raise LifecycleError("event-dispatch-topic-required")
        raw_data = payload.get("payload") or payload.get("data") or {}
        if not isinstance(raw_data, Mapping):
            raise LifecycleError("event-dispatch-payload-invalid")
        metadata = payload.get("metadata") or {}
        if not isinstance(metadata, Mapping):
            raise LifecycleError("event-dispatch-metadata-invalid")
        hooks_value = payload.get("hooks") or payload.get("subscriptions") or []
        hooks = self._parse_hooks(hooks_value)
        dry_run = bool(payload.get("dry_run", self._settings.dry_run))
        event = {
            "event_id": payload.get("event_id") or uuid4().hex,
            "topic": topic,
            "source": payload.get("source") or self._settings.default_source,
            "timestamp": datetime.now(UTC).isoformat(),
            "payload": dict(raw_data),
            "metadata": dict(metadata),
        }
        hook_results = await self._process_hooks(event, hooks, dry_run)
        delivered = sum(1 for result in hook_results if result["status"] == "delivered")
        skipped = sum(1 for result in hook_results if result["status"] == "skipped")
        failed = sum(1 for result in hook_results if result["status"] == "failed")
        status = (
            "dispatched"
            if delivered
            else ("skipped" if hooks and skipped == len(hooks) else "queued")
        )
        self._logger.info(
            "event-action-dispatch",
            topic=topic,
            delivered=delivered,
            skipped=skipped,
            failed=failed,
            dry_run=dry_run,
            hook_count=len(hooks),
        )
        return {
            "status": status,
            "event": event,
            "hooks": hook_results,
            "delivered": delivered,
            "skipped": skipped,
            "failed": failed,
        }

    def _parse_hooks(self, hooks_value: Any) -> list[EventHookConfig]:
        if hooks_value in (None, "", ()):
            return []
        if not isinstance(hooks_value, Iterable):
            raise LifecycleError("event-dispatch-hooks-invalid")
        hooks: list[EventHookConfig] = []
        for raw_hook in hooks_value:
            try:
                hook = EventHookConfig.model_validate(raw_hook)
            except ValidationError as exc:  # pragma: no cover - invalid path
                raise LifecycleError("event-dispatch-hook-invalid") from exc
            hooks.append(hook)
        if len(hooks) > self._settings.max_hooks:
            raise LifecycleError("event-dispatch-hook-limit-exceeded")
        return hooks

    async def _process_hooks(
        self,
        event: Mapping[str, Any],
        hooks: list[EventHookConfig],
        dry_run: bool,
    ) -> list[dict[str, Any]]:
        if not hooks:
            return []
        results: list[dict[str, Any]] = []
        enabled_hooks = [hook for hook in hooks if hook.enabled]
        disabled_hooks = [hook for hook in hooks if not hook.enabled]
        for hook in disabled_hooks:
            results.append(self._hook_result(hook, status="skipped", reason="disabled"))
        if dry_run:
            for hook in enabled_hooks:
                results.append(
                    self._hook_result(hook, status="skipped", reason="dry-run")
                )
            return results
        semaphore = asyncio.Semaphore(max(1, self._settings.concurrency))
        async with self._acquire_client() as client:
            tasks = [
                self._dispatch_hook(client, semaphore, hook, event)
                for hook in enabled_hooks
            ]
            hook_outcomes = await asyncio.gather(*tasks)
            results.extend(hook_outcomes)
        return results

    @asynccontextmanager
    async def _acquire_client(self) -> AsyncIterator[httpx.AsyncClient]:
        if self._client_factory:
            client = self._client_factory()
        else:
            client = httpx.AsyncClient(timeout=self._settings.timeout_seconds)
        async with client:
            yield client

    async def _dispatch_hook(
        self,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
        hook: EventHookConfig,
        event: Mapping[str, Any],
    ) -> dict[str, Any]:
        async with semaphore:
            started = time.perf_counter()
            headers = {"content-type": "application/json"}
            headers.update({key: value for key, value in hook.headers.items()})
            if hook.secret:
                headers.setdefault("x-hook-secret", hook.secret)
            try:
                body = json.dumps(event, default=self._json_default).encode("utf-8")
            except (TypeError, ValueError) as exc:
                raise LifecycleError("event-dispatch-json-invalid") from exc
            try:
                response = await client.request(
                    hook.method.upper(),
                    str(hook.url),
                    content=body,
                    headers=headers,
                    timeout=hook.timeout_seconds or self._settings.timeout_seconds,
                )
                duration_ms = round((time.perf_counter() - started) * 1000, 2)
                if response.status_code < 400:
                    return self._hook_result(
                        hook,
                        status="delivered",
                        code=response.status_code,
                        duration_ms=duration_ms,
                    )
                reason = f"http {response.status_code}"
                return self._hook_result(
                    hook,
                    status="failed",
                    code=response.status_code,
                    duration_ms=duration_ms,
                    reason=reason,
                )
            except Exception as exc:  # pragma: no cover - http error path
                duration_ms = round((time.perf_counter() - started) * 1000, 2)
                return self._hook_result(
                    hook,
                    status="failed",
                    reason=str(exc),
                    duration_ms=duration_ms,
                )

    def _hook_result(
        self,
        hook: EventHookConfig,
        *,
        status: str,
        code: int | None = None,
        duration_ms: float | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        return {
            "name": hook.name,
            "status": status,
            "code": code,
            "duration_ms": duration_ms,
            "reason": reason,
        }

    def _json_default(self, value: Any) -> Any:  # pragma: no cover - fallback hooks
        if isinstance(value, (datetime,)):
            return value.isoformat()
        if isinstance(value, set):
            return list(value)
        return str(value)


__all__ = ["EventDispatchAction", "EventDispatchSettings", "EventHookConfig"]
