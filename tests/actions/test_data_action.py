from __future__ import annotations

import pytest

from oneiric.actions.data import (
    DataSanitizeAction,
    DataSanitizeSettings,
    DataTransformAction,
    DataTransformSettings,
    ValidationFieldRule,
    ValidationSchemaAction,
    ValidationSchemaSettings,
)
from oneiric.core.lifecycle import LifecycleError


@pytest.mark.asyncio
async def test_data_transform_action_applies_rules() -> None:
    action = DataTransformAction(
        DataTransformSettings(
            include_fields=["id", "name", "status"],
            rename_fields={"name": "full_name"},
            defaults={"status": "pending", "priority": "low"},
        )
    )

    result = await action.execute({"data": {"id": 1, "name": "Oneiric", "extra": True}})

    assert result["status"] == "transformed"
    assert result["data"] == {
        "id": 1,
        "full_name": "Oneiric",
        "status": "pending",
        "priority": "low",
    }
    assert result["applied"]["rename_applied"] == 1
    assert result["applied"]["defaults_applied"] == 2


@pytest.mark.asyncio
async def test_data_transform_action_payload_overrides_settings() -> None:
    action = DataTransformAction(DataTransformSettings())
    payload = {
        "data": {"id": 2, "name": "Demo", "secret": "abc"},
        "exclude_fields": ["secret"],
        "rename_fields": {"name": "label"},
        "defaults": {"status": "ok"},
    }

    result = await action.execute(payload)

    assert result["data"] == {"id": 2, "label": "Demo", "status": "ok"}


@pytest.mark.asyncio
async def test_data_transform_action_requires_dict() -> None:
    action = DataTransformAction()

    with pytest.raises(LifecycleError):
        await action.execute({"data": "not-a-dict"})


@pytest.mark.asyncio
async def test_data_sanitize_action_masks_and_drops() -> None:
    action = DataSanitizeAction(
        DataSanitizeSettings(
            drop_fields=["secret"],
            mask_fields=["token"],
        )
    )

    payload = {
        "data": {
            "id": 1,
            "secret": "keep",
            "token": "abc",
            "email": "user@example.com",
        },
    }
    result = await action.execute(payload)

    assert result["status"] == "sanitized"
    assert "secret" not in result["data"]
    assert result["data"]["token"] == "***"
    assert result["applied"]["removed"] == 1
    assert result["applied"]["masked"] == 1


@pytest.mark.asyncio
async def test_data_sanitize_action_allowlist_case_insensitive() -> None:
    action = DataSanitizeAction(DataSanitizeSettings(allow_fields=["ID", "Name"]))

    result = await action.execute({"data": {"id": 3, "Name": "Case", "ignored": True}})

    assert result["data"] == {"id": 3, "Name": "Case"}


@pytest.mark.asyncio
async def test_validation_schema_action_detects_errors() -> None:
    action = ValidationSchemaAction(
        ValidationSchemaSettings(
            fields=[
                ValidationFieldRule(name="id", type="int"),
                ValidationFieldRule(name="email", type="str"),
            ],
            allow_extra=False,
        )
    )

    payload = {
        "data": {"id": "oops", "email": "ops@example.com", "extra": True},
    }

    result = await action.execute(payload)

    assert result["status"] == "invalid"
    assert any("id" in error for error in result["errors"])
    assert any("unexpected-fields" in error for error in result["errors"])


@pytest.mark.asyncio
async def test_validation_schema_action_valid_payload() -> None:
    action = ValidationSchemaAction(
        ValidationSchemaSettings(
            fields=[
                ValidationFieldRule(name="id", type="int"),
                ValidationFieldRule(
                    name="meta", type="dict", required=False, allow_null=True
                ),
            ]
        )
    )

    result = await action.execute({"data": {"id": 10, "meta": None, "extra": "ok"}})

    assert result["status"] == "valid"
    assert result["validated"]["id"] == 10


# --- DataTransform uncovered branches ---


@pytest.mark.asyncio
async def test_data_transform_include_fields_as_string() -> None:
    action = DataTransformAction()
    result = await action.execute({"data": {"x": 1, "y": 2}, "include_fields": "x"})
    assert result["data"] == {"x": 1}


@pytest.mark.asyncio
async def test_data_transform_include_fields_invalid_raises() -> None:
    action = DataTransformAction()
    with pytest.raises(LifecycleError, match="data-transform-list-invalid"):
        await action.execute({"data": {"x": 1}, "include_fields": 42})


@pytest.mark.asyncio
async def test_data_transform_rename_fields_non_mapping_raises() -> None:
    action = DataTransformAction()
    with pytest.raises(LifecycleError, match="data-transform-mapping-invalid"):
        await action.execute({"data": {"x": 1}, "rename_fields": "invalid"})


# --- DataSanitize uncovered branches ---


@pytest.mark.asyncio
async def test_data_sanitize_record_not_mapping_raises() -> None:
    action = DataSanitizeAction()
    with pytest.raises(LifecycleError, match="data-sanitize-record-required"):
        await action.execute({"data": "not-a-dict"})


@pytest.mark.asyncio
async def test_data_sanitize_allow_fields_as_string_in_payload() -> None:
    action = DataSanitizeAction()
    result = await action.execute({"data": {"id": 1, "secret": "x"}, "allow_fields": "id"})
    assert "id" in result["data"]
    assert "secret" not in result["data"]


@pytest.mark.asyncio
async def test_data_sanitize_drop_fields_as_iterable_in_payload() -> None:
    action = DataSanitizeAction()
    result = await action.execute(
        {"data": {"id": 1, "secret": "x"}, "drop_fields": ["secret"]}
    )
    assert "secret" not in result["data"]


@pytest.mark.asyncio
async def test_data_sanitize_allow_fields_invalid_type_raises() -> None:
    action = DataSanitizeAction()
    with pytest.raises(LifecycleError, match="data-sanitize-list-invalid"):
        await action.execute({"data": {"id": 1}, "allow_fields": 42})


# --- ValidationSchema uncovered branches ---


@pytest.mark.asyncio
async def test_validation_schema_record_not_mapping_raises() -> None:
    action = ValidationSchemaAction(
        ValidationSchemaSettings(fields=[ValidationFieldRule(name="id", type="int")])
    )
    with pytest.raises(LifecycleError, match="validation-schema-record-required"):
        await action.execute({"data": "string"})


@pytest.mark.asyncio
async def test_validation_schema_missing_required_field_recorded_as_none() -> None:
    action = ValidationSchemaAction(
        ValidationSchemaSettings(
            fields=[
                ValidationFieldRule(name="id", type="int"),
                ValidationFieldRule(name="name", type="str"),
            ]
        )
    )
    # "name" absent → value=None → error "name missing" → validated["name"] = None
    result = await action.execute({"data": {"id": 1}})
    assert result["status"] == "invalid"
    assert "name" in result["validated"]
    assert result["validated"]["name"] is None


@pytest.mark.asyncio
async def test_validation_schema_fail_fast_stops_at_first_error() -> None:
    action = ValidationSchemaAction(
        ValidationSchemaSettings(
            fields=[
                ValidationFieldRule(name="id", type="int"),
                ValidationFieldRule(name="name", type="str"),
            ]
        )
    )
    # Non-empty record so the data lookup doesn't fail; both fields are absent
    result = await action.execute({"data": {"other": 1}, "fail_fast": True})
    assert result["status"] == "invalid"
    assert len(result["errors"]) == 1


@pytest.mark.asyncio
async def test_validation_schema_fields_from_payload_as_list() -> None:
    action = ValidationSchemaAction()
    result = await action.execute(
        {
            "data": {"score": 10},
            "fields": [{"name": "score", "type": "int"}],
        }
    )
    assert result["status"] == "valid"


@pytest.mark.asyncio
async def test_validation_schema_fields_invalid_type_raises() -> None:
    action = ValidationSchemaAction()
    with pytest.raises(LifecycleError, match="validation-schema-fields-invalid"):
        await action.execute({"data": {"id": 1}, "fields": 42})
