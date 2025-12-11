"""ArangoDB graph adapter."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, Field, SecretStr

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class ArangoDBGraphSettings(BaseModel):
    """Configuration for the ArangoDB adapter."""

    hosts: str = Field(
        default="http://localhost:8529", description="HTTP hosts URI for ArangoDB."
    )
    database: str = Field(default="_system", description="Database name to connect to.")
    graph: str | None = Field(
        default=None, description="Optional named graph to target."
    )
    username: str = Field(default="root", description="ArangoDB username.")
    password: SecretStr | None = Field(
        default=None, description="ArangoDB password/secret."
    )
    verify: bool = Field(default=True, description="Verify TLS certificates.")
    request_timeout: float = Field(
        default=30.0, gt=0, description="HTTP request timeout in seconds."
    )


class ArangoDBGraphAdapter:
    """Adapter that exposes basic vertex/edge helpers backed by python-arango."""

    metadata = AdapterMetadata(
        category="graph",
        provider="arangodb",
        factory="oneiric.adapters.graph.arangodb:ArangoDBGraphAdapter",
        capabilities=["vertices", "edges", "aql"],
        stack_level=30,
        priority=390,
        source=CandidateSource.LOCAL_PKG,
        owner="Data Platform",
        requires_secrets=True,
        settings_model=ArangoDBGraphSettings,
    )

    def __init__(
        self,
        settings: ArangoDBGraphSettings | None = None,
        *,
        client_factory: Callable[[], Any] | None = None,
        sync_executor: Callable[
            [Callable[..., Any], tuple[Any, ...], dict[str, Any]], Awaitable[Any]
        ]
        | None = None,
    ) -> None:
        self._settings = settings or ArangoDBGraphSettings()
        self._client_factory = client_factory
        self._sync_executor = sync_executor
        self._client: Any = None
        self._db: Any = None
        self._graph: Any = None
        self._logger = get_logger("adapter.graph.arangodb").bind(
            domain="adapter",
            key="graph",
            provider="arangodb",
        )

    async def init(self) -> None:
        await self._ensure_client()
        self._logger.info("arangodb-adapter-init")

    async def health(self) -> bool:
        try:
            await self._ensure_client()
            await self.query_aql("RETURN 1")
            return True
        except Exception as exc:  # pragma: no cover - external dependency
            self._logger.warning("arangodb-health-failed", error=str(exc))
            return False

    async def cleanup(self) -> None:
        client = self._client
        self._client = None
        self._db = None
        self._graph = None
        if client:
            close = getattr(client, "close", None)
            if callable(close):
                result = close()
                if inspect.isawaitable(result):
                    await result
        self._logger.info("arangodb-adapter-cleanup")

    async def create_vertex(
        self, collection: str, document: dict[str, Any]
    ) -> dict[str, Any]:
        await self._ensure_client()
        coll = self._vertex_collection(collection)
        result = await self._run_sync(coll.insert, document)
        return result or {}

    async def create_edge(
        self,
        collection: str,
        from_id: str,
        to_id: str,
        document: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        await self._ensure_client()
        coll = self._edge_collection(collection)
        payload = dict(document or {})
        payload.setdefault("_from", from_id)
        payload.setdefault("_to", to_id)
        result = await self._run_sync(coll.insert, payload)
        return result or {}

    async def get_vertex(self, collection: str, key: str) -> dict[str, Any] | None:
        await self._ensure_client()
        coll = self._vertex_collection(collection)
        result = await self._run_sync(coll.get, key)
        return result

    async def query_aql(
        self, query: str, *, bind_vars: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        await self._ensure_client()
        cursor = await self._run_sync(
            self._db.aql.execute,
            query,
            bind_vars=bind_vars or None,
            stream=False,
            timeout=self._settings.request_timeout,
        )
        return [row for row in cursor or []]

    async def _ensure_client(self) -> None:
        if self._db:
            return
        factory = self._client_factory or self._default_client_factory
        client = factory()
        if inspect.isawaitable(client):
            client = await client
        if client is None:  # pragma: no cover - defensive
            raise LifecycleError("arangodb-client-factory-returned-none")
        db = getattr(client, "db", None)
        if not callable(db):  # pragma: no cover - defensive
            raise LifecycleError("arangodb-client-missing-db-method")
        auth_password = (
            self._settings.password.get_secret_value()
            if self._settings.password
            else None
        )
        db_handle = db(
            self._settings.database,
            username=self._settings.username,
            password=auth_password,
        )
        if db_handle is None:  # pragma: no cover - defensive
            raise LifecycleError("arangodb-db-handle-none")
        self._client = client
        self._db = db_handle
        self._graph = None
        if self._settings.graph:
            self._graph = db_handle.graph(self._settings.graph)

    def _vertex_collection(self, collection: str) -> Any:
        if self._graph:
            return self._graph.vertex_collection(collection)
        return self._db.collection(collection)

    def _edge_collection(self, collection: str) -> Any:
        if self._graph:
            return self._graph.edge_collection(collection)
        return self._db.collection(collection)

    async def _run_sync(
        self, func: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> Any:
        if self._sync_executor:
            return await self._sync_executor(func, args, kwargs)
        return await asyncio.to_thread(func, *args, **kwargs)

    def _default_client_factory(self) -> Any:
        try:
            from arango import ArangoClient  # type: ignore
        except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
            raise LifecycleError(
                "arangodb-driver-not-installed: install optional extra 'oneiric[graph-arangodb]' to use ArangoDBGraphAdapter"
            ) from exc

        return ArangoClient(
            hosts=self._settings.hosts,
            verify=self._settings.verify,
            request_timeout=self._settings.request_timeout,
        )
