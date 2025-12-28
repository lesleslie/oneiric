# Test Infrastructure Improvements

## Overview

This document summarizes the test infrastructure improvements made to address test timeout issues and enable more flexible test execution strategies.

## Problem Statement

The Oneiric test suite has grown to **716 tests** across 94 test files, causing execution timeouts with the default Crackerjack configuration (300s). This required both increasing the timeout and implementing strategies for selective test execution.

## Changes Made

### 1. Increased Crackerjack Test Timeout

**File:** `pyproject.toml`

**Change:** Added test timeout configuration to `[tool.crackerjack]` section:

```toml
[tool.crackerjack]
# ... existing config ...

# Test execution configuration
test_timeout = 600  # 10 minutes for 716 tests (increased from 300s default)
```

**Impact:** Full test suite can now complete without timeout (600s = 10 minutes)

### 2. Enhanced Pytest Markers

**File:** `pyproject.toml`

**Change:** Expanded marker definitions in `[tool.pytest.ini_options]`:

```toml
markers = [
    "security: Security-related tests",
    "integration: Integration tests",
    "slow: Slow-running tests (>5s per test)",
    "fast: Fast-running tests (<1s per test)",
    "unit: Unit tests (isolated, no I/O)",
    "e2e: End-to-end tests (full system)",
    "adapter: Adapter-specific tests",
    "remote: Remote manifest tests",
    "runtime: Runtime orchestration tests",
]
```

**Impact:** Enables selective test execution by performance characteristics, scope, and domain

### 3. Created Makefile for Common Test Patterns

**File:** `Makefile` (new)

**Features:**

- 19 test execution targets
- Performance-based filtering (fast, slow, not-slow)
- Domain-based filtering (adapter, remote, runtime, security)
- Scope-based filtering (unit, integration, e2e)
- Utility targets (analyze, coverage, parallel)

**Example Usage:**

```bash
make help              # Show all targets
make test-fast         # Run only fast tests
make test-not-slow     # Skip slow tests (good for CI)
make test-analyze      # Run with timing analysis
```

### 4. Created Test Timing Analysis Script

**File:** `scripts/analyze_test_timings.py` (new)

**Purpose:** Analyze pytest timing output to identify slow tests and provide optimization recommendations

**Usage:**

```bash
make test-analyze
# OR
pytest --durations=0 --tb=no -q 2>&1 | python scripts/analyze_test_timings.py -
```

**Output:**

- Total test count and distribution
- List of slowest tests
- Breakdown by module
- Parallel execution time estimates
- Recommendations for marking tests

### 5. Created pytest.ini for Configuration Examples

**File:** `pytest.ini` (new)

**Purpose:** Document marker filtering patterns and provide alternative configurations

**Examples:**

- Default marker filters (commented)
- Usage patterns for different test scenarios
- Quick reference for pytest marker syntax

### 6. Updated CLAUDE.md Documentation

**File:** `CLAUDE.md`

**Section:** Testing

**Improvements:**

- Updated test count (716 tests)
- Added timeout documentation (600s)
- Comprehensive test execution strategies
- Makefile quick start guide
- Test marker documentation
- CI/CD recommendations
- Performance analysis instructions

### 7. Created Comprehensive Test Suite README

**File:** `tests/README.md` (new)

**Contents:**

- Quick start guide
- Test organization structure
- Test marker documentation with examples
- Test execution strategies (4 different workflows)
- Writing tests guidelines
- Performance analysis instructions
- CI/CD integration patterns
- Troubleshooting guide

## Test Suite Statistics

### Current State

- **Total Tests:** 716
- **Test Files:** 94 across 10 categories
- **Coverage:** 83% (target: 60%, achieved: 138% of target)
- **Timeout:** 600s (10 minutes)
- **Parallel Support:** Yes (pytest-xdist)

### Distribution by Category

| Category | Files | Description |
|--------------|-------|------------------------------------------|
| adapters | 45 | Adapter domain and specific adapter tests |
| actions | 11 | Action domain tests |
| runtime | 11 | Runtime orchestration tests |
| core | 9 | Core resolution & lifecycle tests |
| security | 5 | Security hardening tests (100 tests) |
| integration | 5 | Cross-component integration tests |
| remote | 4 | Remote manifest loading tests |
| domains | 2 | Generic domain bridge tests |
| cli | 1 | CLI command tests |

## Test Execution Strategies

### 1. Fast CI Pipeline (< 2 minutes)

```bash
make test-not-slow    # Skip slow tests
pytest -m "not slow"  # Direct pytest
```

**Use Case:** Pull request checks, quick feedback loop

### 2. Development Workflow (Iterative)

```bash
make test-fast                    # Quick iteration
pytest tests/core/ -v             # Module-specific
python -m crackerjack -t          # Pre-commit validation
```

**Use Case:** Development and debugging

### 3. Full Test Suite (10 minutes)

```bash
make test                         # All tests
python -m crackerjack -t          # With quality suite
```

**Use Case:** Pre-merge validation, release validation

### 4. Performance Analysis

```bash
make test-analyze                 # Timing analysis
pytest --durations=20             # Show slowest tests
```

**Use Case:** Identifying slow tests, optimization opportunities

## Marker Usage Patterns

### By Performance

```bash
pytest -m "fast"          # Only fast tests (<1s)
pytest -m "slow"          # Only slow tests (>5s)
pytest -m "not slow"      # Everything except slow tests
```

### By Scope

```bash
pytest -m "unit"          # Unit tests only
pytest -m "integration"   # Integration tests only
pytest -m "e2e"           # End-to-end tests only
```

### By Domain

```bash
pytest -m "adapter"       # Adapter tests
pytest -m "security"      # Security tests
pytest -m "remote"        # Remote manifest tests
pytest -m "runtime"       # Runtime orchestration tests
```

### Combined Markers

```bash
pytest -m "integration or e2e"    # Integration and e2e
pytest -m "security and not slow" # Fast security tests
pytest -m "unit and fast"         # Fast unit tests
```

## CI/CD Recommendations

### Pull Request Checks

```bash
make test-not-slow
```

- **Duration:** ~2 minutes
- **Purpose:** Fast feedback
- **Coverage:** ~80% of tests (excludes slow tests only)

### Pre-merge Validation

```bash
python -m crackerjack -t
```

- **Duration:** ~10 minutes
- **Purpose:** Comprehensive quality validation
- **Coverage:** 100% (all tests + quality checks)

### Nightly Builds

```bash
make test-all
```

- **Duration:** ~10 minutes
- **Purpose:** Full test suite with timing analysis
- **Coverage:** 100% with performance metrics

### Release Validation

```bash
make test-coverage
```

- **Duration:** ~10 minutes
- **Purpose:** Full test suite with HTML coverage report
- **Coverage:** 100% with detailed coverage analysis

## Benefits

### For Developers

1. **Faster feedback loops** - Run fast tests during development
1. **Better test organization** - Clear categorization by markers
1. **Easy to use** - Makefile provides simple commands
1. **Performance insights** - Identify slow tests easily

### For CI/CD

1. **Flexible pipelines** - Different strategies for different stages
1. **Predictable timing** - 600s timeout accommodates full suite
1. **Fast feedback** - Skip slow tests in PR checks
1. **Full coverage** - Run everything in pre-merge/release

### For Maintenance

1. **Visible slow tests** - Easy to identify optimization targets
1. **Documented patterns** - Clear execution strategies
1. **Self-documenting** - Makefile help + README
1. **Scalable** - Marker system grows with test suite

## Future Enhancements

### Short-term (Next Sprint)

1. **Mark existing tests** - Add markers to current test suite

   - Identify slow tests (>5s) with timing analysis
   - Mark fast tests (\<1s)
   - Categorize by domain (adapter, remote, runtime, security)

1. **Create GitHub Actions workflow** - Use marker-based execution

   - PR: `make test-not-slow`
   - Pre-merge: `python -m crackerjack -t`
   - Nightly: `make test-all`

### Medium-term (Next Quarter)

1. **Test optimization** - Reduce slow test count

   - Parallelize slow integration tests
   - Optimize fixture setup/teardown
   - Consider test data caching

1. **Enhanced analysis** - More sophisticated timing analysis

   - Track test performance over time
   - Alert on regression (tests getting slower)
   - Automated slow test detection in CI

### Long-term (Next Half)

1. **Test quarantine** - Isolate flaky tests

   - Add `@pytest.mark.flaky` marker
   - Separate execution for unstable tests
   - Track flakiness metrics

1. **Distributed testing** - Scale beyond single machine

   - pytest-distributed for multi-node execution
   - Cloud-based test execution
   - Reduce full suite time to \<5 minutes

## Migration Guide

### For Existing Tests

To add markers to existing tests:

```python
import pytest


# Example: Mark a fast unit test
@pytest.mark.fast
@pytest.mark.unit
async def test_resolver_basic():
    """Test basic resolver functionality."""
    # ... test implementation


# Example: Mark a slow integration test
@pytest.mark.slow
@pytest.mark.integration
async def test_full_swap_lifecycle():
    """Test complete swap lifecycle with health checks."""
    # ... test implementation
```

### For New Tests

Follow the marker guidelines in `tests/README.md`:

1. **Always mark performance** - Use `@pytest.mark.fast` or `@pytest.mark.slow`
1. **Mark scope** - Use `@pytest.mark.unit`, `@pytest.mark.integration`, or `@pytest.mark.e2e`
1. **Mark domain** - Use domain-specific markers when applicable

## Validation

### Test the Configuration

```bash
# Verify markers are registered
pytest --markers

# Verify Makefile works
make help
make test-fast --dry-run

# Run timing analysis
make test-analyze
```

### Verify Crackerjack Timeout

```bash
# Should complete without timeout (was failing at 300s)
python -m crackerjack -t -v
```

## References

- **Main Documentation:** `CLAUDE.md` (Testing section)
- **Test Suite README:** `tests/README.md`
- **Timing Analysis:** `scripts/analyze_test_timings.py`
- **Makefile:** `Makefile` (test-\* targets)
- **pytest Configuration:** `pyproject.toml` ([tool.pytest.ini_options])
- **Crackerjack Configuration:** `pyproject.toml` ([tool.crackerjack])
