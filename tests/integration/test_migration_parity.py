"""Integration tests for cross-repo migration fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from oneiric.core.config import (
    OneiricSettings,
    RemoteSourceConfig,
    RuntimePathsConfig,
    RuntimeProfileConfig,
    SecretsHook,
)
from oneiric.core.lifecycle import LifecycleManager
from oneiric.core.resolution import Resolver
from oneiric.runtime.orchestrator import RuntimeOrchestrator


def _parity_settings(cache_dir: Path) -> OneiricSettings:
    """Build Oneiric settings tailored for migration fixture tests."""

    return OneiricSettings(
        remote=RemoteSourceConfig(
            enabled=True,
            manifest_url=None,
            cache_dir=str(cache_dir),
            verify_tls=False,
            refresh_interval=None,
        ),
        profile=RuntimeProfileConfig(
            name="parity-test",
            watchers_enabled=False,
            remote_enabled=True,
            inline_manifest_only=True,
            supervisor_enabled=False,
        ),
        runtime_paths=RuntimePathsConfig(
            workflow_checkpoints_enabled=False,
        ),
    )


@pytest.fixture(scope="module")
def fastblocks_manifest_path() -> Path:
    """Shared path to the Fastblocks parity manifest."""

    return (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "examples"
        / "FASTBLOCKS_PARITY_FIXTURE.yaml"
    )


@pytest.mark.asyncio
async def test_fastblocks_manifest_registers_expected_domains(
    tmp_path, fastblocks_manifest_path: Path
):
    """Remote sync should register every domain required for Fastblocks parity."""

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    settings = _parity_settings(cache_dir)
    settings.remote.allow_file_uris = True
    settings.remote.allowed_file_uri_roots = [str(fastblocks_manifest_path.parent)]
    resolver = Resolver()
    lifecycle = LifecycleManager(
        resolver, status_snapshot_path=str(tmp_path / "lifecycle_status.json")
    )
    secrets = SecretsHook(lifecycle, settings.secrets)
    orchestrator = RuntimeOrchestrator(settings, resolver, lifecycle, secrets)

    manifest_url = f"file://{fastblocks_manifest_path}"
    result = await orchestrator.sync_remote(manifest_url=manifest_url)

    assert result is not None
    manifest_payload = yaml.safe_load(fastblocks_manifest_path.read_text())
    manifest_entries = manifest_payload.get("entries", [])
    expected_counts: dict[str, int] = {}
    for entry in manifest_entries:
        domain = entry.get("domain")
        if not domain:
            continue
        expected_counts[domain] = expected_counts.get(domain, 0) + 1

    assert result.registered == len(manifest_entries)
    for domain, count in expected_counts.items():
        assert result.per_domain[domain] == count

    workflow_specs = orchestrator.workflow_bridge.dag_specs()
    assert "fastblocks.workflows.fulfillment" in workflow_specs
    assert len(workflow_specs["fastblocks.workflows.fulfillment"]["nodes"]) == 2

    event_candidate = resolver.resolve("event", "fastblocks.order.created")
    assert event_candidate is not None
    assert "fastblocks.order.created" in event_candidate.metadata["topics"]

    workflow_candidate = resolver.resolve(
        "workflow", "fastblocks.workflows.fulfillment"
    )
    assert workflow_candidate is not None
    scheduler_metadata = workflow_candidate.metadata.get("scheduler")
    assert scheduler_metadata["queue_category"] == "queue.scheduler"
