"""Tests for the Firestore adapter."""

from __future__ import annotations

from typing import Any

import pytest

from oneiric.adapters.nosql.nosql_types import NoSQLDocument
from oneiric.adapters.nosql.firestore import FirestoreAdapter, FirestoreSettings


class FakeSnapshot:
    def __init__(self, doc_id: str, data: dict[str, Any], exists: bool = True) -> None:
        self.id = doc_id
        self._data = data
        self.exists = exists

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data)


class FakeDocumentRef:
    def __init__(self, store: dict[str, dict[str, Any]], doc_id: str) -> None:
        self._store = store
        self._doc_id = doc_id

    async def get(self) -> FakeSnapshot:
        if self._doc_id not in self._store:
            return FakeSnapshot(self._doc_id, {}, exists=False)
        return FakeSnapshot(self._doc_id, self._store[self._doc_id])

    async def set(self, data: dict[str, Any], merge: bool = False) -> None:
        if merge and self._doc_id in self._store:
            self._store[self._doc_id].update(data)
        else:
            self._store[self._doc_id] = dict(data)

    async def delete(self) -> None:
        self._store.pop(self._doc_id, None)


class FakeQuery:
    def __init__(
        self,
        store: dict[str, dict[str, Any]],
        filters: list[tuple[str, str, Any]] | None = None,
        limit_value: int | None = None,
    ) -> None:
        self._store = store
        self._filters = filters or []
        self._limit = limit_value

    def where(self, field: str, op: str, value: Any) -> FakeQuery:
        filters = list(self._filters)
        filters.append((field, op, value))
        return FakeQuery(self._store, filters, self._limit)

    def limit(self, limit: int) -> FakeQuery:
        return FakeQuery(self._store, self._filters, limit)

    async def get(self) -> list[FakeSnapshot]:
        items = []
        for doc_id, data in self._store.items():
            if self._matches_filters(data):
                items.append(FakeSnapshot(doc_id, data))
        if self._limit is not None:
            items = items[: self._limit]
        return items

    def _matches_filters(self, data: dict[str, Any]) -> bool:
        for field, op, value in self._filters:
            if op not in ("==", "=", "eq"):
                return False
            if data.get(field) != value:
                return False
        return True


class FakeCollection:
    def __init__(self, store: dict[str, dict[str, Any]]) -> None:
        self._store = store

    def document(self, doc_id: str) -> FakeDocumentRef:
        return FakeDocumentRef(self._store, doc_id)

    def where(self, field: str, op: str, value: Any) -> FakeQuery:
        return FakeQuery(self._store).where(field, op, value)

    def limit(self, limit: int) -> FakeQuery:
        return FakeQuery(self._store).limit(limit)

    async def get(self) -> list[FakeSnapshot]:
        return [FakeSnapshot(doc_id, data) for doc_id, data in self._store.items()]


class FakeClient:
    def __init__(self) -> None:
        self.store: dict[str, dict[str, Any]] = {}
        self.closed = False

    def collection(self, name: str) -> FakeCollection:
        namespace = self.store.setdefault(name, {})
        return FakeCollection(namespace)

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def fake_client() -> FakeClient:
    return FakeClient()


@pytest.fixture()
def adapter(fake_client: FakeClient) -> FirestoreAdapter:
    settings = FirestoreSettings(project_id="demo", collection="items")
    return FirestoreAdapter(settings, client_factory=lambda: fake_client)


@pytest.mark.asyncio()
async def test_set_and_get_document(
    adapter: FirestoreAdapter, fake_client: FakeClient
) -> None:
    await adapter.init()
    await adapter.set_document("abc", {"value": 1})
    doc = await adapter.get_document("abc")
    assert isinstance(doc, NoSQLDocument)
    assert doc.id == "abc"
    assert doc.data == {"value": 1}


@pytest.mark.asyncio()
async def test_delete_document(
    adapter: FirestoreAdapter, fake_client: FakeClient
) -> None:
    await adapter.set_document("abc", {"value": 1})
    deleted = await adapter.delete_document("abc")
    assert deleted is True
    assert await adapter.get_document("abc") is None


@pytest.mark.asyncio()
async def test_query_documents(
    adapter: FirestoreAdapter, fake_client: FakeClient
) -> None:
    await adapter.set_document("1", {"status": "ok"})
    await adapter.set_document("2", {"status": "fail"})
    docs = await adapter.query_documents(filters=[("status", "==", "ok")])
    assert len(docs) == 1
    assert docs[0].id == "1"


@pytest.mark.asyncio()
async def test_health_checks_collection(adapter: FirestoreAdapter) -> None:
    assert await adapter.health() is True
