"""SQLite database adapter."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, Field

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class SQLiteDatabaseSettings(BaseModel):
    """Configuration for the SQLite adapter."""

    path: str = Field(
        default=":memory:", description="Path to the SQLite database file."
    )
    isolation_level: str | None = Field(default=None)
    pragmas: dict[str, str | int | float] = Field(default_factory=dict)


class SQLiteDatabaseAdapter:
    """A lightweight SQLite adapter for dev/test scenarios."""

    metadata = AdapterMetadata(
        category="database",
        provider="sqlite",
        factory="oneiric.adapters.database.sqlite:SQLiteDatabaseAdapter",
        capabilities=["sql"],
        stack_level=5,
        priority=50,
        source=CandidateSource.LOCAL_PKG,
        owner="Data Platform",
        requires_secrets=False,
        settings_model=SQLiteDatabaseSettings,
    )

    def __init__(
        self,
        settings: SQLiteDatabaseSettings | None = None,
        *,
        connection_factory: Callable[..., Awaitable[Any]] | None = None,
    ) -> None:
        self._settings = settings or SQLiteDatabaseSettings()
        self._connection_factory = connection_factory
        self._conn: Any = None
        self._logger = get_logger("adapter.database.sqlite").bind(
            domain="adapter",
            key="database",
            provider="sqlite",
        )

    async def init(self) -> None:
        if self._conn:
            return
        factory = self._connection_factory
        if factory is None:
            try:
                import aiosqlite
            except ModuleNotFoundError as exc:  # pragma: no cover - defensive
                raise LifecycleError("aiosqlite-missing") from exc
            factory = aiosqlite.connect
        self._conn = await factory(
            self._settings.path, isolation_level=self._settings.isolation_level
        )
        for pragma, value in self._settings.pragmas.items():
            await self._conn.execute(f"PRAGMA {pragma}={value}")
        await self._conn.commit()
        self._logger.info(
            "adapter-init", adapter="sqlite-database", path=self._settings.path
        )

    async def health(self) -> bool:
        conn = self._ensure_conn()
        try:
            cursor = await conn.execute("SELECT 1;")
            await cursor.close()
            return True
        except Exception as exc:  # pragma: no cover - disk errors
            self._logger.warning("adapter-health-error", error=str(exc))
            return False

    async def cleanup(self) -> None:
        if not self._conn:
            return
        await self._conn.close()
        self._conn = None
        self._logger.info("adapter-cleanup-complete", adapter="sqlite-database")

    async def execute(self, query: str, *args: Any) -> int:
        conn = self._ensure_conn()
        cursor = await conn.execute(query, args)
        await conn.commit()
        rowcount = cursor.rowcount if cursor.rowcount is not None else 0
        await cursor.close()
        return rowcount

    async def fetch_all(self, query: str, *args: Any) -> list[Any]:
        conn = self._ensure_conn()
        cursor = await conn.execute(query, args)
        rows = await cursor.fetchall()
        await cursor.close()
        return rows

    async def fetch_one(self, query: str, *args: Any) -> Any:
        conn = self._ensure_conn()
        cursor = await conn.execute(query, args)
        row = await cursor.fetchone()
        await cursor.close()
        return row

    def _ensure_conn(self) -> Any:
        if not self._conn:
            raise LifecycleError("sqlite-connection-not-initialized")
        return self._conn
