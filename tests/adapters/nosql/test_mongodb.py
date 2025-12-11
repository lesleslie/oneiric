"""Unit tests for the MongoDB adapter."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from oneiric.adapters.nosql.common import NoSQLDocument, NoSQLQuery
from oneiric.adapters.nosql.mongodb import MongoDBAdapter, MongoDBSettings


class FakeCursor:
    def __init__(self, results: list[dict[str, Any]]) -> None:
        self.results = results
        self.sort_spec: list[tuple[str, int]] | None = None
        self.limit_value: int | None = None
        self.to_list_length: int | None = None

    def sort(self, spec: list[tuple[str, int]]) -> FakeCursor:
        self.sort_spec = spec
        return self

    def limit(self, limit: int) -> FakeCursor:
        self.limit_value = limit
        return self

    async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
        self.to_list_length = length
        if length is None:
            return list(self.results)
        return list(self.results[:length])


class FakeCollection:
    def __init__(self) -> None:
        self.find_one_calls: list[tuple[dict[str, Any], dict[str, int] | None]] = []
        self.find_calls: list[tuple[dict[str, Any], dict[str, int] | None]] = []
        self.last_pipeline: list[dict[str, Any]] | None = None
        self.last_cursor: FakeCursor | None = None
        self.find_one_result: dict[str, Any] | None = None
        self.find_results: list[dict[str, Any]] = []
        self.aggregate_results: list[dict[str, Any]] = []

    async def find_one(
        self, filters: dict[str, Any], projection: dict[str, int] | None = None
    ) -> Any:
        self.find_one_calls.append((filters, projection))
        return self.find_one_result

    def find(
        self, filters: dict[str, Any], projection: dict[str, int] | None = None
    ) -> FakeCursor:
        self.find_calls.append((filters, projection))
        cursor = FakeCursor(self.find_results)
        self.last_cursor = cursor
        return cursor

    async def insert_one(self, document: dict[str, Any]) -> Any:
        self.last_insert = document
        return SimpleNamespace(inserted_id="abc123")

    async def update_one(
        self, filters: dict[str, Any], update: dict[str, Any], upsert: bool = False
    ) -> Any:
        self.last_update = (filters, update, upsert)
        return SimpleNamespace(matched_count=1)

    async def delete_one(self, filters: dict[str, Any]) -> Any:
        self.last_delete = filters
        return SimpleNamespace(deleted_count=1)

    def aggregate(self, pipeline: list[dict[str, Any]]) -> FakeCursor:
        self.last_pipeline = pipeline
        cursor = FakeCursor(self.aggregate_results)
        self.last_cursor = cursor
        return cursor


class FakeDatabase:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        collection = self.collections.get(name)
        if not collection:
            collection = FakeCollection()
            self.collections[name] = collection
        return collection


class FakeAdmin:
    def __init__(self) -> None:
        self.pings = 0

    async def command(self, cmd: str) -> None:
        if cmd == "ping":
            self.pings += 1
        else:  # pragma: no cover - defensive
            raise ValueError("unsupported command")


class FakeClient:
    def __init__(self) -> None:
        self.admin = FakeAdmin()
        self.databases: dict[str, FakeDatabase] = {}
        self.closed = False

    def __getitem__(self, name: str) -> FakeDatabase:
        db = self.databases.get(name)
        if not db:
            db = FakeDatabase()
            self.databases[name] = db
        return db

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def fake_client() -> FakeClient:
    return FakeClient()


@pytest.fixture()
def adapter(fake_client: FakeClient) -> MongoDBAdapter:
    settings = MongoDBSettings(database="test_db", default_collection="items")

    def factory(**_: Any) -> FakeClient:
        return fake_client

    return MongoDBAdapter(settings, client_factory=factory)


@pytest.mark.asyncio()
async def test_init_pings_server(
    adapter: MongoDBAdapter, fake_client: FakeClient
) -> None:
    await adapter.init()
    assert fake_client.admin.pings == 1


@pytest.mark.asyncio()
async def test_find_one_returns_document(
    adapter: MongoDBAdapter, fake_client: FakeClient
) -> None:
    await adapter.init()
    collection = fake_client["test_db"]["items"]
    collection.find_one_result = {"_id": 123, "value": "ok"}

    document = await adapter.find_one({"value": "ok"})

    assert isinstance(document, NoSQLDocument)
    assert document.id == "123"
    assert document.data == {"value": "ok"}
    assert collection.find_one_calls[-1][0] == {"value": "ok"}


@pytest.mark.asyncio()
async def test_find_respects_query_params(
    adapter: MongoDBAdapter, fake_client: FakeClient
) -> None:
    await adapter.init()
    collection = fake_client["test_db"]["items"]
    collection.find_results = [
        {"_id": "42", "value": "a"},
        {"_id": "43", "value": "b"},
    ]
    query = NoSQLQuery(
        filters={"value": {"$exists": True}},
        projection=["value"],
        limit=1,
        sort=[("value", 1)],
    )

    documents = await adapter.find(query)

    assert len(documents) == 1
    assert documents[0].id == "42"
    filters, projection = collection.find_calls[-1]
    assert filters == {"value": {"$exists": True}}
    assert projection == {"value": 1}
    assert collection.last_cursor is not None
    assert collection.last_cursor.sort_spec == [("value", 1)]
    assert collection.last_cursor.limit_value == 1


@pytest.mark.asyncio()
async def test_insert_update_delete_flow(
    adapter: MongoDBAdapter, fake_client: FakeClient
) -> None:
    await adapter.init()
    collection = fake_client["test_db"]["items"]

    inserted_id = await adapter.insert_one({"value": "a"})
    assert inserted_id == "abc123"

    updated = await adapter.update_one(
        {"value": "a"}, {"$set": {"value": "b"}}, upsert=True
    )
    assert updated is True

    deleted = await adapter.delete_one({"value": "b"})
    assert deleted is True

    assert collection.last_insert == {"value": "a"}
    assert collection.last_update == ({"value": "a"}, {"$set": {"value": "b"}}, True)
    assert collection.last_delete == {"value": "b"}


@pytest.mark.asyncio()
async def test_aggregate_normalizes_results(
    adapter: MongoDBAdapter, fake_client: FakeClient
) -> None:
    await adapter.init()
    collection = fake_client["test_db"]["items"]
    collection.aggregate_results = [{"_id": 1, "count": 5}]

    results = await adapter.aggregate([{"$match": {}}])

    assert results == [{"_id": "1", "count": 5}]
    assert collection.last_pipeline == [{"$match": {}}]
