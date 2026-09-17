from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from oneiric.mcp.store import SubstrateStore


@pytest.fixture
def store(tmp_path: Path) -> SubstrateStore:
    return SubstrateStore(root=tmp_path)


class TestSubstrateStoreSettings:
    def test_initial_state_is_empty(self, store: SubstrateStore) -> None:
        assert store.read_settings() == {"current": None, "history": []}

    def test_write_settings_appends_to_history(
        self, store: SubstrateStore
    ) -> None:
        # Use the duck-typed payload interface — T3 will replace with the
        # concrete ActiveSettingsVersionIn, but the contract is .model_dump().
        from types import SimpleNamespace

        payload = SimpleNamespace(
            model_dump=lambda: {"version": "1.0", "source": "test"}
        )
        record = store.write_settings(payload)  # type: ignore[arg-type]
        assert record["payload"]["version"] == "1.0"
        bucket = store.read_settings()
        assert bucket["current"]["payload"]["version"] == "1.0"
        assert bucket["history"][-1]["payload"]["version"] == "1.0"
        assert bucket["history"][-1]["id"] == record["id"]


class TestSubstrateStoreThreadSafety:
    """REQ-009: write_* methods are called from worker threads.
    asyncio.Lock does not serialize across threads; threading.Lock does.
    Concurrent writes must produce non-corrupted history.
    """

    def test_locks_are_threading_lock(self, store: SubstrateStore) -> None:
        """Pin the lock type — a regression to asyncio.Lock would fail this
        with a clear assertion failure rather than via ambiguous write race."""
        import threading

        for name, lock in store._locks.items():
            assert isinstance(lock, threading.Lock), (
                f"bucket {name!r} uses {type(lock).__name__}; "
                "expected threading.Lock for cross-thread serialization"
            )

    def test_concurrent_writes_do_not_corrupt(
        self, store: SubstrateStore
    ) -> None:
        import threading
        from types import SimpleNamespace

        # Use a barrier so all worker threads collide in the critical
        # section at the same instant — makes the race deterministic.
        #
        # Note: item count must be a multiple of max_workers so the final
        # partial batch satisfies the barrier (workers are reused by
        # ThreadPoolExecutor.map(), so the last batch has items % 8
        # parties — would deadlock if not zero).
        barrier = threading.Barrier(8)

        def make_payload(i: int):
            return SimpleNamespace(
                model_dump=lambda i=i: {"version": f"v{i}", "source": "stress"}
            )

        def do_write(payload):
            barrier.wait()  # all threads arrive here simultaneously
            return store.write_settings(payload)

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(do_write, [make_payload(i) for i in range(48)]))

        # In-memory assertions.
        bucket = store.read_settings()
        assert len(bucket["history"]) == 48
        ids = {entry["id"] for entry in bucket["history"]}
        assert len(ids) == 48

        # On-disk well-formed JSON check — catches torn writes.
        import json as _json

        raw_text = (store.root / "settings.json").read_text()
        raw_parsed = _json.loads(raw_text)
        assert isinstance(raw_parsed, dict)
        assert len(raw_parsed.get("history", [])) == 48

        # Every record has a parseable created_at — catches reordered writes.
        from datetime import datetime

        for entry in raw_parsed["history"]:
            assert "created_at" in entry
            datetime.fromisoformat(entry["created_at"])

    def test_high_contention_32_workers_200_writes(
        self, store: SubstrateStore
    ) -> None:
        """Catches races that the 8-worker/50-write test misses."""
        from types import SimpleNamespace

        def make_payload(i: int):
            return SimpleNamespace(
                model_dump=lambda i=i: {"version": f"v{i}", "source": "stress"}
            )

        with ThreadPoolExecutor(max_workers=32) as pool:
            list(
                pool.map(store.write_settings, [make_payload(i) for i in range(200)])
            )

        bucket = store.read_settings()
        assert len(bucket["history"]) == 200