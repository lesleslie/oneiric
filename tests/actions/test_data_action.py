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
    assert result["data"] == {"id": 1, "full_name": "Oneiric", "status": "pending", "priority": "low"}
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
        "data": {"id": 1, "secret": "keep", "token": "abc", "email": "user@example.com"},
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
                ValidationFieldRule(name="meta", type="dict", required=False, allow_null=True),
            ]
        )
    )

    result = await action.execute({"data": {"id": 10, "meta": None, "extra": "ok"}})

    assert result["status"] == "valid"
    assert result["validated"]["id"] == 10
