"""Neo4j graph adapter."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable
from typing import Any

from pydantic import BaseModel, Field, SecretStr

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class Neo4jGraphSettings(BaseModel):
    """Configuration for the Neo4j adapter."""

    uri: str = Field(
        default="bolt://localhost:7687", description="Bolt URI for the Neo4j instance."
    )
    database: str | None = Field(
        default=None, description="Optional database name (Neo4j Enterprise)."
    )
    username: str | None = Field(default="neo4j", description="Neo4j username.")
    password: SecretStr | None = Field(
        default=None, description="Neo4j password/secret."
    )
    encrypted: bool = Field(
        default=False, description="Enable TLS encryption (True/False)."
    )
    max_connection_pool_size: int = Field(
        default=10, ge=1, description="Driver connection pool size."
    )


class Neo4jGraphAdapter:
    """Adapter that performs basic graph CRUD and queries via Neo4j's async driver."""

    metadata = AdapterMetadata(
        category="graph",
        provider="neo4j",
        factory="oneiric.adapters.graph.neo4j:Neo4jGraphAdapter",
        capabilities=["nodes", "relationships", "cypher"],
        stack_level=30,
        priority=400,
        source=CandidateSource.LOCAL_PKG,
        owner="Data Platform",
        requires_secrets=True,
        settings_model=Neo4jGraphSettings,
    )

    def __init__(
        self,
        settings: Neo4jGraphSettings | None = None,
        *,
        driver_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._settings = settings or Neo4jGraphSettings()
        self._driver_factory = driver_factory
        self._driver: Any | None = None
        self._logger = get_logger("adapter.graph.neo4j").bind(
            domain="adapter",
            key="graph",
            provider="neo4j",
        )

    async def init(self) -> None:
        await self._ensure_driver()
        self._logger.info("neo4j-adapter-init")

    async def health(self) -> bool:
        try:
            driver = await self._ensure_driver()
            async with driver.session(database=self._settings.database) as session:
                await session.run("RETURN 1;")
            return True
        except Exception as exc:  # pragma: no cover - network
            self._logger.warning("neo4j-health-check-failed", error=str(exc))
            return False

    async def cleanup(self) -> None:
        if self._driver:
            close = getattr(self._driver, "close", None)
            if callable(close):
                result = close()
                if inspect.isawaitable(result):
                    await result
            self._driver = None
        self._logger.info("neo4j-adapter-cleanup")

    async def create_node(
        self, labels: Iterable[str], properties: dict[str, Any]
    ) -> dict[str, Any]:
        query = "CREATE (n" + ":".join(["", *labels]) + ") SET n = $props RETURN n"
        return (await self._run_query(query, props=properties)).get("n")

    async def create_relationship(
        self,
        from_id: Any,
        to_id: Any,
        rel_type: str,
        properties: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        query = (
            "MATCH (a),(b) WHERE id(a) = $from_id AND id(b) = $to_id "
            f"CREATE (a)-[r:{rel_type}]->(b) SET r = $props RETURN r"
        )
        return (
            await self._run_query(
                query, from_id=from_id, to_id=to_id, props=properties or {}
            )
        ).get("r")

    async def query(self, cypher: str, **parameters: Any) -> list[dict[str, Any]]:
        records = await self._run_query_many(cypher, **parameters)
        return [record.data() for record in records]

    async def _run_query(self, cypher: str, **parameters: Any) -> dict[str, Any]:
        records = await self._run_query_many(cypher, **parameters)
        if not records:
            return {}
        first = records[0]
        if hasattr(first, "data"):
            return first.data()
        return first

    async def _run_query_many(self, cypher: str, **parameters: Any) -> list[Any]:
        driver = await self._ensure_driver()
        async with driver.session(database=self._settings.database) as session:
            result = await session.run(cypher, **parameters)
            data = await result.data()
        return data

    async def _ensure_driver(self) -> Any:
        if self._driver:
            return self._driver
        if self._driver_factory:
            driver = self._driver_factory()
        else:
            driver = self._default_driver_factory()
        if inspect.isawaitable(driver):
            driver = await driver
        if driver is None:  # pragma: no cover - defensive
            raise LifecycleError("neo4j-driver-factory-returned-none")
        self._driver = driver
        return driver

    def _default_driver_factory(self) -> Any:
        try:
            from neo4j import AsyncGraphDatabase  # type: ignore
        except ModuleNotFoundError as exc:  # pragma: no cover - optional dep
            raise LifecycleError(
                "neo4j-driver-not-installed: install optional extra 'oneiric[graph-neo4j]' to use Neo4jGraphAdapter"
            ) from exc

        auth = None
        if self._settings.username and self._settings.password:
            auth = (self._settings.username, self._settings.password.get_secret_value())
        return AsyncGraphDatabase.driver(
            self._settings.uri,
            auth=auth,
            encrypted=self._settings.encrypted,
            max_connection_pool_size=self._settings.max_connection_pool_size,
        )
