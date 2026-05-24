"""Tests for the Firestore adapter."""

from __future__ import annotations

from typing import Any

import pytest

from oneiric.adapters.nosql.firestore import FirestoreAdapter, FirestoreSettings
from oneiric.adapters.nosql.nosql_types import NoSQLDocument


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


# ---------------------------------------------------------------------------
# Tests — coverage gaps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_cleanup_closes_client(
    adapter: FirestoreAdapter, fake_client: FakeClient
) -> None:
    """cleanup() closes client and nils _client (lines 80-88)."""
    await adapter.init()
    await adapter.cleanup()
    assert fake_client.closed is True
    assert adapter._client is None


@pytest.mark.asyncio()
async def test_cleanup_noop_when_no_client(adapter: FirestoreAdapter) -> None:
    """cleanup() returns early when _client is None (line 80)."""
    assert adapter._client is None
    await adapter.cleanup()  # must not raise


@pytest.mark.asyncio()
async def test_query_documents_with_limit(adapter: FirestoreAdapter) -> None:
    """query_documents applies limit to query (line 123)."""
    await adapter.set_document("a", {"status": "ok"})
    await adapter.set_document("b", {"status": "ok"})
    docs = await adapter.query_documents(limit=1)
    assert len(docs) == 1


@pytest.mark.asyncio()
async def test_ensure_client_awaitable_factory() -> None:
    """_ensure_client awaits factory when it returns a coroutine (line 141)."""
    fake = FakeClient()

    async def async_factory() -> FakeClient:
        return fake

    settings = FirestoreSettings(project_id="p", collection="items")
    adapter = FirestoreAdapter(settings, client_factory=async_factory)
    await adapter.init()
    assert adapter._client is fake


@pytest.mark.asyncio()
async def test_default_client_factory_uses_google_cloud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_default_client_factory creates AsyncClient when google.cloud is importable (lines 148-172)."""
    import sys
    import types

    created: list[dict] = []

    class FakeAsyncClient:
        def __init__(self, project: str, credentials: Any = None) -> None:
            created.append({"project": project, "credentials": credentials})
            self.store: dict[str, Any] = {}
            self.closed = False

        def collection(self, name: str) -> FakeCollection:
            namespace = self.store.setdefault(name, {})
            return FakeCollection(namespace)

        def close(self) -> None:
            self.closed = True

    fake_fs_module = types.ModuleType("google.cloud.firestore_v1.async_client")
    fake_fs_module.AsyncClient = FakeAsyncClient  # type: ignore[attr-defined]
    fake_google = types.ModuleType("google")
    fake_cloud = types.ModuleType("google.cloud")
    fake_firestore_v1 = types.ModuleType("google.cloud.firestore_v1")

    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.cloud", fake_cloud)
    monkeypatch.setitem(sys.modules, "google.cloud.firestore_v1", fake_firestore_v1)
    monkeypatch.setitem(
        sys.modules, "google.cloud.firestore_v1.async_client", fake_fs_module
    )

    settings = FirestoreSettings(project_id="my-project", collection="items")
    adapter = FirestoreAdapter(settings)
    await adapter.init()
    assert len(created) == 1
    assert created[0]["project"] == "my-project"


@pytest.mark.asyncio()
async def test_cleanup_awaitable_close() -> None:
    """cleanup() awaits close() when it returns a coroutine (line 86)."""
    closed: list[bool] = []

    class AsyncCloseClient:
        store: dict = {}

        def collection(self, name: str) -> FakeCollection:
            namespace = self.store.setdefault(name, {})
            return FakeCollection(namespace)

        async def close(self) -> None:
            closed.append(True)

    settings = FirestoreSettings(project_id="p", collection="items")
    adapter = FirestoreAdapter(settings, client_factory=lambda: AsyncCloseClient())
    await adapter.init()
    await adapter.cleanup()
    assert closed == [True]
    assert adapter._client is None


@pytest.mark.asyncio()
async def test_default_client_factory_with_emulator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_default_client_factory sets FIRESTORE_EMULATOR_HOST when emulator_host is set (line 167-170)."""
    import os
    import sys
    import types

    class FakeAsyncClient:
        def __init__(self, project: str, credentials: Any = None) -> None:
            self.store: dict[str, Any] = {}
            self.closed = False

        def collection(self, name: str) -> FakeCollection:
            namespace = self.store.setdefault(name, {})
            return FakeCollection(namespace)

        def close(self) -> None:
            self.closed = True

    fake_fs_module = types.ModuleType("google.cloud.firestore_v1.async_client")
    fake_fs_module.AsyncClient = FakeAsyncClient  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "google", types.ModuleType("google"))
    monkeypatch.setitem(sys.modules, "google.cloud", types.ModuleType("google.cloud"))
    monkeypatch.setitem(
        sys.modules,
        "google.cloud.firestore_v1",
        types.ModuleType("google.cloud.firestore_v1"),
    )
    monkeypatch.setitem(
        sys.modules, "google.cloud.firestore_v1.async_client", fake_fs_module
    )
    monkeypatch.delenv("FIRESTORE_EMULATOR_HOST", raising=False)

    settings = FirestoreSettings(
        project_id="p", collection="items", emulator_host="localhost:8080"
    )
    adapter = FirestoreAdapter(settings)
    await adapter.init()
    assert os.environ.get("FIRESTORE_EMULATOR_HOST") == "localhost:8080"


@pytest.mark.asyncio()
async def test_default_client_factory_with_credentials_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_default_client_factory loads credentials when credentials_file is set (lines 157-163)."""
    import sys
    import types

    loaded_files: list[str] = []

    class FakeCredentials:
        @staticmethod
        def from_service_account_file(path: str) -> FakeCredentials:
            loaded_files.append(path)
            return FakeCredentials()

    class FakeAsyncClient:
        def __init__(self, project: str, credentials: Any = None) -> None:
            self.store: dict[str, Any] = {}

        def collection(self, name: str) -> FakeCollection:
            return FakeCollection(self.store.setdefault(name, {}))

        def close(self) -> None:
            pass

    fake_fs_module = types.ModuleType("google.cloud.firestore_v1.async_client")
    fake_fs_module.AsyncClient = FakeAsyncClient  # type: ignore[attr-defined]
    fake_sa_module = types.ModuleType("google.oauth2.service_account")
    fake_sa_module.Credentials = FakeCredentials  # type: ignore[attr-defined]
    fake_oauth2 = types.ModuleType("google.oauth2")

    monkeypatch.setitem(sys.modules, "google", types.ModuleType("google"))
    monkeypatch.setitem(sys.modules, "google.cloud", types.ModuleType("google.cloud"))
    monkeypatch.setitem(
        sys.modules,
        "google.cloud.firestore_v1",
        types.ModuleType("google.cloud.firestore_v1"),
    )
    monkeypatch.setitem(
        sys.modules, "google.cloud.firestore_v1.async_client", fake_fs_module
    )
    monkeypatch.setitem(sys.modules, "google.oauth2", fake_oauth2)
    monkeypatch.setitem(sys.modules, "google.oauth2.service_account", fake_sa_module)

    settings = FirestoreSettings(
        project_id="p", collection="items", credentials_file="/path/to/creds.json"
    )
    adapter = FirestoreAdapter(settings)
    await adapter.init()
    assert loaded_files == ["/path/to/creds.json"]
