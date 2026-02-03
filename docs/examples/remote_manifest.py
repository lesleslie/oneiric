"""
Remote Manifest Example

This example demonstrates loading components from remote manifests,
including signature verification and automatic syncing.

Run with:
    uv run python docs/examples/remote_manifest.py
"""

import asyncio
from pathlib import Path

from oneiric.core.resolution import Resolver
from oneiric.remote.loader import RemoteManifestLoader
from oneiric.remote.models import Manifest, AdapterEntry, ServiceEntry


async def main() -> None:
    print("=" * 60)
    print("Remote Manifest Example")
    print("=" * 60)
    print()

    # Create a sample manifest
    print("1. Creating sample manifest...")
    manifest = Manifest(
        api_version="2.0",
        manifest_id="example-manifest",
        manifest_source="local-example",
        adapters=[
            AdapterEntry(
                domain="adapter",
                key="cache",
                provider="redis",
                package="oneiric.adapters",
                import_path="oneiric.adapters.cache.redis:RedisAdapter",
                metadata={
                    "stack_level": 10,
                    "capabilities": ["distributed", "persistent"],
                },
                settings={
                    "url": "redis://localhost:6379",
                },
            ),
            AdapterEntry(
                domain="adapter",
                key="cache",
                provider="memcached",
                package="oneiric.adapters",
                import_path="oneiric.adapters.cache.memcached:MemcachedAdapter",
                metadata={
                    "stack_level": 5,
                },
                settings={
                    "url": "memcached://localhost:11211",
                },
            ),
        ],
        services=[
            ServiceEntry(
                domain="service",
                key="status",
                provider="builtin",
                package="oneiric.domains",
                import_path="oneiric.domains.services:BuiltinStatusService",
                metadata={
                    "stack_level": 10,
                },
            ),
        ],
    )
    print(f"   Manifest ID: {manifest.manifest_id}")
    print(f"   Adapters: {len(manifest.adapters)}")
    print(f"   Services: {len(manifest.services)}")
    print()

    # Load manifest from file (using sample manifest)
    print("2. Loading manifest from file...")
    sample_manifest_path = Path("docs/sample_remote_manifest.yaml")
    if sample_manifest_path.exists():
        resolver = Resolver()

        # Note: In production, use trusted public keys
        # loader = RemoteManifestLoader(
        #     manifest_url=str(sample_manifest_path),
        #     trusted_public_keys=["ed25519:..."],
        # )

        # For demo, we'll load directly
        from oneiric.remote.loader import load_manifest_from_file

        loaded_manifest = load_manifest_from_file(sample_manifest_path)
        print(f"   Loaded: {loaded_manifest.manifest_id}")
        print(f"   Source: {loaded_manifest.manifest_source}")
        print()

        # Register candidates from manifest
        print("3. Registering candidates from manifest...")
        for adapter in loaded_manifest.adapters:
            print(f"   - {adapter.domain}:{adapter.key} ({adapter.provider})")

        # In production, use loader.sync(resolver)
        # await loader.sync(resolver)
        print()
    else:
        print(f"   Sample manifest not found at {sample_manifest_path}")
        print()

    # Demonstrate manifest structure
    print("4. Manifest structure:")
    print(f"   API Version: {manifest.api_version}")
    print(f"   Adapters:")
    for adapter in manifest.adapters:
        print(f"     - {adapter.key} -> {adapter.provider}")
        print(f"       Import: {adapter.import_path}")
        print(f"       Stack Level: {adapter.metadata.get('stack_level', 0)}")
    print(f"   Services:")
    for service in manifest.services:
        print(f"     - {service.key} -> {service.provider}")
    print()

    # Demonstrate metadata capabilities
    print("5. Using metadata for capabilities...")
    cache_adapters = [a for a in manifest.adapters if a.key == "cache"]
    for adapter in cache_adapters:
        capabilities = adapter.metadata.get("capabilities", [])
        if capabilities:
            print(f"   {adapter.provider}: {', '.join(capabilities)}")
    print()

    # Demonstrate settings structure
    print("6. Provider settings:")
    for adapter in manifest.adapters:
        if adapter.settings:
            print(f"   {adapter.provider}:")
            for key, value in adapter.settings.items():
                print(f"     {key}: {value}")
    print()

    print("=" * 60)
    print("Remote manifest demonstration complete!")
    print()
    print("In production:")
    print("  - Use signed manifests with ED25519 signatures")
    print("  - Load from HTTPS URLs or S3")
    print("  - Set up automatic sync with refresh intervals")
    print("  - Use RemoteManifestLoader for secure loading")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
