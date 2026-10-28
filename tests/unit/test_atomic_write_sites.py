"""Every file writer in oneiric publishes atomically and owner-only.

Each of these sites used to write through a *fixed-name* temp file
(``path.with_suffix(".tmp")`` or ``path.with_suffix(path.suffix +
".tmp")``) and then rename it over the destination. That pattern shares
one temp file between every writer of the same destination, reuses
whatever a crashed earlier write left behind, and follows a symlink
planted at the predictable temp path.

The assertions below are deliberately about the *published* file and the
*surrounding directory*, not about how the write is implemented: the
destination must be owner-only, must hold complete content, and must
leave no temp file behind.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from pydantic import BaseModel

from oneiric.adapters.cache.persistent_kv import (
    PersistentKVCacheAdapter,
    PersistentKVCacheSettings,
)
from oneiric.core.lifecycle import LifecycleManager
from oneiric.core.resolution import Candidate, Resolver
from oneiric.mcp.adapter_registry import OneiricAdapterRegistry
from oneiric.mcp.store import SubstrateStore
from oneiric.remote.telemetry import record_remote_failure
from oneiric.runtime.health import RuntimeHealthSnapshot, write_runtime_health
from oneiric.runtime.telemetry import RuntimeTelemetryRecorder


class _Payload(BaseModel):
    """The substrate store takes anything with ``model_dump()``."""

    value: int


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _assert_published_cleanly(dest: Path) -> None:
    """The destination is owner-only and no temp file was left behind."""
    assert _mode(dest) == 0o600
    # Both temp conventions this codebase has used are covered: the old
    # fixed names (``settings.tmp``, ``settings.json.tmp``) and the
    # current ``mkstemp`` names (``.settings.json.XXXX.tmp``).
    siblings = [p.name for p in dest.parent.iterdir() if p != dest]
    tempish = [
        n for n in siblings if n.endswith(".tmp") or n.startswith(f".{dest.name}.")
    ]
    assert not tempish, f"the writer left temp files behind: {tempish}"


class TestLifecycleStatusSnapshot:
    """``LifecycleManager._persist_status_snapshot``."""

    def test_the_status_snapshot_is_published_owner_only(self, tmp_path: Path) -> None:
        dest = tmp_path / "status.json"
        manager = LifecycleManager(Resolver(), status_snapshot_path=str(dest))
        candidate = Candidate(domain="cache", key="redis", factory=lambda: None)

        manager._update_status(candidate, state="ready")

        assert json.loads(dest.read_text())
        _assert_published_cleanly(dest)

    def test_a_symlinked_temp_path_is_not_written_through(self, tmp_path: Path) -> None:
        """The old temp name was ``status.tmp``; it must not be reused.

        ``Path.write_text`` opens with ``O_CREAT | O_TRUNC``, which
        follows a symlink -- so a planted link would have its target
        overwritten.
        """
        dest = tmp_path / "status.json"
        victim = tmp_path / "victim.txt"
        victim.write_text("precious")
        (tmp_path / "status.tmp").symlink_to(victim)

        manager = LifecycleManager(Resolver(), status_snapshot_path=str(dest))
        candidate = Candidate(domain="cache", key="redis", factory=lambda: None)
        manager._update_status(candidate, state="ready")

        assert victim.read_text() == "precious"


class TestRuntimeHealth:
    """``oneiric.runtime.health.write_runtime_health``."""

    def test_the_health_snapshot_is_published_owner_only(self, tmp_path: Path) -> None:
        dest = tmp_path / "runtime_health.json"

        write_runtime_health(dest, RuntimeHealthSnapshot())

        assert json.loads(dest.read_text())
        _assert_published_cleanly(dest)


class TestRuntimeTelemetry:
    """``RuntimeTelemetryRecorder._write``."""

    def test_the_telemetry_snapshot_is_published_owner_only(
        self, tmp_path: Path
    ) -> None:
        dest = tmp_path / "runtime_telemetry.json"
        recorder = RuntimeTelemetryRecorder(dest)

        recorder.record_event_dispatch("topic", [])

        assert json.loads(dest.read_text())
        _assert_published_cleanly(dest)


class TestRemoteTelemetry:
    """``oneiric.remote.telemetry._write``."""

    def test_the_telemetry_snapshot_is_published_owner_only(
        self, tmp_path: Path
    ) -> None:
        cache_dir = tmp_path / "cache"

        record_remote_failure(str(cache_dir), "boom")

        dest = next(cache_dir.glob("*.json"))
        assert json.loads(dest.read_text())
        _assert_published_cleanly(dest)


class TestSubstrateStore:
    """``oneiric.mcp.store._write_json_atomic``."""

    def test_the_substrate_bucket_is_published_owner_only(self, tmp_path: Path) -> None:
        store = SubstrateStore(root=tmp_path / "substrate")

        store.write_settings(_Payload(value=1))

        dest = next((tmp_path / "substrate").rglob("*.json"))
        assert json.loads(dest.read_text())
        _assert_published_cleanly(dest)


class TestAdapterRegistry:
    """``OneiricAdapterRegistry._save``."""

    def test_a_symlinked_temp_path_is_not_written_through(self, tmp_path: Path) -> None:
        """The old temp name was ``adapter_registry.json.tmp``.

        This writer already chmod'd the temp to 0600, but it chmod'd
        *after* writing -- and a symlink at that path redirected both
        the write and the chmod at the link's target.
        """
        registry = OneiricAdapterRegistry(root=tmp_path)
        victim = tmp_path / "victim.txt"
        victim.write_text("precious")
        (tmp_path / "adapter_registry.json.tmp").symlink_to(victim)

        registry._save()

        assert victim.read_text() == "precious"

    def test_the_registry_is_published_owner_only(self, tmp_path: Path) -> None:
        registry = OneiricAdapterRegistry(root=tmp_path)

        registry._save()

        dest = tmp_path / "adapter_registry.json"
        assert isinstance(json.loads(dest.read_text()), dict)
        _assert_published_cleanly(dest)


class TestPersistentKVCache:
    """``PersistentKVCacheAdapter._flush_locked``."""

    @pytest.mark.asyncio
    async def test_the_kv_store_is_published_owner_only(self, tmp_path: Path) -> None:
        adapter = PersistentKVCacheAdapter(
            PersistentKVCacheSettings(storage_path=str(tmp_path / "kv.json"))
        )

        await adapter.commit()

        dest = tmp_path / "kv.json"
        assert json.loads(dest.read_text())
        _assert_published_cleanly(dest)
