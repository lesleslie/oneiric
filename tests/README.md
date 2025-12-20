# Oneiric Test Suite

This directory contains the comprehensive test suite for Oneiric (716 tests across 10 categories).

## Quick Start

```bash
# Run all tests
make test

# Fast feedback loop (skip slow tests)
make test-not-slow

# Run specific test categories
make test-fast         # Only fast tests (<1s)
make test-unit         # Only unit tests
make test-security     # Security tests
make test-integration  # Integration tests
```

## Test Organization

```
tests/
├── actions/       # Action domain tests (11 files)
├── adapters/      # Adapter-specific tests (45 files) - largest category
├── cli/           # CLI command tests (1 file)
├── core/          # Core resolution & lifecycle tests (9 files)
├── domains/       # Generic domain bridge tests (2 files)
├── integration/   # Integration tests (5 files)
├── remote/        # Remote manifest tests (4 files)
├── runtime/       # Runtime orchestration tests (11 files)
├── security/      # Security hardening tests (5 files)
└── README.md      # This file
```

## Test Markers

Tests can be annotated with markers to enable selective execution:

### Performance Markers
- `@pytest.mark.fast` - Fast tests (<1s per test)
- `@pytest.mark.slow` - Slow tests (>5s per test)

### Scope Markers
- `@pytest.mark.unit` - Unit tests (isolated, no I/O)
- `@pytest.mark.integration` - Integration tests
- `@pytest.mark.e2e` - End-to-end tests (full system)

### Domain Markers
- `@pytest.mark.adapter` - Adapter-specific tests
- `@pytest.mark.remote` - Remote manifest tests
- `@pytest.mark.runtime` - Runtime orchestration tests
- `@pytest.mark.security` - Security-related tests

### Usage Examples

```bash
# Run only fast tests
pytest -m "fast" -v

# Run all except slow tests (good for CI)
pytest -m "not slow" -v

# Run security and integration tests
pytest -m "security or integration" -v

# Run everything except e2e tests
pytest -m "not e2e" -v
```

## Test Statistics

- **Total:** 716 tests
- **Coverage:** 83% (target: 60%, achieved: 138% of target)
- **Timeout:** 600s (10 minutes) configured in `pyproject.toml`
- **Execution:** Supports parallel execution via pytest-xdist

### Distribution by Category

| Category      | Files | Description                              |
|--------------|-------|------------------------------------------|
| adapters     | 45    | Adapter domain and specific adapter tests |
| actions      | 11    | Action domain tests                      |
| runtime      | 11    | Runtime orchestration tests              |
| core         | 9     | Core resolution & lifecycle tests        |
| security     | 5     | Security hardening tests (100 tests)     |
| integration  | 5     | Cross-component integration tests        |
| remote       | 4     | Remote manifest loading tests            |
| domains      | 2     | Generic domain bridge tests              |
| cli          | 1     | CLI command tests                        |

## Test Execution Strategies

### 1. Fast CI Pipeline (< 2 minutes)
```bash
make test-not-slow
```
Skip slow tests for quick feedback in pull requests.

### 2. Development Workflow
```bash
# Quick iteration
make test-fast

# Module-specific
pytest tests/core/ -v

# Full pre-commit validation
python -m crackerjack -t
```

### 3. Full Test Suite (10 minutes)
```bash
make test
```

### 4. Performance Analysis
```bash
make test-analyze
```
Runs tests with timing analysis and generates recommendations for marking slow tests.

## Writing Tests

### Test Structure

```python
import pytest
from oneiric.core.resolution import Resolver

@pytest.mark.fast  # Mark fast tests
@pytest.mark.unit  # Mark unit tests
async def test_resolver_basic():
    """Test basic resolver functionality."""
    resolver = Resolver()
    # Test implementation
```

### When to Use Markers

- **fast**: Use for tests that complete in <1s
- **slow**: Use for tests that take >5s (integration, I/O-heavy)
- **unit**: Use for isolated tests with no external dependencies
- **integration**: Use for tests that exercise multiple components
- **security**: Use for security-focused tests
- **adapter/remote/runtime**: Use for domain-specific tests

### Async Tests

Use `pytest-asyncio` for async tests:

```python
import pytest

@pytest.mark.asyncio
async def test_async_operation():
    result = await some_async_function()
    assert result is not None
```

## Analyzing Test Performance

Use the timing analysis script to identify slow tests:

```bash
# Run tests and analyze timing
make test-analyze

# Or manually:
pytest --durations=0 --tb=no -q 2>&1 | tee test_output.txt
python scripts/analyze_test_timings.py test_output.txt
```

The script will:
- Show total test count and distribution
- List the 20 slowest tests
- Break down timing by module
- Estimate parallel execution time
- Suggest which tests should be marked as slow

## CI/CD Integration

### Pull Request Checks
```bash
make test-not-slow  # Fast feedback (~2 minutes)
```

### Pre-merge Validation
```bash
python -m crackerjack -t  # Full quality suite (~10 minutes)
```

### Nightly Builds
```bash
make test-all  # Comprehensive with timing analysis
```

### Release Validation
```bash
make test-coverage  # With HTML coverage report
```

## Troubleshooting

### Tests Timing Out

If tests are timing out:
1. Check `[tool.crackerjack]` in `pyproject.toml` - current timeout is 600s
2. Run `make test-analyze` to identify slow tests
3. Consider parallelizing with `pytest -n auto`

### Marker Warnings

If you see "Unknown marker" warnings, ensure markers are defined in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
markers = [
    "fast: Fast tests (<1s)",
    "slow: Slow tests (>5s)",
    # ... etc
]
```

### Coverage Issues

To investigate coverage gaps:

```bash
# Generate HTML coverage report
make test-coverage

# Open in browser
open htmlcov/index.html
```

## Resources

- **Test Configuration:** `pyproject.toml` (pytest section)
- **Crackerjack Config:** `pyproject.toml` ([tool.crackerjack])
- **Makefile Targets:** `Makefile` (test-* targets)
- **Analysis Script:** `scripts/analyze_test_timings.py`
- **Documentation:** `CLAUDE.md` (Testing section)
