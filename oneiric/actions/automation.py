"""Automation trigger/rule evaluation action kit."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from oneiric.actions.metadata import ActionMetadata
from oneiric.actions.payloads import normalize_payload
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class AutomationCondition(BaseModel):
    """Declarative condition applied to context payloads."""

    field: str = Field(description="Dotted path referencing a context field.")
    operator: Literal[
        "equals",
        "not_equals",
        "contains",
        "in",
        "greater_than",
        "greater_or_equal",
        "less_than",
        "less_or_equal",
        "exists",
        "absent",
        "truthy",
        "falsy",
    ] = Field(description="Comparison operator.")
    value: Any = Field(
        default=None,
        description="Comparison value when required by the operator.",
    )


class AutomationRule(BaseModel):
    """Rule describing an action to trigger when all conditions match."""

    name: str = Field(description="Rule identifier for observability.")
    action: str = Field(description="Action key to trigger when the rule matches.")
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Payload forwarded to downstream resolvers.",
    )
    stop_on_match: bool = Field(
        default=False,
        description="When true, stop evaluating subsequent rules.",
    )
    conditions: list[AutomationCondition] = Field(
        default_factory=list,
        description="List of conditions that must all evaluate True.",
    )


class AutomationTriggerPayload(BaseModel):
    """Typed payload for automation triggers."""

    model_config = ConfigDict(extra="forbid")

    context: Mapping[str, Any] = Field(
        default_factory=dict,
        description="Context dictionary inspected by rules.",
    )
    rules: list[AutomationRule] = Field(
        min_length=1,
        description="Rule list evaluated in order.",
    )
    stop_on_first_match: bool | None = Field(
        default=None,
        description="Override to stop after the first matching rule.",
    )


class AutomationTriggerSettings(BaseModel):
    """Settings for automation trigger evaluation."""

    max_rules: int = Field(
        default=20,
        ge=1,
        le=200,
        description="Safety cap for number of rules per invocation.",
    )


class AutomationTriggerAction:
    """Action kit that evaluates declarative automation rules."""

    metadata = ActionMetadata(
        key="automation.trigger",
        provider="builtin-automation-trigger",
        factory="oneiric.actions.automation:AutomationTriggerAction",
        description="Evaluates declarative automation rules and emits the matched actions/payloads",
        domains=["workflow", "task"],
        capabilities=["trigger", "rules", "selection"],
        stack_level=38,
        priority=365,
        source=CandidateSource.LOCAL_PKG,
        owner="Platform Core",
        requires_secrets=False,
        side_effect_free=True,
        settings_model=AutomationTriggerSettings,
    )

    def __init__(self, settings: AutomationTriggerSettings | None = None) -> None:
        self._settings = settings or AutomationTriggerSettings()
        self._logger = get_logger("action.automation.trigger")

    async def execute(self, payload: dict | None = None) -> dict:
        payload = normalize_payload(payload)
        try:
            request = AutomationTriggerPayload.model_validate(payload)
        except ValidationError as exc:
            raise LifecycleError("automation-trigger-payload-invalid") from exc
        if len(request.rules) > self._settings.max_rules:
            raise LifecycleError("automation-trigger-rule-limit")
        context = self._coerce_mapping(request.context)
        stop_after_first = request.stop_on_first_match
        matched: list[dict[str, Any]] = []
        evaluated_rules = 0
        for rule in request.rules:
            evaluated_rules += 1
            if self._rule_matches(rule, context):
                matched.append(
                    {
                        "name": rule.name,
                        "action": rule.action,
                        "payload": rule.payload,
                        "condition_count": len(rule.conditions),
                    }
                )
                if rule.stop_on_match or stop_after_first:
                    break
        status = "triggered" if matched else "noop"
        self._logger.info(
            "automation-action-trigger",
            matched=len(matched),
            evaluated=evaluated_rules,
            stop_on_first=stop_after_first,
        )
        return {
            "status": status,
            "matched_rules": matched,
            "evaluated_rules": evaluated_rules,
            "context": context,
        }

    def _coerce_mapping(self, value: Mapping[str, Any] | Any) -> dict[str, Any]:
        if isinstance(value, Mapping):
            return {str(key): value[key] for key in value}
        raise LifecycleError("automation-trigger-context-invalid")

    def _rule_matches(self, rule: AutomationRule, context: Mapping[str, Any]) -> bool:
        for condition in rule.conditions:
            if not self._condition_matches(condition, context):
                return False
        return True

    def _condition_matches(
        self, condition: AutomationCondition, context: Mapping[str, Any]
    ) -> bool:
        actual = self._resolve_field(context, condition.field)
        op = condition.operator
        expected = condition.value

        # Simple comparison operators
        if op == "equals":
            return actual == expected
        if op == "not_equals":
            return actual != expected

        # Collection operators
        if op == "contains":
            return self._contains(actual, expected)
        if op == "in":
            return self._in_collection(actual, expected)

        # Numeric comparison operators
        if op in {"greater_than", "greater_or_equal", "less_than", "less_or_equal"}:
            return self._evaluate_numeric_operator(op, actual, expected)

        # Existence operators
        if op == "exists":
            return actual is not None
        if op == "absent":
            return actual is None

        # Boolean operators
        if op == "truthy":
            return bool(actual)
        if op == "falsy":
            return not bool(actual)

        raise LifecycleError("automation-trigger-operator-invalid")

    def _evaluate_numeric_operator(self, op: str, actual: Any, expected: Any) -> bool:
        """Evaluate numeric comparison operators."""
        comparison_map = {
            "greater_than": "gt",
            "greater_or_equal": "gte",
            "less_than": "lt",
            "less_or_equal": "lte",
        }
        return self._compare(actual, expected, op=comparison_map[op])

    def _contains(self, actual: Any, expected: Any) -> bool:
        if actual is None:
            return False
        if isinstance(actual, str):
            return str(expected) in actual
        if isinstance(actual, Mapping):
            return str(expected) in actual
        if isinstance(actual, Sequence) and not isinstance(
            actual, (str, bytes, bytearray)
        ):
            return expected in actual
        return False

    def _in_collection(self, actual: Any, collection: Any) -> bool:
        if isinstance(collection, Sequence) and not isinstance(
            collection, (str, bytes, bytearray)
        ):
            return actual in collection
        return False

    def _compare(self, actual: Any, expected: Any, *, op: str) -> bool:
        try:
            actual_value = float(actual)
            expected_value = float(expected)
        except (TypeError, ValueError):
            return False
        if op == "gt":
            return actual_value > expected_value
        if op == "gte":
            return actual_value >= expected_value
        if op == "lt":
            return actual_value < expected_value
        if op == "lte":
            return actual_value <= expected_value
        return False

    def _resolve_field(self, context: Mapping[str, Any], path: str) -> Any:
        if not path:
            return None
        segments = self._split_path(path)
        current: Any = context
        for segment in segments:
            current = self._resolve_segment(current, segment)
            if current is None:
                return None
        return current

    def _resolve_segment(self, current: Any, segment: str) -> Any:
        """Resolve a single segment of a path."""
        if isinstance(current, Mapping):
            return current.get(segment)

        if self._is_sequence_not_string(current):
            return self._resolve_index(current, segment)

        return None

    def _is_sequence_not_string(self, value: Any) -> bool:
        """Check if value is a sequence but not a string."""
        return isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        )

    def _resolve_index(self, sequence: Sequence, segment: str) -> Any:
        """Resolve an index in a sequence."""
        try:
            index = int(segment)
        except ValueError:
            return None

        if 0 <= index < len(sequence):
            return sequence[index]

        return None

    def _split_path(self, path: str) -> list[str]:
        normalized = path.replace("[", ".").replace("]", ".")
        segments = [
            segment.strip() for segment in normalized.split(".") if segment.strip()
        ]
        return segments


__all__ = ["AutomationTriggerAction", "AutomationTriggerSettings"]
