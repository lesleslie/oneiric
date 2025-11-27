"""Data processing/enrichment/validation action kits."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional
from typing import Literal

from pydantic import BaseModel, Field

from oneiric.actions.metadata import ActionMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class DataTransformSettings(BaseModel):
    """Settings governing field selection/renaming/defaults."""

    include_fields: Optional[list[str]] = Field(
        default=None,
        description="When set, only these fields survive the transform.",
    )
    exclude_fields: list[str] = Field(
        default_factory=list,
        description="Fields dropped from the payload.",
    )
    rename_fields: Dict[str, str] = Field(
        default_factory=dict,
        description="Field rename map (source -> destination).",
    )
    defaults: Dict[str, Any] = Field(
        default_factory=dict,
        description="Default values applied when keys are missing.",
    )


class DataTransformAction:
    """Action kit that reshapes dictionaries using declarative rules."""

    metadata = ActionMetadata(
        key="data.transform",
        provider="builtin-data-transform",
        factory="oneiric.actions.data:DataTransformAction",
        description="Data processing helper for selecting/renaming fields and applying defaults",
        domains=["task", "service", "workflow"],
        capabilities=["transform", "enrich", "validate"],
        stack_level=35,
        priority=395,
        source=CandidateSource.LOCAL_PKG,
        owner="Data Platform",
        requires_secrets=False,
        side_effect_free=True,
        settings_model=DataTransformSettings,
    )

    def __init__(self, settings: DataTransformSettings | None = None) -> None:
        self._settings = settings or DataTransformSettings()
        self._logger = get_logger("action.data.transform")

    async def execute(self, payload: dict | None = None) -> dict:
        payload = payload or {}
        record = payload.get("data") or payload.get("record")
        if not isinstance(record, Mapping):
            raise LifecycleError("data-transform-record-required")
        include_fields = self._coerce_optional_list(payload.get("include_fields"), default=self._settings.include_fields)
        exclude_fields = self._coerce_list(payload.get("exclude_fields"), default=self._settings.exclude_fields)
        rename_fields = self._coerce_mapping(payload.get("rename_fields"), default=self._settings.rename_fields)
        defaults = self._coerce_mapping(payload.get("defaults"), default=self._settings.defaults)
        result = self._apply_include(record, include_fields)
        if exclude_fields:
            for field in exclude_fields:
                result.pop(field, None)
        rename_applied = 0
        for source, target in rename_fields.items():
            if source in result:
                result[target] = result.pop(source)
                rename_applied += 1
        defaults_applied = 0
        for key, value in defaults.items():
            if key not in result:
                result[key] = value
                defaults_applied += 1
        self._logger.info(
            "data-action-transform",
            include_count=len(include_fields) if include_fields else None,
            exclude_count=len(exclude_fields),
            rename_applied=rename_applied,
            defaults_applied=defaults_applied,
        )
        return {
            "status": "transformed",
            "data": result,
            "applied": {
                "include_fields": include_fields,
                "exclude_fields": exclude_fields,
                "rename_applied": rename_applied,
                "defaults_applied": defaults_applied,
            },
        }

    def _apply_include(self, record: Mapping[str, Any], include_fields: Optional[list[str]]) -> Dict[str, Any]:
        if include_fields:
            return {field: record[field] for field in include_fields if field in record}
        return dict(record)

    def _coerce_optional_list(
        self,
        value: Any,
        *,
        default: Optional[list[str]],
    ) -> Optional[list[str]]:
        if value is None:
            return list(default) if default else None
        if isinstance(value, str):
            return [value]
        if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
            coerced = [str(item) for item in value]
            return coerced
        raise LifecycleError("data-transform-list-invalid")

    def _coerce_list(self, value: Any, *, default: Optional[list[str]]) -> list[str]:
        result = self._coerce_optional_list(value, default=default)
        return result or []

    def _coerce_mapping(self, value: Any, *, default: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if value is None:
            return dict(default) if default else {}
        if isinstance(value, Mapping):
            return {str(key): value[key] for key in value}
        raise LifecycleError("data-transform-mapping-invalid")


class DataSanitizeSettings(BaseModel):
    """Settings controlling sanitization behavior."""

    allow_fields: Optional[list[str]] = Field(
        default=None,
        description="Optional allowlist restricting which fields survive sanitization.",
    )
    drop_fields: list[str] = Field(
        default_factory=list,
        description="Fields removed from the payload after allowlist enforcement.",
    )
    mask_fields: list[str] = Field(
        default_factory=list,
        description="Fields replaced with the configured mask value.",
    )
    mask_value: Any = Field(
        default="***",
        description="Replacement value applied to masked fields.",
    )
    case_sensitive: bool = Field(
        default=False,
        description="Whether field comparisons are case-sensitive.",
    )


class DataSanitizeAction:
    """Action kit that drops/masks sensitive fields."""

    metadata = ActionMetadata(
        key="data.sanitize",
        provider="builtin-data-sanitize",
        factory="oneiric.actions.data:DataSanitizeAction",
        description="Sanitizes payloads by masking or removing sensitive fields",
        domains=["task", "service", "workflow"],
        capabilities=["sanitize", "redact", "filter"],
        stack_level=35,
        priority=390,
        source=CandidateSource.LOCAL_PKG,
        owner="Data Platform",
        requires_secrets=False,
        side_effect_free=True,
        settings_model=DataSanitizeSettings,
    )

    def __init__(self, settings: DataSanitizeSettings | None = None) -> None:
        self._settings = settings or DataSanitizeSettings()
        self._logger = get_logger("action.data.sanitize")

    async def execute(self, payload: dict | None = None) -> dict:
        payload = payload or {}
        record = payload.get("data") or payload.get("record")
        if not isinstance(record, Mapping):
            raise LifecycleError("data-sanitize-record-required")
        case_sensitive = payload.get("case_sensitive")
        if case_sensitive is None:
            case_sensitive = self._settings.case_sensitive
        allow_fields = self._coerce_optional_list(
            payload.get("allow_fields"),
            default=self._settings.allow_fields,
        )
        drop_fields = self._coerce_list(payload.get("drop_fields"), default=self._settings.drop_fields)
        mask_fields = self._coerce_list(payload.get("mask_fields"), default=self._settings.mask_fields)
        mask_value = payload.get("mask_value", self._settings.mask_value)

        def normalize(name: Any) -> str:
            key = str(name)
            return key if case_sensitive else key.lower()

        normalized_allow = {normalize(field) for field in allow_fields} if allow_fields else None
        normalized_drop = {normalize(field) for field in drop_fields}
        normalized_mask = {normalize(field) for field in mask_fields}

        sanitized = {}
        for key, value in record.items():
            normalized_key = normalize(key)
            if normalized_allow is not None and normalized_key not in normalized_allow:
                continue
            sanitized[str(key)] = value

        removed = 0
        for key in list(sanitized.keys()):
            if normalize(key) in normalized_drop:
                sanitized.pop(key)
                removed += 1

        masked = 0
        for key in sanitized.keys():
            if normalize(key) in normalized_mask:
                sanitized[key] = mask_value
                masked += 1

        self._logger.info(
            "data-action-sanitize",
            removed=removed,
            masked=masked,
            allow_count=len(normalized_allow) if normalized_allow else None,
        )
        return {
            "status": "sanitized",
            "data": sanitized,
            "applied": {
                "removed": removed,
                "masked": masked,
                "allow_fields": allow_fields,
            },
        }

    def _coerce_optional_list(
        self,
        value: Any,
        *,
        default: Optional[list[str]],
    ) -> Optional[list[str]]:
        if value is None:
            return list(default) if default else None
        if isinstance(value, str):
            return [value]
        if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
            return [str(item) for item in value]
        raise LifecycleError("data-sanitize-list-invalid")

    def _coerce_list(self, value: Any, *, default: Optional[list[str]]) -> list[str]:
        result = self._coerce_optional_list(value, default=default)
        return result or []


class ValidationFieldRule(BaseModel):
    """Rule describing a field requirement."""

    name: str
    type: Literal["str", "int", "float", "bool", "dict", "list", "any"] = Field(default="str")
    required: bool = Field(default=True)
    allow_null: bool = Field(default=False)


class ValidationSchemaSettings(BaseModel):
    """Settings for schema validation action."""

    fields: list[ValidationFieldRule] = Field(default_factory=list)
    allow_extra: bool = Field(
        default=True,
        description="Allow payloads to contain keys beyond the declared schema.",
    )
    fail_fast: bool = Field(
        default=False,
        description="Stop validation on the first error instead of collecting all errors.",
    )


class ValidationSchemaAction:
    """Action kit that validates payloads with lightweight schema rules."""

    metadata = ActionMetadata(
        key="validation.schema",
        provider="builtin-validation-schema",
        factory="oneiric.actions.data:ValidationSchemaAction",
        description="Validates records against declarative field requirements",
        domains=["task", "service", "workflow"],
        capabilities=["validate", "guard", "schema"],
        stack_level=35,
        priority=385,
        source=CandidateSource.LOCAL_PKG,
        owner="Platform Core",
        requires_secrets=False,
        side_effect_free=True,
        settings_model=ValidationSchemaSettings,
    )

    _TYPE_MAP = {
        "str": (str,),
        "int": (int,),
        "float": (float, int),
        "bool": (bool,),
        "dict": (dict,),
        "list": (list,),
        "any": (object,),
    }

    def __init__(self, settings: ValidationSchemaSettings | None = None) -> None:
        self._settings = settings or ValidationSchemaSettings()
        self._logger = get_logger("action.validation.schema")

    async def execute(self, payload: dict | None = None) -> dict:
        payload = payload or {}
        record = payload.get("data") or payload.get("record")
        if not isinstance(record, Mapping):
            raise LifecycleError("validation-schema-record-required")
        fields = self._resolve_fields(payload.get("fields"))
        allow_extra = payload.get("allow_extra")
        if allow_extra is None:
            allow_extra = self._settings.allow_extra
        fail_fast = payload.get("fail_fast")
        if fail_fast is None:
            fail_fast = self._settings.fail_fast
        errors: list[str] = []
        validated: dict[str, Any] = {}
        required_names = {rule.name for rule in fields if rule.required}

        for rule in fields:
            value = record.get(rule.name)
            if value is None:
                if not rule.allow_null and rule.required:
                    errors.append(f"{rule.name} missing")
                    if fail_fast:
                        break
                validated[rule.name] = value
                continue
            expected = self._TYPE_MAP.get(rule.type, (object,))
            if not isinstance(value, expected):
                errors.append(f"{rule.name} invalid-type")
                if fail_fast:
                    break
                continue
            validated[rule.name] = value

        if not allow_extra:
            extra = [str(key) for key in record.keys() if key not in {rule.name for rule in fields}]
            if extra:
                errors.append(f"unexpected-fields: {','.join(extra)}")

        status = "valid" if not errors else "invalid"
        self._logger.info(
            "validation-action-schema",
            status=status,
            error_count=len(errors),
            required=len(required_names),
        )
        return {
            "status": status,
            "data": record,
            "validated": validated,
            "errors": errors,
        }

    def _resolve_fields(self, payload_fields: Any) -> list[ValidationFieldRule]:
        if payload_fields is None:
            return list(self._settings.fields)
        if isinstance(payload_fields, Iterable):
            return [ValidationFieldRule(**item) if not isinstance(item, ValidationFieldRule) else item for item in payload_fields]
        raise LifecycleError("validation-schema-fields-invalid")
