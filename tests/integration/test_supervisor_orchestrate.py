"""Integration coverage for the Service Supervisor orchestration loop."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from oneiric.core.config import (
    OneiricSettings,
    RemoteSourceConfig,
    RuntimeProfileConfig,
    RuntimeSupervisorConfig,
    SecretsHook,
)
from oneiric.core.lifecycle import LifecycleManager
from oneiric.core.resolution import Resolver
from oneiric.runtime.orchestrator import RuntimeOrchestrator


def _supervisor_settings(cache_dir: Path) -> OneiricSettings:
    """Build settings that keep the supervisor enabled for integration tests."""

    return OneiricSettings(
        remote=RemoteSourceConfig(
            enabled=False,
            manifest_url=None,
            cache_dir=str(cache_dir),
            verify_tls=False,
            refresh_interval=None,
        ),
        profile=RuntimeProfileConfig(
            name="serverless-test",
            watchers_enabled=False,
            remote_enabled=False,
            inline_manifest_only=True,
            supervisor_enabled=True,
        ),
        runtime_supervisor=RuntimeSupervisorConfig(
            enabled=True,
            poll_interval=0.01,
        ),
    )


@pytest.mark.asyncio
async def test_supervisor_blocks_paused_domains_and_updates_health(tmp_path):
    """Supervisor loop should block paused domains and update runtime health snapshots."""

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    health_path = tmp_path / "runtime_health.json"
    settings = _supervisor_settings(cache_dir)
    resolver = Resolver()
    lifecycle = LifecycleManager(resolver)
    secrets = SecretsHook(lifecycle, settings.secrets)
    orchestrator = RuntimeOrchestrator(
        settings,
        resolver,
        lifecycle,
        secrets,
        health_path=str(health_path),
    )

    async with orchestrator:
        bridge = orchestrator.service_bridge
        bridge.set_paused("status", True, note="integration-test")
        await asyncio.sleep(0.05)
        assert orchestrator._supervisor is not None
        assert not bridge.should_accept_work("status")

        orchestrator._update_health(watchers_running=False, remote_enabled=False)

    assert health_path.exists()
    contents = json.loads(health_path.read_text())
    paused_state = contents["activity_state"]["service"]["status"]
    assert paused_state["paused"] is True
    assert paused_state["note"] == "integration-test"
