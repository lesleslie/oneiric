"""
Lifecycle Hot-Swap Example

This example demonstrates Oneiric's hot-swapping capabilities:
swapping providers at runtime, with automatic health checks and rollback.

Run with:
    uv run python docs/examples/lifecycle_hotswap.py
"""

import asyncio
from oneiric.core.resolution import Resolver, Candidate
from oneiric.core.lifecycle import LifecycleManager, HealthCheckError


class MockCache:
    """Mock cache implementation for demonstration."""

    def __init__(self, name: str, healthy: bool = True):
        self.name = name
        self.healthy = healthy

    async def health_check(self) -> bool:
        """Simulate health check."""
        return self.healthy

    async def get(self, key: str) -> str:
        """Get value from cache."""
        return f"{self.name}:{key}"

    async def set(self, key: str, value: str) -> None:
        """Set value in cache."""
        pass


async def main() -> None:
    print("=" * 60)
    print("Lifecycle Hot-Swap Example")
    print("=" * 60)
    print()

    # Create resolver and lifecycle manager
    resolver = Resolver()
    lifecycle = LifecycleManager(resolver)

    # Register cache implementations
    resolver.register(
        Candidate(
            domain="adapter",
            key="cache",
            provider="redis",
            stack_level=10,
            factory=lambda: MockCache("RedisCache"),
        )
    )

    resolver.register(
        Candidate(
            domain="adapter",
            key="cache",
            provider="memcached",
            stack_level=5,
            factory=lambda: MockCache("MemcachedCache"),
        )
    )

    resolver.register(
        Candidate(
            domain="adapter",
            key="cache",
            provider="memory",
            stack_level=0,
            factory=lambda: MockCache("MemoryCache"),
        )
    )

    # Activate initial cache
    print("1. Activating initial cache (Redis)...")
    handle = await lifecycle.activate("adapter", "cache")
    print(f"   Active provider: {handle.provider}")
    print(f"   Health check: {await lifecycle.probe_instance_health('adapter', 'cache')}")
    print(f"   Test operation: {await handle.instance.get('test-key')}")
    print()

    # Hot-swap to different provider
    print("2. Hot-swapping to Memcached...")
    handle = await lifecycle.swap("adapter", "cache", provider="memcached")
    print(f"   New provider: {handle.provider}")
    print(f"   Health check: {await lifecycle.probe_instance_health('adapter', 'cache')}")
    print(f"   Test operation: {await handle.instance.get('test-key')}")
    print()

    # Check lifecycle status
    print("3. Checking lifecycle status...")
    status = lifecycle.get_status("adapter", "cache")
    print(f"   State: {status.state}")
    print(f"   Provider: {status.provider}")
    print(f"   Activated at: {status.activated_at}")
    print()

    # Demonstrate rollback on unhealthy swap
    print("4. Demonstrating rollback on unhealthy provider...")

    # Register an unhealthy provider
    resolver.register(
        Candidate(
            domain="adapter",
            key="cache",
            provider="broken-cache",
            stack_level=0,
            factory=lambda: MockCache("BrokenCache", healthy=False),
        )
    )

    try:
        await lifecycle.swap("adapter", "cache", provider="broken-cache")
        print("   ERROR: Swap should have failed!")
    except HealthCheckError as e:
        print(f"   ✓ Swap failed as expected: {e}")
        print(f"   ✓ Rollback occurred - still using: {lifecycle.get_status('adapter', 'cache').provider}")
    print()

    # Force swap (skip health check - dangerous!)
    print("5. Force swap (skipping health check)...")
    await lifecycle.swap("adapter", "cache", provider="broken-cache", force=True)
    status = lifecycle.get_status("adapter", "cache")
    print(f"   Current provider: {status.provider} (unhealthy)")
    print()

    # Swap back to healthy provider
    print("6. Swapping back to healthy provider...")
    await lifecycle.swap("adapter", "cache", provider="redis")
    status = lifecycle.get_status("adapter", "cache")
    print(f"   Current provider: {status.provider}")
    print(f"   Health check: {await lifecycle.probe_instance_health('adapter', 'cache')}")
    print()

    print("=" * 60)
    print("Hot-swap demonstration complete!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
