#!/usr/bin/env python3
"""
Analyze pytest test timings and suggest which tests should be marked as slow.

Usage:
    # Run tests and analyze timings
    uv run pytest --durations=0 --tb=no -q > test_output.txt 2>&1
    uv run python scripts/analyze_test_timings.py test_output.txt

    # Or run directly with pipe
    uv run pytest --durations=0 --tb=no -q 2>&1 | uv run python scripts/analyze_test_timings.py -
"""

import re
import sys
from collections import defaultdict


def parse_test_timings(output_text: str) -> dict[str, float]:
    """Parse pytest duration output and extract test timings."""
    timings = {}

    # Match lines like: "0.52s call     tests/core/test_resolution.py::test_resolver_basic"
    pattern = r"([\d.]+)s\s+\w+\s+(.+)"

    for line in output_text.split("\n"):
        match = re.match(pattern, line.strip())
        if match:
            duration = float(match.group(1))
            test_path = match.group(2)
            timings[test_path] = duration

    return timings


def categorize_by_module(
    timings: dict[str, float],
) -> dict[str, list[tuple[str, float]]]:
    """Group tests by module (directory)."""
    by_module = defaultdict(list)

    for test_path, duration in timings.items():
        # Extract module from path like "tests/core/test_resolution.py::test_name"
        if "::" in test_path:
            module = (
                test_path.split("::")[0].split("/")[1]
                if "/" in test_path
                else "unknown"
            )
            by_module[module].append((test_path, duration))

    return by_module


def analyze_timings(
    timings: dict[str, float], slow_threshold: float = 5.0, fast_threshold: float = 1.0
):
    """Analyze test timings and provide recommendations."""
    slow_tests = [(path, dur) for path, dur in timings.items() if dur >= slow_threshold]
    medium_tests = [
        (path, dur)
        for path, dur in timings.items()
        if fast_threshold <= dur < slow_threshold
    ]
    fast_tests = [(path, dur) for path, dur in timings.items() if dur < fast_threshold]

    print("\n📊 Test Timing Analysis")
    print(f"{'=' * 80}")
    print(f"Total tests analyzed: {len(timings)}")
    print(f"Slow tests (>={slow_threshold}s): {len(slow_tests)}")
    print(f"Medium tests ({fast_threshold}s-{slow_threshold}s): {len(medium_tests)}")
    print(f"Fast tests (<{fast_threshold}s): {len(fast_tests)}")
    print(f"{'=' * 80}\n")

    if slow_tests:
        print("🐌 Slow Tests (should be marked with @pytest.mark.slow):")
        print(f"{'-' * 80}")
        for test_path, duration in sorted(slow_tests, key=lambda x: x[1], reverse=True)[
            :20
        ]:
            print(f"  {duration:6.2f}s  {test_path}")
        if len(slow_tests) > 20:
            print(f"  ... and {len(slow_tests) - 20} more")
        print()

    # Group by module
    by_module = categorize_by_module(timings)
    print("\n📁 Test Timings by Module:")
    print(f"{'-' * 80}")
    for module in sorted(by_module.keys()):
        module_tests = by_module[module]
        total_time = sum(dur for _, dur in module_tests)
        avg_time = total_time / len(module_tests)
        slow_count = sum(1 for _, dur in module_tests if dur >= slow_threshold)

        print(
            f"  {module:20s}: {len(module_tests):4d} tests, "
            f"{total_time:7.2f}s total, {avg_time:5.2f}s avg, "
            f"{slow_count:3d} slow"
        )

    # Total time estimate
    total_time = sum(timings.values())
    print(f"\n⏱️  Total Test Time (serial): {total_time:.2f}s ({total_time / 60:.2f}m)")

    # Estimate parallel execution time (assuming 8 workers)
    workers = 8
    parallel_time = total_time / workers * 1.3  # 30% overhead for coordination
    print(
        f"⚡ Estimated Time (8 workers): {parallel_time:.2f}s ({parallel_time / 60:.2f}m)"
    )
    print()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    input_file = sys.argv[1]

    if input_file == "-":
        output_text = sys.stdin.read()
    else:
        with open(input_file) as f:
            output_text = f.read()

    timings = parse_test_timings(output_text)

    if not timings:
        print(
            "⚠️  No test timings found in output. Make sure to run pytest with --durations=0"
        )
        sys.exit(1)

    analyze_timings(timings, slow_threshold=5.0, fast_threshold=1.0)

    print("💡 Recommendations:")
    print("=" * 80)
    print("1. Mark slow tests (>=5s) with @pytest.mark.slow")
    print("2. Mark fast tests (<1s) with @pytest.mark.fast")
    print("3. Use 'pytest -m \"not slow\"' for quick CI runs")
    print("4. Use 'pytest -m slow' to run only slow tests in dedicated jobs")
    print("5. Consider parallelizing slow tests or optimizing their setup/teardown")
    print()


if __name__ == "__main__":
    main()
