"""Shared persistence helpers for domain pause/drain state."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class DomainActivity:
    paused: bool = False
    draining: bool = False
    note: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "paused": self.paused,
            "draining": self.draining,
            "note": self.note,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> DomainActivity:
        return cls(
            paused=bool(data.get("paused", False)),
            draining=bool(data.get("draining", False)),
            note=data.get("note"),
        )

    def is_default(self) -> bool:
        return not self.paused and not self.draining and self.note is None


class DomainActivityStore:
    """SQLite-backed persistence for domain pause/drain activity."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._ensure_schema()

    def get(self, domain: str, key: str) -> DomainActivity:
        with self._connection() as conn:
            conn: sqlite3.Connection
            row = conn.execute(
                "SELECT paused, draining, note FROM activity WHERE domain=? AND key=?",
                (domain, key),
            ).fetchone()
        if row:
            return DomainActivity(
                paused=bool(row[0]),
                draining=bool(row[1]),
                note=row[2],
            )
        return DomainActivity()

    def all_for_domain(self, domain: str) -> dict[str, DomainActivity]:
        with self._connection() as conn:
            conn: sqlite3.Connection
            rows = conn.execute(
                "SELECT key, paused, draining, note FROM activity WHERE domain=?",
                (domain,),
            ).fetchall()
        return {
            row[0]: DomainActivity(
                paused=bool(row[1]), draining=bool(row[2]), note=row[3]
            )
            for row in rows
        }

    def set(self, domain: str, key: str, state: DomainActivity) -> None:
        with self._connection() as conn:
            conn: sqlite3.Connection
            if state.is_default():
                conn.execute(
                    "DELETE FROM activity WHERE domain=? AND key=?", (domain, key)
                )
                conn.commit()
                return
            conn.execute(
                """
                INSERT INTO activity(domain, key, paused, draining, note)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(domain, key) DO UPDATE SET
                    paused=excluded.paused,
                    draining=excluded.draining,
                    note=excluded.note
                """,
                (domain, key, int(state.paused), int(state.draining), state.note),
            )
            conn.commit()

    def snapshot(self) -> dict[str, dict[str, DomainActivity]]:
        with self._connection() as conn:
            conn: sqlite3.Connection
            rows = conn.execute(
                "SELECT domain, key, paused, draining, note FROM activity",
            ).fetchall()
        snapshot: dict[str, dict[str, DomainActivity]] = {}
        for domain, key, paused, draining, note in rows:
            domain_map = snapshot.setdefault(domain, {})
            domain_map[key] = DomainActivity(
                paused=bool(paused),
                draining=bool(draining),
                note=note,
            )
        return snapshot

    # internal -----------------------------------------------------------------

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = sqlite3.connect(self.path)
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
                CREATE TABLE IF NOT EXISTS activity (
                    domain TEXT NOT NULL,
                    key TEXT NOT NULL,
                    paused INTEGER NOT NULL DEFAULT 0,
                    draining INTEGER NOT NULL DEFAULT 0,
                    note TEXT,
                    PRIMARY KEY (domain, key)
                )
                """
            )
            conn.commit()
