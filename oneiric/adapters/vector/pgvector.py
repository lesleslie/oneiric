"""Postgres pgvector adapter with lifecycle integration."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from pydantic import Field, SecretStr

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource

from .common import VectorBase, VectorBaseSettings, VectorDocument, VectorSearchResult

SAFE_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class PgvectorSettings(VectorBaseSettings):
    """Settings for the pgvector adapter."""

    dsn: str | None = Field(
        default=None,
        description="Optional DSN string to override discrete connection fields.",
    )
    host: str = "localhost"
    port: int = 5432
    user: str = "postgres"
    password: SecretStr | None = None
    database: str = "postgres"
    db_schema: str = "public"
    collection_prefix: str = "vectors_"
    statement_timeout_ms: int | None = Field(default=None, ge=1)
    ssl: bool = False
    ensure_extension: bool = True
    ivfflat_lists: int = Field(
        default=100,
        ge=1,
        description="Number of IVF lists to use when creating indexes.",
    )


class PgvectorAdapter(VectorBase):
    """Asyncpg-backed adapter for the pgvector Postgres extension."""

    metadata = AdapterMetadata(
        category="vector",
        provider="pgvector",
        factory="oneiric.adapters.vector.pgvector:PgvectorAdapter",
        capabilities=[
            "vector_search",
            "batch_operations",
            "metadata_filtering",
            "collections",
            "sql",
        ],
        stack_level=30,
        priority=450,
        source=CandidateSource.LOCAL_PKG,
        owner="Data Platform",
        requires_secrets=True,
        settings_model=PgvectorSettings,
    )

    def __init__(
        self,
        settings: PgvectorSettings,
        *,
        pool_factory: Callable[..., Awaitable[Any]] | None = None,
        register_vector: Callable[[Any], Awaitable[None]] | None = None,
    ) -> None:
        super().__init__(settings)
        self._settings = settings
        self._pool_factory = pool_factory
        self._register_vector = register_vector
        self._pool: Any | None = None
        self._logger = get_logger("adapter.vector.pgvector").bind(
            domain="adapter",
            key="vector",
            provider="pgvector",
        )

    async def init(self) -> None:
        await self._ensure_client()
        if self._settings.ensure_extension:
            await self._ensure_extension()
        self._logger.info("pgvector-adapter-init")

    async def health(self) -> bool:
        try:
            async with self._connection() as conn:
                await conn.execute("SELECT 1;")
            return True
        except Exception as exc:  # pragma: no cover - defensive
            self._logger.warning("pgvector-health-failed", error=str(exc))
            return False

    async def cleanup(self) -> None:
        if not self._pool:
            return
        await self._pool.close()
        self._pool = None
        self._logger.info("pgvector-cleanup-complete")

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        limit: int = 10,
        filter_expr: dict[str, Any] | None = None,
        include_vectors: bool = False,
        **_: Any,
    ) -> list[VectorSearchResult]:
        table = self._qualified_collection(collection)
        operator = self._distance_operator()
        params: list[Any] = []
        sql_parts = [
            f"SELECT id, metadata, {'embedding' if include_vectors else 'NULL'} AS embedding, "
            f"embedding {operator} $1::vector AS distance",
            f"FROM {table}",
        ]
        params.append(query_vector)
        if filter_expr:
            sql_parts.append("WHERE metadata @> $2::jsonb")
            params.append(json.dumps(filter_expr))
            limit_param = "$3"
        else:
            limit_param = "$2"
        params.append(limit)
        sql_parts.append(f"ORDER BY distance ASC LIMIT {limit_param}")

        async with self._connection() as conn:
            records = await conn.fetch("\n".join(sql_parts), *params)
        return [
            VectorSearchResult(
                id=record["id"],
                score=float(record["distance"]),
                metadata=record["metadata"] or {},
                vector=record["embedding"] if include_vectors else None,
            )
            for record in records
        ]

    async def insert(
        self,
        collection: str,
        documents: list[VectorDocument],
        **_: Any,
    ) -> list[str]:
        return await self._write_documents(collection, documents, upsert=False)

    async def upsert(
        self,
        collection: str,
        documents: list[VectorDocument],
        **_: Any,
    ) -> list[str]:
        return await self._write_documents(collection, documents, upsert=True)

    async def delete(
        self,
        collection: str,
        ids: list[str],
        **_: Any,
    ) -> bool:
        table = self._qualified_collection(collection)
        if not ids:
            return True
        async with self._connection() as conn:
            await conn.execute(f"DELETE FROM {table} WHERE id = ANY($1::text[])", ids)
        return True

    async def get(
        self,
        collection: str,
        ids: list[str],
        include_vectors: bool = False,
        **_: Any,
    ) -> list[VectorDocument]:
        table = self._qualified_collection(collection)
        if not ids:
            return []
        fields = "id, metadata" + (", embedding" if include_vectors else "")
        async with self._connection() as conn:
            records = await conn.fetch(
                f"SELECT {fields} FROM {table} WHERE id = ANY($1::text[])",
                ids,
            )
        return [
            VectorDocument(
                id=record["id"],
                metadata=record["metadata"] or {},
                vector=record["embedding"] if include_vectors else [],
            )
            for record in records
        ]

    async def count(
        self,
        collection: str,
        filter_expr: dict[str, Any] | None = None,
        **_: Any,
    ) -> int:
        table = self._qualified_collection(collection)
        if filter_expr:
            sql = f"SELECT COUNT(*) FROM {table} WHERE metadata @> $1::jsonb"
            params: Sequence[Any] = (json.dumps(filter_expr),)
        else:
            sql = f"SELECT COUNT(*) FROM {table}"
            params = ()
        async with self._connection() as conn:
            value = await conn.fetchval(sql, *params)
        return int(value or 0)

    async def create_collection(
        self,
        name: str,
        dimension: int,
        distance_metric: str = "cosine",
        **_: Any,
    ) -> bool:
        table_name = self._normalize_collection_name(name)
        schema = self._sanitize_identifier(self._settings.db_schema)
        qualified = f"{self._quote_ident(schema)}.{self._quote_ident(table_name)}"
        operator_class = self._index_operator(distance_metric)
        async with self._connection() as conn:
            if self._settings.ensure_extension:
                await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            await conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {qualified} (
                    id TEXT PRIMARY KEY,
                    embedding vector({dimension}),
                    metadata JSONB DEFAULT '{{}}'::jsonb
                )
                """
            )
            await conn.execute(
                f"""
                CREATE INDEX IF NOT EXISTS {table_name}_embedding_idx
                ON {qualified}
                USING ivfflat (embedding {operator_class})
                WITH (lists := {self._settings.ivfflat_lists})
                """
            )
        return True

    async def delete_collection(self, name: str, **_: Any) -> bool:
        table_name = self._normalize_collection_name(name)
        schema = self._sanitize_identifier(self._settings.db_schema)
        qualified = f"{self._quote_ident(schema)}.{self._quote_ident(table_name)}"
        async with self._connection() as conn:
            await conn.execute(f"DROP TABLE IF EXISTS {qualified}")
        return True

    async def list_collections(self, **_: Any) -> list[str]:
        prefix = self._normalize_collection_name("")
        async with self._connection() as conn:
            records = await conn.fetch(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = $1 AND table_name LIKE $2
                """,
                self._sanitize_identifier(self._settings.db_schema),
                f"{prefix}%",
            )
        return [record["table_name"] for record in records or []]

    async def _ensure_client(self) -> Any:
        if self._pool:
            return self._pool
        self._pool = await self._create_client()
        return self._pool

    async def _create_client(self) -> Any:
        factory = self._pool_factory
        if factory is None:
            try:
                import asyncpg
            except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
                raise LifecycleError(
                    "asyncpg-missing: install oneiric[vector-pgvector] or oneiric[database]"
                ) from exc
            factory = asyncpg.create_pool

        register_vector = self._register_vector
        if register_vector is None:
            try:
                from pgvector.asyncpg import register_vector as _register_vector
            except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
                raise LifecycleError("pgvector-missing: pip install pgvector") from exc

            async def register_vector(conn: Any) -> None:
                await _register_vector(conn)

        async def _pool_init(conn: Any) -> None:
            await register_vector(conn)

        kwargs = self._connection_kwargs()
        return await factory(init=_pool_init, **kwargs)

    async def _ensure_extension(self) -> None:
        async with self._connection() as conn:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")

    @asynccontextmanager
    async def _connection(self) -> AsyncGenerator[Any]:
        pool = await self._ensure_client()
        conn = await pool.acquire()
        try:
            yield conn
        finally:
            await pool.release(conn)

    def _connection_kwargs(self) -> dict[str, Any]:
        if self._settings.dsn:
            return {"dsn": self._settings.dsn}
        kwargs: dict[str, Any] = {
            "host": self._settings.host,
            "port": self._settings.port,
            "user": self._settings.user,
            "database": self._settings.database,
            "min_size": 1,
            "max_size": self._settings.max_connections,
        }
        if self._settings.password:
            kwargs["password"] = self._settings.password.get_secret_value()
        if self._settings.ssl:
            kwargs["ssl"] = True
        if self._settings.statement_timeout_ms:
            kwargs["command_timeout"] = self._settings.statement_timeout_ms / 1000
        return kwargs

    def _distance_operator(self) -> str:
        metric = self._settings.default_distance_metric.lower()
        if metric in {"euclidean", "l2"}:
            return "<->"
        if metric in {"dot_product", "inner_product"}:
            return "<#>"
        return "<=>"

    def _index_operator(self, distance_metric: str) -> str:
        metric = distance_metric.lower()
        if metric in {"euclidean", "l2"}:
            return "vector_l2_ops"
        if metric in {"dot_product", "inner_product"}:
            return "vector_ip_ops"
        return "vector_cosine_ops"

    def _qualified_collection(self, collection: str) -> str:
        schema = self._sanitize_identifier(self._settings.db_schema)
        name = self._normalize_collection_name(collection)
        return f"{self._quote_ident(schema)}.{self._quote_ident(name)}"

    def _normalize_collection_name(self, name: str) -> str:
        base = f"{self._settings.collection_prefix}{name}"
        sanitized = re.sub(r"[^A-Za-z0-9_]", "_", base)
        if not sanitized:
            raise LifecycleError("pgvector-invalid-collection-name")
        if sanitized[0].isdigit():
            sanitized = f"v_{sanitized}"
        return sanitized

    def _sanitize_identifier(self, identifier: str) -> str:
        if not (normalized := re.sub(r"[^A-Za-z0-9_]", "_", identifier)):
            pass
        if not normalized:
            raise LifecycleError("pgvector-invalid-identifier")
        if normalized[0].isdigit():
            normalized = f"v_{normalized}"
        if not SAFE_IDENTIFIER_PATTERN.fullmatch(normalized):
            raise LifecycleError(f"pgvector-identifier-not-safe: {identifier}")
        return normalized

    def _quote_ident(self, identifier: str) -> str:
        return f'"{identifier}"'

    async def _write_documents(
        self,
        collection: str,
        documents: list[VectorDocument],
        *,
        upsert: bool,
    ) -> list[str]:
        table = self._qualified_collection(collection)
        statement = f"""
            INSERT INTO {table} (id, embedding, metadata)
            VALUES ($1, $2::vector, $3::jsonb)
            """
        if upsert:
            statement += "ON CONFLICT (id) DO UPDATE SET embedding = EXCLUDED.embedding, metadata = EXCLUDED.metadata "
        else:
            statement += "ON CONFLICT (id) DO NOTHING "
        statement += "RETURNING id"

        inserted: list[str] = []
        async with self._connection() as conn:
            for doc in documents:
                doc_id = doc.id or str(uuid4())
                record = await conn.fetchrow(
                    statement,
                    doc_id,
                    doc.vector,
                    json.dumps(doc.metadata),
                )
                if record and record.get("id"):
                    inserted.append(record["id"])
        return inserted


__all__ = ["PgvectorAdapter", "PgvectorSettings"]
