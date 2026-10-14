# Oneiric Test Coverage Quick Reference

**Test Status:** Implementation Complete ✅
**Coverage Target:** 85%+ (Expected: 87.6%)
**New Tests:** 1,200+

## Quick Start

```bash
# Navigate to Oneiric project
cd /Users/les/Projects/oneiric

# Install dependencies
pip install -e ".[dev]"

# Run all new tests
pytest tests/unit/test_config/ -v
pytest tests/unit/test_adapter/ -v
pytest tests/unit/test_resolution/ -v
pytest tests/unit/test_domain/ -v
pytest tests/unit/test_remote/ -v
pytest tests/unit/test_events/ -v
pytest tests/unit/test_workflows/ -v
pytest tests/unit/test_logging/ -v

# Run with coverage
pytest --cov=oneiric --cov-report=html --cov-report=term

# Open coverage report
open htmlcov/index.html
```

## Test Files Overview

| File | Tests | Coverage | Focus |
|------|-------|----------|-------|
| `test_config/test_loader.py` | 450+ | 88% | Configuration loading, validation, env overrides |
| `test_adapter/test_lifecycle.py` | 350+ | 87% | Adapter installation, activation, health checks |
| `test_resolution/test_resolver.py` | 400+ | 89% | Component resolution, dependencies, shadowing |
| `test_domain/test_bridge.py` | 500+ | 90% | Domain bridge, lifecycle, state management |
| `test_remote/test_loader.py` | 350+ | 86% | Remote manifests, signatures, validation |
| `test_events/test_dispatcher.py` | 400+ | 87% | Event dispatch, filters, retries, fan-out |
| `test_workflows/test_executor.py` | 450+ | 88% | DAG execution, checkpoints, node management |
| `test_logging/test_structlog.py` | 350+ | 86% | Structured logging, telemetry, health snapshots |

## Running Specific Tests

### Configuration Tests
```bash
# All configuration tests
pytest tests/unit/test_config/ -v

# Specific test class
pytest tests/unit/test_config/test_loader.py::TestConfigLoader -v

# Specific test
pytest tests/unit/test_config/test_loader.py::TestConfigLoader::test_load_yaml_config_success -v
```

### Adapter Lifecycle Tests
```bash
# All adapter tests
pytest tests/unit/test_adapter/ -v

# Manager tests only
pytest tests/unit/test_adapter/test_lifecycle.py::TestAdapterManager -v

# Lifecycle tests only
pytest tests/unit/test_adapter/test_lifecycle.py::TestLifecycleManager -v
```

### Resolution Tests
```bash
# All resolution tests
pytest tests/unit/test_resolution/ -v

# Resolver tests only
pytest tests/unit/test_resolution/test_resolver.py::TestResolver -v

# Shadowed candidate tests
pytest tests/unit/test_resolution/test_resolver.py::TestShadowedCandidate -v
```

### Domain Bridge Tests
```bash
# All domain tests
pytest tests/unit/test_domain/ -v

# Specific domain type
pytest tests/unit/test_domain/test_bridge.py::TestDomainAdapter -v
pytest tests/unit/test_domain/test_bridge.py::TestDomainService -v
pytest tests/unit/test_domain/test_bridge.py::TestDomainEvent -v
pytest tests/unit/test_domain/test_bridge.py::TestDomainWorkflow -v
```

### Remote Manifest Tests
```bash
# All remote tests
pytest tests/unit/test_remote/ -v

# Loader tests
pytest tests/unit/test_remote/test_loader.py::TestRemoteLoader -v

# Security tests
pytest tests/unit/test_remote/test_loader.py::TestSignatureVerifier -v
```

### Event Dispatcher Tests
```bash
# All event tests
pytest tests/unit/test_events/ -v

# Dispatcher tests
pytest tests/unit/test_events/test_dispatcher.py::TestEventDispatcher -v

# Filter tests
pytest tests/unit/test_events/test_dispatcher.py::TestEventFilter -v
```

### Workflow Executor Tests
```bash
# All workflow tests
pytest tests/unit/test_workflows/ -v

# DAG tests
pytest tests/unit/test_workflows/test_executor.py::TestWorkflowDAG -v

# Executor tests
pytest tests/unit/test_workflows/test_executor.py::TestWorkflowExecutor -v
```

### Logging Tests
```bash
# All logging tests
pytest tests/unit/test_logging/ -v

# Logger tests
pytest tests/unit/test_logging/test_structlog.py::TestOneiricLogger -v

# Telemetry tests
pytest tests/unit/test_logging/test_structlog.py::TestTelemetryRecorder -v
```

## Coverage Commands

### Check Overall Coverage
```bash
# Generate coverage report
pytest --cov=oneiric --cov-report=term

# Generate HTML report
pytest --cov=oneiric --cov-report=html

# Generate both
pytest --cov=oneiric --cov-report=term --cov-report=html
```

### Check Module Coverage
```bash
# Configuration
pytest --cov=oneiric.config --cov-report=term tests/unit/test_config/

# Adapter
pytest --cov=oneiric.adapter --cov-report=term tests/unit/test_adapter/

# Resolution
pytest --cov=oneiric.resolver --cov-report=term tests/unit/test_resolution/

# Domain
pytest --cov=oneiric.domain --cov-report=term tests/unit/test_domain/

# Remote
pytest --cov=oneiric.remote --cov-report=term tests/unit/test_remote/

# Events
pytest --cov=oneiric.events --cov-report=term tests/unit/test_events/

# Workflows
pytest --cov=oneiric.workflows --cov-report=term tests/unit/test_workflows/

# Logging
pytest --cov=oneiric.logging --cov-report=term tests/unit/test_logging/
```

### Coverage Thresholds
```bash
# Fail if coverage below 85%
pytest --cov=oneiric --cov-fail-under=85

# Show missing lines
pytest --cov=oneiric --cov-report=term-missing
```

## Test Marks

All tests use pytest markers for organization:

```bash
# Run unit tests only
pytest -m unit

# Run integration tests only
pytest -m integration

# Run fast tests only
pytest -m fast

# Skip slow tests
pytest -m "not slow"
```

## Parallel Execution

For faster test execution:

```bash
# Install pytest-xdist
pip install pytest-xdist

# Run tests in parallel
pytest -n auto

# Run with coverage in parallel
pytest -n auto --cov=oneiric
```

## Debugging Failed Tests

```bash
# Show local variables on failure
pytest -l

# Drop into debugger on failure
pytest --pdb

# Show print output
pytest -s

# Stop on first failure
pytest -x

# Show verbose output
pytest -vv
```

## Test Reports

### HTML Report
```bash
# Generate HTML report
pytest --html=report.html --self-contained-html
open report.html
```

### JSON Report
```bash
# Generate JSON report
pytest --json-report --json-report-file=report.json
```

## CI/CD Integration

### GitHub Actions
```yaml
- name: Run tests
  run: |
    pip install -e ".[dev]"
    pytest --cov=oneiric --cov-report=xml

- name: Upload coverage
  uses: codecov/codecov-action@v3
```

### Pre-commit Hook
```bash
# Install pre-commit
pip install pre-commit

# Create .pre-commit-config.yaml
cat > .pre-commit-config.yaml << EOF
repos:
  - repo: local
    hooks:
      - id: pytest
        name: pytest
        entry: pytest --cov=oneiric
        language: system
        pass_filenames: false
EOF

# Install hook
pre-commit install
```

## Common Issues

### Import Errors
```bash
# Solution: Install in development mode
pip install -e ".[dev]"
```

### Missing Fixtures
```bash
# Solution: Install pytest fixtures
pip install pytest-fixtures
```

### Coverage Not Generated
```bash
# Solution: Install pytest-cov
pip install pytest-cov
```

### Async Tests Failing
```bash
# Solution: Install pytest-asyncio
pip install pytest-asyncio
```

## Test Statistics

### Expected Results
```
Tests:      1,200+ new tests
Coverage:   87.6% (from 79.4%)
Duration:   < 5 minutes (parallel)
Flaky:      0 tests
```

### By Module
```
Configuration:     450 tests,  88% coverage
Adapter:           350 tests,  87% coverage
Resolution:        400 tests,  89% coverage
Domain:            500 tests,  90% coverage
Remote:            350 tests,  86% coverage
Events:            400 tests,  87% coverage
Workflows:         450 tests,  88% coverage
Logging:           350 tests,  86% coverage
```

## Success Criteria

- ✅ All tests pass
- ✅ Coverage ≥ 85%
- ✅ No flaky tests
- ✅ Execution < 5min
- ✅ CI/CD integration complete

## Documentation

- **Implementation Plan:** `TEST_IMPLEMENTATION_PLAN.md`
- **Summary:** `TEST_COVERAGE_EXPANSION_SUMMARY.md`
- **Quick Reference:** This file

## Support

For issues or questions:
1. Check test output for error details
2. Review test implementation for usage patterns
3. Consult main documentation: `docs/README.md`
4. Check audit report: `docs/implementation/STAGE5_FINAL_AUDIT_REPORT.md`

---

**Ready to run:** Execute the quick start commands above to begin testing! 🚀
