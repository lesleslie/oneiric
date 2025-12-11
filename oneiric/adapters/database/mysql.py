"""MySQL database adapter."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, Field

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class MySQLDatabaseSettings(BaseModel):
    """Configuration for the MySQL adapter."""

    host: str = "localhost"
    port: int = 3306
    user: str = "root"
    password: str | None = None
    database: str = "mysql"
    min_size: int = Field(default=1, ge=1)
    max_size: int = Field(default=5, ge=1)
    connect_timeout: float = Field(default=10.0, gt=0)
    autocommit: bool = True
    charset: str = "utf8mb4"


class MySQLDatabaseAdapter:
    """aiomysql-backed MySQL adapter."""

    metadata = AdapterMetadata(
        category="database",
        provider="mysql",
        factory="oneiric.adapters.database.mysql:MySQLDatabaseAdapter",
        capabilities=["sql", "pool"],
        stack_level=30,
        priority=450,
        source=CandidateSource.LOCAL_PKG,
        owner="Data Platform",
        requires_secrets=True,
        settings_model=MySQLDatabaseSettings,
    )

    def __init__(
        self,
        settings: MySQLDatabaseSettings,
        *,
        pool_factory: Callable[..., Awaitable[Any]] | None = None,
    ) -> None:
        self._settings = settings
        self._pool_factory = pool_factory
        self._pool: Any = None
        self._logger = get_logger("adapter.database.mysql").bind(
            domain="adapter",
            key="database",
            provider="mysql",
        )

    async def init(self) -> None:
        if self._pool:
            return
        factory = self._pool_factory
        if factory is None:
            try:
                import aiomysql
            except ModuleNotFoundError as exc:  # pragma: no cover - defensive
                raise LifecycleError("aiomysql-missing") from exc
            factory = aiomysql.create_pool
        self._pool = await factory(
            host=self._settings.host,
            port=self._settings.port,
            user=self._settings.user,
            password=self._settings.password,
            db=self._settings.database,
            minsize=self._settings.min_size,
            maxsize=self._settings.max_size,
            autocommit=self._settings.autocommit,
            connect_timeout=self._settings.connect_timeout,
            charset=self._settings.charset,
        )
        self._logger.info("adapter-init", adapter="mysql-database")

    async def health(self) -> bool:
        pool = self._ensure_pool()
        try:
            conn = await pool.acquire()
            try:
                cursor = await conn.cursor()
                await cursor.execute("SELECT 1;")
                await cursor.close()
            finally:
                pool.release(conn)
            return True
        except Exception as exc:  # pragma: no cover - network
            self._logger.warning("adapter-health-error", error=str(exc))
            return False

    async def cleanup(self) -> None:
        if not self._pool:
            return
        self._pool.close()
        await self._pool.wait_closed()
        self._pool = None
        self._logger.info("adapter-cleanup-complete", adapter="mysql-database")

    async def execute(self, query: str, *args: Any) -> int:
        pool = self._ensure_pool()
        conn = await pool.acquire()
        try:
            cursor = await conn.cursor()
            await cursor.execute(query, args)
            if not self._settings.autocommit:
                await conn.commit()
            rowcount = cursor.rowcount or 0
            await cursor.close()
            return rowcount
        finally:
            pool.release(conn)

    async def fetch_all(self, query: str, *args: Any) -> list[Any]:
        pool = self._ensure_pool()
        conn = await pool.acquire()
        try:
            cursor = await conn.cursor()
            await cursor.execute(query, args)
            rows = await cursor.fetchall()
            await cursor.close()
            return list(rows)
        finally:
            pool.release(conn)

    async def fetch_one(self, query: str, *args: Any) -> Any:
        pool = self._ensure_pool()
        conn = await pool.acquire()
        try:
            cursor = await conn.cursor()
            await cursor.execute(query, args)
            row = await cursor.fetchone()
            await cursor.close()
            return row
        finally:
            pool.release(conn)

    def _ensure_pool(self) -> Any:
        if not self._pool:
            raise LifecycleError("mysql-pool-not-initialized")
        return self._pool
