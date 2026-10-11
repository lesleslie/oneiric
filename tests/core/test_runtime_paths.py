from __future__ import annotations

from pathlib import Path

from oneiric.core.config import (
    OneiricSettings,
    RemoteSourceConfig,
    RuntimePathsConfig,
    workflow_checkpoint_path,
)


def test_workflow_checkpoint_path_defaults_to_cache(tmp_path: Path) -> None:
    # Phase 1 amendment: OneiricSettings is now a BaseSettings subclass, so
    # YAML layers can populate ``cache_dir`` and override ``remote.cache_dir``
    # in ``workflow_checkpoint_path``'s ``cache_dir or remote.cache_dir``
    # fallback. Pin ``cache_dir`` explicitly here so the test is hermetic
    # against the worktree's settings/oneiric.yaml.
    settings = OneiricSettings(
        cache_dir=str(tmp_path),
        remote=RemoteSourceConfig(cache_dir=str(tmp_path)),
    )
    resolved = workflow_checkpoint_path(settings)
    assert resolved == tmp_path / "workflow_checkpoints.sqlite"


def test_workflow_checkpoint_path_override(tmp_path: Path) -> None:
    override = tmp_path / "custom.sqlite"
    settings = OneiricSettings(
        cache_dir=str(tmp_path),
        remote=RemoteSourceConfig(cache_dir=str(tmp_path)),
        runtime_paths=RuntimePathsConfig(workflow_checkpoints_path=str(override)),
    )
    resolved = workflow_checkpoint_path(settings)
    assert resolved == override


def test_workflow_checkpoint_path_disabled(tmp_path: Path) -> None:
    settings = OneiricSettings(
        cache_dir=str(tmp_path),
        remote=RemoteSourceConfig(cache_dir=str(tmp_path)),
        runtime_paths=RuntimePathsConfig(workflow_checkpoints_enabled=False),
    )
    resolved = workflow_checkpoint_path(settings)
    assert resolved is None
