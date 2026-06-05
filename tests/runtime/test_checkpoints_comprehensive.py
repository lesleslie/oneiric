"""Comprehensive tests for WorkflowCheckpointStore.

Covers save/load/clear semantics, schema idempotency, parent-directory
creation, defensive handling of corrupt or NULL payloads, persistence
across instances, and concurrent save serialisation. Includes one
property-based round-trip via Hypothesis.

Source under test: oneiric/runtime/checkpoints.py
Style template: tests/core/test_logging.py (module-level functions).
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from oneiric.runtime.checkpoints import WorkflowCheckpointStore


def _raw_set_payload(db_path: Path, workflow_key: str, payload: str | None) -> None:
    """Bypass the store and write a raw payload directly into the sqlite row.

    Used by defensive tests to inject corrupt JSON or NULL payloads.
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO workflow_checkpoints(workflow_key, payload)
            VALUES (?, ?)
            ON CONFLICT(workflow_key) DO UPDATE SET payload=excluded.payload
            """,
            (workflow_key, payload),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Basic CRUD semantics
# ---------------------------------------------------------------------------


def test_save_then_load(checkpoint_store: WorkflowCheckpointStore) -> None:
    payload = {"step": "extract", "duration": 0.42, "ok": True}
    checkpoint_store.save("workflow-a", payload)
    assert checkpoint_store.load("workflow-a") == payload


def test_load_missing_key_returns_empty_dict(
    checkpoint_store: WorkflowCheckpointStore,
) -> None:
    assert checkpoint_store.load("nonexistent-key") == {}


def test_clear_removes_payload(checkpoint_store: WorkflowCheckpointStore) -> None:
    checkpoint_store.save("workflow-b", {"value": 1})
    checkpoint_store.clear("workflow-b")
    assert checkpoint_store.load("workflow-b") == {}


def test_save_overwrites_existing(checkpoint_store: WorkflowCheckpointStore) -> None:
    checkpoint_store.save("workflow-c", {"version": 1})
    checkpoint_store.save("workflow-c", {"version": 2, "extra": "yes"})
    assert checkpoint_store.load("workflow-c") == {"version": 2, "extra": "yes"}


def test_clear_unknown_key_is_noop(
    checkpoint_store: WorkflowCheckpointStore,
) -> None:
    # Should not raise even when no row exists for the key.
    checkpoint_store.clear("never-saved")
    assert checkpoint_store.load("never-saved") == {}


# ---------------------------------------------------------------------------
# Defensive handling: corrupt payload, NULL payload
# ---------------------------------------------------------------------------


def test_corrupt_payload_returns_empty_dict(tmp_path: Path) -> None:
    db_path = tmp_path / "checkpoints.db"
    store = WorkflowCheckpointStore(db_path)
    _raw_set_payload(db_path, "broken", "{not valid json")
    assert store.load("broken") == {}


def test_load_returns_empty_dict_for_none_payload(tmp_path: Path) -> None:
    db_path = tmp_path / "checkpoints.db"
    store = WorkflowCheckpointStore(db_path)
    _raw_set_payload(db_path, "null-payload", None)
    assert store.load("null-payload") == {}


# ---------------------------------------------------------------------------
# Filesystem and schema lifecycle
# ---------------------------------------------------------------------------


def test_creates_parent_directory(tmp_path: Path) -> None:
    nested_path = tmp_path / "a" / "b" / "c" / "checkpoints.db"
    assert not nested_path.parent.exists()
    store = WorkflowCheckpointStore(nested_path)
    assert nested_path.parent.is_dir()
    store.save("k", {"x": 1})
    assert store.load("k") == {"x": 1}


def test_schema_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "checkpoints.db"
    first = WorkflowCheckpointStore(db_path)
    first.save("workflow", {"a": 1})
    # Re-opening the same store should not raise (CREATE TABLE IF NOT EXISTS).
    second = WorkflowCheckpointStore(db_path)
    assert second.load("workflow") == {"a": 1}


def test_persistence_across_instances(tmp_path: Path) -> None:
    db_path = tmp_path / "checkpoints.db"
    writer = WorkflowCheckpointStore(db_path)
    writer.save("persistent", {"saved": True, "count": 42})

    reader = WorkflowCheckpointStore(db_path)
    assert reader.load("persistent") == {"saved": True, "count": 42}


# ---------------------------------------------------------------------------
# Structured payloads
# ---------------------------------------------------------------------------


def test_save_with_nested_dict(checkpoint_store: WorkflowCheckpointStore) -> None:
    nested = {
        "stages": {
            "extract": {"status": "ok", "metrics": {"rows": 100, "errors": 0}},
            "transform": {"status": "ok", "metrics": {"rows": 100}},
        },
        "meta": {"run_id": "abc-123"},
    }
    checkpoint_store.save("nested", nested)
    assert checkpoint_store.load("nested") == nested


def test_save_with_list_values(checkpoint_store: WorkflowCheckpointStore) -> None:
    payload = {
        "tags": ["alpha", "beta", "gamma"],
        "errors": [],
        "history": [{"step": 1, "ok": True}, {"step": 2, "ok": False}],
    }
    checkpoint_store.save("with-lists", payload)
    assert checkpoint_store.load("with-lists") == payload


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


def test_concurrent_save_is_serialised(
    checkpoint_store: WorkflowCheckpointStore,
) -> None:
    errors: list[BaseException] = []

    def writer(idx: int) -> None:
        try:
            checkpoint_store.save(f"key-{idx}", {"idx": idx, "value": idx * 10})
        except BaseException as exc:  # pragma: no cover - reason: capture for assert
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not errors, f"concurrent save raised: {errors!r}"
    for i in range(8):
        assert checkpoint_store.load(f"key-{i}") == {"idx": i, "value": i * 10}


# ---------------------------------------------------------------------------
# Property-based round-trip
# ---------------------------------------------------------------------------


@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    payload=st.dictionaries(
        keys=st.text(max_size=10),
        values=st.integers(),
        max_size=10,
    )
)
def test_round_trip_via_json(payload: dict[str, int], tmp_path: Path) -> None:
    db_path = tmp_path / "property-roundtrip.db"
    store = WorkflowCheckpointStore(db_path)
    store.save("prop", payload)
    assert store.load("prop") == payload
