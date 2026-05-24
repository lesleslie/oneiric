"""Helpers for generating deployment-specific runtime configuration."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml


class DeploymentConfigError(RuntimeError):
    """Raised when deployment config generation fails."""


def load_yaml_config(path: Path) -> dict[str, Any]:
    """Load a YAML configuration file."""
    try:
        loaded = yaml.safe_load(path.read_text()) or {}  # type: ignore
    except FileNotFoundError as exc:
        raise DeploymentConfigError(f"Missing config file: {path}") from exc
    except yaml.YAMLError as exc:
        raise DeploymentConfigError(f"Invalid YAML in {path}: {exc}") from exc

    if not isinstance(loaded, Mapping):
        raise DeploymentConfigError(f"Config file must contain a mapping: {path}")
    return dict(loaded)


def deep_merge(base: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively merge mapping values.

    Nested mappings are merged, while scalars and lists are replaced by the
    overlay value. This matches the runtime config layering semantics.
    """
    result: dict[str, Any] = dict(base)
    for key, value in overlay.items():
        existing = result.get(key)
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            result[key] = deep_merge(existing, value)
        else:
            result[key] = value
    return result


def render_deployment_config(
    *,
    base_path: Path,
    overlay_paths: Sequence[Path],
    output_path: Path,
) -> dict[str, Any]:
    """Render a deployment config by merging a base config and overlays."""
    rendered = load_yaml_config(base_path)
    for overlay_path in overlay_paths:
        if overlay_path.exists():
            rendered = deep_merge(rendered, load_yaml_config(overlay_path))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        yaml.safe_dump(rendered, sort_keys=False, default_flow_style=False)
    )
    return rendered
