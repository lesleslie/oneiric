"""Durable execution hooks for workflow DAG runs."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio

from oneiric.runtime.dag import DAGExecutionHooks
from oneiric.runtime.protocols import WorkflowExecutionStoreProtocol


class WorkflowExecutionStore:
    """SQLite-backed store for durable workflow execution state."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._ensure_schema()

    def start_run(self, workflow_key: str, run_id: str, started_at: str) -> None:
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
        await anyio.to_thread.run_sync(fn, *args)

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
