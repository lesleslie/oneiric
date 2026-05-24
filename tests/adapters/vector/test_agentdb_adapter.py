from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from oneiric.adapters.vector.agentdb import AgentDBAdapter, AgentDBSettings
from oneiric.adapters.vector.vector_types import VectorDocument


class FakeMCPClient:
    def __init__(self, server_url: str, timeout: float) -> None:
        self.server_url = server_url
        self.timeout = timeout
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._closed = False

    async def call_tool(self, tool: str, params: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((tool, params))
        return _default_response(tool)

    async def close(self) -> None:
        self._closed = True


def _default_response(tool: str) -> dict[str, Any]:
    responses: dict[str, dict[str, Any]] = {
        "agentdb_init": {"status": "ok"},
        "agentdb_health": {"status": "healthy"},
        "agentdb_search": {
            "results": [
                {"id": "doc-1", "score": 0.9, "metadata": {"k": "v"}, "vector": [0.1]}
            ]
        },
        "agentdb_insert": {"ids": ["doc-1"]},
        "agentdb_upsert": {"ids": ["doc-1"]},
        "agentdb_delete": {"success": True},
        "agentdb_get": {
            "documents": [{"id": "doc-1", "vector": [0.1], "metadata": {"k": "v"}}]
        },
        "agentdb_count": {"count": 5},
        "agentdb_create_collection": {"success": True},
        "agentdb_delete_collection": {"success": True},
        "agentdb_list_collections": {"collections": ["agent_docs", "agent_notes"]},
    }
    return responses.get(tool, {})


def _inject_mcp_common(monkeypatch: pytest.MonkeyPatch) -> type:
    """Inject fake mcp_common.client so _create_client can import MCPClient."""
    fake_mod = types.ModuleType("mcp_common")
    fake_client_mod = types.ModuleType("mcp_common.client")
    fake_client_mod.MCPClient = FakeMCPClient  # type: ignore[attr-defined]
    fake_mod.client = fake_client_mod  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mcp_common", fake_mod)
    monkeypatch.setitem(sys.modules, "mcp_common.client", fake_client_mod)
    return FakeMCPClient


def _make_adapter(monkeypatch: pytest.MonkeyPatch) -> AgentDBAdapter:
    """Create an AgentDBAdapter with injected fake MCPClient."""
    _inject_mcp_common(monkeypatch)
    return AgentDBAdapter(AgentDBSettings())


# ---------------------------------------------------------------------------
# Infrastructure tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agentdb_create_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """_create_client() imports MCPClient, initialises it, calls agentdb_init (lines 72-95)."""
    adapter = _make_adapter(monkeypatch)
    client = await adapter._create_client()
    assert isinstance(client, FakeMCPClient)
    assert client.calls[0][0] == "agentdb_init"


@pytest.mark.asyncio
async def test_agentdb_create_client_raises_on_import_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_create_client() wraps import errors in LifecycleError (lines 97-103)."""
    from oneiric.core.lifecycle import LifecycleError

    monkeypatch.setitem(sys.modules, "mcp_common", None)
    monkeypatch.setitem(sys.modules, "mcp_common.client", None)
    adapter = AgentDBAdapter(AgentDBSettings())
    with pytest.raises(LifecycleError, match="Failed to initialize AgentDB"):
        await adapter._create_client()


@pytest.mark.asyncio
async def test_agentdb_ensure_client_when_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """_ensure_client() creates client when _client is None (lines 106-108)."""
    adapter = _make_adapter(monkeypatch)
    assert adapter._client is None
    client = await adapter._ensure_client()
    assert isinstance(client, FakeMCPClient)
    assert adapter._client is client


@pytest.mark.asyncio
async def test_agentdb_init_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """init() calls _ensure_client and health check, succeeds (lines 111-123)."""
    adapter = _make_adapter(monkeypatch)
    await adapter.init()  # must not raise
    assert adapter._client is not None


@pytest.mark.asyncio
async def test_agentdb_init_raises_when_health_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """init() raises LifecycleError when health() returns False (lines 116-117)."""
    from oneiric.core.lifecycle import LifecycleError

    _inject_mcp_common(monkeypatch)

    class UnhealthyClient(FakeMCPClient):
        async def call_tool(self, tool: str, params: dict[str, Any]) -> dict[str, Any]:
            if tool == "agentdb_health":
                return {"status": "unhealthy"}
            return await super().call_tool(tool, params)

    adapter = AgentDBAdapter(AgentDBSettings())

    async def fake_create(_self: Any) -> UnhealthyClient:
        return UnhealthyClient("", 30.0)

    monkeypatch.setattr(AgentDBAdapter, "_create_client", fake_create)
    with pytest.raises(LifecycleError, match="health check failed"):
        await adapter.init()


@pytest.mark.asyncio
async def test_agentdb_health_returns_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """health() returns True when call_tool returns status=healthy (lines 130-133)."""
    adapter = _make_adapter(monkeypatch)
    adapter._client = FakeMCPClient("", 30.0)
    assert await adapter.health() is True


@pytest.mark.asyncio
async def test_agentdb_health_returns_false_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """health() returns False when call_tool raises (lines 134-136)."""
    adapter = _make_adapter(monkeypatch)

    class BrokenClient(FakeMCPClient):
        async def call_tool(self, tool: str, params: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("connection reset")

    adapter._client = BrokenClient("", 30.0)
    assert await adapter.health() is False


@pytest.mark.asyncio
async def test_agentdb_cleanup_with_mcp_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """cleanup() closes mcp_client and nulls both clients (lines 139-144)."""
    adapter = _make_adapter(monkeypatch)
    mcp = FakeMCPClient("", 30.0)
    adapter._mcp_client = mcp
    adapter._client = mcp
    await adapter.cleanup()
    assert mcp._closed is True
    assert adapter._mcp_client is None
    assert adapter._client is None


@pytest.mark.asyncio
async def test_agentdb_cleanup_no_mcp_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """cleanup() is safe when _mcp_client is None (line 140 branch)."""
    adapter = _make_adapter(monkeypatch)
    await adapter.cleanup()  # must not raise


@pytest.mark.asyncio
async def test_agentdb_cleanup_error_is_logged(monkeypatch: pytest.MonkeyPatch) -> None:
    """cleanup() logs warning instead of raising when close() errors (lines 145-146)."""
    adapter = _make_adapter(monkeypatch)

    class BrokenClose(FakeMCPClient):
        async def close(self) -> None:
            raise RuntimeError("close failed")

    adapter._mcp_client = BrokenClose("", 30.0)
    await (
        adapter.cleanup()
    )  # must not raise — _mcp_client stays set since None assignment was skipped


# ---------------------------------------------------------------------------
# CRUD operation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agentdb_search(monkeypatch: pytest.MonkeyPatch) -> None:
    """search() calls agentdb_search and maps results (lines 157-184)."""
    adapter = _make_adapter(monkeypatch)
    adapter._client = FakeMCPClient("", 30.0)
    results = await adapter.search("docs", [0.1], limit=5, include_vectors=True)
    assert len(results) == 1
    assert results[0].id == "doc-1"
    assert results[0].score == 0.9
    assert results[0].vector == [0.1]


@pytest.mark.asyncio
async def test_agentdb_search_with_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    """search() passes filter_expr to the tool call (line 168)."""
    adapter = _make_adapter(monkeypatch)
    client = FakeMCPClient("", 30.0)
    adapter._client = client
    await adapter.search("docs", [0.1], filter_expr={"kind": "article"})
    assert client.calls[0][1]["filter"] == {"kind": "article"}


@pytest.mark.asyncio
async def test_agentdb_search_raises_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """search() re-raises when call_tool fails (lines 186-188)."""
    adapter = _make_adapter(monkeypatch)

    class BrokenSearch(FakeMCPClient):
        async def call_tool(self, tool: str, params: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("search failed")

    adapter._client = BrokenSearch("", 30.0)
    with pytest.raises(RuntimeError, match="search failed"):
        await adapter.search("docs", [0.1])


@pytest.mark.asyncio
async def test_agentdb_insert(monkeypatch: pytest.MonkeyPatch) -> None:
    """insert() calls agentdb_insert and returns ids (lines 196-217)."""
    adapter = _make_adapter(monkeypatch)
    adapter._client = FakeMCPClient("", 30.0)
    docs = [VectorDocument(id="doc-1", vector=[0.1])]
    ids = await adapter.insert("docs", docs)
    assert ids == ["doc-1"]


@pytest.mark.asyncio
async def test_agentdb_insert_generates_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """insert() generates id when doc.id is None (line 202)."""
    adapter = _make_adapter(monkeypatch)
    client = FakeMCPClient("", 30.0)
    adapter._client = client
    docs = [VectorDocument(id=None, vector=[0.1, 0.2])]
    await adapter.insert("docs", docs)
    sent_id = client.calls[0][1]["documents"][0]["id"]
    assert sent_id  # non-empty generated id


@pytest.mark.asyncio
async def test_agentdb_insert_raises_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """insert() re-raises when call_tool fails (lines 219-221)."""
    adapter = _make_adapter(monkeypatch)

    class BrokenInsert(FakeMCPClient):
        async def call_tool(self, tool: str, params: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("insert failed")

    adapter._client = BrokenInsert("", 30.0)
    with pytest.raises(RuntimeError, match="insert failed"):
        await adapter.insert("docs", [VectorDocument(id="d1", vector=[0.1])])


@pytest.mark.asyncio
async def test_agentdb_upsert(monkeypatch: pytest.MonkeyPatch) -> None:
    """upsert() calls agentdb_upsert and returns ids (lines 229-250)."""
    adapter = _make_adapter(monkeypatch)
    adapter._client = FakeMCPClient("", 30.0)
    docs = [VectorDocument(id="doc-1", vector=[0.1])]
    ids = await adapter.upsert("docs", docs)
    assert ids == ["doc-1"]


@pytest.mark.asyncio
async def test_agentdb_upsert_raises_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """upsert() re-raises when call_tool fails (lines 252-254)."""
    adapter = _make_adapter(monkeypatch)

    class BrokenUpsert(FakeMCPClient):
        async def call_tool(self, tool: str, params: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("upsert failed")

    adapter._client = BrokenUpsert("", 30.0)
    with pytest.raises(RuntimeError, match="upsert failed"):
        await adapter.upsert("docs", [VectorDocument(id="d1", vector=[0.1])])


@pytest.mark.asyncio
async def test_agentdb_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    """delete() calls agentdb_delete and returns True (lines 262-274)."""
    adapter = _make_adapter(monkeypatch)
    adapter._client = FakeMCPClient("", 30.0)
    assert await adapter.delete("docs", ["id1", "id2"]) is True


@pytest.mark.asyncio
async def test_agentdb_delete_raises_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """delete() re-raises when call_tool fails (lines 276-278)."""
    adapter = _make_adapter(monkeypatch)

    class BrokenDelete(FakeMCPClient):
        async def call_tool(self, tool: str, params: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("delete failed")

    adapter._client = BrokenDelete("", 30.0)
    with pytest.raises(RuntimeError, match="delete failed"):
        await adapter.delete("docs", ["id1"])


@pytest.mark.asyncio
async def test_agentdb_get(monkeypatch: pytest.MonkeyPatch) -> None:
    """get() retrieves and maps documents (lines 287-307)."""
    adapter = _make_adapter(monkeypatch)
    adapter._client = FakeMCPClient("", 30.0)
    docs = await adapter.get("docs", ["doc-1"], include_vectors=True)
    assert len(docs) == 1
    assert docs[0].id == "doc-1"
    assert docs[0].vector == [0.1]


@pytest.mark.asyncio
async def test_agentdb_get_raises_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """get() re-raises when call_tool fails (lines 309-311)."""
    adapter = _make_adapter(monkeypatch)

    class BrokenGet(FakeMCPClient):
        async def call_tool(self, tool: str, params: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("get failed")

    adapter._client = BrokenGet("", 30.0)
    with pytest.raises(RuntimeError, match="get failed"):
        await adapter.get("docs", ["id1"])


@pytest.mark.asyncio
async def test_agentdb_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """count() returns result from agentdb_count (lines 319-331)."""
    adapter = _make_adapter(monkeypatch)
    adapter._client = FakeMCPClient("", 30.0)
    assert await adapter.count("docs") == 5


@pytest.mark.asyncio
async def test_agentdb_count_with_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    """count() passes filter to agentdb_count (line 327)."""
    adapter = _make_adapter(monkeypatch)
    client = FakeMCPClient("", 30.0)
    adapter._client = client
    await adapter.count("docs", filter_expr={"kind": "article"})
    assert client.calls[0][1]["filter"] == {"kind": "article"}


@pytest.mark.asyncio
async def test_agentdb_count_raises_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """count() re-raises when call_tool fails (lines 333-335)."""
    adapter = _make_adapter(monkeypatch)

    class BrokenCount(FakeMCPClient):
        async def call_tool(self, tool: str, params: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("count failed")

    adapter._client = BrokenCount("", 30.0)
    with pytest.raises(RuntimeError, match="count failed"):
        await adapter.count("docs")


@pytest.mark.asyncio
async def test_agentdb_create_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    """create_collection() calls agentdb_create_collection (lines 344-357)."""
    adapter = _make_adapter(monkeypatch)
    adapter._client = FakeMCPClient("", 30.0)
    assert await adapter.create_collection("docs", dimension=128) is True


@pytest.mark.asyncio
async def test_agentdb_create_collection_raises_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create_collection() re-raises when call_tool fails (lines 359-361)."""
    adapter = _make_adapter(monkeypatch)

    class BrokenCreate(FakeMCPClient):
        async def call_tool(self, tool: str, params: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("create failed")

    adapter._client = BrokenCreate("", 30.0)
    with pytest.raises(RuntimeError, match="create failed"):
        await adapter.create_collection("docs", dimension=128)


@pytest.mark.asyncio
async def test_agentdb_delete_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    """delete_collection() calls agentdb_delete_collection (lines 368-379)."""
    adapter = _make_adapter(monkeypatch)
    adapter._client = FakeMCPClient("", 30.0)
    assert await adapter.delete_collection("docs") is True


@pytest.mark.asyncio
async def test_agentdb_delete_collection_raises_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """delete_collection() re-raises when call_tool fails (lines 381-383)."""
    adapter = _make_adapter(monkeypatch)

    class BrokenDelete(FakeMCPClient):
        async def call_tool(self, tool: str, params: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("delete collection failed")

    adapter._client = BrokenDelete("", 30.0)
    with pytest.raises(RuntimeError, match="delete collection failed"):
        await adapter.delete_collection("docs")


@pytest.mark.asyncio
async def test_agentdb_list_collections(monkeypatch: pytest.MonkeyPatch) -> None:
    """list_collections() returns collections with prefix stripped (lines 386-397)."""
    adapter = _make_adapter(monkeypatch)
    adapter._client = FakeMCPClient("", 30.0)
    names = await adapter.list_collections()
    assert "docs" in names  # agent_docs → strips "agent_" prefix
    assert "notes" in names


@pytest.mark.asyncio
async def test_agentdb_list_collections_raises_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """list_collections() re-raises when call_tool fails (lines 399-401)."""
    adapter = _make_adapter(monkeypatch)

    class BrokenList(FakeMCPClient):
        async def call_tool(self, tool: str, params: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("list failed")

    adapter._client = BrokenList("", 30.0)
    with pytest.raises(RuntimeError, match="list failed"):
        await adapter.list_collections()


def test_agentdb_has_capability(monkeypatch: pytest.MonkeyPatch) -> None:
    """has_capability() checks against metadata.capabilities (line 404)."""
    adapter = AgentDBAdapter(AgentDBSettings())
    assert adapter.has_capability("vector_search") is True
    assert adapter.has_capability("quic_sync") is True
    assert adapter.has_capability("nonexistent") is False
