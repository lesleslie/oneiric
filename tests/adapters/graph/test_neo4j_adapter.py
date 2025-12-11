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
