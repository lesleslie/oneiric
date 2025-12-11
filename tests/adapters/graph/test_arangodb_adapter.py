"""Tests for the ArangoDB graph adapter."""

from __future__ import annotations

from typing import Any

import pytest

from oneiric.adapters.graph.arangodb import ArangoDBGraphAdapter, ArangoDBGraphSettings


class FakeCollection:
    def __init__(self) -> None:
        self.inserted: list[dict[str, Any]] = []

    def insert(self, document: dict[str, Any]) -> dict[str, Any]:
        doc = dict(document)
        doc.setdefault("_key", f"key-{len(self.inserted) + 1}")
        self.inserted.append(doc)
        return doc

    def get(self, key: str) -> dict[str, Any] | None:
        for document in self.inserted:
            if document.get("_key") == key or document.get("_id") == key:
                return document
        return None


class FakeGraphHandle:
    def __init__(self) -> None:
        self.vertex_collections: dict[str, FakeCollection] = {}
        self.edge_collections: dict[str, FakeCollection] = {}

    def vertex_collection(self, name: str) -> FakeCollection:
        return self.vertex_collections.setdefault(name, FakeCollection())

    def edge_collection(self, name: str) -> FakeCollection:
        return self.edge_collections.setdefault(name, FakeCollection())


class FakeAQL:
    def __init__(self) -> None:
        self.executed: list[tuple[str, dict[str, Any] | None]] = []

    def execute(
        self, query: str, *, bind_vars=None, stream=False, timeout=None
    ) -> list[dict[str, Any]]:
        self.executed.append((query, bind_vars))
        return [{"value": 1}]


class FakeDB:
    def __init__(self) -> None:
        self.graph_handle = FakeGraphHandle()
        self.collections: dict[str, FakeCollection] = {}
        self.aql = FakeAQL()

    def graph(self, name: str) -> FakeGraphHandle:
        self.graph_name = name
        return self.graph_handle

    def collection(self, name: str) -> FakeCollection:
        return self.collections.setdefault(name, FakeCollection())


class FakeClient:
    def __init__(self, db: FakeDB) -> None:
        self._db = db
        self.closed = False
        self.db_args = None

    def db(self, name: str, *, username: str, password: str | None):
        self.db_args = (name, username, password)
        return self._db

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def fake_db() -> FakeDB:
    return FakeDB()


@pytest.fixture()
def fake_client(fake_db: FakeDB) -> FakeClient:
    return FakeClient(fake_db)


@pytest.fixture()
def adapter(fake_client: FakeClient) -> ArangoDBGraphAdapter:
    settings = ArangoDBGraphSettings(graph="demo", database="oneiric")
    return ArangoDBGraphAdapter(settings, client_factory=lambda: fake_client)


@pytest.mark.asyncio()
async def test_init_and_health(
    adapter: ArangoDBGraphAdapter, fake_client: FakeClient, fake_db: FakeDB
) -> None:
    await adapter.init()
    assert fake_client.db_args == ("oneiric", "root", None)
    assert await adapter.health() is True
    assert fake_db.aql.executed[-1][0] == "RETURN 1"


@pytest.mark.asyncio()
async def test_create_vertex_and_edge(
    adapter: ArangoDBGraphAdapter, fake_db: FakeDB
) -> None:
    await adapter.init()
    vertex = await adapter.create_vertex("people", {"name": "Ada"})
    assert vertex["name"] == "Ada"
    assert fake_db.graph_handle.vertex_collections["people"].inserted

    edge = await adapter.create_edge("knows", "people/1", "people/2", {"weight": 5})
    assert edge["_from"] == "people/1"
    assert edge["_to"] == "people/2"
    assert edge["weight"] == 5


@pytest.mark.asyncio()
async def test_get_vertex(adapter: ArangoDBGraphAdapter) -> None:
    await adapter.init()
    created = await adapter.create_vertex("projects", {"name": "Graph"})
    fetched = await adapter.get_vertex("projects", created["_key"])
    assert fetched == created


@pytest.mark.asyncio()
async def test_cleanup(adapter: ArangoDBGraphAdapter, fake_client: FakeClient) -> None:
    await adapter.init()
    await adapter.cleanup()
    assert fake_client.closed is True
