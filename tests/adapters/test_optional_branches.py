from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from pathlib import Path

import numpy as np
import pytest

from oneiric.adapters.metrics import (
    _extract_numeric,
    _read_value,
    capture_adapter_state_metrics,
    record_adapter_request_metrics,
)
from oneiric.adapters.observability.embeddings import EmbeddingService
from oneiric.adapters.queue.nats import NATSQueueAdapter, NATSQueueSettings
from oneiric.adapters.storage.local import LocalStorageAdapter, LocalStorageSettings
from oneiric.adapters.dns.gcdns import GCDNSAdapter, GCDNSSettings
from oneiric.adapters.file_transfer.http_artifact import (
    HTTPArtifactAdapter,
    HTTPArtifactSettings,
)


class _Recorder:
    def __init__(self) -> None:
        self.calls = []

    def record(self, value, attributes=None):
        self.calls.append(("record", value, dict(attributes or {})))

    def add(self, value, attributes=None):
        self.calls.append(("add", value, dict(attributes or {})))


def test_adapter_metrics_branches(monkeypatch) -> None:
    duration = _Recorder()
    errors = _Recorder()
    timeouts = _Recorder()
    pool = _Recorder()
    queue = _Recorder()
    monkeypatch.setattr("oneiric.adapters.metrics._duration_hist", duration)
    monkeypatch.setattr("oneiric.adapters.metrics._error_counter", errors)
    monkeypatch.setattr("oneiric.adapters.metrics._timeout_counter", timeouts)
    monkeypatch.setattr("oneiric.adapters.metrics._pool_hist", pool)
    monkeypatch.setattr("oneiric.adapters.metrics._queue_hist", queue)

    record_adapter_request_metrics(
        domain="adapter",
        adapter="storage",
        provider="local",
        operation="save",
        duration_ms=-5.0,
        success=False,
        timeout=True,
    )
    capture_adapter_state_metrics(
        SimpleNamespace(pool_size=lambda: 4, queue_depth=2),
        category="storage",
        provider="local",
    )

    assert duration.calls[0][1] == 0.0
    assert errors.calls[0][0] == "add"
    assert timeouts.calls[0][0] == "add"
    assert pool.calls[0][1] == 4.0
    assert queue.calls[0][1] == 2.0
    assert _extract_numeric(SimpleNamespace(), ("missing",)) is None
    assert _read_value(SimpleNamespace(bad=lambda: (_ for _ in ()).throw(RuntimeError())), "bad") is None


@pytest.mark.asyncio
async def test_embedding_service_branches(monkeypatch) -> None:
    service = EmbeddingService()
    trace = {
        "trace_id": "abc",
        "service": "svc",
        "operation": "op",
        "status": "OK",
        "duration_ms": 12,
        "attributes": {"b": 2, "a": 1},
    }
    text = service._build_text_from_trace(trace)
    assert "a=1 b=2" in text
    assert isinstance(service._generate_cache_key({"trace_id": "abc", "service": "svc", "operation": "op"}), int)
    assert len(service._generate_fallback_embedding("x")) == 384

    monkeypatch.setattr(
        "oneiric.adapters.observability.embeddings.SENTENCE_TRANSFORMERS_AVAILABLE",
        False,
    )
    with pytest.raises(ImportError):
        service._load_model()

    monkeypatch.setattr(
        "oneiric.adapters.observability.embeddings.SENTENCE_TRANSFORMERS_AVAILABLE",
        True,
    )

    class FakeModel:
        def encode(self, text):
            return np.array([1.0, 2.0])

    monkeypatch.setattr(
        "oneiric.adapters.observability.embeddings.SentenceTransformer",
        lambda model_name: FakeModel(),
    )
    monkeypatch.setattr(service, "_embed_cached", lambda cache_key, text: (_ for _ in ()).throw(RuntimeError("boom")))
    fallback = await service.embed_trace({"trace_id": "trace-1"})
    assert len(fallback) == 384


@pytest.mark.asyncio
async def test_local_storage_branches(tmp_path) -> None:
    adapter = LocalStorageAdapter(
        LocalStorageSettings(base_path=tmp_path / "store", create_parents=False)
    )
    with pytest.raises(Exception):
        await adapter.init()

    adapter = LocalStorageAdapter(LocalStorageSettings(base_path=tmp_path / "store"))
    await adapter.init()
    assert await adapter.health() is True
    assert await adapter.read("missing") is None
    assert await adapter.exists("missing") is False
    saved = await adapter.save("nested/file.txt", b"hello")
    assert Path(saved).read_bytes() == b"hello"
    assert await adapter.list(prefix="nested") == ["nested/file.txt"]
    await adapter.delete("nested/file.txt")
    assert await adapter.read("nested/file.txt") is None
    with pytest.raises(Exception):
        adapter._resolve_path("../escape")


@pytest.mark.asyncio
async def test_nats_queue_branches() -> None:
    class FakeClient:
        is_connected = False

        async def publish(self, subject, payload, headers=None):
            return None

        async def subscribe(self, subject, queue=None, cb=None):
            return SimpleNamespace(subject=subject, queue=queue)

        async def request(self, subject, payload, timeout=None):
            return SimpleNamespace(data=b"ok")

        async def drain(self):
            return None

        async def close(self):
            return None

    adapter = NATSQueueAdapter(settings=NATSQueueSettings(), client=FakeClient())
    assert await adapter.health() is False
    with pytest.raises(Exception):
        await adapter.subscribe("demo")
    await adapter.publish("demo", b"payload")
    resp = await adapter.request("demo", b"payload")
    assert resp.data == b"ok"
    await adapter.cleanup()


@pytest.mark.asyncio
async def test_gcdns_branches(monkeypatch) -> None:
    class FakeRecord:
        def __init__(self, name, record_type, ttl=300, rrdatas=None):
            self.name = name
            self.record_type = record_type
            self.ttl = ttl
            self.rrdatas = rrdatas or []

    class FakeChange:
        def __init__(self):
            self.id = "change-1"
            self.calls = []

        def add_record_set(self, record):
            self.calls.append(("add", record))

        def delete_record_set(self, record):
            self.calls.append(("del", record))

        def create(self):
            return None

    class FakeZone:
        def __init__(self):
            self.records = [FakeRecord("a.example.com.", "A", 60, ["1.2.3.4"])]

        def exists(self):
            return True

        def list_resource_record_sets(self):
            return self.records

        def resource_record_set(self, name, record_type, ttl, content):
            return FakeRecord(name, record_type, ttl, content)

        def changes(self):
            return FakeChange()

    class FakeClient:
        def zone(self, name):
            return FakeZone()

    adapter = GCDNSAdapter(GCDNSSettings(managed_zone="example.com"), client=FakeClient(), zone=FakeZone())
    assert await adapter.health() is True
    records = await adapter.list_records(record_type="A")
    assert records[0]["name"] == "a.example.com."
    change_id = await adapter.create_record(name="b.example.com.", content="5.6.7.8")
    assert change_id == "change-1"
    assert await adapter.delete_record(name="a.example.com.", content="1.2.3.4") is True
    assert adapter._ensure_zone() is not None


@pytest.mark.asyncio
async def test_http_artifact_branches(monkeypatch) -> None:
    class FakeResponse:
        status_code = 200
        content = b"hello"

        def raise_for_status(self):
            return None

    class FakeClient:
        async def aclose(self):
            return None

        async def get(self, url, timeout=None):
            return FakeResponse()

    adapter = HTTPArtifactAdapter(HTTPArtifactSettings(base_url=None), client=FakeClient())
    assert await adapter.health() is True
    data = await adapter.download("artifact.bin")
    assert data == b"hello"
    await adapter.cleanup()
