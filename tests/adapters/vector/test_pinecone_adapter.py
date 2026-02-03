from __future__ import annotations

import pytest
from pydantic import SecretStr

from oneiric.adapters.vector.vector_types import VectorDocument
from oneiric.adapters.vector.pinecone import PineconeAdapter, PineconeSettings


class FakeIndex:
    def __init__(self) -> None:
        self.queries: list[dict[str, object]] = []
        self.upserts: list[dict[str, object]] = []
        self.deletes: list[dict[str, object]] = []
        self.fetches: list[dict[str, object]] = []

    def query(self, **kwargs: object) -> dict[str, object]:
        self.queries.append(kwargs)
        return {
            "matches": [
                {"id": "doc-1", "score": 0.42, "metadata": {"k": "v"}, "values": [1.0]}
            ]
        }

    def upsert(self, **kwargs: object) -> dict[str, object]:
        self.upserts.append(kwargs)
        return {"upserted_count": len(kwargs.get("vectors", []))}

    def delete(self, **kwargs: object) -> None:
        self.deletes.append(kwargs)

    def fetch(self, **kwargs: object) -> dict[str, object]:
        self.fetches.append(kwargs)
        return {"vectors": {"doc-1": {"values": [1.0], "metadata": {"k": "v"}}}}

    def describe_index_stats(self, **kwargs: object) -> dict[str, object]:
        return {
            "total_vector_count": 5,
            "namespaces": {"ns": {"vector_count": 2}},
        }


@pytest.mark.asyncio
async def test_pinecone_prepare_and_search(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = PineconeSettings(api_key=SecretStr("key"))
    adapter = PineconeAdapter(settings)
    index = FakeIndex()

    async def _get_index() -> FakeIndex:
        return index

    monkeypatch.setattr(adapter, "_get_index", _get_index)

    doc_ids, vectors = adapter._prepare_all_vectors(
        [VectorDocument(id=None, vector=[0.1], metadata={"a": 1})]
    )
    assert doc_ids == ["vec_0"]
    assert vectors[0]["metadata"] == {"a": 1}

    results = await adapter.search(
        "ns",
        [0.1],
        limit=1,
        filter_expr={"kind": "demo"},
        include_vectors=True,
    )
    assert results[0].id == "doc-1"
    assert index.queries[0]["namespace"] == "ns"
    assert index.queries[0]["filter"] == {"kind": "demo"}


@pytest.mark.asyncio
async def test_pinecone_upsert_count_and_list(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = PineconeSettings(api_key=SecretStr("key"), upsert_batch_size=1)
    adapter = PineconeAdapter(settings)
    index = FakeIndex()

    async def _get_index() -> FakeIndex:
        return index

    monkeypatch.setattr(adapter, "_get_index", _get_index)

    inserted = await adapter.upsert(
        "ns",
        [
            VectorDocument(id="a", vector=[0.1], metadata={}),
            VectorDocument(id="b", vector=[0.2], metadata={}),
        ],
    )
    assert inserted == ["a", "b"]
    assert len(index.upserts) == 2
    assert index.upserts[0]["namespace"] == "ns"

    count_ns = await adapter.count("ns")
    assert count_ns == 2
    count_all = await adapter.count("default")
    assert count_all == 5

    collections = await adapter.list_collections()
    assert "ns" in collections
    assert "default" in collections
