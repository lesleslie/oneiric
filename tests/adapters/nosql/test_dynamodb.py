"""Tests for the DynamoDB adapter."""

from __future__ import annotations

from typing import Any

import pytest

from oneiric.adapters.nosql.dynamodb import DynamoDBAdapter, DynamoDBSettings
from oneiric.adapters.nosql.nosql_types import NoSQLDocument


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


# ---------------------------------------------------------------------------
# Tests — coverage gaps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_init_and_cleanup() -> None:
    """init() and cleanup() log info and nil _session (lines 83-84, 98-99)."""
    settings = DynamoDBSettings(table_name="demo", primary_key_field="id")
    adapter = DynamoDBAdapter(settings, session_factory=lambda: object())
    await adapter.init()
    await adapter.cleanup()
    assert adapter._session is None


@pytest.mark.asyncio()
async def test_put_item_with_condition_expression(
    adapter: DynamoDBAdapter, fake_table: FakeTable
) -> None:
    """put_item passes ConditionExpression when set (line 123)."""
    await adapter.put_item({"id": "x"}, condition_expression="attribute_not_exists(id)")
    assert "ConditionExpression" in fake_table.put_items[-1]


@pytest.mark.asyncio()
async def test_update_item_with_condition_expression(
    adapter: DynamoDBAdapter, fake_table: FakeTable
) -> None:
    """update_item passes ConditionExpression when set (line 143)."""
    await adapter.update_item(
        {"id": "x"},
        update_expression="SET v = :v",
        expression_attribute_values={":v": 1},
        condition_expression="attribute_exists(id)",
    )
    assert "ConditionExpression" in fake_table.update_calls[-1]


@pytest.mark.asyncio()
async def test_delete_item_with_condition_expression(
    adapter: DynamoDBAdapter, fake_table: FakeTable
) -> None:
    """delete_item passes ConditionExpression when set (line 153)."""
    await adapter.delete_item({"id": "x"}, condition_expression="attribute_exists(id)")
    assert "ConditionExpression" in fake_table.delete_calls[-1]


@pytest.mark.asyncio()
async def test_scan_with_limit(adapter: DynamoDBAdapter, fake_table: FakeTable) -> None:
    """scan() passes Limit kwarg when limit is provided (line 161)."""
    fake_table.items.append({"id": "1", "v": "a"})
    await adapter.scan(limit=5)
    assert fake_table.scan_calls == 1


@pytest.mark.asyncio()
async def test_table_factory_awaitable() -> None:
    """_table() awaits factory result when it returns a coroutine (line 193)."""
    table = FakeTable()

    async def async_table_factory() -> FakeTable:
        return table

    settings = DynamoDBSettings(table_name="t", primary_key_field="id")
    adapter = DynamoDBAdapter(settings, table_factory=async_table_factory)
    table.items.append({"id": "z"})
    docs = await adapter.scan()
    assert docs[0].id == "z"


@pytest.mark.asyncio()
async def test_ensure_session_with_custom_factory() -> None:
    """_ensure_session uses session_factory when provided (lines 167-186)."""
    class FakeSession:
        pass

    session = FakeSession()
    settings = DynamoDBSettings(table_name="t", primary_key_field="id")
    adapter = DynamoDBAdapter(settings, session_factory=lambda: session)
    result = adapter._ensure_session()
    assert result is session
    assert adapter._session is session
    # Second call returns cached session (line 168)
    result2 = adapter._ensure_session()
    assert result2 is session


@pytest.mark.asyncio()
async def test_ensure_session_with_aioboto3_mock(monkeypatch) -> None:
    """_ensure_session imports aioboto3 and creates Session (lines 171-186)."""
    import sys
    import types

    class FakeAioboto3Session:
        pass

    fake_aioboto3 = types.ModuleType("aioboto3")
    fake_aioboto3.Session = FakeAioboto3Session  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "aioboto3", fake_aioboto3)

    settings = DynamoDBSettings(table_name="t", primary_key_field="id")
    adapter = DynamoDBAdapter(settings)
    session = adapter._ensure_session()
    assert isinstance(session, FakeAioboto3Session)


@pytest.mark.asyncio()
async def test_ensure_session_with_profile(monkeypatch) -> None:
    """_ensure_session wraps aioboto3.Session with profile_name when set (lines 179-181)."""
    import sys
    import types

    created: list[dict] = []

    class FakeAioboto3Session:
        def __init__(self, profile_name: str | None = None) -> None:
            created.append({"profile_name": profile_name})

    fake_aioboto3 = types.ModuleType("aioboto3")
    fake_aioboto3.Session = FakeAioboto3Session  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "aioboto3", fake_aioboto3)

    settings = DynamoDBSettings(table_name="t", primary_key_field="id", profile_name="my-profile")
    adapter = DynamoDBAdapter(settings)
    adapter._ensure_session()
    assert created[0]["profile_name"] == "my-profile"


@pytest.mark.asyncio()
async def test_table_via_session_path() -> None:
    """_table() uses session.resource when no table_factory (lines 196-219)."""
    inner_table = FakeTable()
    inner_table.items.append({"id": "sess-1", "v": "ok"})

    class FakeDynamoDB:
        def Table(self, name: str) -> FakeTable:
            return inner_table

    class FakeResource:
        async def __aenter__(self) -> FakeDynamoDB:
            return FakeDynamoDB()

        async def __aexit__(self, *_: Any) -> None:
            pass

    class FakeSession:
        def resource(self, service: str, **kwargs: Any) -> FakeResource:
            return FakeResource()

    settings = DynamoDBSettings(table_name="t", primary_key_field="id")
    adapter = DynamoDBAdapter(settings, session_factory=lambda: FakeSession())
    docs = await adapter.scan()
    assert docs[0].id == "sess-1"


@pytest.mark.asyncio()
async def test_table_via_session_with_credentials() -> None:
    """_table() merges credentials into resource_kwargs when set (lines 200-215)."""
    from pydantic import SecretStr

    inner_table = FakeTable()

    class FakeDynamoDB:
        def Table(self, name: str) -> FakeTable:
            return inner_table

    class FakeResource:
        async def __aenter__(self) -> FakeDynamoDB:
            return FakeDynamoDB()

        async def __aexit__(self, *_: Any) -> None:
            pass

    class FakeSession:
        def resource(self, service: str, **kwargs: Any) -> FakeResource:
            self.last_kwargs = kwargs
            return FakeResource()

    session = FakeSession()
    settings = DynamoDBSettings(
        table_name="t",
        primary_key_field="id",
        aws_access_key_id=SecretStr("AKID"),
        aws_secret_access_key=SecretStr("SECRET"),
    )
    adapter = DynamoDBAdapter(settings, session_factory=lambda: session)
    await adapter.scan()
    assert session.last_kwargs.get("aws_access_key_id") == "AKID"


def test_document_from_item_none_returns_none(adapter: DynamoDBAdapter) -> None:
    """_document_from_item(None) returns None (line 223)."""
    assert adapter._document_from_item(None) is None
    assert adapter._document_from_item({}) is None
