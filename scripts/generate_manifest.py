#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml


sys.path.insert(0, str(Path(__file__).parent.parent))

from oneiric.actions.bootstrap import builtin_action_metadata
from oneiric.actions.metadata import ActionMetadata
from oneiric.adapters.bootstrap import builtin_adapter_metadata
from oneiric.adapters.metadata import AdapterMetadata
from oneiric.remote.models import (
    CapabilityDescriptor,
    RemoteManifest,
    RemoteManifestEntry,
)


def adapter_to_manifest_entry(
    adapter: AdapterMetadata, version: str
) -> RemoteManifestEntry:

    factory_str: str
    if isinstance(adapter.factory, str):
        factory_str = adapter.factory
    elif callable(adapter.factory):
        factory_str = f"{adapter.factory.__module__}:{adapter.factory.__qualname__}"
    else:
        raise ValueError(f"Unsupported factory type: {type(adapter.factory)}")


    settings_model_str: str | None = None
    if adapter.settings_model:
        if isinstance(adapter.settings_model, str):
            settings_model_str = adapter.settings_model
        else:
            settings_model_str = (
                f"{adapter.settings_model.__module__}:{adapter.settings_model.__name__}"
            )

    capability_descriptors = [
        CapabilityDescriptor(name=name, description=None)
        for name in adapter.capabilities
    ]

    return RemoteManifestEntry(
        domain="adapter",
        key=adapter.category,
        provider=adapter.provider,
        factory=factory_str,
        stack_level=adapter.stack_level or 0,
        priority=adapter.priority,
        version=adapter.version or version,

        capabilities=capability_descriptors,
        owner=adapter.owner,
        requires_secrets=adapter.requires_secrets,
        settings_model=settings_model_str,

        metadata={
            "description": adapter.description or "",
            "source": str(adapter.source),
        },
    )


def action_to_manifest_entry(
    action: ActionMetadata, version: str
) -> RemoteManifestEntry:

    factory_str: str
    if isinstance(action.factory, str):
        factory_str = action.factory
    elif callable(action.factory):
        factory_str = f"{action.factory.__module__}:{action.factory.__qualname__}"
    else:
        raise ValueError(f"Unsupported factory type: {type(action.factory)}")

    return RemoteManifestEntry(
        domain="action",
        key=action.action_type,
        provider=action.provider,
        factory=factory_str,
        stack_level=action.stack_level or 0,
        priority=action.priority,
        version=action.version or version,

        side_effect_free=action.extras.get("side_effect_free", False),
        timeout_seconds=action.extras.get("timeout_seconds"),

        metadata={
            "description": action.description or "",
            "source": str(action.source),
        },
    )


def generate_manifest(
    output_path: Path,
    version: str,
    source: str = "oneiric-production",
    include_adapters: bool = True,
    include_actions: bool = True,
    pretty: bool = True,
) -> RemoteManifest:
    entries: list[RemoteManifestEntry] = []


    if include_adapters:
        print("Scanning builtin adapters...")
        for adapter_meta in builtin_adapter_metadata():
            try:
                entry = adapter_to_manifest_entry(adapter_meta, version)
                entries.append(entry)
                print(f"  ✓ adapter/{entry.key} ({entry.provider})")
            except Exception as exc:
                print(
                    f"  ✗ adapter/{adapter_meta.category} ({adapter_meta.provider}): {exc}"
                )


    if include_actions:
        print("Scanning builtin actions...")
        for action_meta in builtin_action_metadata():
            try:
                entry = action_to_manifest_entry(action_meta, version)
                entries.append(entry)
                print(f"  ✓ action/{entry.key} ({entry.provider})")
            except Exception as exc:
                print(
                    f"  ✗ action/{action_meta.action_type} ({action_meta.provider}): {exc}"
                )

    manifest = RemoteManifest(source=source, entries=entries)


    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as f:
        if pretty:
            yaml.dump(
                manifest.model_dump(exclude_none=True),
                f,
                sort_keys=False,
                default_flow_style=False,
                allow_unicode=True,
            )
        else:
            yaml.dump(manifest.model_dump(exclude_none=True), f)

    print(f"\n✓ Generated manifest with {len(entries)} entries → {output_path}")
    print(f"  Source: {source}")
    print(f"  Version: {version}")
    print(f"  Adapters: {sum(1 for e in entries if e.domain == 'adapter')}")
    print(f"  Actions: {sum(1 for e in entries if e.domain == 'action')}")

    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate remote manifest from codebase metadata",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:

  python scripts/generate_manifest.py --output dist/manifest.yaml --version 1.0.0


  python scripts/generate_manifest.py --output adapters.yaml --version 1.0.0 --no-actions


  python scripts/generate_manifest.py --output actions.yaml --version 1.0.0 --no-adapters


  python scripts/generate_manifest.py \\
    --output manifest.yaml \\
    --version 1.0.0 \\
    --source my-org-production
        """,
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output path for generated manifest (YAML)",
    )
    parser.add_argument(
        "--version",
        required=True,
        help="Default version for entries (semantic versioning)",
    )
    parser.add_argument(
        "--source",
        default="oneiric-production",
        help="Manifest source identifier (default: oneiric-production)",
    )
    parser.add_argument(
        "--no-adapters",
        action="store_true",
        help="Exclude adapter entries",
    )
    parser.add_argument(
        "--no-actions",
        action="store_true",
        help="Exclude action entries",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Use compact YAML formatting (no pretty-print)",
    )

    args = parser.parse_args()

    try:
        generate_manifest(
            args.output,
            args.version,
            args.source,
            include_adapters=not args.no_adapters,
            include_actions=not args.no_actions,
            pretty=not args.compact,
        )
    except Exception as exc:
        print(f"\n✗ Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
