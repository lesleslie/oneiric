"""DuckDB PGQ adapter."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class DuckDBPGQSettings(BaseModel):
    """Configuration for DuckDB PGQ adapter."""

    database: str = Field(
        default=":memory:",
        description="DuckDB database path; use ':memory:' for in-memory graphs.",
    )
    read_only: bool = Field(default=False, description="Open DuckDB in read-only mode.")
    install_pgq: bool = Field(
        default=True,
        description="Install the PGQ extension before loading it (skipped when read_only=True).",
    )
    edge_table: str = Field(
        default="pgq_edges",
        description="Edge table name used for graph storage.",
    )
    source_column: str = Field(
        default="source_id",
        description="Column name for edge source/node identifier.",
    )
    target_column: str = Field(
        default="target_id",
        description="Column name for edge target node identifier.",
    )

    def ensure_database_dir(self) -> None:
        """Create parent directory when database points to a file."""
        if self.database not in (":memory:", "", None):
            path = Path(self.database)
            if path.parent:
                path.parent.mkdir(parents=True, exist_ok=True)


class DuckDBPGQAdapter:
    """Adapter exposing PGQ helpers on top of DuckDB."""

    metadata = AdapterMetadata(
        category="graph",
        provider="duckdb_pgq",
        factory="oneiric.adapters.graph.duckdb_pgq:DuckDBPGQAdapter",
        capabilities=["pgq", "table_edges", "analytics"],
        stack_level=30,
        priority=360,
        source=CandidateSource.LOCAL_PKG,
        owner="Data Platform",
        requires_secrets=False,
        settings_model=DuckDBPGQSettings,
    )

    def __init__(
        self,
        settings: DuckDBPGQSettings | None = None,
        *,
        connection_factory: Callable[[], Any] | None = None,
        sync_executor: Callable[
            [Callable[..., Any], tuple[Any, ...], dict[str, Any]], Awaitable[Any]
        ]
        | None = None,
    ) -> None:
        self._settings = settings or DuckDBPGQSettings()
        self._connection_factory = connection_factory
        self._sync_executor = sync_executor
        self._conn: Any = None
        self._logger = get_logger("adapter.graph.duckdb_pgq").bind(
            domain="adapter",
            key="graph",
            provider="duckdb_pgq",
        )

    async def init(self) -> None:
        await self._ensure_connection()
        self._logger.info("duckdb-pgq-adapter-init")

    async def health(self) -> bool:
        try:
            rows = await self.query("SELECT 1 AS ok")
            return bool(rows and rows[0].get("ok") == 1)
        except Exception as exc:  # pragma: no cover - defensive
            self._logger.warning("duckdb-pgq-health-failed", error=str(exc))
            return False

    async def cleanup(self) -> None:
        conn = self._conn
        self._conn = None
        if conn:
            close = getattr(conn, "close", None)
            if callable(close):
                result = close()
                if inspect.isawaitable(result):
                    await result
        self._logger.info("duckdb-pgq-adapter-cleanup")

    async def ingest_edges(self, edges: Sequence[tuple[str, str]]) -> None:
        """Insert multiple edges into the configured edge table."""
        if not edges:
            return
        table = self._table_identifier()
        sql = f"INSERT INTO {table} ({self._source_column()}, {self._target_column()}) VALUES (?, ?)"
        await self._executemany(sql, edges)

    async def neighbors(self, node_id: str) -> list[str]:
        """Return direct neighbors for the provided node."""
        table = self._table_identifier()
        sql = f"SELECT {self._target_column()} FROM {table} WHERE {self._source_column()} = ?"
        rows = await self.query(sql, parameters=(node_id,))
        return [
            row[self._settings.target_column]
            for row in rows
            if self._settings.target_column in row
        ]

    async def query(
        self, sql: str, *, parameters: Iterable[Any] | None = None
    ) -> list[dict[str, Any]]:
        """Execute a SQL/PGQ query and return rows as dicts."""
        conn = await self._ensure_connection()
        params_tuple: tuple[Any, ...] = tuple(parameters or ())

        def _run_query() -> tuple[list[tuple[Any, ...]], list[str]]:
            cursor = conn.execute(sql, params_tuple)
            rows = cursor.fetchall()
            columns = [col[0] for col in getattr(cursor, "description", []) or []]
            return rows, columns

        rows, columns = await self._run_sync(_run_query)
        if not columns:
            # When DuckDB omits description (e.g., PRAGMA) fall back to positional keys
            return [dict(enumerate(row)) for row in rows]
        return [{columns[idx]: value for idx, value in enumerate(row)} for row in rows]

    async def _ensure_connection(self) -> Any:
        if self._conn:
            return self._conn
        self._settings.ensure_database_dir()
        factory = self._connection_factory or self._default_connection_factory
        conn = factory()
        if inspect.isawaitable(conn):
            conn = await conn
        if conn is None:  # pragma: no cover - defensive
            raise LifecycleError("duckdb-pgq-connection-none")
        self._conn = conn
        await self._bootstrap()
        return conn

    async def _bootstrap(self) -> None:
        """Install/Load PGQ extension and ensure edge table exists."""
        if not self._conn:
            return
        if self._settings.install_pgq and not self._settings.read_only:
            await self._execute("INSTALL pgq")
        await self._execute("LOAD pgq")
        table = self._table_identifier()
        sql = (
            f"CREATE TABLE IF NOT EXISTS {table} ("
            f"{self._source_column()} TEXT, "
            f"{self._target_column()} TEXT)"
        )
        await self._execute(sql)

    async def _execute(self, sql: str, parameters: Iterable[Any] | None = None) -> None:
        conn = await self._ensure_connection()
        params_tuple: tuple[Any, ...] = tuple(parameters or ())

        def _run() -> None:
            conn.execute(sql, params_tuple)

        await self._run_sync(_run)

    async def _executemany(
        self, sql: str, sequences: Sequence[tuple[Any, ...]]
    ) -> None:
        conn = await self._ensure_connection()

        def _run() -> None:
            executemany = getattr(conn, "executemany", None)
            if callable(executemany):
                executemany(sql, sequences)
            else:  # pragma: no cover - fallback
                for item in sequences:
                    conn.execute(sql, item)

        await self._run_sync(_run)

    async def _run_sync(self, func: Callable[[], Any]) -> Any:
        if self._sync_executor:
            return await self._sync_executor(func, (), {})
        return await asyncio.to_thread(func)

    def _default_connection_factory(self) -> Any:
        try:
            import duckdb  # type: ignore
        except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
            raise LifecycleError(
                "duckdb-not-installed: install 'oneiric[graph-duckdb-pgq]' to use DuckDBPGQAdapter"
            ) from exc

        return duckdb.connect(
            database=self._settings.database, read_only=self._settings.read_only
        )

    def _table_identifier(self) -> str:
        return self._sanitize_identifier(self._settings.edge_table or "pgq_edges")

    def _source_column(self) -> str:
        return self._sanitize_identifier(self._settings.source_column or "source_id")

    def _target_column(self) -> str:
        return self._sanitize_identifier(self._settings.target_column or "target_id")

    def _sanitize_identifier(self, name: str) -> str:
        safe = "".join(ch for ch in name if ch.isalnum() or ch == "_")
        return safe or "pgq_identifier"
