"""Targeted coverage tests for oneiric.actions.task and oneiric.actions.automation.

These tests focus on execution paths, error handling, edge cases,
configuration validation, and state management that are under-covered.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from oneiric.actions.automation import (
    AutomationCondition,
    AutomationRule,
    AutomationTriggerAction,
    AutomationTriggerPayload,
    AutomationTriggerSettings,
)
from oneiric.actions.task import (
    TaskScheduleAction,
    TaskSchedulePayload,
    TaskScheduleSettings,
    _CronExpression,
    _ScheduleRule,
)
from oneiric.core.lifecycle import LifecycleError


# ---------------------------------------------------------------------------
# _CronExpression tests
# ---------------------------------------------------------------------------


class TestCronExpression:
    """Tests for the internal _CronExpression helper."""

    def test_valid_five_fields(self) -> None:
        expr = _CronExpression("0 12 * * 1")
        assert expr is not None

    def test_invalid_part_count_raises(self) -> None:
        with pytest.raises(ValueError, match="five fields"):
            _CronExpression("0 12 *")

    def test_invalid_cron_step_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="step must be positive"):
            _CronExpression("0/0 * * * *")

    def test_invalid_cron_step_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid cron step"):
            _CronExpression("*/ * * * *")

    def test_parse_field_wildcard(self) -> None:
        expr = _CronExpression("* * * * *")
        # Wildcards should produce None internally (matches everything)
        assert expr._minutes is None
        assert expr._hours is None

    def test_parse_field_question_mark(self) -> None:
        expr = _CronExpression("? ? ? ? ?")
        assert expr._minutes is None
        assert expr._hours is None

    def test_parse_field_empty(self) -> None:
        # Empty string treated same as wildcard
        expr = _CronExpression("* * * * *")
        result = expr._parse_field("", 0, 59)
        assert result is None

    def test_parse_field_single_value(self) -> None:
        expr = _CronExpression("30 * * * *")
        assert expr._minutes == [30]

    def test_parse_field_range(self) -> None:
        expr = _CronExpression("0 8-17 * * *")
        assert expr._hours == list(range(8, 18))

    def test_parse_field_range_out_of_bounds(self) -> None:
        with pytest.raises(ValueError, match="outside bounds"):
            _CronExpression("0 25 * * *")

    def test_parse_field_step(self) -> None:
        expr = _CronExpression("*/15 * * * *")
        assert expr._minutes == [0, 15, 30, 45]

    def test_parse_field_step_with_range(self) -> None:
        expr = _CronExpression("10-30/5 * * * *")
        assert expr._minutes == [10, 15, 20, 25, 30]

    def test_parse_field_comma_separated(self) -> None:
        expr = _CronExpression("0,15,30,45 * * * *")
        assert expr._minutes == [0, 15, 30, 45]

    def test_parse_field_comma_separated_with_ranges(self) -> None:
        expr = _CronExpression("0-5,10-12 * * * *")
        assert expr._minutes == [0, 1, 2, 3, 4, 5, 10, 11, 12]

    def test_weekday_wrap_sunday_seven_to_zero(self) -> None:
        """Day-of-week 7 should be normalized to 0."""
        expr = _CronExpression("* * * * 7")
        assert 0 in expr._weekdays
        assert 7 not in expr._weekdays

    def test_weekday_out_of_range_low(self) -> None:
        # Negative values are caught by int() parsing via the dash-as-range logic
        with pytest.raises(ValueError):
            _CronExpression("* * * * -1")

    def test_weekday_out_of_range_high(self) -> None:
        with pytest.raises(ValueError, match="Day-of-week"):
            _CronExpression("* * * * 8")

    def test_range_start_greater_than_end_raises(self) -> None:
        with pytest.raises(ValueError, match="start cannot be greater than end"):
            _CronExpression("30-10 * * * *")

    def test_next_after_basic(self) -> None:
        expr = _CronExpression("0 12 * * *")
        base = datetime(2026, 1, 1, 11, 0, tzinfo=ZoneInfo("UTC"))
        next_time = expr.next_after(base)
        assert next_time.hour == 12
        assert next_time.minute == 0

    def test_next_after_already_past_minute(self) -> None:
        expr = _CronExpression("30 12 * * *")
        base = datetime(2026, 1, 1, 12, 30, tzinfo=ZoneInfo("UTC"))
        next_time = expr.next_after(base)
        # Should return next day's 12:30
        assert next_time.day == 2
        assert next_time.hour == 12
        assert next_time.minute == 30

    def test_matches_specific_day(self) -> None:
        expr = _CronExpression("0 12 15 * *")
        base = datetime(2026, 1, 14, 12, 0, tzinfo=ZoneInfo("UTC"))
        next_time = expr.next_after(base)
        assert next_time.day == 15

    def test_matches_specific_month(self) -> None:
        expr = _CronExpression("0 0 1 6 *")
        base = datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC"))
        next_time = expr.next_after(base)
        assert next_time.month == 6

    def test_matches_specific_weekday(self) -> None:
        """Monday (dow=1) - 2026-01-05 is a Monday."""
        expr = _CronExpression("0 9 * * 1")
        base = datetime(2026, 1, 4, 9, 0, tzinfo=ZoneInfo("UTC"))  # Sunday
        next_time = expr.next_after(base)
        assert next_time.weekday() == 0  # Monday

    def test_matches_day_or_weekday_logic(self) -> None:
        """When both dom and dow are specified, either match is sufficient."""
        # 15th of month OR Monday
        expr = _CronExpression("0 0 15 * 1")
        # Jan 5 2026 is Monday
        base = datetime(2026, 1, 4, 0, 0, tzinfo=ZoneInfo("UTC"))
        next_time = expr.next_after(base)
        # Should match Monday Jan 5 (not wait until Jan 15)
        assert next_time.day == 5

    def test_matches_day_only(self) -> None:
        expr = _CronExpression("0 0 15 * *")
        # Jan 4 - next should be Jan 15
        base = datetime(2026, 1, 4, 0, 0, tzinfo=ZoneInfo("UTC"))
        next_time = expr.next_after(base)
        assert next_time.day == 15

    def test_matches_weekday_only(self) -> None:
        expr = _CronExpression("0 0 * * 1")
        # Jan 4 (Sunday) - next Monday is Jan 5
        base = datetime(2026, 1, 4, 0, 0, tzinfo=ZoneInfo("UTC"))
        next_time = expr.next_after(base)
        assert next_time.weekday() == 0  # Monday

    def test_match_field_none_matches_anything(self) -> None:
        expr = _CronExpression("0 * * * *")
        # _match_field(None, ...) should return True
        assert expr._match_field(None, 25) is True

    def test_match_field_list_contains(self) -> None:
        expr = _CronExpression("0,30 * * * *")
        assert expr._match_field(expr._minutes, 0) is True
        assert expr._match_field(expr._minutes, 30) is True
        assert expr._match_field(expr._minutes, 15) is False

    def test_extract_step_no_slash(self) -> None:
        expr = _CronExpression("* * * * *")
        step, range_expr = expr._extract_step("5")
        assert step == 1
        assert range_expr == "5"

    def test_extract_step_with_base_only(self) -> None:
        expr = _CronExpression("* * * * *")
        step, range_expr = expr._extract_step("/5")
        assert step == 5
        assert range_expr == "*"

    def test_normalize_weekday_seven(self) -> None:
        expr = _CronExpression("* * * * *")
        assert expr._normalize_weekday(7) == 0
        assert expr._normalize_weekday(0) == 0
        assert expr._normalize_weekday(3) == 3

    def test_parse_range_wildcard(self) -> None:
        expr = _CronExpression("* * * * *")
        start, end = expr._parse_range("*", 0, 59)
        assert start == 0
        assert end == 59

    def test_parse_range_question_mark(self) -> None:
        expr = _CronExpression("* * * * *")
        start, end = expr._parse_range("?", 0, 59)
        assert start == 0
        assert end == 59

    def test_parse_range_single_value(self) -> None:
        expr = _CronExpression("* * * * *")
        start, end = expr._parse_range("15", 0, 59)
        assert start == 15
        assert end == 15

    def test_validate_range_normal(self) -> None:
        expr = _CronExpression("* * * * *")
        # Should not raise
        expr._validate_range(0, 59, 0, 59, "0-59", wrap_sunday=False)

    def test_validate_range_out_of_bounds(self) -> None:
        expr = _CronExpression("* * * * *")
        with pytest.raises(ValueError, match="outside bounds"):
            expr._validate_range(-1, 59, 0, 59, "-1-59", wrap_sunday=False)


# ---------------------------------------------------------------------------
# TaskScheduleSettings / TaskSchedulePayload validation tests
# ---------------------------------------------------------------------------


class TestTaskScheduleSettings:
    def test_defaults(self) -> None:
        s = TaskScheduleSettings()
        assert s.default_queue == "default"
        assert s.default_priority == 100
        assert s.timezone == "UTC"
        assert s.max_preview_runs == 5

    def test_custom_values(self) -> None:
        s = TaskScheduleSettings(
            default_queue="critical",
            default_priority=500,
            timezone="America/New_York",
            max_preview_runs=10,
        )
        assert s.default_queue == "critical"
        assert s.default_priority == 500
        assert s.max_preview_runs == 10

    def test_max_preview_runs_min(self) -> None:
        with pytest.raises(ValidationError):
            TaskScheduleSettings(max_preview_runs=0)

    def test_max_preview_runs_max(self) -> None:
        with pytest.raises(ValidationError):
            TaskScheduleSettings(max_preview_runs=100)

    def test_default_priority_negative(self) -> None:
        with pytest.raises(ValidationError):
            TaskScheduleSettings(default_priority=-1)


class TestTaskSchedulePayload:
    def test_minimal_valid(self) -> None:
        p = TaskSchedulePayload(task_type="email")
        assert p.task_type == "email"
        assert p.queue is None
        assert p.cron_expression is None
        assert p.interval_seconds is None

    def test_alias_queue_name(self) -> None:
        p = TaskSchedulePayload(task_type="email", queue_name="urgent")
        assert p.queue == "urgent"

    def test_alias_rule_name(self) -> None:
        p = TaskSchedulePayload(task_type="email", rule_name="daily-email")
        assert p.name == "daily-email"

    def test_alias_id(self) -> None:
        p = TaskSchedulePayload(task_type="email", id="abc-123")
        assert p.rule_id == "abc-123"

    def test_alias_cron(self) -> None:
        p = TaskSchedulePayload(task_type="email", cron="0 8 * * *")
        assert p.cron_expression == "0 8 * * *"

    def test_alias_interval(self) -> None:
        p = TaskSchedulePayload(task_type="email", interval=300.0)
        assert p.interval_seconds == 300.0

    def test_alias_every_seconds(self) -> None:
        p = TaskSchedulePayload(task_type="email", every_seconds=600.0)
        assert p.interval_seconds == 600.0

    def test_priority_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TaskSchedulePayload(task_type="email", priority=-1)

    def test_interval_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TaskSchedulePayload(task_type="email", interval_seconds=0)

    def test_interval_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TaskSchedulePayload(task_type="email", interval_seconds=-5)

    def test_max_runs_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TaskSchedulePayload(task_type="email", max_runs=0)

    def test_preview_runs_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TaskSchedulePayload(task_type="email", preview_runs=-1)

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            TaskSchedulePayload(task_type="email", unknown_field="bad")


# ---------------------------------------------------------------------------
# TaskScheduleAction.execute tests
# ---------------------------------------------------------------------------


class TestTaskScheduleActionExecute:
    @pytest.mark.asyncio
    async def test_basic_cron_schedule(self) -> None:
        action = TaskScheduleAction()
        result = await action.execute({"task_type": "email", "cron_expression": "0 8 * * *"})
        assert result["status"] == "scheduled"
        assert result["next_run"] is not None
        assert len(result["upcoming_runs"]) == 5  # default max_preview_runs

    @pytest.mark.asyncio
    async def test_basic_interval_schedule(self) -> None:
        action = TaskScheduleAction()
        result = await action.execute({"task_type": "email", "interval_seconds": 3600})
        assert result["status"] == "scheduled"
        assert result["next_run"] is not None

    @pytest.mark.asyncio
    async def test_no_timing_raises(self) -> None:
        action = TaskScheduleAction()
        with pytest.raises(LifecycleError, match="timing-required"):
            await action.execute({"task_type": "email"})

    @pytest.mark.asyncio
    async def test_invalid_payload_raises(self) -> None:
        action = TaskScheduleAction()
        with pytest.raises(LifecycleError, match="payload-invalid"):
            await action.execute({"bad_field": True})

    @pytest.mark.asyncio
    async def test_none_payload(self) -> None:
        action = TaskScheduleAction()
        with pytest.raises(LifecycleError, match="payload-invalid"):
            await action.execute(None)

    @pytest.mark.asyncio
    async def test_empty_payload(self) -> None:
        action = TaskScheduleAction()
        with pytest.raises(LifecycleError, match="payload-invalid"):
            await action.execute({})

    @pytest.mark.asyncio
    async def test_cron_expression_invalid(self) -> None:
        action = TaskScheduleAction()
        with pytest.raises(LifecycleError, match="cron-invalid"):
            await action.execute({"task_type": "email", "cron_expression": "bad"})

    @pytest.mark.asyncio
    async def test_invalid_timezone_raises(self) -> None:
        action = TaskScheduleAction()
        with pytest.raises(LifecycleError, match="timezone-invalid"):
            await action.execute({
                "task_type": "email",
                "cron_expression": "0 8 * * *",
                "timezone": "Nonexistent/Zone",
            })

    @pytest.mark.asyncio
    async def test_task_type_whitespace_only_raises(self) -> None:
        action = TaskScheduleAction()
        with pytest.raises(LifecycleError, match="task-type-invalid"):
            await action.execute({
                "task_type": "   ",
                "cron_expression": "0 8 * * *",
            })

    @pytest.mark.asyncio
    async def test_queue_whitespace_only_raises(self) -> None:
        action = TaskScheduleAction(
            settings=TaskScheduleSettings(default_queue="   ")
        )
        with pytest.raises(LifecycleError, match="queue-invalid"):
            await action.execute({
                "task_type": "email",
                "cron_expression": "0 8 * * *",
            })

    @pytest.mark.asyncio
    async def test_end_before_start_raises(self) -> None:
        action = TaskScheduleAction()
        with pytest.raises(LifecycleError, match="window-invalid"):
            await action.execute({
                "task_type": "email",
                "cron_expression": "0 8 * * *",
                "start_time": "2026-12-01T00:00:00+00:00",
                "end_time": "2026-01-01T00:00:00+00:00",
            })

    @pytest.mark.asyncio
    async def test_custom_timezone(self) -> None:
        action = TaskScheduleAction()
        result = await action.execute({
            "task_type": "email",
            "cron_expression": "0 8 * * *",
            "timezone": "America/New_York",
        })
        assert result["status"] == "scheduled"

    @pytest.mark.asyncio
    async def test_custom_preview_count(self) -> None:
        action = TaskScheduleAction(
            settings=TaskScheduleSettings(max_preview_runs=20)
        )
        result = await action.execute({
            "task_type": "email",
            "cron_expression": "0 8 * * *",
            "preview_runs": 3,
        })
        assert len(result["upcoming_runs"]) == 3

    @pytest.mark.asyncio
    async def test_preview_count_exceeds_max_capped(self) -> None:
        action = TaskScheduleAction(
            settings=TaskScheduleSettings(max_preview_runs=5)
        )
        result = await action.execute({
            "task_type": "email",
            "cron_expression": "0 8 * * *",
            "preview_runs": 100,
        })
        assert len(result["upcoming_runs"]) == 5

    @pytest.mark.asyncio
    async def test_preview_count_zero(self) -> None:
        action = TaskScheduleAction()
        result = await action.execute({
            "task_type": "email",
            "cron_expression": "0 8 * * *",
            "preview_runs": 0,
        })
        assert result["status"] == "scheduled"
        assert len(result["upcoming_runs"]) == 0
        assert result["next_run"] is not None

    @pytest.mark.asyncio
    async def test_all_aliases_in_execute(self) -> None:
        action = TaskScheduleAction()
        result = await action.execute({
            "task_type": "report",
            "queue_name": "reports",
            "rule_name": "daily-report",
            "id": "my-rule-id",
            "cron": "0 6 * * 1-5",
            "interval": 86400,
        })
        rule = result["rule"]
        assert rule["queue"] == "reports"
        assert rule["name"] == "daily-report"
        assert rule["rule_id"] == "my-rule-id"

    @pytest.mark.asyncio
    async def test_custom_priority(self) -> None:
        action = TaskScheduleAction()
        result = await action.execute({
            "task_type": "email",
            "cron_expression": "0 8 * * *",
            "priority": 999,
        })
        assert result["rule"]["priority"] == 999

    @pytest.mark.asyncio
    async def test_default_priority_used(self) -> None:
        action = TaskScheduleAction(
            settings=TaskScheduleSettings(default_priority=42)
        )
        result = await action.execute({
            "task_type": "email",
            "cron_expression": "0 8 * * *",
        })
        assert result["rule"]["priority"] == 42

    @pytest.mark.asyncio
    async def test_max_runs_limits_schedule(self) -> None:
        action = TaskScheduleAction()
        result = await action.execute({
            "task_type": "email",
            "interval_seconds": 60,
            "max_runs": 2,
        })
        assert len(result["upcoming_runs"]) == 2

    @pytest.mark.asyncio
    async def test_end_time_limits_schedule(self) -> None:
        action = TaskScheduleAction()
        now = datetime.now(tz=ZoneInfo("UTC"))
        end = now + timedelta(minutes=5)
        result = await action.execute({
            "task_type": "email",
            "interval_seconds": 60,
            "end_time": end.isoformat(),
        })
        # Should have a limited number of runs within 5 minutes
        assert len(result["upcoming_runs"]) <= 6

    @pytest.mark.asyncio
    async def test_start_time_in_future(self) -> None:
        action = TaskScheduleAction()
        future_start = datetime(2030, 1, 1, tzinfo=ZoneInfo("UTC"))
        result = await action.execute({
            "task_type": "email",
            "cron_expression": "0 8 * * *",
            "start_time": future_start.isoformat(),
        })
        assert result["status"] == "scheduled"
        # next_run should be at or after start_time
        next_run = datetime.fromisoformat(result["next_run"])
        assert next_run >= future_start

    @pytest.mark.asyncio
    async def test_tags_include_defaults(self) -> None:
        action = TaskScheduleAction()
        result = await action.execute({
            "task_type": "email",
            "cron_expression": "0 8 * * *",
        })
        tags = result["rule"]["tags"]
        assert tags["scheduled"] == "true"
        assert "rule_name" in tags
        assert tags["task_type"] == "email"

    @pytest.mark.asyncio
    async def test_custom_tags(self) -> None:
        action = TaskScheduleAction()
        result = await action.execute({
            "task_type": "email",
            "cron_expression": "0 8 * * *",
            "tags": {"team": "backend", "env": "prod"},
        })
        tags = result["rule"]["tags"]
        assert tags["team"] == "backend"
        assert tags["env"] == "prod"
        assert tags["scheduled"] == "true"  # default preserved

    @pytest.mark.asyncio
    async def test_payload_forwarded(self) -> None:
        action = TaskScheduleAction()
        result = await action.execute({
            "task_type": "email",
            "cron_expression": "0 8 * * *",
            "payload": {"to": "user@example.com", "subject": "Hello"},
        })
        assert result["payload"]["to"] == "user@example.com"
        assert result["payload"]["subject"] == "Hello"

    @pytest.mark.asyncio
    async def test_rule_dict_structure(self) -> None:
        action = TaskScheduleAction()
        result = await action.execute({
            "task_type": "email",
            "cron_expression": "0 8 * * *",
            "name": "test-rule",
            "rule_id": "test-id",
        })
        rule = result["rule"]
        assert rule["rule_id"] == "test-id"
        assert rule["name"] == "test-rule"
        assert rule["task_type"] == "email"
        assert rule["cron_expression"] == "0 8 * * *"
        assert rule["interval_seconds"] is None
        assert rule["start_time"] is None
        assert rule["end_time"] is None
        assert rule["max_runs"] is None

    @pytest.mark.asyncio
    async def test_auto_generated_rule_id(self) -> None:
        action = TaskScheduleAction()
        result1 = await action.execute({
            "task_type": "email",
            "cron_expression": "0 8 * * *",
        })
        result2 = await action.execute({
            "task_type": "email",
            "cron_expression": "0 8 * * *",
        })
        # Each invocation should generate a unique ID
        assert result1["rule"]["rule_id"] != result2["rule"]["rule_id"]

    @pytest.mark.asyncio
    async def test_auto_generated_name(self) -> None:
        action = TaskScheduleAction()
        result = await action.execute({
            "task_type": "report",
            "cron_expression": "0 8 * * *",
        })
        assert result["rule"]["name"] == "report-schedule"

    @pytest.mark.asyncio
    async def test_coerce_datetime_naive_adds_tz(self) -> None:
        """Naive datetimes should have the action's timezone added."""
        action = TaskScheduleAction(
            settings=TaskScheduleSettings(timezone="America/New_York")
        )
        result = await action.execute({
            "task_type": "email",
            "cron_expression": "0 8 * * *",
            "start_time": "2030-01-01T08:00:00",  # naive
        })
        rule = result["rule"]
        assert rule["start_time"] is not None
        start = datetime.fromisoformat(rule["start_time"])
        assert start.tzinfo is not None


# ---------------------------------------------------------------------------
# TaskScheduleAction internal methods
# ---------------------------------------------------------------------------


class TestTaskScheduleActionInternals:
    def test_resolve_timezone_valid(self) -> None:
        action = TaskScheduleAction()
        tz = action._resolve_timezone("UTC")
        assert str(tz) == "UTC"

    def test_resolve_timezone_invalid(self) -> None:
        action = TaskScheduleAction()
        with pytest.raises(LifecycleError, match="timezone-invalid"):
            action._resolve_timezone("Bad/Zone")

    def test_resolve_preview_count_none_uses_default(self) -> None:
        action = TaskScheduleAction(
            settings=TaskScheduleSettings(max_preview_runs=7)
        )
        assert action._resolve_preview_count(None) == 7

    def test_resolve_preview_count_custom_capped(self) -> None:
        action = TaskScheduleAction(
            settings=TaskScheduleSettings(max_preview_runs=5)
        )
        assert action._resolve_preview_count(3) == 3

    def test_resolve_preview_count_exceeds_max(self) -> None:
        action = TaskScheduleAction(
            settings=TaskScheduleSettings(max_preview_runs=5)
        )
        assert action._resolve_preview_count(100) == 5

    def test_coerce_datetime_none(self) -> None:
        action = TaskScheduleAction()
        assert action._coerce_datetime(None, ZoneInfo("UTC")) is None

    def test_coerce_datetime_naive(self) -> None:
        action = TaskScheduleAction()
        naive = datetime(2026, 1, 1, 12, 0)
        result = action._coerce_datetime(naive, ZoneInfo("America/New_York"))
        assert result.tzinfo is not None
        assert result.hour == 12

    def test_coerce_datetime_aware(self) -> None:
        action = TaskScheduleAction()
        aware = datetime(2026, 1, 1, 12, 0, tzinfo=ZoneInfo("UTC"))
        result = action._coerce_datetime(aware, ZoneInfo("America/New_York"))
        assert result.tzinfo.key == "America/New_York"

    def test_build_rule_dict(self) -> None:
        action = TaskScheduleAction()
        rule = _ScheduleRule(
            rule_id="test",
            name="test-name",
            task_type="email",
            queue="default",
            payload={"key": "val"},
            priority=100,
            cron_expression="0 8 * * *",
            interval_seconds=None,
            start_time=None,
            end_time=None,
            max_runs=10,
            tags={"scheduled": "true"},
        )
        d = action._build_rule_dict(rule)
        assert d["rule_id"] == "test"
        assert d["name"] == "test-name"
        assert d["task_type"] == "email"
        assert d["priority"] == 100
        assert d["cron_expression"] == "0 8 * * *"
        assert d["start_time"] is None
        assert d["end_time"] is None
        assert d["max_runs"] == 10
        assert d["tags"] == {"scheduled": "true"}

    def test_build_rule_dict_with_datetimes(self) -> None:
        action = TaskScheduleAction()
        start = datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC"))
        end = datetime(2026, 12, 31, tzinfo=ZoneInfo("UTC"))
        rule = _ScheduleRule(
            rule_id="test",
            name="test",
            task_type="email",
            queue="default",
            payload={},
            priority=100,
            cron_expression=None,
            interval_seconds=60,
            start_time=start,
            end_time=end,
            max_runs=None,
            tags={},
        )
        d = action._build_rule_dict(rule)
        assert d["start_time"] == start.isoformat()
        assert d["end_time"] == end.isoformat()

    def test_next_occurrence_cron(self) -> None:
        action = TaskScheduleAction()
        cron = _CronExpression("0 8 * * *")
        base = datetime(2026, 1, 1, 7, 0, tzinfo=ZoneInfo("UTC"))
        result = action._next_occurrence(base, cron, None)
        assert result is not None
        assert result.hour == 8

    def test_next_occurrence_interval(self) -> None:
        action = TaskScheduleAction()
        base = datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC"))
        result = action._next_occurrence(base, None, 3600)
        assert result == base + timedelta(seconds=3600)

    def test_next_occurrence_none(self) -> None:
        action = TaskScheduleAction()
        base = datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC"))
        result = action._next_occurrence(base, None, None)
        assert result is None

    def test_is_valid_candidate_within_end_time(self) -> None:
        action = TaskScheduleAction()
        end = datetime(2026, 12, 31, tzinfo=ZoneInfo("UTC"))
        candidate = datetime(2026, 6, 1, tzinfo=ZoneInfo("UTC"))
        rule = _ScheduleRule(
            rule_id="t", name="t", task_type="t", queue="q",
            payload={}, priority=100, cron_expression=None,
            interval_seconds=60, start_time=None, end_time=end,
            max_runs=None, tags={},
        )
        assert action._is_valid_candidate(candidate, rule) is True

    def test_is_valid_candidate_past_end_time(self) -> None:
        action = TaskScheduleAction()
        end = datetime(2026, 6, 1, tzinfo=ZoneInfo("UTC"))
        candidate = datetime(2026, 12, 31, tzinfo=ZoneInfo("UTC"))
        rule = _ScheduleRule(
            rule_id="t", name="t", task_type="t", queue="q",
            payload={}, priority=100, cron_expression=None,
            interval_seconds=60, start_time=None, end_time=end,
            max_runs=None, tags={},
        )
        assert action._is_valid_candidate(candidate, rule) is False

    def test_is_valid_candidate_none_end_time(self) -> None:
        action = TaskScheduleAction()
        candidate = datetime(2026, 6, 1, tzinfo=ZoneInfo("UTC"))
        rule = _ScheduleRule(
            rule_id="t", name="t", task_type="t", queue="q",
            payload={}, priority=100, cron_expression=None,
            interval_seconds=60, start_time=None, end_time=None,
            max_runs=None, tags={},
        )
        assert action._is_valid_candidate(candidate, rule) is True

    def test_is_valid_candidate_none_candidate(self) -> None:
        action = TaskScheduleAction()
        rule = _ScheduleRule(
            rule_id="t", name="t", task_type="t", queue="q",
            payload={}, priority=100, cron_expression=None,
            interval_seconds=60, start_time=None, end_time=None,
            max_runs=None, tags={},
        )
        assert action._is_valid_candidate(None, rule) is False

    def test_check_iteration_limit_ok(self) -> None:
        action = TaskScheduleAction()
        action._check_iteration_limit(5000)  # should not raise

    def test_check_iteration_limit_exceeded(self) -> None:
        action = TaskScheduleAction()
        with pytest.raises(LifecycleError, match="iterations-exceeded"):
            action._check_iteration_limit(10001)

    def test_update_schedule_state_first_run(self) -> None:
        action = TaskScheduleAction()
        state: dict[str, Any] = {
            "next_run": None,
            "runs_remaining": None,
            "limit": 5,
            "current": datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")),
            "upcoming": [],
        }
        candidate = datetime(2026, 1, 2, tzinfo=ZoneInfo("UTC"))
        action._update_schedule_state(state, candidate)
        assert state["next_run"] == candidate
        assert len(state["upcoming"]) == 1
        assert state["current"] == candidate

    def test_update_schedule_state_subsequent_run(self) -> None:
        action = TaskScheduleAction()
        state: dict[str, Any] = {
            "next_run": datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")),
            "runs_remaining": None,
            "limit": 2,
            "current": datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")),
            "upcoming": ["2026-01-01T00:00:00+00:00"],
        }
        candidate = datetime(2026, 1, 2, tzinfo=ZoneInfo("UTC"))
        action._update_schedule_state(state, candidate)
        assert state["next_run"] == datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC"))
        assert len(state["upcoming"]) == 2

    def test_update_schedule_state_decrements_runs_remaining(self) -> None:
        action = TaskScheduleAction()
        state: dict[str, Any] = {
            "next_run": None,
            "runs_remaining": 5,
            "limit": 10,
            "current": datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")),
            "upcoming": [],
        }
        candidate = datetime(2026, 1, 2, tzinfo=ZoneInfo("UTC"))
        action._update_schedule_state(state, candidate)
        assert state["runs_remaining"] == 4

    def test_update_schedule_state_limit_reached(self) -> None:
        action = TaskScheduleAction()
        state: dict[str, Any] = {
            "next_run": datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")),
            "runs_remaining": None,
            "limit": 2,
            "current": datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")),
            "upcoming": ["run1", "run2"],
        }
        candidate = datetime(2026, 1, 3, tzinfo=ZoneInfo("UTC"))
        action._update_schedule_state(state, candidate)
        # Should not append beyond limit
        assert len(state["upcoming"]) == 2

    def test_schedule_complete_limit_reached(self) -> None:
        action = TaskScheduleAction()
        state: dict[str, Any] = {
            "limit": 3,
            "upcoming": ["a", "b", "c"],
            "runs_remaining": None,
            "next_run": datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")),
        }
        assert action._schedule_complete(state) is True

    def test_schedule_complete_runs_remaining_zero(self) -> None:
        action = TaskScheduleAction()
        state: dict[str, Any] = {
            "limit": 10,
            "upcoming": ["a"],
            "runs_remaining": 0,
            "next_run": datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")),
        }
        assert action._schedule_complete(state) is True

    def test_schedule_complete_zero_limit_with_next_run(self) -> None:
        action = TaskScheduleAction()
        state: dict[str, Any] = {
            "limit": 0,
            "upcoming": [],
            "runs_remaining": None,
            "next_run": datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")),
        }
        assert action._schedule_complete(state) is True

    def test_schedule_complete_not_done(self) -> None:
        action = TaskScheduleAction()
        state: dict[str, Any] = {
            "limit": 10,
            "upcoming": ["a"],
            "runs_remaining": 5,
            "next_run": datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")),
        }
        assert action._schedule_complete(state) is False

    def test_schedule_complete_zero_limit_no_next_run(self) -> None:
        action = TaskScheduleAction()
        state: dict[str, Any] = {
            "limit": 0,
            "upcoming": [],
            "runs_remaining": None,
            "next_run": None,
        }
        assert action._schedule_complete(state) is False


# ---------------------------------------------------------------------------
# AutomationTriggerSettings / AutomationTriggerPayload / AutomationRule tests
# ---------------------------------------------------------------------------


class TestAutomationTriggerSettings:
    def test_defaults(self) -> None:
        s = AutomationTriggerSettings()
        assert s.max_rules == 20

    def test_custom_max_rules(self) -> None:
        s = AutomationTriggerSettings(max_rules=5)
        assert s.max_rules == 5

    def test_max_rules_min(self) -> None:
        with pytest.raises(ValidationError):
            AutomationTriggerSettings(max_rules=0)

    def test_max_rules_max(self) -> None:
        with pytest.raises(ValidationError):
            AutomationTriggerSettings(max_rules=300)


class TestAutomationTriggerPayload:
    def test_minimal(self) -> None:
        p = AutomationTriggerPayload(rules=[{"name": "r", "action": "a"}])
        assert len(p.rules) == 1

    def test_empty_rules_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AutomationTriggerPayload(rules=[])

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            AutomationTriggerPayload(rules=[{"name": "r", "action": "a"}], bad="field")


class TestAutomationRule:
    def test_defaults(self) -> None:
        r = AutomationRule(name="test", action="workflow.notify")
        assert r.payload == {}
        assert r.stop_on_match is False
        assert r.conditions == []

    def test_custom(self) -> None:
        c = AutomationCondition(field="status", operator="equals", value="ok")
        r = AutomationRule(
            name="test",
            action="workflow.notify",
            payload={"key": "val"},
            stop_on_match=True,
            conditions=[c],
        )
        assert r.payload == {"key": "val"}
        assert r.stop_on_match is True
        assert len(r.conditions) == 1


# ---------------------------------------------------------------------------
# AutomationTriggerAction.execute tests
# ---------------------------------------------------------------------------


class TestAutomationTriggerActionExecute:
    @pytest.mark.asyncio
    async def test_no_match_returns_noop(self) -> None:
        action = AutomationTriggerAction()
        result = await action.execute({
            "context": {"status": "ok"},
            "rules": [
                {
                    "name": "r1",
                    "action": "a",
                    "conditions": [
                        {"field": "status", "operator": "equals", "value": "fail"}
                    ],
                }
            ],
        })
        assert result["status"] == "noop"
        assert result["matched_rules"] == []

    @pytest.mark.asyncio
    async def test_invalid_payload_raises(self) -> None:
        action = AutomationTriggerAction()
        with pytest.raises(LifecycleError, match="payload-invalid"):
            await action.execute({"bad": True})

    @pytest.mark.asyncio
    async def test_none_payload(self) -> None:
        action = AutomationTriggerAction()
        with pytest.raises(LifecycleError, match="payload-invalid"):
            await action.execute(None)

    @pytest.mark.asyncio
    async def test_empty_payload(self) -> None:
        action = AutomationTriggerAction()
        with pytest.raises(LifecycleError, match="payload-invalid"):
            await action.execute({})

    @pytest.mark.asyncio
    async def test_rule_limit_exceeded(self) -> None:
        action = AutomationTriggerAction(
            settings=AutomationTriggerSettings(max_rules=2)
        )
        rules = [{"name": f"r{i}", "action": "a"} for i in range(5)]
        with pytest.raises(LifecycleError, match="rule-limit"):
            await action.execute({"rules": rules})

    @pytest.mark.asyncio
    async def test_context_returned(self) -> None:
        action = AutomationTriggerAction()
        result = await action.execute({
            "context": {"key": "value"},
            "rules": [{"name": "r", "action": "a"}],
        })
        assert result["context"] == {"key": "value"}

    @pytest.mark.asyncio
    async def test_evaluated_rules_count(self) -> None:
        action = AutomationTriggerAction()
        result = await action.execute({
            "context": {"status": "ok"},
            "rules": [
                {"name": "r1", "action": "a1"},
                {"name": "r2", "action": "a2"},
                {"name": "r3", "action": "a3"},
            ],
        })
        assert result["evaluated_rules"] == 3

    @pytest.mark.asyncio
    async def test_multiple_matches(self) -> None:
        action = AutomationTriggerAction()
        result = await action.execute({
            "context": {"status": "ok"},
            "rules": [
                {"name": "r1", "action": "a1"},
                {"name": "r2", "action": "a2"},
            ],
        })
        assert result["status"] == "triggered"
        assert len(result["matched_rules"]) == 2

    @pytest.mark.asyncio
    async def test_stop_on_match_per_rule(self) -> None:
        action = AutomationTriggerAction()
        result = await action.execute({
            "context": {"status": "ok"},
            "rules": [
                {"name": "r1", "action": "a1", "stop_on_match": True},
                {"name": "r2", "action": "a2"},
            ],
        })
        assert len(result["matched_rules"]) == 1
        assert result["evaluated_rules"] == 1

    @pytest.mark.asyncio
    async def test_matched_rule_structure(self) -> None:
        action = AutomationTriggerAction()
        result = await action.execute({
            "context": {"x": 1},
            "rules": [
                {
                    "name": "test-rule",
                    "action": "test.action",
                    "payload": {"data": True},
                    "conditions": [
                        {"field": "x", "operator": "equals", "value": 1},
                        {"field": "y", "operator": "absent"},
                    ],
                }
            ],
        })
        matched = result["matched_rules"][0]
        assert matched["name"] == "test-rule"
        assert matched["action"] == "test.action"
        assert matched["payload"] == {"data": True}
        assert matched["condition_count"] == 2


# ---------------------------------------------------------------------------
# AutomationTriggerAction condition operator tests
# ---------------------------------------------------------------------------


class TestAutomationConditionOperators:
    @pytest.mark.asyncio
    async def test_operator_equals(self) -> None:
        action = AutomationTriggerAction()
        result = await action.execute({
            "context": {"val": "hello"},
            "rules": [
                {
                    "name": "r",
                    "action": "a",
                    "conditions": [{"field": "val", "operator": "equals", "value": "hello"}],
                }
            ],
        })
        assert result["status"] == "triggered"

    @pytest.mark.asyncio
    async def test_operator_not_equals(self) -> None:
        action = AutomationTriggerAction()
        result = await action.execute({
            "context": {"val": "hello"},
            "rules": [
                {
                    "name": "r",
                    "action": "a",
                    "conditions": [{"field": "val", "operator": "not_equals", "value": "world"}],
                }
            ],
        })
        assert result["status"] == "triggered"

    @pytest.mark.asyncio
    async def test_operator_not_equals_fails(self) -> None:
        action = AutomationTriggerAction()
        result = await action.execute({
            "context": {"val": "hello"},
            "rules": [
                {
                    "name": "r",
                    "action": "a",
                    "conditions": [{"field": "val", "operator": "not_equals", "value": "hello"}],
                }
            ],
        })
        assert result["status"] == "noop"

    @pytest.mark.asyncio
    async def test_operator_contains_string(self) -> None:
        action = AutomationTriggerAction()
        result = await action.execute({
            "context": {"msg": "hello world"},
            "rules": [
                {
                    "name": "r",
                    "action": "a",
                    "conditions": [{"field": "msg", "operator": "contains", "value": "world"}],
                }
            ],
        })
        assert result["status"] == "triggered"

    @pytest.mark.asyncio
    async def test_operator_contains_none_returns_false(self) -> None:
        action = AutomationTriggerAction()
        result = await action.execute({
            "context": {"msg": None},
            "rules": [
                {
                    "name": "r",
                    "action": "a",
                    "conditions": [{"field": "msg", "operator": "contains", "value": "x"}],
                }
            ],
        })
        assert result["status"] == "noop"

    @pytest.mark.asyncio
    async def test_operator_contains_in_mapping(self) -> None:
        action = AutomationTriggerAction()
        result = await action.execute({
            "context": {"data": {"key1": "val1", "key2": "val2"}},
            "rules": [
                {
                    "name": "r",
                    "action": "a",
                    "conditions": [{"field": "data", "operator": "contains", "value": "key1"}],
                }
            ],
        })
        assert result["status"] == "triggered"

    @pytest.mark.asyncio
    async def test_operator_contains_in_sequence(self) -> None:
        action = AutomationTriggerAction()
        result = await action.execute({
            "context": {"items": [10, 20, 30]},
            "rules": [
                {
                    "name": "r",
                    "action": "a",
                    "conditions": [{"field": "items", "operator": "contains", "value": 20}],
                }
            ],
        })
        assert result["status"] == "triggered"

    @pytest.mark.asyncio
    async def test_operator_contains_unsupported_type(self) -> None:
        action = AutomationTriggerAction()
        result = await action.execute({
            "context": {"num": 42},
            "rules": [
                {
                    "name": "r",
                    "action": "a",
                    "conditions": [{"field": "num", "operator": "contains", "value": "4"}],
                }
            ],
        })
        assert result["status"] == "noop"

    @pytest.mark.asyncio
    async def test_operator_in(self) -> None:
        action = AutomationTriggerAction()
        result = await action.execute({
            "context": {"role": "admin"},
            "rules": [
                {
                    "name": "r",
                    "action": "a",
                    "conditions": [
                        {"field": "role", "operator": "in", "value": ["admin", "superadmin"]}
                    ],
                }
            ],
        })
        assert result["status"] == "triggered"

    @pytest.mark.asyncio
    async def test_operator_in_not_in_list(self) -> None:
        action = AutomationTriggerAction()
        result = await action.execute({
            "context": {"role": "user"},
            "rules": [
                {
                    "name": "r",
                    "action": "a",
                    "conditions": [
                        {"field": "role", "operator": "in", "value": ["admin", "superadmin"]}
                    ],
                }
            ],
        })
        assert result["status"] == "noop"

    @pytest.mark.asyncio
    async def test_operator_in_non_sequence(self) -> None:
        action = AutomationTriggerAction()
        result = await action.execute({
            "context": {"role": "admin"},
            "rules": [
                {
                    "name": "r",
                    "action": "a",
                    "conditions": [
                        {"field": "role", "operator": "in", "value": "admin-superadmin"}
                    ],
                }
            ],
        })
        # String is excluded from sequence check
        assert result["status"] == "noop"

    @pytest.mark.asyncio
    async def test_operator_greater_than(self) -> None:
        action = AutomationTriggerAction()
        result = await action.execute({
            "context": {"count": 10},
            "rules": [
                {
                    "name": "r",
                    "action": "a",
                    "conditions": [{"field": "count", "operator": "greater_than", "value": 5}],
                }
            ],
        })
        assert result["status"] == "triggered"

    @pytest.mark.asyncio
    async def test_operator_greater_or_equal(self) -> None:
        action = AutomationTriggerAction()
        result = await action.execute({
            "context": {"count": 10},
            "rules": [
                {
                    "name": "r",
                    "action": "a",
                    "conditions": [{"field": "count", "operator": "greater_or_equal", "value": 10}],
                }
            ],
        })
        assert result["status"] == "triggered"

    @pytest.mark.asyncio
    async def test_operator_less_than(self) -> None:
        action = AutomationTriggerAction()
        result = await action.execute({
            "context": {"count": 3},
            "rules": [
                {
                    "name": "r",
                    "action": "a",
                    "conditions": [{"field": "count", "operator": "less_than", "value": 5}],
                }
            ],
        })
        assert result["status"] == "triggered"

    @pytest.mark.asyncio
    async def test_operator_less_or_equal(self) -> None:
        action = AutomationTriggerAction()
        result = await action.execute({
            "context": {"count": 5},
            "rules": [
                {
                    "name": "r",
                    "action": "a",
                    "conditions": [{"field": "count", "operator": "less_or_equal", "value": 5}],
                }
            ],
        })
        assert result["status"] == "triggered"

    @pytest.mark.asyncio
    async def test_operator_numeric_non_numeric_returns_false(self) -> None:
        action = AutomationTriggerAction()
        result = await action.execute({
            "context": {"val": "not-a-number"},
            "rules": [
                {
                    "name": "r",
                    "action": "a",
                    "conditions": [{"field": "val", "operator": "greater_than", "value": 5}],
                }
            ],
        })
        assert result["status"] == "noop"

    @pytest.mark.asyncio
    async def test_operator_exists_field_present(self) -> None:
        action = AutomationTriggerAction()
        result = await action.execute({
            "context": {"data": {"nested": "value"}},
            "rules": [
                {
                    "name": "r",
                    "action": "a",
                    "conditions": [{"field": "data.nested", "operator": "exists"}],
                }
            ],
        })
        assert result["status"] == "triggered"

    @pytest.mark.asyncio
    async def test_operator_exists_field_absent(self) -> None:
        action = AutomationTriggerAction()
        result = await action.execute({
            "context": {"data": {}},
            "rules": [
                {
                    "name": "r",
                    "action": "a",
                    "conditions": [{"field": "data.missing", "operator": "exists"}],
                }
            ],
        })
        assert result["status"] == "noop"

    @pytest.mark.asyncio
    async def test_operator_absent_field_missing(self) -> None:
        action = AutomationTriggerAction()
        result = await action.execute({
            "context": {"data": {}},
            "rules": [
                {
                    "name": "r",
                    "action": "a",
                    "conditions": [{"field": "data.missing", "operator": "absent"}],
                }
            ],
        })
        assert result["status"] == "triggered"

    @pytest.mark.asyncio
    async def test_operator_absent_field_present(self) -> None:
        action = AutomationTriggerAction()
        result = await action.execute({
            "context": {"data": {"key": "val"}},
            "rules": [
                {
                    "name": "r",
                    "action": "a",
                    "conditions": [{"field": "data.key", "operator": "absent"}],
                }
            ],
        })
        assert result["status"] == "noop"

    @pytest.mark.asyncio
    async def test_operator_truthy_true(self) -> None:
        action = AutomationTriggerAction()
        result = await action.execute({
            "context": {"flag": "non-empty"},
            "rules": [
                {
                    "name": "r",
                    "action": "a",
                    "conditions": [{"field": "flag", "operator": "truthy"}],
                }
            ],
        })
        assert result["status"] == "triggered"

    @pytest.mark.asyncio
    async def test_operator_truthy_false(self) -> None:
        action = AutomationTriggerAction()
        result = await action.execute({
            "context": {"flag": ""},
            "rules": [
                {
                    "name": "r",
                    "action": "a",
                    "conditions": [{"field": "flag", "operator": "truthy"}],
                }
            ],
        })
        assert result["status"] == "noop"

    @pytest.mark.asyncio
    async def test_operator_truthy_none(self) -> None:
        action = AutomationTriggerAction()
        result = await action.execute({
            "context": {"flag": None},
            "rules": [
                {
                    "name": "r",
                    "action": "a",
                    "conditions": [{"field": "flag", "operator": "truthy"}],
                }
            ],
        })
        assert result["status"] == "noop"

    @pytest.mark.asyncio
    async def test_operator_falsy_empty(self) -> None:
        action = AutomationTriggerAction()
        result = await action.execute({
            "context": {"flag": ""},
            "rules": [
                {
                    "name": "r",
                    "action": "a",
                    "conditions": [{"field": "flag", "operator": "falsy"}],
                }
            ],
        })
        assert result["status"] == "triggered"

    @pytest.mark.asyncio
    async def test_operator_falsy_non_empty(self) -> None:
        action = AutomationTriggerAction()
        result = await action.execute({
            "context": {"flag": "value"},
            "rules": [
                {
                    "name": "r",
                    "action": "a",
                    "conditions": [{"field": "flag", "operator": "falsy"}],
                }
            ],
        })
        assert result["status"] == "noop"

    @pytest.mark.asyncio
    async def test_operator_falsy_zero(self) -> None:
        action = AutomationTriggerAction()
        result = await action.execute({
            "context": {"count": 0},
            "rules": [
                {
                    "name": "r",
                    "action": "a",
                    "conditions": [{"field": "count", "operator": "falsy"}],
                }
            ],
        })
        assert result["status"] == "triggered"


# ---------------------------------------------------------------------------
# AutomationTriggerAction field resolution tests
# ---------------------------------------------------------------------------


class TestAutomationFieldResolution:
    @pytest.mark.asyncio
    async def test_nested_field_resolution(self) -> None:
        action = AutomationTriggerAction()
        result = await action.execute({
            "context": {"a": {"b": {"c": 42}}},
            "rules": [
                {
                    "name": "r",
                    "action": "a",
                    "conditions": [{"field": "a.b.c", "operator": "equals", "value": 42}],
                }
            ],
        })
        assert result["status"] == "triggered"

    @pytest.mark.asyncio
    async def test_array_index_resolution(self) -> None:
        action = AutomationTriggerAction()
        result = await action.execute({
            "context": {"items": [10, 20, 30]},
            "rules": [
                {
                    "name": "r",
                    "action": "a",
                    "conditions": [{"field": "items.1", "operator": "equals", "value": 20}],
                }
            ],
        })
        assert result["status"] == "triggered"

    @pytest.mark.asyncio
    async def test_array_out_of_bounds_returns_none(self) -> None:
        action = AutomationTriggerAction()
        result = await action.execute({
            "context": {"items": [10]},
            "rules": [
                {
                    "name": "r",
                    "action": "a",
                    "conditions": [{"field": "items.99", "operator": "absent"}],
                }
            ],
        })
        assert result["status"] == "triggered"

    @pytest.mark.asyncio
    async def test_empty_field_path_returns_none(self) -> None:
        action = AutomationTriggerAction()
        result = await action.execute({
            "context": {"val": "x"},
            "rules": [
                {
                    "name": "r",
                    "action": "a",
                    "conditions": [{"field": "", "operator": "absent"}],
                }
            ],
        })
        assert result["status"] == "triggered"

    @pytest.mark.asyncio
    async def test_bracket_notation_in_path(self) -> None:
        action = AutomationTriggerAction()
        result = await action.execute({
            "context": {"items": [10, 20, 30]},
            "rules": [
                {
                    "name": "r",
                    "action": "a",
                    "conditions": [{"field": "items[0]", "operator": "equals", "value": 10}],
                }
            ],
        })
        assert result["status"] == "triggered"

    @pytest.mark.asyncio
    async def test_mixed_dot_bracket_notation(self) -> None:
        action = AutomationTriggerAction()
        result = await action.execute({
            "context": {"data": {"items": [100, 200]}},
            "rules": [
                {
                    "name": "r",
                    "action": "a",
                    "conditions": [{"field": "data.items[1]", "operator": "equals", "value": 200}],
                }
            ],
        })
        assert result["status"] == "triggered"


# ---------------------------------------------------------------------------
# AutomationTriggerAction internal method tests
# ---------------------------------------------------------------------------


class TestAutomationTriggerActionInternals:
    def test_coerce_mapping_valid(self) -> None:
        action = AutomationTriggerAction()
        result = action._coerce_mapping({"key": "value"})
        assert result == {"key": "value"}

    def test_coerce_mapping_non_mapping_raises(self) -> None:
        action = AutomationTriggerAction()
        with pytest.raises(LifecycleError, match="context-invalid"):
            action._coerce_mapping("not a mapping")

    def test_coerce_mapping_converts_keys_to_str(self) -> None:
        action = AutomationTriggerAction()
        result = action._coerce_mapping({1: "a", 2: "b"})
        assert result == {"1": "a", "2": "b"}

    def test_rule_matches_no_conditions(self) -> None:
        action = AutomationTriggerAction()
        rule = AutomationRule(name="r", action="a")
        assert action._rule_matches(rule, {}) is True

    def test_rule_matches_all_conditions_true(self) -> None:
        action = AutomationTriggerAction()
        rule = AutomationRule(
            name="r",
            action="a",
            conditions=[
                AutomationCondition(field="x", operator="exists"),
                AutomationCondition(field="y", operator="exists"),
            ],
        )
        assert action._rule_matches(rule, {"x": 1, "y": 2}) is True

    def test_rule_matches_one_condition_false(self) -> None:
        action = AutomationTriggerAction()
        rule = AutomationRule(
            name="r",
            action="a",
            conditions=[
                AutomationCondition(field="x", operator="exists"),
                AutomationCondition(field="missing", operator="exists"),
            ],
        )
        assert action._rule_matches(rule, {"x": 1}) is False

    def test_contains_none_actual(self) -> None:
        action = AutomationTriggerAction()
        assert action._contains(None, "anything") is False

    def test_contains_string(self) -> None:
        action = AutomationTriggerAction()
        assert action._contains("hello world", "world") is True
        assert action._contains("hello world", "mars") is False

    def test_contains_mapping_key(self) -> None:
        action = AutomationTriggerAction()
        assert action._contains({"a": 1, "b": 2}, "a") is True
        assert action._contains({"a": 1}, "c") is False

    def test_contains_sequence(self) -> None:
        action = AutomationTriggerAction()
        assert action._contains([1, 2, 3], 2) is True
        assert action._contains([1, 2, 3], 5) is False

    def test_contains_bytes_excluded(self) -> None:
        """Bytes should not be treated as a sequence for contains."""
        action = AutomationTriggerAction()
        assert action._contains(b"hello", b"e") is False

    def test_in_collection_list(self) -> None:
        action = AutomationTriggerAction()
        assert action._in_collection("admin", ["admin", "user"]) is True
        assert action._in_collection("guest", ["admin", "user"]) is False

    def test_in_collection_string_excluded(self) -> None:
        action = AutomationTriggerAction()
        assert action._in_collection("a", "abc") is False

    def test_in_collection_bytes_excluded(self) -> None:
        action = AutomationTriggerAction()
        assert action._in_collection(b"a", b"abc") is False

    def test_compare_gt(self) -> None:
        action = AutomationTriggerAction()
        assert action._compare(10, 5, op="gt") is True
        assert action._compare(5, 10, op="gt") is False

    def test_compare_gte(self) -> None:
        action = AutomationTriggerAction()
        assert action._compare(10, 10, op="gte") is True
        assert action._compare(9, 10, op="gte") is False

    def test_compare_lt(self) -> None:
        action = AutomationTriggerAction()
        assert action._compare(3, 5, op="lt") is True
        assert action._compare(5, 3, op="lt") is False

    def test_compare_lte(self) -> None:
        action = AutomationTriggerAction()
        assert action._compare(5, 5, op="lte") is True
        assert action._compare(6, 5, op="lte") is False

    def test_compare_non_numeric_returns_false(self) -> None:
        action = AutomationTriggerAction()
        assert action._compare("abc", 5, op="gt") is False

    def test_compare_string_numbers(self) -> None:
        action = AutomationTriggerAction()
        assert action._compare("10", "5", op="gt") is True

    def test_evaluate_numeric_operator_unknown_direct(self) -> None:
        """_evaluate_numeric_operator raises KeyError for unknown op (unreachable via public API)."""
        action = AutomationTriggerAction()
        with pytest.raises(KeyError):
            action._evaluate_numeric_operator("unknown_op", 1, 5)

    def test_resolve_field_empty_path(self) -> None:
        action = AutomationTriggerAction()
        assert action._resolve_field({"key": "val"}, "") is None

    def test_resolve_field_missing_key(self) -> None:
        action = AutomationTriggerAction()
        assert action._resolve_field({"key": "val"}, "missing") is None

    def test_resolve_segment_mapping(self) -> None:
        action = AutomationTriggerAction()
        assert action._resolve_segment({"key": "val"}, "key") == "val"

    def test_resolve_segment_non_mapping_non_sequence(self) -> None:
        action = AutomationTriggerAction()
        assert action._resolve_segment(42, "0") is None

    def test_resolve_index_valid(self) -> None:
        action = AutomationTriggerAction()
        assert action._resolve_index([10, 20, 30], "1") == 20

    def test_resolve_index_negative(self) -> None:
        action = AutomationTriggerAction()
        assert action._resolve_index([10, 20], "-1") is None

    def test_resolve_index_out_of_bounds(self) -> None:
        action = AutomationTriggerAction()
        assert action._resolve_index([10], "5") is None

    def test_resolve_index_non_numeric_segment(self) -> None:
        action = AutomationTriggerAction()
        assert action._resolve_index([10, 20], "abc") is None

    def test_is_sequence_not_string_true(self) -> None:
        action = AutomationTriggerAction()
        assert action._is_sequence_not_string([1, 2]) is True

    def test_is_sequence_not_string_false_for_str(self) -> None:
        action = AutomationTriggerAction()
        assert action._is_sequence_not_string("hello") is False

    def test_is_sequence_not_string_false_for_bytes(self) -> None:
        action = AutomationTriggerAction()
        assert action._is_sequence_not_string(b"hello") is False

    def test_is_sequence_not_string_false_for_bytearray(self) -> None:
        action = AutomationTriggerAction()
        assert action._is_sequence_not_string(bytearray(b"hello")) is False

    def test_split_path_dot_notation(self) -> None:
        action = AutomationTriggerAction()
        assert action._split_path("a.b.c") == ["a", "b", "c"]

    def test_split_path_bracket_notation(self) -> None:
        action = AutomationTriggerAction()
        assert action._split_path("a[0].b[1]") == ["a", "0", "b", "1"]

    def test_split_path_strips_whitespace(self) -> None:
        action = AutomationTriggerAction()
        assert action._split_path("a . b ") == ["a", "b"]

    def test_split_path_empty_segments_filtered(self) -> None:
        action = AutomationTriggerAction()
        assert action._split_path("a..b") == ["a", "b"]


# ---------------------------------------------------------------------------
# Metadata / ActionMetadata tests for coverage
# ---------------------------------------------------------------------------


class TestActionMetadata:
    def test_task_schedule_action_metadata(self) -> None:
        m = TaskScheduleAction.metadata
        assert m.key == "task.schedule"
        assert m.provider == "builtin-task-schedule"
        assert "task" in m.domains
        assert "workflow" in m.domains
        assert "schedule" in m.capabilities
        assert m.requires_secrets is False
        assert m.side_effect_free is True
        assert m.settings_model is TaskScheduleSettings

    def test_automation_trigger_action_metadata(self) -> None:
        m = AutomationTriggerAction.metadata
        assert m.key == "automation.trigger"
        assert m.provider == "builtin-automation-trigger"
        assert "workflow" in m.domains
        assert "task" in m.domains
        assert "trigger" in m.capabilities
        assert "rules" in m.capabilities
        assert m.requires_secrets is False
        assert m.side_effect_free is True
        assert m.settings_model is AutomationTriggerSettings

    def test_task_schedule_action_init_defaults(self) -> None:
        action = TaskScheduleAction()
        assert action._settings.default_queue == "default"

    def test_task_schedule_action_init_custom_settings(self) -> None:
        settings = TaskScheduleSettings(default_queue="custom")
        action = TaskScheduleAction(settings=settings)
        assert action._settings.default_queue == "custom"

    def test_automation_trigger_action_init_defaults(self) -> None:
        action = AutomationTriggerAction()
        assert action._settings.max_rules == 20

    def test_automation_trigger_action_init_custom_settings(self) -> None:
        settings = AutomationTriggerSettings(max_rules=3)
        action = AutomationTriggerAction(settings=settings)
        assert action._settings.max_rules == 3
