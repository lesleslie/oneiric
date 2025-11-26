"""Tests for RuntimeHealthSnapshot."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from oneiric.runtime.health import RuntimeHealthSnapshot, load_runtime_health, write_runtime_health


class TestRuntimeHealthSnapshot:
    """Test RuntimeHealthSnapshot dataclass."""

    def test_health_snapshot_defaults(self):
        """RuntimeHealthSnapshot has sensible defaults."""
        snapshot = RuntimeHealthSnapshot()

        assert snapshot.watchers_running is False
        assert snapshot.remote_enabled is False
        assert snapshot.last_remote_sync_at is None
        assert snapshot.last_remote_error is None
        assert snapshot.orchestrator_pid is None
        assert snapshot.updated_at is None
        assert snapshot.last_remote_registered is None
        # These fields have None defaults with type: ignore
        assert snapshot.last_remote_per_domain is None
        assert snapshot.last_remote_skipped is None
        assert snapshot.activity_state is None

    def test_health_snapshot_with_values(self):
        """RuntimeHealthSnapshot accepts all fields."""
        snapshot = RuntimeHealthSnapshot(
            watchers_running=True,
            remote_enabled=True,
            last_remote_sync_at="2025-01-15T10:00:00Z",
            last_remote_error=None,
            orchestrator_pid=12345,
            updated_at="2025-01-15T10:01:00Z",
            last_remote_registered=10,
            last_remote_per_domain={"adapter": 5, "service": 5},
            last_remote_skipped=2,
            activity_state={
                "adapter:cache": {"paused": False, "draining": False},
            },
        )

        assert snapshot.watchers_running is True
        assert snapshot.remote_enabled is True
        assert snapshot.last_remote_sync_at == "2025-01-15T10:00:00Z"
        assert snapshot.orchestrator_pid == 12345
        assert snapshot.last_remote_registered == 10
        assert snapshot.last_remote_per_domain == {"adapter": 5, "service": 5}
        assert snapshot.last_remote_skipped == 2

    def test_as_dict(self):
        """RuntimeHealthSnapshot.as_dict() serializes to dict."""
        snapshot = RuntimeHealthSnapshot(
            watchers_running=True,
            remote_enabled=True,
            orchestrator_pid=12345,
            last_remote_registered=10,
            last_remote_per_domain={"adapter": 5},
        )

        data = snapshot.as_dict()

        assert isinstance(data, dict)
        assert data["watchers_running"] is True
        assert data["remote_enabled"] is True
        assert data["orchestrator_pid"] == 12345
        assert data["last_remote_registered"] == 10
        assert data["last_remote_per_domain"] == {"adapter": 5}


class TestLoadRuntimeHealth:
    """Test load_runtime_health() function."""

    def test_load_from_existing_file(self, tmp_path):
        """load_runtime_health() loads from existing JSON file."""
        health_file = tmp_path / "health.json"
        health_data = {
            "watchers_running": True,
            "remote_enabled": True,
            "orchestrator_pid": 12345,
            "last_remote_registered": 10,
            "last_remote_per_domain": {"adapter": 5},
            "last_remote_skipped": 2,
            "updated_at": "2025-01-15T10:00:00Z",
        }
        health_file.write_text(json.dumps(health_data))

        snapshot = load_runtime_health(str(health_file))

        assert snapshot.watchers_running is True
        assert snapshot.remote_enabled is True
        assert snapshot.orchestrator_pid == 12345
        assert snapshot.last_remote_registered == 10
        assert snapshot.last_remote_per_domain == {"adapter": 5}

    def test_load_from_nonexistent_file(self, tmp_path):
        """load_runtime_health() returns defaults if file missing."""
        health_file = tmp_path / "health.json"

        snapshot = load_runtime_health(str(health_file))

        assert snapshot.watchers_running is False
        assert snapshot.remote_enabled is False
        assert snapshot.orchestrator_pid is None

    def test_load_from_invalid_json(self, tmp_path):
        """load_runtime_health() returns defaults if JSON invalid."""
        health_file = tmp_path / "health.json"
        health_file.write_text("not valid json{")

        snapshot = load_runtime_health(str(health_file))

        assert snapshot.watchers_running is False
        assert snapshot.remote_enabled is False

    def test_load_handles_missing_fields(self, tmp_path):
        """load_runtime_health() handles partial JSON data."""
        health_file = tmp_path / "health.json"
        health_data = {
            "watchers_running": True,
            # Missing other fields
        }
        health_file.write_text(json.dumps(health_data))

        snapshot = load_runtime_health(str(health_file))

        assert snapshot.watchers_running is True
        assert snapshot.remote_enabled is False  # Default
        assert snapshot.orchestrator_pid is None  # Default


class TestWriteRuntimeHealth:
    """Test write_runtime_health() function."""

    def test_write_creates_file(self, tmp_path):
        """write_runtime_health() creates JSON file."""
        health_file = tmp_path / "health.json"
        snapshot = RuntimeHealthSnapshot(
            watchers_running=True,
            remote_enabled=True,
            orchestrator_pid=12345,
        )

        write_runtime_health(str(health_file), snapshot)

        assert health_file.exists()
        data = json.loads(health_file.read_text())
        assert data["watchers_running"] is True
        assert data["remote_enabled"] is True
        assert data["orchestrator_pid"] == 12345

    def test_write_overwrites_existing(self, tmp_path):
        """write_runtime_health() overwrites existing file."""
        health_file = tmp_path / "health.json"
        health_file.write_text('{"old": "data"}')

        snapshot = RuntimeHealthSnapshot(
            watchers_running=True,
            orchestrator_pid=99999,
        )

        write_runtime_health(str(health_file), snapshot)

        data = json.loads(health_file.read_text())
        assert "old" not in data
        assert data["watchers_running"] is True
        assert data["orchestrator_pid"] == 99999

    def test_write_creates_parent_directory(self, tmp_path):
        """write_runtime_health() creates parent directories."""
        health_file = tmp_path / "nested" / "dir" / "health.json"
        snapshot = RuntimeHealthSnapshot(watchers_running=True)

        write_runtime_health(str(health_file), snapshot)

        assert health_file.exists()
        assert health_file.parent.exists()

    def test_write_atomic(self, tmp_path):
        """write_runtime_health() uses atomic write."""
        health_file = tmp_path / "health.json"
        snapshot = RuntimeHealthSnapshot(watchers_running=True)

        write_runtime_health(str(health_file), snapshot)

        # Verify no temp file left behind
        temp_files = list(health_file.parent.glob("*.tmp"))
        assert len(temp_files) == 0

    def test_write_with_activity_state(self, tmp_path):
        """write_runtime_health() persists activity state."""
        health_file = tmp_path / "health.json"
        snapshot = RuntimeHealthSnapshot(
            watchers_running=True,
            activity_state={
                "adapter:cache": {
                    "paused": True,
                    "draining": False,
                    "pause_note": "maintenance",
                },
                "service:payment": {
                    "paused": False,
                    "draining": True,
                    "drain_note": "migration",
                },
            },
        )

        write_runtime_health(str(health_file), snapshot)

        data = json.loads(health_file.read_text())
        assert "activity_state" in data
        assert data["activity_state"]["adapter:cache"]["paused"] is True
        assert data["activity_state"]["service:payment"]["draining"] is True

    def test_write_includes_updated_timestamp(self, tmp_path):
        """write_runtime_health() includes updated_at timestamp."""
        health_file = tmp_path / "health.json"
        snapshot = RuntimeHealthSnapshot(watchers_running=True)

        write_runtime_health(str(health_file), snapshot)

        data = json.loads(health_file.read_text())
        assert "updated_at" in data
        assert data["updated_at"] is not None

    def test_roundtrip_write_and_load(self, tmp_path):
        """write and load roundtrip preserves data."""
        health_file = tmp_path / "health.json"
        original = RuntimeHealthSnapshot(
            watchers_running=True,
            remote_enabled=True,
            orchestrator_pid=12345,
            last_remote_registered=10,
            last_remote_per_domain={"adapter": 5, "service": 5},
            last_remote_skipped=2,
            activity_state={
                "adapter:cache": {"paused": False, "draining": False},
            },
        )

        write_runtime_health(str(health_file), original)
        loaded = load_runtime_health(str(health_file))

        assert loaded.watchers_running == original.watchers_running
        assert loaded.remote_enabled == original.remote_enabled
        assert loaded.orchestrator_pid == original.orchestrator_pid
        assert loaded.last_remote_registered == original.last_remote_registered
        assert loaded.last_remote_per_domain == original.last_remote_per_domain
        assert loaded.last_remote_skipped == original.last_remote_skipped
        assert loaded.activity_state == original.activity_state
