"""
Serverless Deployment Example

This example demonstrates how to configure Oneiric for serverless
deployment on Google Cloud Run or similar platforms.

Key considerations for serverless:
- Disable file watchers (use polling instead)
- Disable remote sync or use long refresh intervals
- Use inline manifests baked into the container image
- Configure health checks for readiness probes
- Use Secret Manager for secrets

Run with:
    uv run python docs/examples/serverless_deployment.py
"""

import asyncio
from pathlib import Path

from oneiric.core.config import Settings, load_settings
from oneiric.core.resolution import Resolver
from oneiric.core.lifecycle import LifecycleManager
from oneiric.adapters import AdapterBridge, register_builtin_adapters


async def main() -> None:
    print("=" * 60)
    print("Serverless Deployment Example")
    print("=" * 60)
    print()

    # 1. Serverless profile configuration
    print("1. Serverless profile configuration:")
    print("   ONEIRIC_PROFILE=serverless")
    print()
    print("   This profile automatically:")
    print("   - Disables file watchers (not supported in serverless)")
    print("   - Disables remote sync (use baked-in manifests)")
    print("   - Enables Secret Manager for secrets")
    print("   - Enables Service Supervisor for pause/drain")
    print()

    # 2. Load settings with serverless profile
    print("2. Loading serverless configuration...")
    print()
    print("   Example Procfile entry:")
    print("   web: uv run python -m oneiric.cli orchestrate \\")
    print("         --profile serverless \\")
    print("         --no-remote \\")
    print("         --health-path /tmp/runtime_health.json")
    print()

    # 3. Create resolver and register adapters
    print("3. Setting up resolver with built-in adapters...")
    resolver = Resolver()
    register_builtin_adapters(resolver)
    print(f"   Registered {len(list(resolver.get_all_candidates('adapter', '*')))} adapters")
    print()

    # 4. Create lifecycle manager
    print("4. Creating lifecycle manager...")
    lifecycle = LifecycleManager(
        resolver,
        status_snapshot_path=".oneiric_cache/lifecycle_status.json",
    )
    print("   Lifecycle manager ready")
    print()

    # 5. Example: Activate cache adapter
    print("5. Activating cache adapter...")
    try:
        # In production, settings would come from config file
        # For demo, we'll use minimal settings
        class DemoSettings:
            class Adapters:
                selections = {}
                provider_settings = {}

        settings = DemoSettings()
        bridge = AdapterBridge(resolver, lifecycle, settings.adapters)

        handle = await bridge.use("cache", provider="memory")
        print(f"   Activated: {handle.provider}")
        print()
    except Exception as e:
        print(f"   Note: {e}")
        print()

    # 6. Health check for readiness probe
    print("6. Health check (for Cloud Run readiness probe):")
    print("   Command: oneiric.cli health --probe --json")
    print()
    print("   This returns:")
    print("   {")
    print('     "healthy": true,')
    print('     "components": {')
    print('       "adapter:cache": {"healthy": true}')
    print('     }')
    print("   }")
    print()

    # 7. Superviser info for validation
    print("7. Service Supervisor status:")
    print("   Command: oneiric.cli supervisor-info --json")
    print()
    print("   Returns supervisor state, activity store, and profile info")
    print()

    # 8. Deployment checklist
    print("8. Serverless deployment checklist:")
    print()
    print("   Before deployment:")
    print("   ✓ Package manifest into container image")
    print("     oneiric.cli manifest pack \\")
    print("       --input manifest.yaml \\")
    print("       --output build/serverless_manifest.json")
    print()
    print("   ✓ Configure Secret Manager")
    print("     - Store sensitive credentials in Secret Manager")
    print("     - Reference via $SECRET_NAME in settings")
    print()
    print("   ✓ Set environment variables:")
    print("     ONEIRIC_PROFILE=serverless")
    print("     ONEIRIC_CONFIG=/workspace/config/serverless.toml")
    print("     ONEIRIC_RUNTIME_SUPERVISOR__ENABLED=true")
    print()
    print("   ✓ Configure health checks:")
    print("     Readiness: GET /health (or /tmp/runtime_health.json)")
    print("     Liveness: TCP port check")
    print()
    print("   ✓ Validate deployment:")
    print("     oneiric.cli supervisor-info --json")
    print("     oneiric.cli health --probe --json")
    print("     oneiric.cli activity --json")
    print()

    # 9. Monitoring and observability
    print("9. Monitoring and observability:")
    print()
    print("   Logs:")
    print("   - Structured JSON logs to stdout")
    print("   - Cloud Logging automatically captures stdout")
    print()
    print("   Metrics:")
    print("   - OpenTelemetry traces exported")
    print("   - Cloud Monitoring integration")
    print()
    print("   Health snapshots:")
    print("   - /tmp/runtime_health.json updated every 30s")
    print("   - Use for readiness probes")
    print()

    # 10. Example config file
    print("10. Example serverless config (config/serverless.toml):")
    print()
    print("    [app]")
    print("    environment = 'production'")
    print()
    print("    [adapters.selections]")
    print("    cache = 'redis'")
    print("    queue = 'cloudtasks'")
    print()
    print("    [adapters.provider_settings.redis]")
    print('    url = "$REDIS_URL"  # From Secret Manager')
    print()
    print("    [runtime]")
    print('    activity_store = "/workspace/.oneiric_cache/domain_activity.sqlite"')
    print('    health_snapshot = "/tmp/runtime_health.json"')
    print()
    print("    [runtime.supervisor]")
    print("    enabled = true")
    print('    loop_interval = 30')
    print()
    print("    [runtime.profile]")
    print('    watchers_enabled = false')
    print('    remote_enabled = false')
    print()

    print("=" * 60)
    print("Serverless deployment example complete!")
    print()
    print("Full deployment guide:")
    print("  docs/deployment/CLOUD_RUN_BUILD.md")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
