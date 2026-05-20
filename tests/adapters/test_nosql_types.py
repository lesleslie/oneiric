from __future__ import annotations

import pytest

from oneiric.adapters.nosql.nosql_types import (
    NoSQLAdapterBase,
    NoSQLBaseSettings,
    NoSQLDocument,
    NoSQLQuery,
)


class _ConcreteAdapter(NoSQLAdapterBase):
    async def init(self) -> None:
        await super().init()

    async def health(self) -> bool:
        await super().health()
        return True

    async def cleanup(self) -> None:
        await super().cleanup()


def _make() -> _ConcreteAdapter:
    return _ConcreteAdapter(NoSQLBaseSettings())


# ---------------------------------------------------------------------------
# Tests — models
# ---------------------------------------------------------------------------


def test_nosql_document_defaults() -> None:
    doc = NoSQLDocument()
    assert doc.id is None
    assert doc.data == {}


def test_nosql_document_with_data() -> None:
    doc = NoSQLDocument(id="x", data={"key": "val"})
    assert doc.id == "x"
    assert doc.data["key"] == "val"


def test_nosql_query_defaults() -> None:
    q = NoSQLQuery()
    assert q.filters == {}
    assert q.projection is None
    assert q.limit is None
    assert q.sort is None


def test_nosql_query_full() -> None:
    q = NoSQLQuery(
        filters={"status": "active"},
        projection=["id", "name"],
        limit=10,
        sort=[("created_at", -1)],
    )
    assert q.limit == 10
    assert q.sort == [("created_at", -1)]


def test_nosql_base_settings_defaults() -> None:
    s = NoSQLBaseSettings()
    assert s.connect_timeout == 30.0
    assert s.health_timeout == 5.0


# ---------------------------------------------------------------------------
# Tests — settings property
# ---------------------------------------------------------------------------


def test_settings_property() -> None:
    settings = NoSQLBaseSettings(connect_timeout=60.0)
    adapter = _make()
    adapter._settings = settings
    assert adapter.settings is settings


# ---------------------------------------------------------------------------
# Tests — abstract method bodies via super()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_abstract_init_body() -> None:
    adapter = _make()
    await adapter.init()  # reaches super().init() → pass body


@pytest.mark.asyncio
async def test_abstract_health_body() -> None:
    adapter = _make()
    result = await adapter.health()
    assert result is True


@pytest.mark.asyncio
async def test_abstract_cleanup_body() -> None:
    adapter = _make()
    await adapter.cleanup()  # reaches super().cleanup() → pass body


# ---------------------------------------------------------------------------
# Tests — span context manager
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_span_success_path() -> None:
    adapter = _make()
    async with adapter.span("test-event", extra="x"):
        pass  # success path — logs start + complete


@pytest.mark.asyncio
async def test_span_error_path() -> None:
    adapter = _make()
    with pytest.raises(ValueError, match="boom"):
        async with adapter.span("test-event"):
            raise ValueError("boom")
