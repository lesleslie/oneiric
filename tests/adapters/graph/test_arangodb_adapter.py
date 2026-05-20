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


# ---------------------------------------------------------------------------
# Tests — coverage gaps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_cleanup_awaitable_close(fake_db: FakeDB) -> None:
    """cleanup() awaits close() when it returns a coroutine (line 93)."""
    closed: list[bool] = []

    class AsyncCloseClient:
        def db(self, name: str, *, username: str, password: str | None) -> FakeDB:
            return fake_db

        async def close(self) -> None:
            closed.append(True)

    adapter = ArangoDBGraphAdapter(
        ArangoDBGraphSettings(database="test"),
        client_factory=lambda: AsyncCloseClient(),
    )
    await adapter.init()
    await adapter.cleanup()
    assert closed == [True]


@pytest.mark.asyncio()
async def test_ensure_client_awaitable_factory(fake_db: FakeDB) -> None:
    """_ensure_client awaits factory result when it is a coroutine (line 144)."""

    class AsyncClient:
        def db(self, name: str, *, username: str, password: str | None) -> FakeDB:
            return fake_db

    async def async_factory() -> AsyncClient:
        return AsyncClient()

    adapter = ArangoDBGraphAdapter(
        ArangoDBGraphSettings(database="test"), client_factory=async_factory
    )
    await adapter.init()
    assert adapter._db is fake_db


@pytest.mark.asyncio()
async def test_vertex_and_edge_collection_no_graph(fake_client: FakeClient) -> None:
    """_vertex_collection and _edge_collection fall back to db.collection when no graph (lines 171, 176)."""
    settings = ArangoDBGraphSettings(database="test")  # no graph
    adapter = ArangoDBGraphAdapter(settings, client_factory=lambda: fake_client)
    await adapter.init()
    vertex = await adapter.create_vertex("nodes", {"name": "test"})
    assert vertex["name"] == "test"
    edge = await adapter.create_edge("links", "nodes/1", "nodes/2")
    assert edge["_from"] == "nodes/1"


@pytest.mark.asyncio()
async def test_run_sync_with_custom_executor(fake_db: FakeDB) -> None:
    """_run_sync uses sync_executor when provided (line 182)."""
    called_with: list[tuple] = []

    async def my_executor(func, args, kwargs):
        called_with.append((func.__name__, args, kwargs))
        return func(*args, **kwargs)

    class MyClient:
        def db(self, name: str, *, username: str, password: str | None) -> FakeDB:
            return fake_db

    adapter = ArangoDBGraphAdapter(
        ArangoDBGraphSettings(database="test"),
        client_factory=lambda: MyClient(),
        sync_executor=my_executor,
    )
    await adapter.init()
    await adapter.create_vertex("nodes", {"x": 1})
    assert len(called_with) > 0


@pytest.mark.asyncio()
async def test_default_client_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_default_client_factory creates ArangoClient when arango is importable (lines 186-193)."""
    import sys
    import types

    created: list[dict] = []

    class FakeArangoClient:
        def __init__(self, hosts: str, verify: bool, request_timeout: float) -> None:
            created.append({"hosts": hosts, "verify": verify})

        def db(self, name: str, *, username: str, password: str | None) -> FakeDB:
            return FakeDB()

    fake_arango = types.ModuleType("arango")
    fake_arango.ArangoClient = FakeArangoClient  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "arango", fake_arango)

    adapter = ArangoDBGraphAdapter(ArangoDBGraphSettings(database="test"))
    await adapter.init()
    assert len(created) == 1
