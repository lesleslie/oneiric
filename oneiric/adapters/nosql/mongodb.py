"""MongoDB adapter built on top of Motor."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from pydantic import Field, SecretStr

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource

from .common import NoSQLAdapterBase, NoSQLBaseSettings, NoSQLDocument, NoSQLQuery

if TYPE_CHECKING:  # pragma: no cover - optional dependency typing
    from motor.motor_asyncio import (
        AsyncIOMotorClient,
        AsyncIOMotorCollection,
        AsyncIOMotorDatabase,
    )
else:  # pragma: no cover - runtime guard
    AsyncIOMotorClient = Any
    AsyncIOMotorCollection = Any
    AsyncIOMotorDatabase = Any


class MongoDBSettings(NoSQLBaseSettings):
    """Configuration for the MongoDB adapter."""

    uri: str | None = Field(
        default=None,
        description="Optional MongoDB URI; overrides discrete host/port credentials when set.",
    )
    host: str = Field(
        default="localhost", description="MongoDB host when URI is not supplied."
    )
    port: int = Field(
        default=27017, description="MongoDB port when URI is not supplied."
    )
    username: str | None = Field(
        default=None, description="Optional username for auth."
    )
    password: SecretStr | None = Field(
        default=None, description="Optional password/secret."
    )
    auth_source: str | None = Field(
        default=None,
        description="Optional authentication database; defaults to the target database.",
    )
    database: str = Field(
        default="oneiric", description="Primary database to operate on."
    )
    default_collection: str = Field(
        default="documents",
        description="Fallback collection name when none is supplied at call time.",
    )
    tls: bool = Field(default=False, description="Enable TLS/SSL (defaults to False).")
    replica_set: str | None = Field(
        default=None, description="Optional replica set name."
    )


class MongoDBAdapter(NoSQLAdapterBase):
    """Motor-backed MongoDB adapter with CRUD helpers."""

    metadata = AdapterMetadata(
        category="nosql",
        provider="mongodb",
        factory="oneiric.adapters.nosql.mongodb:MongoDBAdapter",
        capabilities=[
            "documents",
            "aggregation",
            "filtering",
        ],
        stack_level=30,
        priority=440,
        source=CandidateSource.LOCAL_PKG,
        owner="Data Platform",
        requires_secrets=True,
        settings_model=MongoDBSettings,
    )

    def __init__(
        self,
        settings: MongoDBSettings,
        *,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        super().__init__(settings)
        self._settings = settings
        self._client_factory = client_factory
        self._client: AsyncIOMotorClient | None = None
        self._db: AsyncIOMotorDatabase | None = None
        self._logger = get_logger("adapter.nosql.mongodb").bind(
            domain="adapter",
            key="nosql",
            provider="mongodb",
        )

    async def init(self) -> None:
        await self._ensure_client()
        self._logger.info("mongodb-adapter-init")

    async def health(self) -> bool:
        try:
            await self._ensure_client()
            await self._client.admin.command("ping")  # type: ignore[union-attr]
            return True
        except Exception as exc:  # pragma: no cover - network
            self._logger.warning("mongodb-health-failed", error=str(exc))
            return False

    async def cleanup(self) -> None:
        if self._client:
            self._client.close()
            self._client = None
            self._db = None
            self._logger.info("mongodb-adapter-cleanup")

    async def find_one(
        self,
        filters: dict[str, Any] | None = None,
        *,
        projection: dict[str, int] | None = None,
        collection: str | None = None,
    ) -> NoSQLDocument | None:
        await self._ensure_client()
        coll = self._collection(collection)
        document = await coll.find_one(filters or {}, projection=projection)
        return self._serialize_document(document)

    async def find(
        self,
        query: NoSQLQuery | None = None,
        *,
        collection: str | None = None,
    ) -> list[NoSQLDocument]:
        await self._ensure_client()
        query = query or NoSQLQuery()
        projection = self._projection_dict(query.projection)
        cursor = self._collection(collection).find(query.filters, projection=projection)
        if query.sort:
            cursor = cursor.sort(query.sort)
        limit = query.limit
        if limit:
            cursor = cursor.limit(limit)
        results = await cursor.to_list(length=limit or 1000)
        return [
            serialized
            for document in results
            if (serialized := self._serialize_document(document))
        ]

    async def insert_one(
        self,
        document: dict[str, Any],
        *,
        collection: str | None = None,
    ) -> str:
        await self._ensure_client()
        coll = self._collection(collection)
        result = await coll.insert_one(document)
        inserted_id = getattr(result, "inserted_id", None)
        return str(inserted_id) if inserted_id is not None else ""

    async def update_one(
        self,
        filters: dict[str, Any],
        update: dict[str, Any],
        *,
        collection: str | None = None,
        upsert: bool = False,
    ) -> bool:
        await self._ensure_client()
        coll = self._collection(collection)
        result = await coll.update_one(filters, update, upsert=upsert)
        return bool(
            getattr(result, "matched_count", 0) or getattr(result, "upserted_id", None)
        )

    async def delete_one(
        self,
        filters: dict[str, Any],
        *,
        collection: str | None = None,
    ) -> bool:
        await self._ensure_client()
        coll = self._collection(collection)
        result = await coll.delete_one(filters)
        return bool(getattr(result, "deleted_count", 0))

    async def aggregate(
        self,
        pipeline: Sequence[dict[str, Any]],
        *,
        collection: str | None = None,
    ) -> list[dict[str, Any]]:
        await self._ensure_client()
        cursor = self._collection(collection).aggregate(list(pipeline))
        results = await cursor.to_list(length=None)
        return [self._normalize_raw(document) for document in results]

    async def _ensure_client(self) -> None:
        if self._client and self._db:
            return
        params = self._client_params()
        factory = self._client_factory or self._default_client_factory
        self._client = factory(**params)
        if self._client is None:  # pragma: no cover - defensive
            raise LifecycleError("mongodb-client-factory-returned-none")
        self._db = self._client[self._settings.database]
        await self._client.admin.command("ping")  # type: ignore[union-attr]

    def _collection(self, collection: str | None) -> AsyncIOMotorCollection:
        if not self._db:
            raise LifecycleError("mongodb-database-not-initialized")
        return self._db[collection or self._settings.default_collection]

    def _client_params(self) -> dict[str, Any]:
        """Build Motor client parameters."""

        params: dict[str, Any] = {
            "serverSelectionTimeoutMS": int(self._settings.connect_timeout * 1000),
            "socketTimeoutMS": int(self._settings.operation_timeout * 1000),
            "tls": self._settings.tls,
        }
        if self._settings.uri:
            params["host"] = self._settings.uri
        else:
            params["host"] = self._settings.host
            params["port"] = self._settings.port
            if self._settings.username:
                params["username"] = self._settings.username
            if self._settings.password:
                params["password"] = self._settings.password.get_secret_value()
        if self._settings.auth_source:
            params["authSource"] = self._settings.auth_source
        elif not self._settings.uri and self._settings.username:
            params["authSource"] = self._settings.database
        if self._settings.replica_set:
            params["replicaSet"] = self._settings.replica_set
        return params

    def _default_client_factory(self, **kwargs: Any) -> AsyncIOMotorClient:
        try:
            from motor.motor_asyncio import AsyncIOMotorClient as MotorClient
        except ModuleNotFoundError as exc:  # pragma: no cover - optional dep
            raise LifecycleError(
                "motor-not-installed: install optional extra 'oneiric[nosql-mongo]' to use MongoDBAdapter"
            ) from exc
        return MotorClient(**kwargs)

    def _serialize_document(
        self, document: dict[str, Any] | None
    ) -> NoSQLDocument | None:
        if not document:
            return None
        payload = document.copy()
        doc_id = payload.pop("_id", None)
        return NoSQLDocument(
            id=str(doc_id) if doc_id is not None else None, data=payload
        )

    def _normalize_raw(self, document: dict[str, Any]) -> dict[str, Any]:
        payload = document.copy()
        doc_id = payload.get("_id")
        if doc_id is not None:
            payload["_id"] = str(doc_id)
        return payload

    def _projection_dict(self, fields: list[str] | None) -> dict[str, int] | None:
        if not fields:
            return None
        return {field: 1 for field in fields}
