"""Tests for deployment config rendering helpers."""

from __future__ import annotations

from pathlib import Path

import yaml

from oneiric.deployment.config import deep_merge, render_deployment_config


class TestDeepMerge:
    def test_merges_nested_mappings(self) -> None:
        base = {
            "remote": {"enabled": True, "refresh_interval": 300},
            "secrets": {"provider": "gcp.secret_manager"},
        }
        overlay = {
            "remote": {"enabled": False},
            "runtime_supervisor": {"enabled": True},
        }

        merged = deep_merge(base, overlay)

        assert merged["remote"]["enabled"] is False
        assert merged["remote"]["refresh_interval"] == 300
        assert merged["secrets"]["provider"] == "gcp.secret_manager"
        assert merged["runtime_supervisor"]["enabled"] is True

    def test_replaces_lists_and_scalars(self) -> None:
        base = {"items": ["a", "b"], "count": 1}
        overlay = {"items": ["c"], "count": 2}

        merged = deep_merge(base, overlay)

        assert merged["items"] == ["c"]
        assert merged["count"] == 2


class TestRenderDeploymentConfig:
    def test_renders_yaml_output(self, tmp_path: Path) -> None:
        base = tmp_path / "standard.yaml"
        base.write_text(
            yaml.safe_dump(
                {
                    "profile": {"name": "standard"},
                    "remote": {"enabled": True},
                },
                sort_keys=False,
            )
        )

        overlay = tmp_path / "deploy.yaml"
        overlay.write_text(
            yaml.safe_dump(
                {
                    "profile": {"name": "serverless"},
                    "remote": {"enabled": False},
                    "secrets": {"provider": "gcp.secret_manager"},
                },
                sort_keys=False,
            )
        )

        output = tmp_path / "config" / "serverless.yaml"
        rendered = render_deployment_config(
            base_path=base,
            overlay_paths=[overlay],
            output_path=output,
        )

        assert output.exists()
        assert rendered["profile"]["name"] == "serverless"
        assert rendered["remote"]["enabled"] is False
        assert rendered["secrets"]["provider"] == "gcp.secret_manager"
        assert yaml.safe_load(output.read_text()) == rendered
