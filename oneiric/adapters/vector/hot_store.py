"""HotStore Protocol — substrate contract for vector-backed hot-tier storage.

Per ADR 017, this protocol is owned by Oneiric (the persistence substrate
library), NOT by any Bodai application component (Mahavishnu, Akosha,
Crackerjack, Session-Buddy). Bodai application components import this
protocol; concrete implementations (DuckDB-backed for development,
pgvector-backed for production) live in their respective adapter modules.

Refactor context (2026-09-15):
- The HotStore Protocol was previously defined implicitly by the concrete
  ``akosha.storage.HotStore`` class (DuckDB-backed). Mahavishnu's
  ``ingesters/otel_ingester.py`` referenced it under TYPE_CHECKING, which
  was a cross-component forward-reference violation by the spirit of
  ADR 017 even if not technically runtime-coupled (forward references
  are read by type-checkers only).
- Phase 5 task 8 of docs/superpowers/specs/2026-09-14-dhara-mcp-decomposition-design.md
  lifts this contract here. Akosha's concrete ``HotStore`` and
  ``PgvectorHotStore`` classes continue to live in Akosha and conform to
  this Protocol via structural (duck) typing — no inheritance required.

Architectural rationale:
- A substrate contract belongs with the substrate library. Putting it
  in ``mcp-common`` would split the interface from its owning substrate
  (textbook layering anti-pattern).
- Duck typing means concrete implementations (AkoSHA's ``HotStore``
  DuckDB-backed, future pgvector-backed Oneiric class, etc.) conform
  automatically without an ``implements HotStore`` declaration.
- AkoSHA retains the existing ``HotStore`` class as an application-layer
  concrete (DuckDB-backed for development). Once Phase 6 / Phase 10
  lift pgvector into Oneiric, a Oneiric ``PgvectorHotStore`` joins.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class HotStore(Protocol):
    """Substrate contract: a vector-backed hot-tier store.

    Operations captured by this contract are the ones
    ``mahavishnu/ingesters/otel_ingester.py`` calls at runtime:
    ``__init__``, ``initialize``, ``insert``, ``search_similar``,
    ``close``. The ``conn`` attribute access is also captured for the
    diagnosis/fallback path in otel_ingester.

    Implementations are duck-typed: any class with matching methods
    conforms. The Protocol enables structural subtyping without forcing
    inheritance across components.
    """

    def __init__(
        self,
        database_path: str | Path = ":memory:",
        embedding_dim: int | None = None,
    ) -> None:
        """Initialize the hot store.

        Args:
            database_path: backend-specific location (``":memory:"`` for
                ephemeral; file path for persistent DuckDB; Postgres
                DSN for pgvector-backed impl).
            embedding_dim: Vector dimensionality. ``None`` lets the
                implementation resolve from a registered embedding
                service; explicit ``int`` pins it (used by tests).
        """
        ...

    async def initialize(self) -> None:
        """Open connections / create schema. Idempotent."""
        ...

    async def insert(self, record: Any) -> None:
        """Insert a record (typically an embedding + metadata).

        Implementations may raise ``ValueError`` on embedding dim
        mismatch — the spec is the schema dim baked at ``__init__`` time.
        """
        ...

    async def search_similar(
        self,
        query_embedding: list[float],
        system_id: str | None = None,
        limit: int = 10,
        threshold: float = 0.7,
    ) -> list[dict[str, Any]]:
        """Vector similarity search.

        Args:
            query_embedding: Query vector (dim must match schema).
            system_id: Optional source filter.
            limit: Max results returned.
            threshold: Minimum cosine similarity score in [0, 1].

        Returns:
            List of record-shaped dicts ordered by similarity descending.

        Raises:
            ValueError on query dim mismatch.
        """
        ...

    async def close(self) -> None:
        """Release connections / flush buffers. Idempotent."""
        ...

    # Attribute access: ``otel_ingester`` reads ``self._hot_store.conn`` for the
    # raw DuckDB connection in one diagnosis/fallback path. Implementations
    # may expose ``conn`` of any backend-specific connection type; typing as
    # ``Any`` documents the contract without forcing the protocol to know
    # about DuckDB specifically.
    conn: Any


__all__ = ["HotStore"]
