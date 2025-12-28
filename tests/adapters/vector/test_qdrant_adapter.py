from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from oneiric.adapters.vector.qdrant import QdrantAdapter, QdrantSettings


@dataclass
class MatchValue:
    value: Any


@dataclass
class MatchAny:
    any: list[Any]


@dataclass
class FieldCondition:
    key: str
    match: Any


@dataclass
class Filter:
    must: list[FieldCondition]


@dataclass
class VectorParams:
    size: int
    distance: str
    on_disk: bool


@dataclass
class HnswConfigDiff:
    m: int
    ef_construct: int
    full_scan_threshold: int
    max_indexing_threads: int


@dataclass
class ScalarQuantizationConfig:
    type: str
    quantile: float
    always_ram: bool


@dataclass
class ScalarQuantization:
    scalar: ScalarQuantizationConfig


class ScalarType:
    INT8 = "int8"


class Distance:
    COSINE = "cosine"
    EUCLID = "euclid"
    DOT = "dot"
    MANHATTAN = "manhattan"


@dataclass
class PointStruct:
    id: str
    vector: list[float]
    payload: dict[str, Any]


@dataclass
class PointIdsList:
    points: list[str]


class FakeCollections:
    def __init__(self, names: list[str]) -> None:
        self.collections = [SimpleNamespace(name=name) for name in names]


class FakeClient:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.deleted: list[str] = []

    async def get_collections(self) -> FakeCollections:
        return FakeCollections(["existing"])

    async def create_collection(self, **kwargs: Any) -> None:
        self.created.append(kwargs)

    async def get_cluster_info(self) -> dict[str, Any]:
        return {"status": "ok"}

    async def search(self, **kwargs: Any) -> list[Any]:
        return [
            SimpleNamespace(
                id="doc-1",
                score=0.4,
                payload={"k": "v"},
                vector=[0.1],
            )
        ]

    async def upsert(self, **kwargs: Any) -> Any:
        return SimpleNamespace(status=SimpleNamespace(name="COMPLETED"))

    async def delete(self, **kwargs: Any) -> Any:
        return SimpleNamespace(status=SimpleNamespace(name="COMPLETED"))

    async def retrieve(self, **kwargs: Any) -> list[Any]:
        return [
            SimpleNamespace(id="doc-1", vector=[0.2], payload={"k": "v"}),
        ]

    async def count(self, **kwargs: Any) -> Any:
        return SimpleNamespace(count=7)

    async def scroll(self, **kwargs: Any) -> tuple[list[Any], str | None]:
        return (
            [
                SimpleNamespace(id="doc-2", vector=[0.3], payload={"k": "v"}),
            ],
            "next",
        )

    async def delete_collection(self, collection_name: str) -> None:
        self.deleted.append(collection_name)

    async def close(self) -> None:
        return None


def _inject_qdrant_models(monkeypatch: pytest.MonkeyPatch) -> None:
    models = SimpleNamespace(
        FieldCondition=FieldCondition,
        Filter=Filter,
        MatchAny=MatchAny,
        MatchValue=MatchValue,
        Distance=Distance,
        VectorParams=VectorParams,
        HnswConfigDiff=HnswConfigDiff,
        ScalarQuantization=ScalarQuantization,
        ScalarQuantizationConfig=ScalarQuantizationConfig,
        ScalarType=ScalarType,
        PointStruct=PointStruct,
        PointIdsList=PointIdsList,
    )
    sys_modules = __import__("sys").modules
    monkeypatch.setitem(sys_modules, "qdrant_client.models", models)
    monkeypatch.setitem(sys_modules, "qdrant_client", SimpleNamespace(models=models))


@pytest.mark.asyncio
async def test_qdrant_filter_and_collection_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _inject_qdrant_models(monkeypatch)
    settings = QdrantSettings(enable_quantization=True)
    adapter = QdrantAdapter(settings)
    adapter._client = FakeClient()

    q_filter = adapter._build_qdrant_filter({"kind": "demo", "tags": ["a", "b"]})
    assert isinstance(q_filter, Filter)
    assert len(q_filter.must) == 2

    created = await adapter._ensure_collection_exists("new", dimension=3)
    assert created is True
    created_call = adapter._client.created[0]
    assert created_call["collection_name"] == "new"
    assert created_call["quantization_config"] is not None


@pytest.mark.asyncio
async def test_qdrant_search_and_scroll(monkeypatch: pytest.MonkeyPatch) -> None:
    _inject_qdrant_models(monkeypatch)
    adapter = QdrantAdapter(QdrantSettings())
    adapter._client = FakeClient()

    results = await adapter.search("docs", [0.1], include_vectors=True)
    assert results[0].vector == [0.1]

    documents, offset = await adapter.scroll("docs", include_vectors=True)
    assert documents[0].id == "doc-2"
    assert offset == "next"
