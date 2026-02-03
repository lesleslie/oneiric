"""
Basic Resolution Example

This example demonstrates the fundamental resolution pattern in Oneiric:
registering candidates, resolving them, and understanding why a specific
candidate was chosen.

Run with:
    uv run python docs/examples/basic_resolution.py
"""

import asyncio
from oneiric.core.resolution import Resolver, Candidate


async def main() -> None:
    print("=" * 60)
    print("Basic Resolution Example")
    print("=" * 60)
    print()

    # Create a resolver
    resolver = Resolver()

    # Register multiple cache implementations
    resolver.register(
        Candidate(
            domain="adapter",
            key="cache",
            provider="redis",
            stack_level=10,
            factory=lambda: type("RedisCache", (), {"name": "RedisCache"})(),
            description="Redis cache implementation",
        )
    )

    resolver.register(
        Candidate(
            domain="adapter",
            key="cache",
            provider="memcached",
            stack_level=5,
            factory=lambda: type("MemcachedCache", (), {"name": "MemcachedCache"})(),
            description="Memcached cache implementation",
        )
    )

    resolver.register(
        Candidate(
            domain="adapter",
            key="cache",
            provider="memory",
            stack_level=0,
            factory=lambda: type("MemoryCache", (), {"name": "MemoryCache"})(),
            description="In-memory cache implementation",
        )
    )

    # Resolve the cache (highest stack_level wins)
    print("Resolving cache adapter...")
    result = resolver.resolve("adapter", "cache")
    print(f"  Selected: {result.provider}")
    print(f"  Instance: {result.instance.name}")
    print()

    # Explain why this candidate was chosen
    print("Resolution explanation:")
    explanation = resolver.explain("adapter", "cache")
    print(f"  Selected: {explanation.selected}")
    print(f"  Reason: {explanation.reason}")
    print(f"  Shadowed candidates: {[c.provider for c in explanation.shadowed]}")
    print()

    # Demonstrate priority override
    print("Registering high-priority override...")
    resolver.register(
        Candidate(
            domain="adapter",
            key="cache",
            provider="custom-redis",
            priority=100,  # High priority
            stack_level=0,
            factory=lambda: type("CustomRedisCache", (), {"name": "CustomRedisCache"})(),
            description="Custom Redis cache",
        )
    )

    result = resolver.resolve("adapter", "cache")
    print(f"  New selection: {result.provider}")
    print(f"  Reason: High priority ({result.metadata.get('priority', 0)})")
    print()

    # Demonstrate explicit selection (highest precedence)
    print("Setting explicit selection...")
    resolver.set_selection("adapter", "cache", "memcached")

    result = resolver.resolve("adapter", "cache")
    print(f"  New selection: {result.provider}")
    print(f"  Reason: Explicit selection (highest precedence)")
    print()

    # Show all registered candidates
    print("All registered candidates:")
    for candidate in resolver.get_all_candidates("adapter", "cache"):
        print(f"  - {candidate.provider} (stack_level={candidate.metadata.get('stack_level', 0)})")
    print()


if __name__ == "__main__":
    asyncio.run(main())
