from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from oneiric.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class RuntimeSnapshot:
    server_name: str
    timestamp: str
    version: str = "1.0"
    components: dict[str, Any] = None
    metadata: dict[str, Any] = None

    def __init__(self, server_name: str, timestamp: str):
        self.server_name = server_name
        self.timestamp = timestamp
        self.components = {}
        self.metadata = {}

    def add_component(self, name: str, data: dict[str, Any]) -> None:
        self.components[name] = data

    def add_metadata(self, key: str, value: Any) -> None:
        self.metadata[key] = value

    def to_dict(self) -> dict[str, Any]:
        return {
            "server_name": self.server_name,
            "timestamp": self.timestamp,
            "version": self.version,
            "components": self.components,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RuntimeSnapshot:
        snapshot = cls(server_name=data["server_name"], timestamp=data["timestamp"])
        snapshot.version = data.get("version", "1.0")
        snapshot.components = data.get("components", {})
        snapshot.metadata = data.get("metadata", {})
        return snapshot


class RuntimeSnapshotManager:
    def __init__(
        self,
        cache_dir: str = ".oneiric_cache",
        server_name: str = "mcp-server",
        max_snapshots: int = 5,
    ):
        self.cache_dir = Path(cache_dir)
        self.server_name = server_name
        self.max_snapshots = max_snapshots
        self.snapshots_dir = self.cache_dir / "snapshots"
        self.current_snapshot: RuntimeSnapshot | None = None

    async def initialize(self) -> None:
        logger.info(f"Initializing RuntimeSnapshotManager for {self.server_name}")

        self.cache_dir.mkdir(exist_ok=True)
        self.snapshots_dir.mkdir(exist_ok=True)

        await self._load_latest_snapshot()

        logger.info(f"Snapshot manager initialized: {self.snapshots_dir}")

    async def _load_latest_snapshot(self) -> None:
        snapshot_files = list(self.snapshots_dir.glob(f"{self.server_name}_*.json"))

        if snapshot_files:
            snapshot_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
            latest_file = snapshot_files[0]

            try:
                with open(latest_file, encoding="utf-8") as f:
                    data = json.load(f)
                    self.current_snapshot = RuntimeSnapshot.from_dict(data)

                logger.info(f"Loaded snapshot from {latest_file}")
            except (json.JSONDecodeError, KeyError) as e:
                logger.error(f"Failed to load snapshot {latest_file}: {e}")

    async def create_snapshot(self, components: dict[str, Any]) -> RuntimeSnapshot:
        timestamp = time.strftime("%Y-%m-%dT%H-%M-%S")
        snapshot = RuntimeSnapshot(server_name=self.server_name, timestamp=timestamp)

        for name, data in components.items():
            snapshot.add_component(name, data)

        snapshot.add_metadata("system_time", time.time())
        snapshot.add_metadata(
            "python_version", f"{sys.version_info.major}.{sys.version_info.minor}"
        )

        self.current_snapshot = snapshot

        await self._save_snapshot(snapshot)

        await self._cleanup_old_snapshots()

        return snapshot

    async def _save_snapshot(self, snapshot: RuntimeSnapshot) -> None:
        filename = f"{self.server_name}_{snapshot.timestamp}.json"
        filepath = self.snapshots_dir / filename

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(snapshot.to_dict(), f, indent=2)

            logger.info(f"Saved snapshot to {filepath}")
        except OSError as e:
            logger.error(f"Failed to save snapshot {filepath}: {e}")
            raise

    async def _cleanup_old_snapshots(self) -> None:
        snapshot_files = list(self.snapshots_dir.glob(f"{self.server_name}_*.json"))

        if len(snapshot_files) > self.max_snapshots:
            snapshot_files.sort(key=lambda f: f.stat().st_mtime)

            for old_file in snapshot_files[: -self.max_snapshots]:
                try:
                    old_file.unlink()
                    logger.info(f"Deleted old snapshot: {old_file}")
                except OSError as e:
                    logger.error(f"Failed to delete old snapshot {old_file}: {e}")

    async def get_current_snapshot(self) -> RuntimeSnapshot | None:
        return self.current_snapshot

    async def get_snapshot_history(self) -> list[RuntimeSnapshot]:
        snapshots = []
        snapshot_files = list(self.snapshots_dir.glob(f"{self.server_name}_*.json"))

        snapshot_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)

        for file in snapshot_files:
            try:
                with open(file, encoding="utf-8") as f:
                    data = json.load(f)
                    snapshots.append(RuntimeSnapshot.from_dict(data))
            except (json.JSONDecodeError, KeyError) as e:
                logger.error(f"Failed to load snapshot {file}: {e}")

        return snapshots

    async def cleanup(self) -> None:
        logger.info(f"Cleaning up RuntimeSnapshotManager for {self.server_name}")

        self.current_snapshot = None


__all__ = ["RuntimeSnapshotManager", "RuntimeSnapshot"]
