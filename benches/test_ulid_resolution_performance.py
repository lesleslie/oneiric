"""ULID resolution service performance benchmarks."""

import sys
import os
import time

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from oneiric.core.ulid_resolution import (
    register_reference,
    resolve_ulid,
    find_references_by_system,
    find_related_ulids,
    export_registry,
    get_registry_stats,
)
from dhruva import generate


def bench_registration(count: int = 100) -> dict:
    """Benchmark ULID registration performance.

    Args:
        count: Number of ULIDs to register

    Returns:
        Dictionary with benchmark results
    """
    from oneiric.core.ulid_resolution import _ulid_registry
    _ulid_registry.clear()

    start = time.time()
    for i in range(count):
        ulid = generate()
        register_reference(
            ulid=ulid,
            system=f"test_system_{i % 5}",  # Round-robin systems
            reference_type=f"test_ref_{i % 3}",
            metadata={"index": i},
        )
    elapsed = time.time() - start

    return {
        "operation": "ULID registration",
        "count": count,
        "elapsed_seconds": elapsed,
        "throughput_per_sec": count / elapsed if elapsed > 0 else 0,
        "avg_time_ms": (elapsed / count) * 1000 if count > 0 else 0,
    }


def bench_resolution(count: int = 100) -> dict:
    """Benchmark ULID resolution performance.

    Args:
        count: Number of ULIDs to resolve

    Returns:
        Dictionary with benchmark results
    """
    # Register test ULIDs first
    from oneiric.core.ulid_resolution import _ulid_registry
    _ulid_registry.clear()

    test_ulids = [generate() for _ in range(count)]
    for ulid in test_ulids:
        register_reference(ulid, "test_system", "test_ref", {"data": "test"})

    # Benchmark resolution
    start = time.time()
    for ulid in test_ulids:
        ref = resolve_ulid(ulid)
    elapsed = time.time() - start

    return {
        "operation": "ULID resolution",
        "count": count,
        "elapsed_seconds": elapsed,
        "throughput_per_sec": count / elapsed if elapsed > 0 else 0,
        "avg_time_ms": (elapsed / count) * 1000 if count > 0 else 0,
    }


def bench_find_related(count: int = 100) -> dict:
    """Benchmark find_related_ulids performance.

    Args:
        count: Number of ULIDs to search

    Returns:
        Dictionary with benchmark results
    """
    # Register test ULIDs
    from oneiric.core.ulid_resolution import _ulid_registry
    _ulid_registry.clear()

    test_ulids = [generate() for _ in range(count)]
    for i, ulid in enumerate(test_ulids):
        register_reference(
            ulid=ulid,
            system=f"system_{i % 10}",
            reference_type="test_ref",
            metadata={"batch": i // 10},
        )

    # Benchmark find related
    start = time.time()
    related = find_related_ulids(test_ulids[0], time_window_ms=60000)
    elapsed = time.time() - start

    return {
        "operation": "find_related_ulids",
        "count": count,
        "elapsed_seconds": elapsed,
        "found_count": len(related),
        "avg_time_ms": (elapsed / count) * 1000 if count > 0 else 0,
    }


def bench_export_stats(count: int = 100) -> dict:
    """Benchmark registry export and stats performance.

    Args:
        count: Number of ULIDs in registry

    Returns:
        Dictionary with benchmark results
    """
    # Register test ULIDs
    from oneiric.core.ulid_resolution import _ulid_registry
    _ulid_registry.clear()

    test_ulids = [generate() for _ in range(count)]
    for i, ulid in enumerate(test_ulids):
        register_reference(
            ulid=ulid,
            system=f"system_{i % 5}",
            reference_type=f"ref_{i % 3}",
            metadata={"index": i},
        )

    # Benchmark export
    start = time.time()
    exported = export_registry()
    export_elapsed = time.time() - start

    # Benchmark stats
    start = time.time()
    stats = get_registry_stats()
    stats_elapsed = time.time() - start

    return {
        "operation": "export_registry and get_registry_stats",
        "count": count,
        "export_elapsed_seconds": export_elapsed,
        "stats_elapsed_seconds": stats_elapsed,
        "total_elapsed_seconds": export_elapsed + stats_elapsed,
    }


if __name__ == "__main__":
    print("ULID Resolution Service Performance Benchmark")
    print("=" * 60)

    # Test 1: Registration performance
    print("\nTest 1: ULID Registration (100 ULIDs)...")
    result1 = bench_registration(100)
    print(f"  Total time: {result1['elapsed_seconds']:.4f}s")
    print(f"  Throughput: {result1['throughput_per_sec']:.0f} ops/sec")
    print(f"  Avg time: {result1['avg_time_ms']:.3f}ms per operation")

    # Test 2: Resolution performance
    print("\nTest 2: ULID Resolution (100 lookups)...")
    result2 = bench_resolution(100)
    print(f"  Total time: {result2['elapsed_seconds']:.4f}s")
    print(f"  Throughput: {result2['throughput_per_sec']:.0f} ops/sec")
    print(f"  Avg time: {result2['avg_time_ms']:.3f}ms per lookup")

    # Test 3: Find related ULIDs
    print("\nTest 3: Find Related ULIDs (100 ULID registry)...")
    result3 = bench_find_related(100)
    print(f"  Time: {result3['elapsed_seconds']:.4f}s")
    print(f"  Found: {result3['found_count']} related ULIDs")
    print(f"  Avg time: {result3['avg_time_ms']:.3f}ms per query")

    # Test 4: Export and stats
    print("\nTest 4: Export Registry & Stats (100 ULIDs)...")
    result4 = bench_export_stats(100)
    print(f"  Export time: {result4['export_elapsed_seconds']:.4f}s")
    print(f"  Stats time: {result4['stats_elapsed_seconds']:.4f}s")
    print(f"  Total time: {result4['total_elapsed_seconds']:.4f}s")

    # Test 5: Scale test (1000 ULIDs)
    print("\nTest 5: Scale Test - Registration (1000 ULIDs)...")
    result5 = bench_registration(1000)
    print(f"  Total time: {result5['elapsed_seconds']:.4f}s")
    print(f"  Throughput: {result5['throughput_per_sec']:.0f} ops/sec")
    print(f"  Avg time: {result5['avg_time_ms']:.3f}ms per operation")

    print("\n" + "=" * 60)
    print("✅ Benchmark complete")
