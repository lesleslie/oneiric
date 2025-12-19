"""Workflow automation action kits."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from oneiric.actions.metadata import ActionMetadata
from oneiric.actions.payloads import normalize_payload
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class WorkflowAuditSettings(BaseModel):
    """Settings for the workflow audit action kit."""

    channel: str = Field(
        default="workflow",
        description="Default audit channel name stored on every record.",
    )
    include_timestamp: bool = Field(
        default=True,
        description="Include an ISO-8601 timestamp on each emitted record.",
    )
    default_event: str = Field(
        default="workflow.audit",
        description="Fallback event name when payload omits 'event'.",
    )
    redact_fields: list[str] = Field(
        default_factory=lambda: ["secret", "token", "password", "key"],
        description="Fields that should be redacted in nested detail payloads.",
    )


class WorkflowAuditAction:
    """Action kit that records workflow audit/notification events."""

    metadata = ActionMetadata(
        key="workflow.audit",
        provider="builtin-workflow-audit",
        factory="oneiric.actions.workflow:WorkflowAuditAction",
        description="Structured workflow audit/notification helper with redaction",
        domains=["workflow", "task", "event"],
        capabilities=["audit-log", "notify", "redact"],
        stack_level=30,
        priority=425,
        source=CandidateSource.LOCAL_PKG,
        owner="Platform Core",
        requires_secrets=False,
        side_effect_free=True,
        settings_model=WorkflowAuditSettings,
    )

    def __init__(self, settings: WorkflowAuditSettings | None = None) -> None:
        self._settings = settings or WorkflowAuditSettings()
        self._logger = get_logger("action.workflow_audit")

    async def execute(self, payload: dict | None = None) -> dict:
        payload = normalize_payload(payload)
        event = payload.get("event") or self._settings.default_event
        if not isinstance(event, str) or not event:
            raise LifecycleError("workflow-audit-event-required")
        details = payload.get("details", {})
        if not isinstance(details, dict):
            raise LifecycleError("workflow-audit-details-invalid")
        extra_redact = payload.get("redact_fields")
        redact_fields: set[str] = set(self._settings.redact_fields)
        if isinstance(extra_redact, Iterable) and not isinstance(
            extra_redact, (str, bytes)
        ):
            redact_fields.update(str(v) for v in extra_redact)
        channel = payload.get("channel") or self._settings.channel
        include_timestamp = payload.get("include_timestamp")
        if include_timestamp is None:
            include_timestamp = self._settings.include_timestamp
        record = {
            "event": event,
            "channel": channel,
            "details": self._redact(details, redact_fields),
        }
        if include_timestamp:
            record["timestamp"] = datetime.now(UTC).isoformat()
        log_kwargs = {
            "audit_event": event,
            "channel": channel,
            "details": record["details"],
        }
        if "timestamp" in record:
            log_kwargs["timestamp"] = record["timestamp"]
        self._logger.info("workflow-action-audit", **log_kwargs)
        return {"status": "recorded"} | record

    def _redact(
        self, details: dict[str, Any], redact_fields: set[str]
    ) -> dict[str, Any]:
        sanitized: dict[str, Any] = {}
        for key, value in details.items():
            if key in redact_fields:
                sanitized[key] = "***"
                continue
            if isinstance(value, dict):
                sanitized[key] = self._redact(value, redact_fields)
            elif isinstance(value, list):
                sanitized[key] = [
                    self._redact(item, redact_fields)
                    if isinstance(item, dict)
                    else item
                    for item in value
                ]
            else:
                sanitized[key] = value
        return sanitized


class WorkflowNotifySettings(BaseModel):
    """Settings for workflow notification helpers."""

    default_channel: str = Field(
        default="workflow",
        description="Channel used when payload omits 'channel'.",
    )
    default_level: str = Field(
        default="info",
        description="Default severity level logged with notifications.",
    )
    default_recipients: list[str] = Field(
        default_factory=list,
        description="Recipients applied when payload omits 'recipients'.",
    )
    require_message: bool = Field(
        default=True,
        description="Require payloads to include a non-empty 'message'.",
    )


class WorkflowNotifyAction:
    """Action kit that emits structured workflow notifications."""

    metadata = ActionMetadata(
        key="workflow.notify",
        provider="builtin-workflow-notify",
        factory="oneiric.actions.workflow:WorkflowNotifyAction",
        description="Workflow notification helper that logs structured messages",
        domains=["workflow", "task", "event"],
        capabilities=["notify", "broadcast", "context"],
        stack_level=30,
        priority=420,
        source=CandidateSource.LOCAL_PKG,
        owner="Platform Core",
        requires_secrets=False,
        side_effect_free=True,
        settings_model=WorkflowNotifySettings,
    )

    _ALLOWED_LEVELS: tuple[str, ...] = ("debug", "info", "warning", "error", "critical")

    def __init__(self, settings: WorkflowNotifySettings | None = None) -> None:
        self._settings = settings or WorkflowNotifySettings()
        self._logger = get_logger("action.workflow_notify")

    async def execute(self, payload: dict | None = None) -> dict:
        payload = normalize_payload(payload)
        message = payload.get("message")
        if message is not None and not isinstance(message, str):
            raise LifecycleError("workflow-notify-message-invalid")
        if self._settings.require_message and not message:
            raise LifecycleError("workflow-notify-message-required")
        message = message or ""
        channel = payload.get("channel") or self._settings.default_channel
        if not isinstance(channel, str) or not channel:
            raise LifecycleError("workflow-notify-channel-invalid")
        level = self._normalize_level(payload.get("level"))
        recipients = self._normalize_recipients(payload.get("recipients"))
        context = payload.get("context")
        if context is not None and not isinstance(context, dict):
            raise LifecycleError("workflow-notify-context-invalid")
        record = {
            "message": message,
            "channel": channel,
            "level": level,
            "recipients": recipients,
        }
        if context:
            record["context"] = context
        self._logger.info(
            "workflow-action-notify",
            channel=channel,
            level=level,
            recipients=recipients,
            message=message,
            context=context,
        )
        return {"status": "queued" if recipients else "logged"} | record

    def _normalize_recipients(self, value: Any) -> list[str]:
        if value is None:
            return self._settings.default_recipients.copy()
        if isinstance(value, str):
            return [value]
        if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
            recipients = [str(item) for item in value]
            if not recipients:
                return []
            return recipients
        raise LifecycleError("workflow-notify-recipients-invalid")

    def _normalize_level(self, value: Any) -> str:
        candidate = (value or self._settings.default_level or "info").lower()
        if candidate not in self._ALLOWED_LEVELS:
            return "info"
        return candidate


class WorkflowStepSpec(BaseModel):
    """Declarative specification for a workflow step."""

    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(description="Unique step identifier")
    name: str = Field(description="Human-friendly name for the step")
    action: str = Field(description="Action key invoked by the orchestrator")
    depends_on: list[str] = Field(
        default_factory=list,
        description="Step identifiers that must complete before this step runs",
    )
    retry_attempts: int | None = Field(
        default=None,
        ge=0,
        description="Override retry attempts for the step (defaults to kit settings)",
    )
    timeout_seconds: float | None = Field(
        default=None,
        gt=0,
        description="Override timeout in seconds for the step",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary metadata stored alongside the step",
    )
    tags: list[str] = Field(
        default_factory=list, description="Tags applied to the step"
    )


class WorkflowDefinitionSpec(BaseModel):
    """Workflow definition accepted by the orchestrator action."""

    model_config = ConfigDict(extra="forbid")

    workflow_id: str = Field(description="Unique workflow identifier")
    name: str | None = Field(default=None, description="Human readable name")
    version: str | None = Field(default=None, description="Workflow version")
    description: str | None = Field(default=None, description="Optional description")
    start_paused: bool = Field(
        default=False,
        description="Produce a paused plan so external orchestrators can resume later",
    )
    steps: list[WorkflowStepSpec] = Field(description="Workflow steps")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Metadata copied verbatim to the plan",
    )
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Opaque context forwarded with the plan",
    )
    tags: list[str] = Field(default_factory=list, description="Workflow level tags")
    target_steps: list[str] | None = Field(
        default=None,
        description="Optional subset of steps to compile (dependencies included).",
    )


class WorkflowOrchestratorSettings(BaseModel):
    """Settings that control workflow orchestration planning."""

    max_parallel_steps: int = Field(
        default=4,
        ge=1,
        description="Maximum number of steps scheduled per parallel batch",
    )
    default_version: str = Field(
        default="1.0.0",
        description="Version value applied when definitions omit one",
    )
    default_retry_attempts: int = Field(
        default=3,
        ge=0,
        description="Retry attempts applied when a step omits overrides",
    )
    default_timeout_seconds: float = Field(
        default=300.0,
        gt=0,
        description="Timeout applied when a step does not supply one",
    )


class WorkflowOrchestratorAction:
    """Action kit that builds deterministic workflow execution plans."""

    metadata = ActionMetadata(
        key="workflow.orchestrate",
        provider="builtin-workflow-orchestrator",
        factory="oneiric.actions.workflow:WorkflowOrchestratorAction",
        description="Workflow planner producing versioned dependency graphs",
        domains=["workflow", "task", "event"],
        capabilities=["plan", "graph", "versioned"],
        stack_level=30,
        priority=430,
        source=CandidateSource.LOCAL_PKG,
        owner="Platform Core",
        requires_secrets=False,
        side_effect_free=True,
        settings_model=WorkflowOrchestratorSettings,
    )

    def __init__(self, settings: WorkflowOrchestratorSettings | None = None) -> None:
        self._settings = settings or WorkflowOrchestratorSettings()
        self._logger = get_logger("action.workflow_orchestrate")

    async def execute(self, payload: dict | None = None) -> dict:
        payload = normalize_payload(payload)
        definition = self._load_definition(payload)
        normalized_steps = self._normalize_steps(definition.steps)
        if definition.target_steps:
            normalized_steps = self._select_steps(
                normalized_steps, definition.target_steps
            )
        schedule = self._build_schedule(
            {step_id: data["depends_on"] for step_id, data in normalized_steps.items()}
        )
        from itertools import chain

        ordered_steps = list(chain.from_iterable(schedule))
        version = definition.version or self._settings.default_version
        result_steps = [
            {
                "step_id": step_id,
                "name": (data := normalized_steps[step_id])["spec"].name,
                "action": data["spec"].action,
                "depends_on": data["depends_on"],
                "retry_attempts": data["retry_attempts"],
                "retry_policy": {"attempts": data["retry_attempts"]},
                "timeout_seconds": data["timeout_seconds"],
                "metadata": data["spec"].metadata,
                "tags": data["spec"].tags,
            }
            for step_id in ordered_steps
        ]
        graph_dependencies = {
            step_id: data["depends_on"] for step_id, data in normalized_steps.items()
        }
        dependents: dict[str, list[str]] = {key: [] for key in normalized_steps}
        for step_id, deps in graph_dependencies.items():
            for dep in deps:
                dependents.setdefault(dep, []).append(step_id)
        plan_status = "paused" if definition.start_paused else "planned"
        batches_count = len(schedule)
        plan = {
            "status": plan_status,
            "workflow_id": definition.workflow_id,
            "name": definition.name or definition.workflow_id,
            "version": version,
            "run_token": uuid4().hex,
            "generated_at": datetime.now(UTC).isoformat(),
            "step_count": len(normalized_steps),
            "schedule": schedule,
            "ordered_steps": ordered_steps,
            "steps": result_steps,
            "graph": {
                "dependencies": graph_dependencies,
                "entry_steps": [
                    step for step, deps in graph_dependencies.items() if not deps
                ],
                "terminal_steps": [
                    step
                    for step, children in dependents.items()
                    if not children and step in normalized_steps
                ],
            },
            "context": definition.context,
            "metadata": definition.metadata,
            "tags": sorted(dict.fromkeys(definition.tags)),
            "stats": {
                "parallel_groups": batches_count,
                "max_group_size": max((len(batch) for batch in schedule), default=0),
                "default_retry_attempts": self._settings.default_retry_attempts,
                "default_timeout_seconds": self._settings.default_timeout_seconds,
            },
        }
        self._logger.info(
            "workflow-action-orchestrate",
            workflow_id=definition.workflow_id,
            version=version,
            steps=len(normalized_steps),
            parallel_groups=batches_count,
            start_paused=definition.start_paused,
        )
        return plan

    def _load_definition(self, payload: dict) -> WorkflowDefinitionSpec:
        try:
            definition = WorkflowDefinitionSpec.model_validate(payload)
        except ValidationError as exc:  # pragma: no cover - defensive guard
            raise LifecycleError("workflow-orchestrate-invalid-payload") from exc
        if not definition.steps:
            raise LifecycleError("workflow-orchestrate-steps-required")
        return definition

    def _normalize_steps(
        self, steps: list[WorkflowStepSpec]
    ) -> dict[str, dict[str, Any]]:
        normalized: dict[str, dict[str, Any]] = {}
        for step in steps:
            self._validate_step(step, normalized)
            normalized[step.step_id] = self._build_normalized_step(step)
        self._validate_dependencies(normalized)
        return normalized

    def _select_steps(
        self, normalized: dict[str, dict[str, Any]], targets: list[str]
    ) -> dict[str, dict[str, Any]]:
        missing = [step for step in targets if step not in normalized]
        if missing:
            raise LifecycleError("workflow-orchestrate-target-missing")
        keep: set[str] = set()

        def _visit(step_id: str) -> None:
            if step_id in keep:
                return
            keep.add(step_id)
            for dep in normalized[step_id]["depends_on"]:
                _visit(dep)

        for step_id in targets:
            _visit(step_id)

        return {
            step_id: data for step_id, data in normalized.items() if step_id in keep
        }

    def _validate_step(
        self, step: WorkflowStepSpec, existing: dict[str, dict[str, Any]]
    ) -> None:
        """Validate step before normalization."""
        if step.step_id in existing:
            raise LifecycleError("workflow-orchestrate-duplicate-step")
        depends_on = self._dedupe_dependencies(step.depends_on)
        if step.step_id in depends_on:
            raise LifecycleError("workflow-orchestrate-self-dependency")

    def _build_normalized_step(self, step: WorkflowStepSpec) -> dict[str, Any]:
        """Build normalized step dictionary."""
        return {
            "spec": step,
            "depends_on": self._dedupe_dependencies(step.depends_on),
            "retry_attempts": (
                step.retry_attempts
                if step.retry_attempts is not None
                else self._settings.default_retry_attempts
            ),
            "timeout_seconds": (
                step.timeout_seconds
                if step.timeout_seconds is not None
                else self._settings.default_timeout_seconds
            ),
        }

    def _validate_dependencies(self, normalized: dict[str, dict[str, Any]]) -> None:
        """Validate all dependencies exist."""
        for data in normalized.values():
            for dep in data["depends_on"]:
                if dep not in normalized:
                    raise LifecycleError("workflow-orchestrate-missing-dependency")

    def _dedupe_dependencies(self, deps: Iterable[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for dep in deps:
            if not dep or dep in seen:
                continue
            seen.add(dep)
            cleaned.append(dep)
        return cleaned

    def _build_schedule(self, dependencies: dict[str, list[str]]) -> list[list[str]]:
        graph = {step_id: set(deps) for step_id, deps in dependencies.items()}
        ready = sorted(step_id for step_id, deps in graph.items() if not deps)
        schedule: list[list[str]] = []
        processed: list[str] = []
        max_parallel = self._settings.max_parallel_steps
        while ready:
            batch: list[str] = []
            while ready and len(batch) < max_parallel:
                batch.append(ready.pop(0))
            schedule.append(batch)
            processed.extend(batch)
            completed = set(batch)
            for step_id, deps in graph.items():
                if step_id in completed:
                    continue
                deps.difference_update(completed)
            newly_ready = [
                step_id
                for step_id, deps in graph.items()
                if step_id not in processed and not deps and step_id not in ready
            ]
            ready.extend(sorted(newly_ready))
        if len(processed) != len(graph):
            raise LifecycleError("workflow-orchestrate-cycle-detected")
        return schedule


class WorkflowRetrySettings(BaseModel):
    """Settings for workflow retry helpers."""

    max_attempts: int = Field(
        default=3, ge=1, description="Total attempts before exhaust"
    )
    base_delay_seconds: float = Field(
        default=1.0, ge=0.0, description="Initial delay in seconds"
    )
    multiplier: float = Field(
        default=2.0, ge=1.0, description="Exponential multiplier applied per attempt"
    )
    max_delay_seconds: float = Field(
        default=60.0, ge=0.0, description="Upper bound for computed delay"
    )
    jitter: float = Field(
        default=0.1, ge=0.0, description="Deterministic jitter factor (0-1)"
    )


class WorkflowRetryAction:
    """Action kit that computes retry/backoff schedules for workflows."""

    metadata = ActionMetadata(
        key="workflow.retry",
        provider="builtin-workflow-retry",
        factory="oneiric.actions.workflow:WorkflowRetryAction",
        description="Workflow retry helper providing deterministic backoff guidance",
        domains=["workflow", "task", "event"],
        capabilities=["retry", "backoff", "control"],
        stack_level=30,
        priority=415,
        source=CandidateSource.LOCAL_PKG,
        owner="Platform Core",
        requires_secrets=False,
        side_effect_free=True,
        settings_model=WorkflowRetrySettings,
    )

    def __init__(self, settings: WorkflowRetrySettings | None = None) -> None:
        self._settings = settings or WorkflowRetrySettings()
        self._logger = get_logger("action.workflow_retry")

    async def execute(self, payload: dict | None = None) -> dict:
        payload = normalize_payload(payload)
        attempt = payload.get("attempt", 0)
        if not isinstance(attempt, int) or attempt < 0:
            raise LifecycleError("workflow-retry-attempt-invalid")
        max_attempts = payload.get("max_attempts", self._settings.max_attempts)
        if not isinstance(max_attempts, int) or max_attempts < 1:
            raise LifecycleError("workflow-retry-max-attempts-invalid")
        base_delay = float(
            payload.get("base_delay_seconds", self._settings.base_delay_seconds)
        )
        if base_delay < 0:
            raise LifecycleError("workflow-retry-base-delay-invalid")
        multiplier = float(payload.get("multiplier", self._settings.multiplier))
        if multiplier < 1:
            raise LifecycleError("workflow-retry-multiplier-invalid")
        max_delay = float(
            payload.get("max_delay_seconds", self._settings.max_delay_seconds)
        )
        if max_delay < 0:
            raise LifecycleError("workflow-retry-max-delay-invalid")
        jitter = float(payload.get("jitter", self._settings.jitter))
        jitter = max(0.0, min(jitter, 1.0))
        should_retry = attempt < max_attempts
        record = {
            "attempt": attempt,
            "max_attempts": max_attempts,
            "status": "exhausted",
        }
        if not should_retry:
            self._logger.info("workflow-action-retry-exhausted", **record)
            return record
        next_attempt = attempt + 1
        delay = base_delay * (multiplier**attempt)
        delay = min(delay, max_delay)
        delay = delay * (1 + (0.25 if attempt % 2 == 0 else 0.15) * jitter)
        record.update(
            {
                "status": "scheduled",
                "next_attempt": next_attempt,
                "delay_seconds": delay,
            }
        )
        self._logger.info(
            "workflow-action-retry",
            attempt=attempt,
            next_attempt=next_attempt,
            delay_seconds=delay,
            max_attempts=max_attempts,
        )
        return record
