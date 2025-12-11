"""Workflow checkpoint persistence helpers."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class WorkflowCheckpointStore:
    """SQLite-backed persistence for workflow DAG checkpoints."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._ensure_schema()

    def load(self, workflow_key: str) -> dict[str, Any]:
        """Load checkpoint payload for the workflow key."""

        with self._connection() as conn:
            conn: sqlite3.Connection
            row = conn.execute(
                "SELECT payload FROM workflow_checkpoints WHERE workflow_key=?",
                (workflow_key,),
            ).fetchone()
        if not row or row["payload"] is None:
            return {}
        try:
            return json.loads(row["payload"])
        except json.JSONDecodeError:
            return {}

    def save(self, workflow_key: str, checkpoint: Mapping[str, Any]) -> None:
        """Persist checkpoint mapping for the workflow key."""

        payload = json.dumps(dict(checkpoint))
        with self._connection() as conn:
            conn: sqlite3.Connection
            conn.execute(
                """
                INSERT INTO workflow_checkpoints(workflow_key, payload)
                VALUES (?, ?)
                ON CONFLICT(workflow_key) DO UPDATE SET payload=excluded.payload
                """,
                (workflow_key, payload),
            )
            conn.commit()

    def clear(self, workflow_key: str) -> None:
        """Remove checkpoint state for the workflow key."""

        with self._connection() as conn:
            conn: sqlite3.Connection
            conn.execute(
                "DELETE FROM workflow_checkpoints WHERE workflow_key=?",
                (workflow_key,),
            )
            conn.commit()

    # internal helpers -----------------------------------------------------

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
            conn: sqlite3.Connection
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workflow_checkpoints (
                    workflow_key TEXT PRIMARY KEY,
                    payload TEXT
                )
                """
            )
            conn.commit()
