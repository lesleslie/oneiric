"""Firestore adapter built on google-cloud-firestore async client."""

from __future__ import annotations

import inspect
import os
from collections.abc import Callable, Sequence
from typing import Any

from pydantic import Field

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource

from .common import NoSQLAdapterBase, NoSQLBaseSettings, NoSQLDocument


class FirestoreSettings(NoSQLBaseSettings):
    """Configuration for the Firestore adapter."""

    project_id: str = Field(
        default="demo-project", description="Google Cloud project ID."
    )
    collection: str = Field(
        default="documents", description="Collection used for CRUD operations."
    )
    credentials_file: str | None = Field(
        default=None,
        description="Optional path to a service account JSON file when not using ADC.",
    )
    emulator_host: str | None = Field(
        default=None,
        description="Optional Firestore emulator host (HOST:PORT). When set, this value is injected into FIRESTORE_EMULATOR_HOST.",
    )


class FirestoreAdapter(NoSQLAdapterBase):
    """Async Firestore adapter."""

    metadata = AdapterMetadata(
        category="nosql",
        provider="firestore",
        factory="oneiric.adapters.nosql.firestore:FirestoreAdapter",
        capabilities=["documents", "query", "serverless"],
        stack_level=30,
        priority=420,
        source=CandidateSource.LOCAL_PKG,
        owner="Data Platform",
        requires_secrets=True,
        settings_model=FirestoreSettings,
    )

    def __init__(
        self,
        settings: FirestoreSettings,
        *,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        super().__init__(settings)
        self._settings = settings
        self._client_factory = client_factory
        self._client: Any | None = None
        self._logger = get_logger("adapter.nosql.firestore").bind(
            domain="adapter",
            key="nosql",
            provider="firestore",
        )

    async def init(self) -> None:
        await self._ensure_client()
        self._logger.info("firestore-adapter-init")

    async def health(self) -> bool:
        try:
            collection = await self._get_collection()
            query = collection.limit(1)
            await query.get()
            return True
        except Exception as exc:  # pragma: no cover - network/runtime errors
            self._logger.warning("firestore-health-check-failed", error=str(exc))
            return False

    async def cleanup(self) -> None:
        if not self._client:
            return
        close = getattr(self._client, "close", None)
        if callable(close):
            result = close()
            if inspect.isawaitable(result):
                await result
        self._client = None
        self._logger.info("firestore-adapter-cleanup")

    async def get_document(self, document_id: str) -> NoSQLDocument | None:
        collection = await self._get_collection()
        snapshot = await collection.document(document_id).get()
        return self._serialize_snapshot(snapshot)

    async def set_document(
        self,
        document_id: str,
        data: dict[str, Any],
        *,
        merge: bool = False,
    ) -> str:
        collection = await self._get_collection()
        await collection.document(document_id).set(data, merge=merge)
        return document_id

    async def delete_document(self, document_id: str) -> bool:
        collection = await self._get_collection()
        await collection.document(document_id).delete()
        return True

    async def query_documents(
        self,
        filters: Sequence[tuple[str, str, Any]] | None = None,
        *,
        limit: int | None = None,
    ) -> list[NoSQLDocument]:
        collection = await self._get_collection()
        query = collection
        for filter_entry in filters or []:
            field, op, value = filter_entry
            query = query.where(field, op, value)
        if limit:
            query = query.limit(limit)
        snapshots = await query.get()
        documents: list[NoSQLDocument] = []
        for snapshot in snapshots or []:
            serialized = self._serialize_snapshot(snapshot)
            if serialized:
                documents.append(serialized)
        return documents

    async def _get_collection(self) -> Any:
        return (await self._ensure_client()).collection(self._settings.collection)

    async def _ensure_client(self) -> Any:
        if self._client:
            return self._client
        factory = self._client_factory or self._default_client_factory
        client = factory()
        if inspect.isawaitable(client):
            client = await client
        if client is None:  # pragma: no cover - defensive
            raise LifecycleError("firestore-client-factory-returned-none")
        self._client = client
        return client

    def _default_client_factory(self) -> Any:
        try:
            from google.cloud.firestore_v1.async_client import AsyncClient
        except ModuleNotFoundError as exc:  # pragma: no cover - optional dep
            raise LifecycleError(
                "firestore-extra-missing: install 'oneiric[nosql-firestore]' to use FirestoreAdapter"
            ) from exc

        credentials = None
        if self._settings.credentials_file:
            try:
                from google.oauth2 import service_account
            except ModuleNotFoundError as exc:  # pragma: no cover - optional dep
                raise LifecycleError(
                    "google-oauth-extra-missing: install 'google-cloud-firestore' extras for credentials support"
                ) from exc
            credentials = service_account.Credentials.from_service_account_file(
                self._settings.credentials_file
            )

        if self._settings.emulator_host:
            os.environ.setdefault(
                "FIRESTORE_EMULATOR_HOST", self._settings.emulator_host
            )

        return AsyncClient(project=self._settings.project_id, credentials=credentials)

    def _serialize_snapshot(self, snapshot: Any) -> NoSQLDocument | None:
        if not snapshot or not getattr(snapshot, "exists", True):
            return None
        data = snapshot.to_dict() or {}
        return NoSQLDocument(id=getattr(snapshot, "id", None), data=data)
