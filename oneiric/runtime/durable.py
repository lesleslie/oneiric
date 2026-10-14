from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import anyio

from oneiric.core.logging import get_logger
from oneiric.runtime.dag import DAGExecutionHooks
from oneiric.runtime.protocols import WorkflowExecutionStoreProtocol

if TYPE_CHECKING:  # pragma: no cover - hints only
    from oneiric.adapters.protocol import OneiricAdapter

logger = get_logger("runtime.durable")


class WorkflowExecutionStore:
    def __init__(
        self,
        path: str | Path,
        adapter: OneiricAdapter | WorkflowExecutionStoreProtocol | None = None,
    ) -> None:
        self.path = Path(path)
        self.adapter = adapter
        # When an adapter is provided, writes may be routed through it.
        # The store remains functional without an adapter (dev/CI default)
        # — the SQLite path is preserved as the durable fallback so reads
        # (load_run, load_nodes) can always work locally. Adapter routing
        # is opt-in: if the supplied adapter also implements the
        # WorkflowExecutionStoreProtocol duck type, the adapter's methods
        # take precedence for writes; otherwise we keep SQLite-only and
        # leave the adapter available for direct calls.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._adapter_is_execution_store = (
            adapter is not None
            and hasattr(adapter, "start_run")
            and hasattr(adapter, "finish_run")
            and hasattr(adapter, "start_node")
            and hasattr(adapter, "finish_node")
        )
        if self._adapter_is_execution_store:
            logger.debug(
                "workflow-execution-store-adapter-routed",
                adapter=getattr(getattr(adapter, "metadata", None), "provider", None),
            )
        self._ensure_schema()

    def _route_start_run(self, workflow_key: str, run_id: str, started_at: str) -> None:
        if self._adapter_is_execution_store and self.adapter is not None:
            store = cast(WorkflowExecutionStoreProtocol, self.adapter)
            store.start_run(workflow_key, run_id, started_at)

    def _route_finish_run(
        self,
        run_id: str,
        status: str,
        ended_at: str,
        error: str | None,
    ) -> None:
        if self._adapter_is_execution_store and self.adapter is not None:
            store = cast(WorkflowExecutionStoreProtocol, self.adapter)
            store.finish_run(run_id, status, ended_at, error)

    def _route_start_node(self, run_id: str, node_key: str, started_at: str) -> None:
        if self._adapter_is_execution_store and self.adapter is not None:
            store = cast(WorkflowExecutionStoreProtocol, self.adapter)
            store.start_node(run_id, node_key, started_at)

    def _route_finish_node(
        self,
        run_id: str,
        node_key: str,
        status: str,
        ended_at: str,
        attempts: int | None,
        error: str | None,
    ) -> None:
        if self._adapter_is_execution_store and self.adapter is not None:
            store = cast(WorkflowExecutionStoreProtocol, self.adapter)
            store.finish_node(
                run_id,
                node_key,
                status,
                ended_at,
                attempts,
                error,
            )

    def _json_payload(self, **fields: Any) -> str:
        """Serialize a payload to JSON for adapter-backed backends that
        expect JSON rather than keyword args. Reserved for adapter
        implementations that don't expose the typed methods."""

        return json.dumps(fields, default=str, sort_keys=True)

    def start_run(self, workflow_key: str, run_id: str, started_at: str) -> None:
        self._route_start_run(workflow_key, run_id, started_at)
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO workflow_executions(run_id, workflow_key, status, started_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET workflow_key=excluded.workflow_key,
                  status=excluded.status,
                  started_at=excluded.started_at
                """,
                (run_id, workflow_key, "running", started_at),
            )
            conn.commit()

    def finish_run(
        self, run_id: str, status: str, ended_at: str, error: str | None = None
    ) -> None:
        self._route_finish_run(run_id, status, ended_at, error)
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE workflow_executions
                SET status=?, ended_at=?, error=?
                WHERE run_id=?
                """,
                (status, ended_at, error, run_id),
            )
            conn.commit()

    def start_node(self, run_id: str, node_key: str, started_at: str) -> None:
        self._route_start_node(run_id, node_key, started_at)
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO workflow_execution_nodes(
                    run_id, node_key, status, started_at
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(run_id, node_key) DO UPDATE SET status=excluded.status,
                  started_at=excluded.started_at
                """,
                (run_id, node_key, "running", started_at),
            )
            conn.commit()

    def finish_node(
        self,
        run_id: str,
        node_key: str,
        status: str,
        ended_at: str,
        attempts: int | None = None,
        error: str | None = None,
    ) -> None:
        self._route_finish_node(run_id, node_key, status, ended_at, attempts, error)
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE workflow_execution_nodes
                SET status=?, ended_at=?, attempts=?, error=?
                WHERE run_id=? AND node_key=?
                """,
                (status, ended_at, attempts, error, run_id, node_key),
            )
            conn.commit()

    def load_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT run_id, workflow_key, status, started_at, ended_at, error
                FROM workflow_executions
                WHERE run_id=?
                """,
                (run_id,),
            ).fetchone()
        return dict(row) if row else None

    def load_nodes(self, run_id: str) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT run_id, node_key, status, started_at, ended_at, attempts, error
                FROM workflow_execution_nodes
                WHERE run_id=?
                ORDER BY node_key
                """,
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn: sqlite3.Connection = sqlite3.connect(self.path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
            finally:
                conn.close()

    def _ensure_schema(self) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workflow_executions (
                    run_id TEXT PRIMARY KEY,
                    workflow_key TEXT,
                    status TEXT,
                    started_at TEXT,
                    ended_at TEXT,
                    error TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workflow_execution_nodes (
                    run_id TEXT,
                    node_key TEXT,
                    status TEXT,
                    started_at TEXT,
                    ended_at TEXT,
                    attempts INTEGER,
                    error TEXT,
                    PRIMARY KEY(run_id, node_key)
                )
                """
            )
            conn.commit()


def build_durable_execution_hooks(
    store: WorkflowExecutionStoreProtocol,
    *,
    clock: Callable[[], datetime] | None = None,
) -> DAGExecutionHooks:
    time_source = clock or (lambda: datetime.now(UTC))

    async def _run_in_thread(fn: Callable[..., None], *args: Any) -> None:
        await anyio.to_thread.run_sync(fn, *args)  # ty: ignore[unresolved-attribute]

    async def on_run_start(*, run_id: str, workflow_key: str, **_: Any) -> None:
        await _run_in_thread(
            store.start_run,
            workflow_key,
            run_id,
            time_source().isoformat(),
        )

    async def on_run_complete(*, run_id: str, **_: Any) -> None:
        await _run_in_thread(
            store.finish_run,
            run_id,
            "completed",
            time_source().isoformat(),
            None,
        )

    async def on_run_error(*, run_id: str, error: str | None = None, **_: Any) -> None:
        await _run_in_thread(
            store.finish_run,
            run_id,
            "failed",
            time_source().isoformat(),
            error,
        )

    async def on_node_start(*, run_id: str, node: str, **_: Any) -> None:
        await _run_in_thread(
            store.start_node,
            run_id,
            node,
            time_source().isoformat(),
        )

    async def on_node_skip(*, run_id: str, node: str, **_: Any) -> None:
        await _run_in_thread(
            store.finish_node,
            run_id,
            node,
            "skipped",
            time_source().isoformat(),
            None,
            None,
        )

    async def on_node_complete(
        *,
        run_id: str,
        node: str,
        attempts: int | None = None,
        **_: Any,
    ) -> None:
        await _run_in_thread(
            store.finish_node,
            run_id,
            node,
            "completed",
            time_source().isoformat(),
            attempts,
            None,
        )

    async def on_node_error(
        *,
        run_id: str,
        node: str,
        attempts: int | None = None,
        error: str | None = None,
        **_: Any,
    ) -> None:
        await _run_in_thread(
            store.finish_node,
            run_id,
            node,
            "failed",
            time_source().isoformat(),
            attempts,
            error,
        )

    return DAGExecutionHooks(
        on_run_start=on_run_start,
        on_run_complete=on_run_complete,
        on_run_error=on_run_error,
        on_node_start=on_node_start,
        on_node_skip=on_node_skip,
        on_node_complete=on_node_complete,
        on_node_error=on_node_error,
    )


__all__ = ["WorkflowExecutionStore", "build_durable_execution_hooks"]
