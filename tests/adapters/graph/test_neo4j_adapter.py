"""Tests for the Neo4j graph adapter."""

from __future__ import annotations

import pytest

from oneiric.adapters.graph.neo4j import Neo4jGraphAdapter, Neo4jGraphSettings


class FakeSession:
    def __init__(self, records):
        self.records = records
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.closed = True

    async def run(self, cypher, **params):
        self.last_query = (cypher, params)
        return FakeResult(self.records)


class FakeResult:
    def __init__(self, records):
        self._records = records

    async def data(self):
        return self._records


class FakeDriver:
    def __init__(self, records):
        self.records = records
        self.sessions = []
        self.closed = False

    def session(self, database=None):
        session = FakeSession(self.records)
        self.sessions.append((database, session))
        return session

    async def close(self):
        self.closed = True


@pytest.fixture()
def fake_driver():
    return FakeDriver([{"n": {"id": 1}}])


@pytest.fixture()
def adapter(fake_driver):
    settings = Neo4jGraphSettings()
    return Neo4jGraphAdapter(settings, driver_factory=lambda: fake_driver)


@pytest.mark.asyncio()
async def test_init_and_health(adapter, fake_driver):
    await adapter.init()
    assert await adapter.health() is True
    assert fake_driver.sessions  # session was created


@pytest.mark.asyncio()
async def test_create_node(adapter):
    result = await adapter.create_node(["Demo"], {"name": "node"})
    assert result == {"id": 1}


@pytest.mark.asyncio()
async def test_cleanup(adapter, fake_driver):
    await adapter.init()
    await adapter.cleanup()
    assert fake_driver.closed is True


# ---------------------------------------------------------------------------
# Tests — coverage gaps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_create_relationship(adapter) -> None:
    """create_relationship() builds Cypher query and returns result (lines 100-104)."""
    result = await adapter.create_relationship(1, 2, "KNOWS", {"since": 2020})
    assert result is None  # FakeDriver returns {"n": ...}, no "r" key


@pytest.mark.asyncio()
async def test_query_method(adapter, monkeypatch) -> None:
    """query() calls record.data() on each record returned (lines 111-112)."""

    class FakeRecord:
        def data(self) -> dict:
            return {"name": "Alice"}

    async def fake_run_query_many(cypher: str, **params) -> list:
        return [FakeRecord()]

    monkeypatch.setattr(adapter, "_run_query_many", fake_run_query_many)
    results = await adapter.query("MATCH (n) RETURN n")
    assert results == [{"name": "Alice"}]


@pytest.mark.asyncio()
async def test_run_query_empty_records(adapter, monkeypatch) -> None:
    """_run_query returns {} when records list is empty (line 117)."""

    async def fake_run_query_many(cypher: str, **params) -> list:
        return []

    monkeypatch.setattr(adapter, "_run_query_many", fake_run_query_many)
    result = await adapter._run_query("MATCH (n) RETURN n")
    assert result == {}


@pytest.mark.asyncio()
async def test_run_query_first_has_data_method(adapter, monkeypatch) -> None:
    """_run_query calls first.data() when first has data method (line 120)."""

    class RecordWithData:
        def data(self) -> dict:
            return {"value": 99}

    async def fake_run_query_many(cypher: str, **params) -> list:
        return [RecordWithData()]

    monkeypatch.setattr(adapter, "_run_query_many", fake_run_query_many)
    result = await adapter._run_query("RETURN 1")
    assert result == {"value": 99}


@pytest.mark.asyncio()
async def test_ensure_driver_awaitable_factory(fake_driver) -> None:
    """_ensure_driver awaits factory result when it returns a coroutine (line 138)."""

    async def async_factory():
        return fake_driver

    settings = Neo4jGraphSettings()
    adapter = Neo4jGraphAdapter(settings, driver_factory=async_factory)
    driver = await adapter._ensure_driver()
    assert driver is fake_driver


@pytest.mark.asyncio()
async def test_default_driver_factory(monkeypatch, fake_driver) -> None:
    """_default_driver_factory uses neo4j.AsyncGraphDatabase when neo4j is importable (lines 136, 145-155)."""
    import sys
    import types

    fake_neo4j = types.ModuleType("neo4j")
    fake_neo4j.AsyncGraphDatabase = types.SimpleNamespace(  # type: ignore[attr-defined]
        driver=lambda uri, auth, encrypted, max_connection_pool_size: fake_driver
    )
    monkeypatch.setitem(sys.modules, "neo4j", fake_neo4j)

    adapter = Neo4jGraphAdapter(Neo4jGraphSettings())  # no driver_factory → default
    await adapter.init()
    assert adapter._driver is fake_driver


@pytest.mark.asyncio()
async def test_default_driver_factory_with_auth(monkeypatch, fake_driver) -> None:
    """_default_driver_factory passes auth tuple when username+password set (line 154)."""
    import sys
    import types

    from pydantic import SecretStr

    auth_received: list[tuple] = []

    fake_neo4j = types.ModuleType("neo4j")
    fake_neo4j.AsyncGraphDatabase = types.SimpleNamespace(  # type: ignore[attr-defined]
        driver=lambda uri, auth, **kw: (auth_received.append(auth), fake_driver)[1]
    )
    monkeypatch.setitem(sys.modules, "neo4j", fake_neo4j)

    settings = Neo4jGraphSettings(username="user", password=SecretStr("secret"))
    adapter = Neo4jGraphAdapter(settings)
    await adapter.init()
    assert auth_received[0] == ("user", "secret")
