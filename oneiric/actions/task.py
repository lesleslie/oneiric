"""Task scheduling action kit."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError

from oneiric.actions.metadata import ActionMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class TaskScheduleSettings(BaseModel):
    """Settings controlling schedule planning defaults."""

    default_queue: str = Field(
        default="default",
        description="Queue assigned when payload omits 'queue'.",
    )
    default_priority: int = Field(
        default=100,
        ge=0,
        description="Default priority for scheduled tasks.",
    )
    timezone: str = Field(
        default="UTC",
        description="Timezone applied to schedules lacking explicit tz offsets.",
    )
    max_preview_runs: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Maximum number of future runs returned per invocation.",
    )


class TaskSchedulePayload(BaseModel):
    """Typed payload for cron/interval scheduling."""

    model_config = ConfigDict(extra="forbid")

    task_type: str = Field(description="Task type to enqueue when the rule fires.")
    queue: str | None = Field(
        default=None,
        validation_alias=AliasChoices("queue", "queue_name"),
    )
    name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("name", "rule_name"),
    )
    rule_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("rule_id", "id"),
    )
    payload: Mapping[str, Any] = Field(
        default_factory=dict,
        description="Payload injected into scheduled tasks.",
    )
    priority: int | None = Field(
        default=None,
        ge=0,
        description="Optional priority overriding the default.",
    )
    cron_expression: str | None = Field(
        default=None,
        validation_alias=AliasChoices("cron_expression", "cron"),
        description="Cron (minute hour day month weekday) string.",
    )
    interval_seconds: float | None = Field(
        default=None,
        gt=0,
        validation_alias=AliasChoices("interval_seconds", "interval", "every_seconds"),
        description="Interval cadence in seconds.",
    )
    start_time: datetime | None = Field(
        default=None,
        description="Optional start boundary.",
    )
    end_time: datetime | None = Field(
        default=None,
        description="Optional end boundary.",
    )
    max_runs: int | None = Field(
        default=None,
        gt=0,
        description="Optional cap on total executions.",
    )
    preview_runs: int | None = Field(
        default=None,
        ge=0,
        description="Override for number of runs returned.",
    )
    timezone: str | None = Field(
        default=None,
        description="Custom timezone identifier.",
    )
    tags: Mapping[str, Any] = Field(
        default_factory=dict,
        description="Custom tags appended to the scheduled task.",
    )


@dataclass(slots=True)
class _ScheduleRule:
    """Runtime representation of a schedule definition."""

    rule_id: str
    name: str
    task_type: str
    queue: str
    payload: dict[str, Any]
    priority: int
    cron_expression: str | None
    interval_seconds: float | None
    start_time: datetime | None
    end_time: datetime | None
    max_runs: int | None
    tags: dict[str, str]


class _CronExpression:
    """Minimal cron parser that supports */step, ranges, and lists."""

    _MAX_SEARCH_MINUTES = 525_600  # Prevent runaway loops (≈1 year)

    def __init__(self, expression: str) -> None:
        parts = expression.split()
        if len(parts) != 5:
            raise ValueError("Cron expressions require five fields (m h dom mon dow)")
        minute, hour, dom, month, dow = parts
        self._minutes = self._parse_field(minute, 0, 59)
        self._hours = self._parse_field(hour, 0, 23)
        self._days = self._parse_field(dom, 1, 31)
        self._months = self._parse_field(month, 1, 12)
        # allow 0-7 with both representing Sunday
        self._weekdays = self._parse_field(dow, 0, 7, wrap_sunday=True)

    def next_after(self, current: datetime) -> datetime:
        candidate = current.replace(second=0, microsecond=0) + timedelta(minutes=1)
        for _ in range(self._MAX_SEARCH_MINUTES):
            if self._matches(candidate):
                return candidate
            candidate += timedelta(minutes=1)
        msg = "Unable to compute next cron occurrence within search window"
        raise LifecycleError(msg)

    def _matches(self, candidate: datetime) -> bool:
        if not self._match_field(self._minutes, candidate.minute):
            return False
        if not self._match_field(self._hours, candidate.hour):
            return False
        if not self._match_field(self._months, candidate.month):
            return False
        dom_match = self._match_field(self._days, candidate.day)
        dow_value = (candidate.weekday() + 1) % 7
        dow_match = self._match_field(self._weekdays, dow_value)
        if self._days is not None and self._weekdays is not None:
            return dom_match or dow_match
        if self._days is not None and not dom_match:
            return False
        if self._weekdays is not None and not dow_match:
            return False
        return True

    def _match_field(self, values: list[int] | None, candidate: int) -> bool:
        return values is None or candidate in values

    def _parse_field(
        self,
        token: str,
        minimum: int,
        maximum: int,
        *,
        wrap_sunday: bool = False,
    ) -> list[int] | None:
        value = token.strip()
        if value in {"*", "?", ""}:
            return None
        allowed: set[int] = set()
        for part in value.split(","):
            step = 1
            range_expr = part
            if "/" in part:
                base, step_text = part.split("/", 1)
                range_expr = base or "*"
                if not step_text:
                    msg = f"Invalid cron step: {part}"
                    raise ValueError(msg)
                step = int(step_text)
                if step <= 0:
                    raise ValueError("Cron step must be positive")
            if range_expr in {"*", "?"}:
                start, end = minimum, maximum
            elif "-" in range_expr:
                start_text, end_text = range_expr.split("-", 1)
                start = int(start_text)
                end = int(end_text)
            else:
                start = end = int(range_expr)
            if wrap_sunday:
                if start < minimum and start != 7:
                    raise ValueError("Day-of-week values must be between 0 and 7")
                if end > maximum and end != 7:
                    raise ValueError("Day-of-week values must be between 0 and 7")
            else:
                if start < minimum or end > maximum:
                    msg = f"Cron value {range_expr} outside bounds {minimum}-{maximum}"
                    raise ValueError(msg)
            if start > end:
                raise ValueError("Cron range start cannot be greater than end")
            for candidate in range(start, end + 1, step):
                allowed.add(self._normalize_weekday(candidate) if wrap_sunday else candidate)
        return sorted(allowed)

    def _normalize_weekday(self, value: int) -> int:
        if value == 7:
            return 0
        return value


class TaskScheduleAction:
    """Action kit that plans cron/interval task schedules."""

    metadata = ActionMetadata(
        key="task.schedule",
        provider="builtin-task-schedule",
        factory="oneiric.actions.task:TaskScheduleAction",
        description="Builds cron/interval schedules for resolver-managed task runners",
        domains=["task", "workflow"],
        capabilities=["schedule", "plan", "cron"],
        stack_level=45,
        priority=360,
        source=CandidateSource.LOCAL_PKG,
        owner="Platform Core",
        requires_secrets=False,
        side_effect_free=True,
        settings_model=TaskScheduleSettings,
    )

    def __init__(self, settings: TaskScheduleSettings | None = None) -> None:
        self._settings = settings or TaskScheduleSettings()
        self._logger = get_logger("action.task.schedule")

    async def execute(self, payload: dict | None = None) -> dict:
        payload_data = payload or {}
        try:
            request = TaskSchedulePayload.model_validate(payload_data)
        except ValidationError as exc:
            raise LifecycleError("task-schedule-payload-invalid") from exc
        if not request.cron_expression and request.interval_seconds is None:
            raise LifecycleError("task-schedule-timing-required")
        timezone_name = request.timezone or self._settings.timezone
        tzinfo = self._resolve_timezone(timezone_name)
        rule = self._build_rule(request, tzinfo)
        preview_count = self._resolve_preview_count(request.preview_runs)
        now = datetime.now(tz=tzinfo)
        base_time = max(rule.start_time or now, now)
        schedule = self._compute_schedule(rule, base_time, preview_count)
        self._logger.info(
            "task-action-schedule",
            rule_id=rule.rule_id,
            task_type=rule.task_type,
            queue=rule.queue,
            cron=rule.cron_expression,
            interval=rule.interval_seconds,
            preview=len(schedule["upcoming_runs"]),
        )
        return schedule

    def _resolve_timezone(self, name: str) -> ZoneInfo:
        try:
            return ZoneInfo(name)
        except Exception as exc:  # pragma: no cover - invalid timezone path
            raise LifecycleError("task-schedule-timezone-invalid") from exc

    def _build_rule(self, request: TaskSchedulePayload, tzinfo: ZoneInfo) -> _ScheduleRule:
        cron_expression = request.cron_expression
        if cron_expression:
            try:
                _CronExpression(cron_expression)
            except ValueError as exc:
                raise LifecycleError("task-schedule-cron-invalid") from exc
        interval_seconds = request.interval_seconds
        rule_id = request.rule_id or uuid4().hex
        name = request.name or f"{request.task_type}-schedule"
        task_type = request.task_type.strip()
        if not task_type:
            raise LifecycleError("task-schedule-task-type-invalid")
        queue = (request.queue or self._settings.default_queue).strip()
        if not queue:
            raise LifecycleError("task-schedule-queue-invalid")
        payload = dict(request.payload)
        priority = request.priority if request.priority is not None else self._settings.default_priority
        start_time = self._coerce_datetime(request.start_time, tzinfo)
        end_time = self._coerce_datetime(request.end_time, tzinfo)
        if end_time and start_time and end_time <= start_time:
            raise LifecycleError("task-schedule-window-invalid")
        tags = {str(key): str(value) for key, value in request.tags.items()}
        tags.setdefault("scheduled", "true")
        tags.setdefault("rule_name", name)
        tags.setdefault("task_type", task_type)
        return _ScheduleRule(
            rule_id=rule_id,
            name=name,
            task_type=task_type,
            queue=queue,
            payload=payload,
            priority=priority,
            cron_expression=cron_expression,
            interval_seconds=interval_seconds,
            start_time=start_time,
            end_time=end_time,
            max_runs=request.max_runs,
            tags=tags,
        )

    def _coerce_datetime(self, value: datetime | None, tzinfo: ZoneInfo) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=tzinfo)
        return value.astimezone(tzinfo)

    def _resolve_preview_count(self, requested: int | None) -> int:
        if requested is not None:
            return min(requested, self._settings.max_preview_runs)
        return self._settings.max_preview_runs

    def _compute_schedule(
        self,
        rule: _ScheduleRule,
        base_time: datetime,
        preview_count: int,
    ) -> dict[str, Any]:
        cron_helper = _CronExpression(rule.cron_expression) if rule.cron_expression else None
        next_run: datetime | None = None
        runs_remaining = rule.max_runs
        limit = preview_count if preview_count > 0 else 0
        current = base_time
        upcoming: list[str] = []
        iterations = 0
        while True:
            iterations += 1
            candidate = self._next_occurrence(current, cron_helper, rule.interval_seconds)
            if candidate is None:
                break
            if rule.end_time and candidate > rule.end_time:
                break
            if next_run is None:
                next_run = candidate
            if len(upcoming) < limit:
                upcoming.append(candidate.isoformat())
            if limit > 0 and len(upcoming) >= limit:
                break
            current = candidate
            if runs_remaining is not None:
                runs_remaining -= 1
                if runs_remaining <= 0:
                    break
            if limit == 0 and next_run is not None:
                break
            if iterations > 10_000:
                raise LifecycleError("task-schedule-iterations-exceeded")
        return {
            "status": "scheduled" if next_run else "unscheduled",
            "rule": {
                "rule_id": rule.rule_id,
                "name": rule.name,
                "task_type": rule.task_type,
                "queue": rule.queue,
                "priority": rule.priority,
                "cron_expression": rule.cron_expression,
                "interval_seconds": rule.interval_seconds,
                "start_time": rule.start_time.isoformat() if rule.start_time else None,
                "end_time": rule.end_time.isoformat() if rule.end_time else None,
                "max_runs": rule.max_runs,
                "tags": rule.tags,
            },
            "next_run": next_run.isoformat() if next_run else None,
            "upcoming_runs": upcoming,
            "payload": rule.payload,
        }

    def _next_occurrence(
        self,
        base_time: datetime,
        cron_helper: _CronExpression | None,
        interval_seconds: float | None,
    ) -> datetime | None:
        if cron_helper:
            return cron_helper.next_after(base_time)
        if interval_seconds is None:
            return None
        return base_time + timedelta(seconds=interval_seconds)


__all__ = ["TaskScheduleAction", "TaskScheduleSettings"]
