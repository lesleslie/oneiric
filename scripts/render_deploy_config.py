#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from oneiric.deployment import DeploymentConfigError, render_deployment_config


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render a deployment runtime config from YAML overlays",
    )
    parser.add_argument(
        "--base",
        type=Path,
        default=Path("config/standard.yaml"),
        help="Base runtime config YAML (default: config/standard.yaml)",
    )
    parser.add_argument(
        "--overlay",
        type=Path,
        action="append",
        default=None,
        help="Overlay YAML file to merge after the base config (repeatable).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("config/serverless.yaml"),
        help="Output path for the generated runtime config YAML.",
    )

    args = parser.parse_args()

    overlay_paths = args.overlay or [Path("deploy.yaml")]

    try:
        rendered = render_deployment_config(
            base_path=args.base,
            overlay_paths=overlay_paths,
            output_path=args.output,
        )
    except DeploymentConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(f"Wrote {args.output} from {args.base} + {len(overlay_paths)} overlay(s)")
    print(f"Top-level keys: {', '.join(sorted(rendered.keys()))}")


if __name__ == "__main__":
    main()
