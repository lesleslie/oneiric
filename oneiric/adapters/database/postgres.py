"""Postgres database adapter."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, Field

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class PostgresDatabaseSettings(BaseModel):
    """Configuration for the Postgres adapter."""

    dsn: str | None = Field(
        default=None,
        description="Optional DSN string; overrides host/port/database if provided.",
    )
    host: str = "localhost"
    port: int = 5432
    user: str = "postgres"
    password: str | None = None
    database: str = "postgres"
    min_size: int = Field(default=1, ge=1)
    max_size: int = Field(default=10, ge=1)
    statement_timeout_ms: int | None = Field(default=None, ge=1)
    ssl: bool = False


class PostgresDatabaseAdapter:
    """Asyncpg-backed Postgres adapter with lifecycle hooks."""

    metadata = AdapterMetadata(
        category="database",
        provider="postgres",
        factory="oneiric.adapters.database.postgres:PostgresDatabaseAdapter",
        capabilities=["sql", "pool", "transactions"],
        stack_level=30,
        priority=500,
        source=CandidateSource.LOCAL_PKG,
        owner="Data Platform",
        requires_secrets=True,
        settings_model=PostgresDatabaseSettings,
    )

    def __init__(
        self,
        settings: PostgresDatabaseSettings,
        *,
        pool_factory: Callable[..., Awaitable[Any]] | None = None,
    ) -> None:
        self._settings = settings
        self._pool_factory = pool_factory
        self._pool: Any = None
        self._logger = get_logger("adapter.database.postgres").bind(
            domain="adapter",
            key="database",
            provider="postgres",
        )

    async def init(self) -> None:
        if self._pool:
            return
        factory = self._pool_factory
        if factory is None:
            try:
                import asyncpg
            except ModuleNotFoundError as exc:  # pragma: no cover - defensive
                raise LifecycleError("asyncpg-missing") from exc
            factory = asyncpg.create_pool
        conn_kwargs = self._connection_kwargs()
        if self._settings.dsn:
            conn_kwargs["dsn"] = self._settings.dsn
        self._pool = await factory(
            **conn_kwargs,
        )
        self._logger.info("adapter-init", adapter="postgres-database")

    async def health(self) -> bool:
        pool = self._ensure_pool()
        try:
            connection = await pool.acquire()
            try:
                await connection.execute("SELECT 1;")
            finally:
                await pool.release(connection)
            return True
        except Exception as exc:  # pragma: no cover - network path
            self._logger.warning("adapter-health-error", error=str(exc))
            return False

    async def cleanup(self) -> None:
        if not self._pool:
            return
        await self._pool.close()
        self._pool = None
        self._logger.info("adapter-cleanup-complete", adapter="postgres-database")

    async def execute(self, query: str, *args: Any) -> Any:
        pool = self._ensure_pool()
        return await pool.execute(query, *args)

    async def fetch_all(self, query: str, *args: Any) -> list[Any]:
        pool = self._ensure_pool()
        records = await pool.fetch(query, *args)
        return list(records)

    async def fetch_one(self, query: str, *args: Any) -> Any:
        pool = self._ensure_pool()
        return await pool.fetchrow(query, *args)

    def _ensure_pool(self) -> Any:
        if not self._pool:
            raise LifecycleError("postgres-pool-not-initialized")
        return self._pool

    def _connection_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "host": self._settings.host,
            "port": self._settings.port,
            "user": self._settings.user,
            "password": self._settings.password,
            "database": self._settings.database,
            "min_size": self._settings.min_size,
            "max_size": self._settings.max_size,
        }
        if self._settings.statement_timeout_ms:
            kwargs["statement_cache_size"] = 0
            kwargs["command_timeout"] = self._settings.statement_timeout_ms / 1000
        if self._settings.ssl:
            kwargs["ssl"] = True
        return kwargs
