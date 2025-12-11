"""Tests for the DynamoDB adapter."""

from __future__ import annotations

from typing import Any

import pytest

from oneiric.adapters.nosql.common import NoSQLDocument
from oneiric.adapters.nosql.dynamodb import DynamoDBAdapter, DynamoDBSettings


class FakeTable:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []
        self.get_params: list[dict[str, Any]] = []
        self.put_items: list[dict[str, Any]] = []
        self.update_calls: list[dict[str, Any]] = []
        self.delete_calls: list[dict[str, Any]] = []
        self.scan_calls: int = 0

    async def load(self) -> None:
        return None

    async def get_item(self, **kwargs: Any) -> dict[str, Any]:
        self.get_params.append(kwargs)
        key = kwargs.get("Key", {})
        for item in self.items:
            if all(item.get(k) == v for k, v in key.items()):
                return {"Item": item}
        return {}

    async def put_item(self, **kwargs: Any) -> None:
        self.put_items.append(kwargs)
        self.items.append(kwargs["Item"])

    async def update_item(self, **kwargs: Any) -> dict[str, Any]:
        self.update_calls.append(kwargs)
        return {"Attributes": {"status": "updated"}}

    async def delete_item(self, **kwargs: Any) -> None:
        self.delete_calls.append(kwargs)
        key = kwargs.get("Key", {})
        self.items = [
            item
            for item in self.items
            if not all(item.get(k) == v for k, v in key.items())
        ]

    async def scan(self, **kwargs: Any) -> dict[str, Any]:
        self.scan_calls += 1
        return {"Items": list(self.items)}


@pytest.fixture()
def fake_table() -> FakeTable:
    return FakeTable()


@pytest.fixture()
def adapter(fake_table: FakeTable) -> DynamoDBAdapter:
    settings = DynamoDBSettings(table_name="demo_table", primary_key_field="id")
    return DynamoDBAdapter(settings, table_factory=lambda: fake_table)


@pytest.mark.asyncio()
async def test_get_item_returns_document(
    adapter: DynamoDBAdapter, fake_table: FakeTable
) -> None:
    fake_table.items.append({"id": "123", "value": "demo"})
    document = await adapter.get_item({"id": "123"})
    assert isinstance(document, NoSQLDocument)
    assert document.id == "123"
    assert document.data == {"value": "demo"}
    assert fake_table.get_params[-1]["ConsistentRead"] is False


@pytest.mark.asyncio()
async def test_put_update_delete_flow(
    adapter: DynamoDBAdapter, fake_table: FakeTable
) -> None:
    await adapter.put_item({"id": "a", "value": "1"})
    assert fake_table.put_items[-1]["Item"]["value"] == "1"

    updated = await adapter.update_item(
        {"id": "a"},
        update_expression="SET #v = :value",
        expression_attribute_values={":value": "2"},
    )
    assert updated == {"status": "updated"}
    assert fake_table.update_calls[-1]["UpdateExpression"] == "SET #v = :value"

    deleted = await adapter.delete_item({"id": "a"})
    assert deleted is True
    assert fake_table.delete_calls[-1]["Key"] == {"id": "a"}


@pytest.mark.asyncio()
async def test_scan_returns_documents(
    adapter: DynamoDBAdapter, fake_table: FakeTable
) -> None:
    fake_table.items.extend([{"id": "1", "value": "x"}, {"id": "2", "value": "y"}])
    documents = await adapter.scan()
    assert [doc.id for doc in documents] == ["1", "2"]
    assert fake_table.scan_calls == 1


@pytest.mark.asyncio()
async def test_health_uses_table_load(
    adapter: DynamoDBAdapter, fake_table: FakeTable
) -> None:
    healthy = await adapter.health()
    assert healthy is True
