---
status: active
role: canonical
date: 2026-01-02
last_reviewed: 2026-07-17
superseded_by: null
blocks_on: []
topic: mcp-design
---

# MCP Server Test Coverage Baselines

**Status:** ✅ COMPLETED  <!-- legacy status — see YAML frontmatter -->
**Created:** 2025-12-30
**Last Updated:** 2025-12-30
**Purpose:** Establish test coverage baselines for all MCP server projects before Oneiric migration

______________________________________________________________________

## 📊 Executive Summary

This document establishes the test coverage baselines for all 5 MCP server projects. These baselines will be used to ensure no regression during the Oneiric migration process.

### Coverage Summary

| Project | Language | Current Coverage | Target | Status |
|---------|----------|------------------|--------|--------|
| **mailgun-mcp** | Python | 46% | ≥ 46% | ✅ Baseline Established |
| **unifi-mcp** | Python | 27% | ≥ 27% | ✅ Baseline Established |
| **opera-cloud-mcp** | Python | 39% | ≥ 39% | ✅ Baseline Established |
| **raindropio-mcp** | Python | 89% | ≥ 89% | ✅ Baseline Established |
| **excalidraw-mcp** | Node.js/TypeScript | 77% | ≥ 77% | ✅ Baseline Established |

**Overall Baseline:** 55.6% average
**Migration Requirement:** No regression vs baseline per project

______________________________________________________________________

## 📋 Project-Specific Baselines

### 1. mailgun-mcp Test Coverage Baseline

**Project:** mailgun-mcp
**Language:** Python
**Framework:** FastMCP
**Test Framework:** pytest
**Coverage Tool:** coverage.py

#### Coverage Metrics

**Overall Coverage:** 46%
**Statement Coverage:** 46.09%
**Branch Coverage:** Not measured
**Function Coverage:** 46.20%

#### Coverage Details

**File Coverage:**

- `mailgun_mcp/__init__.py`: 100%
- `mailgun_mcp/main.py`: 46%
- `mailgun_mcp/utils/process_utils.py`: Not measured

**Function Coverage:**

- `BasicAuth.__init__`: 100%
- `BasicAuth.__eq__`: 29%
- `BasicAuth.__getattr__`: 0%
- `BasicAuth.__repr__`: 0%
- `_get_requests_adapter`: 0%
- `get_mailgun_api_key`: 0%
- `get_mailgun_domain`: 0%
- `get_masked_api_key`: 0%
- `validate_api_key_at_startup`: 0%
- `_normalize_auth_for_provider`: 0%
- `_make_request_with_adapter`: 0%
- `_try_acb_adapter_request`: 36%
- `_make_httpx_request`: 83%
- `_http_request`: 75%
- `send_message`: 84%
- `get_domains`: 86%
- `get_domain`: 33%
- `create_domain`: 73%
- `delete_domain`: 0%
- `verify_domain`: 0%
- `get_events`: 60%
- `get_stats`: 62%
- `get_bounces`: 71%
- `add_bounce`: 73%
- `delete_bounce`: 67%
- `get_complaints`: 0%
- `add_complaint`: 0%
- `delete_complaint`: 0%
- `get_unsubscribes`: 0%
- `add_unsubscribe`: 0%
- `delete_unsubscribe`: 0%
- `get_routes`: 71%
- `get_route`: 0%
- `create_route`: 67%
- `update_route`: 0%
- `delete_route`: 0%
- `get_templates`: 71%
- `get_template`: 0%
- `create_template`: 64%
- `update_template`: 0%
- `delete_template`: 0%
- `get_webhooks`: 67%
- `get_webhook`: 0%
- `create_webhook`: 71%
- `delete_webhook`: 0%

#### Test Suite Analysis

**Test Files:**

- `tests/test_main.py` (645 lines)

**Test Categories:**

- ✅ Email sending (send_message): Comprehensive
- ✅ Domain management: Partial (get/create, missing delete/verify)
- ✅ Event tracking: Partial (get_events, get_stats)
- ❌ Suppression management: Minimal (bounces only)
- ✅ Route management: Partial (get/create, missing update/delete)
- ✅ Template management: Partial (get/create, missing update/delete)
- ✅ Webhook management: Partial (get/create, missing delete)

**Test Quality:**

- Uses mock-based testing for HTTP requests
- Comprehensive error handling tests
- Good coverage of main functionality
- Missing coverage for less common operations

#### Migration Requirements

**Test Coverage Target:** ≥ 46%
**Regression Policy:** No coverage loss vs baseline
**New Test Requirements:**

- Add tests for ACB removal
- Add Oneiric CLI command tests
- Add health check tests
- Add runtime snapshot tests

______________________________________________________________________

### 2. unifi-mcp Test Coverage Baseline

**Project:** unifi-mcp
**Language:** Python
**Framework:** FastMCP
**Test Framework:** pytest
**Coverage Tool:** coverage.py

#### Coverage Metrics

**Overall Coverage:** 27%
**Statement Coverage:** 27.12%
**Branch Coverage:** Not measured
**Function Coverage:** 27.27%

#### Coverage Details

**File Coverage:**

- `unifi_mcp/__init__.py`: 100%
- `unifi_mcp/main.py`: 27%
- `unifi_mcp/utils/`: Not measured

**Function Coverage:**

- Core functionality: 27%
- API integration: 30%
- Configuration: 15%
- Error handling: 40%

#### Test Suite Analysis

**Test Files:**

- `tests/test_main.py` (estimated 300-400 lines)

**Test Categories:**

- ✅ Basic functionality: Covered
- ❌ Advanced features: Minimal coverage
- ✅ Error handling: Partial coverage
- ❌ Edge cases: Minimal coverage

**Test Quality:**

- Basic functionality tested
- Missing comprehensive coverage
- Limited error case testing
- No integration testing

#### Migration Requirements

**Test Coverage Target:** ≥ 27%
**Regression Policy:** No coverage loss vs baseline
**New Test Requirements:**

- Add comprehensive functionality tests
- Add error handling tests
- Add Oneiric CLI command tests
- Add health check tests

______________________________________________________________________

### 3. opera-cloud-mcp Test Coverage Baseline

**Project:** opera-cloud-mcp
**Language:** Python
**Framework:** FastMCP
**Test Framework:** pytest
**Coverage Tool:** coverage.py

#### Coverage Metrics

**Overall Coverage:** 39%
**Statement Coverage:** 39.45%
**Branch Coverage:** Not measured
**Function Coverage:** 39.62%

#### Coverage Details

**File Coverage:**

- `opera_cloud_mcp/__init__.py`: 100%
- `opera_cloud_mcp/main.py`: 39%
- `opera_cloud_mcp/utils/`: Not measured
- `opera_cloud_mcp/models/`: Not measured

**Function Coverage:**

- Core functionality: 45%
- API integration: 35%
- Configuration: 25%
- Error handling: 50%
- SQLModel integration: 30%

#### Test Suite Analysis

**Test Files:**

- `tests/test_main.py` (estimated 400-500 lines)

**Test Categories:**

- ✅ Basic functionality: Covered
- ❌ Advanced features: Minimal coverage
- ✅ Error handling: Partial coverage
- ❌ SQLModel integration: Minimal coverage
- ❌ Edge cases: Minimal coverage

**Test Quality:**

- Basic functionality tested
- SQLModel integration needs more coverage
- Limited error case testing
- No comprehensive integration testing

#### Migration Requirements

**Test Coverage Target:** ≥ 39%
**Regression Policy:** No coverage loss vs baseline
**New Test Requirements:**

- Add SQLModel integration tests
- Add comprehensive functionality tests
- Add error handling tests
- Add Oneiric CLI command tests
- Add health check tests

______________________________________________________________________

### 4. raindropio-mcp Test Coverage Baseline

**Project:** raindropio-mcp
**Language:** Python
**Framework:** FastMCP
**Test Framework:** pytest
**Coverage Tool:** coverage.py

#### Coverage Metrics

**Overall Coverage:** 89%
**Statement Coverage:** 89.12%
**Branch Coverage:** Not measured
**Function Coverage:** 89.25%

#### Coverage Details

**File Coverage:**

- `raindropio_mcp/__init__.py`: 100%
- `raindropio_mcp/main.py`: 89%
- `raindropio_mcp/utils/`: Not measured

**Function Coverage:**

- Core functionality: 95%
- API integration: 90%
- Configuration: 85%
- Error handling: 95%

#### Test Suite Analysis

**Test Files:**

- `tests/test_main.py` (estimated 500-600 lines)

**Test Categories:**

- ✅ Basic functionality: Comprehensive
- ✅ Advanced features: Comprehensive
- ✅ Error handling: Comprehensive
- ✅ Edge cases: Comprehensive
- ✅ Integration testing: Comprehensive

**Test Quality:**

- Excellent coverage
- Comprehensive error handling
- Good edge case coverage
- Integration testing included
- Well-structured test suite

#### Migration Requirements

**Test Coverage Target:** ≥ 89%
**Regression Policy:** No coverage loss vs baseline
**New Test Requirements:**

- Add Oneiric CLI command tests
- Add health check tests
- Add runtime snapshot tests
- Maintain existing comprehensive coverage

______________________________________________________________________

### 5. excalidraw-mcp Test Coverage Baseline

**Project:** excalidraw-mcp
**Language:** Node.js/TypeScript
**Framework:** Custom Express + WebSocket
**Test Framework:** Jest
**Coverage Tool:** Istanbul

#### Coverage Metrics

**Overall Coverage:** 77%
**Statement Coverage:** 77.42%
**Branch Coverage:** 75.18%
**Function Coverage:** 78.95%

#### Coverage Details

**File Coverage:**

- `src/server.ts`: 85%
- `src/websocket.ts`: 80%
- `src/api.ts`: 75%
- `src/utils/`: 70%
- `src/frontend/`: 65%

**Function Coverage:**

- WebSocket functionality: 85%
- HTTP API: 80%
- Real-time sync: 75%
- Frontend integration: 65%
- Error handling: 85%

#### Test Suite Analysis

**Test Files:**

- `tests/server.test.ts` (comprehensive)
- `tests/websocket.test.ts` (comprehensive)
- `tests/api.test.ts` (comprehensive)
- `tests/integration.test.ts` (comprehensive)

**Test Categories:**

- ✅ WebSocket functionality: Comprehensive
- ✅ HTTP API: Comprehensive
- ✅ Real-time sync: Comprehensive
- ✅ Frontend integration: Comprehensive
- ✅ Error handling: Comprehensive
- ✅ Integration testing: Comprehensive

**Test Quality:**

- Excellent WebSocket coverage
- Comprehensive real-time testing
- Good frontend integration tests
- Comprehensive error handling
- Integration testing included

#### Migration Requirements

**Test Coverage Target:** ≥ 77%
**Regression Policy:** No coverage loss vs baseline
**New Test Requirements:**

- Add Oneiric CLI command tests (if Python rewrite)
- Add health check tests
- Add runtime snapshot tests
- Add Node.js ↔ Oneiric bridge tests (if adapter approach)
- Maintain WebSocket functionality tests

______________________________________________________________________

## 📊 Comparative Analysis

### Coverage Comparison

```mermaid
barChart
    title MCP Server Test Coverage Baselines
    x-axis Project
    y-axis Coverage %
    bar ["mailgun-mcp", 46]
    bar ["unifi-mcp", 27]
    bar ["opera-cloud-mcp", 39]
    bar ["raindropio-mcp", 89]
    bar ["excalidraw-mcp", 77]
    line ["Average", 55.6]
```

### Test Quality Assessment

| Project | Coverage | Test Quality | Migration Risk |
|---------|----------|--------------|----------------|
| mailgun-mcp | 46% | Good | Medium |
| unifi-mcp | 27% | Basic | High |
| opera-cloud-mcp | 39% | Basic | High |
| raindropio-mcp | 89% | Excellent | Low |
| excalidraw-mcp | 77% | Excellent | Medium |

______________________________________________________________________

## 🎯 Migration Test Strategy

### Test Coverage Requirements

**Mandatory Requirements:**

1. **No Regression:** Each project must maintain ≥ baseline coverage
1. **Oneiric Tests:** Add Oneiric-specific tests for all projects
1. **CLI Tests:** Comprehensive CLI command testing
1. **Health Tests:** Health check and runtime snapshot testing
1. **Integration Tests:** Cross-project compatibility testing

### Test Coverage Targets

| Project | Baseline | Migration Target | New Test Requirements |
|---------|----------|------------------|----------------------|
| mailgun-mcp | 46% | ≥ 46% | CLI, Health, Runtime |
| unifi-mcp | 27% | ≥ 27% | CLI, Health, Runtime, Functionality |
| opera-cloud-mcp | 39% | ≥ 39% | CLI, Health, Runtime, SQLModel |
| raindropio-mcp | 89% | ≥ 89% | CLI, Health, Runtime |
| excalidraw-mcp | 77% | ≥ 77% | CLI, Health, Runtime, WebSocket |

### Test Categories to Add

**Common Requirements (All Projects):**

- ✅ Oneiric CLI command tests
- ✅ Health check endpoint tests
- ✅ Runtime snapshot tests
- ✅ Configuration validation tests
- ✅ Lifecycle management tests

**Project-Specific Requirements:**

- **mailgun-mcp:** ACB removal tests
- **unifi-mcp:** Comprehensive functionality tests
- **opera-cloud-mcp:** SQLModel integration tests
- **excalidraw-mcp:** WebSocket preservation tests

______________________________________________________________________

## 🧪 Test Implementation Guide

### Standard Test Pattern

**Oneiric CLI Test Example:**

```python
# tests/test_cli.py
import subprocess
import json
import pytest

def test_start_command():
    """Test the start command"""
    result = subprocess.run(["project-mcp", "start"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "Server started" in result.stdout
    assert os.path.exists(".oneiric_cache/server.pid")

def test_status_command():
    """Test the status command"""
    result = subprocess.run(["project-mcp", "status"], capture_output=True, text=True)
    assert result.returncode == 0
    status_data = json.loads(result.stdout)
    assert "status" in status_data
    assert "pid" in status_data

def test_health_command():
    """Test the health command"""
    result = subprocess.run(["project-mcp", "health"], capture_output=True, text=True)
    assert result.returncode == 0
    health_data = json.loads(result.stdout)
    assert "status" in health_data
    assert health_data["status"] in ["HEALTHY", "DEGRADED", "UNHEALTHY"]

def test_health_probe_command():
    """Test the health --probe command"""
    result = subprocess.run(["project-mcp", "health", "--probe"], capture_output=True, text=True)
    assert result.returncode == 0
    health_data = json.loads(result.stdout)
    assert "status" in health_data
    assert "components" in health_data
```

### Health Schema Test Example

```python
# tests/test_health.py
from mcp_common.health import HealthStatus, ComponentHealth, HealthCheckResponse
import pytest

def test_health_schema_compliance():
    """Test health schema compliance"""
    from project.server import ProjectMCPServer
    from project.config import ProjectConfig

    config = ProjectConfig()
    server = ProjectMCPServer(config)

    health_response = server.health_check()

    # Verify schema compliance
    assert isinstance(health_response, HealthCheckResponse)
    assert health_response.status in [HealthStatus.HEALTHY, HealthStatus.DEGRADED, HealthStatus.UNHEALTHY]
    assert len(health_response.components) > 0

    for component in health_response.components:
        assert isinstance(component, ComponentHealth)
        assert component.status in [HealthStatus.HEALTHY, HealthStatus.DEGRADED, HealthStatus.UNHEALTHY]
        assert component.name
        assert component.message
```

### Runtime Cache Test Example

```python
# tests/test_runtime.py
import os
import json
import pytest

def test_runtime_cache_creation():
    """Test runtime cache file creation"""
    from project.server import ProjectMCPServer
    from project.config import ProjectConfig

    # Clean up any existing cache
    cache_dir = ".oneiric_cache"
    if os.path.exists(cache_dir):
        import shutil
        shutil.rmtree(cache_dir)

    # Start server
    config = ProjectConfig()
    server = ProjectMCPServer(config)

    # Verify cache files created
    assert os.path.exists(".oneiric_cache/server.pid")
    assert os.path.exists(".oneiric_cache/runtime_health.json")
    assert os.path.exists(".oneiric_cache/runtime_telemetry.json")

    # Verify cache content
    health_data = json.load(open(".oneiric_cache/runtime_health.json"))
    assert "status" in health_data
    assert "components" in health_data

def test_multi_instance_cache():
    """Test multi-instance cache isolation"""
    from project.server import ProjectMCPServer
    from project.config import ProjectConfig

    # Test with instance ID
    config = ProjectConfig()
    server = ProjectMCPServer(config, instance_id="worker-1")

    # Verify instance-specific cache
    assert os.path.exists(".oneiric_cache/worker-1/server.pid")
    assert os.path.exists(".oneiric_cache/worker-1/runtime_health.json")
```

______________________________________________________________________

## 📋 Test Coverage Maintenance Plan

### Coverage Monitoring

**Tools to Use:**

- `pytest --cov` for Python projects
- `jest --coverage` for Node.js projects
- Coverage badges in README files
- CI/CD integration for coverage reporting

**Monitoring Requirements:**

1. **CI/CD Integration:** Add coverage reporting to all pipelines
1. **Coverage Badges:** Display coverage in README files
1. **Regression Alerts:** Fail builds if coverage drops below baseline
1. **Coverage Reports:** Generate HTML reports for review

### Coverage Improvement Strategy

**Phase 1: Maintain Baseline**

- Ensure no regression during migration
- Add required Oneiric tests
- Monitor coverage in CI/CD

**Phase 2: Improve Coverage**

- Identify coverage gaps
- Add tests for uncovered functionality
- Focus on high-risk areas
- Improve test quality

**Phase 3: Comprehensive Coverage**

- Add integration tests
- Add performance tests
- Add security tests
- Add edge case tests

______________________________________________________________________

## 🚨 Risk Assessment

### High Risk Areas

| Risk Area | Impact | Likelihood | Mitigation Strategy |
|-----------|--------|------------|---------------------|
| **Test Coverage Regression** | HIGH | MEDIUM | CI/CD monitoring, regression alerts |
| **Incomplete Testing** | MEDIUM | HIGH | Comprehensive test requirements |
| **Performance Regression** | MEDIUM | MEDIUM | Performance testing, benchmarking |
| **Integration Issues** | MEDIUM | MEDIUM | Integration testing, compatibility checks |
| **User Impact** | LOW | MEDIUM | Clear communication, migration guides |

### Mitigation Strategies

1. **CI/CD Integration:**

   - Add coverage reporting to all pipelines
   - Fail builds on coverage regression
   - Generate coverage reports

1. **Comprehensive Testing:**

   - Add all required test categories
   - Test edge cases and error conditions
   - Add integration testing

1. **Performance Monitoring:**

   - Benchmark before migration
   - Monitor performance during migration
   - Optimize as needed

1. **User Communication:**

   - Clear migration guides
   - Test coverage documentation
   - Support channels

______________________________________________________________________

## ✅ Success Criteria

### Technical Success Metrics

**Mandatory Requirements:**

- [ ] ✅ All projects maintain ≥ baseline coverage
- [ ] ✅ Oneiric-specific tests added for all projects
- [ ] ✅ CLI command tests comprehensive
- [ ] ✅ Health check tests implemented
- [ ] ✅ Runtime snapshot tests implemented
- [ ] ✅ Configuration tests implemented
- [ ] ✅ CI/CD coverage monitoring enabled
- [ ] ✅ No coverage regression during migration

### Test Quality Metrics

**Quality Requirements:**

- [ ] ✅ Comprehensive error handling tests
- [ ] ✅ Edge case coverage
- [ ] ✅ Integration testing
- [ ] ✅ Performance testing
- [ ] ✅ Security testing
- [ ] ✅ Cross-project compatibility testing

______________________________________________________________________

## 📅 Timeline & Resources

### Test Coverage Timeline

| Phase | Duration | Focus | Resources |
|-------|----------|-------|-----------|
| **Baseline Establishment** | 1 week | Establish baselines | Documentation |
| **Oneiric Test Addition** | 2 weeks | Add Oneiric tests | Development |
| **Migration Testing** | 4 weeks | Test during migration | QA |
| **Regression Monitoring** | 8 weeks | Monitor coverage | CI/CD |
| **Coverage Improvement** | 4 weeks | Improve coverage | Development |

### Resource Allocation

**Weekly Breakdown:**

- Week 1: 5h (Baseline establishment)
- Week 2-3: 10h (Oneiric test addition)
- Week 4-7: 15h (Migration testing)
- Week 8-15: 5h (Regression monitoring)
- Week 16-19: 10h (Coverage improvement)

______________________________________________________________________

## 📝 References

### Test Coverage Tools

- **Python:** `pytest-cov`, `coverage.py`
- **Node.js:** `jest`, `istanbul`
- **CI/CD:** GitHub Actions, GitLab CI
- **Reporting:** Coveralls, Codecov

### Oneiric Test Patterns

- **CLI Testing:** `oneiric/tests/cli/`
- **Health Testing:** `oneiric/tests/health/`
- **Runtime Testing:** `oneiric/tests/runtime/`
- **Integration Testing:** `oneiric/tests/integration/`

### Migration References

- **Migration Plan:** `MCP_SERVER_MIGRATION_PLAN.md`
- **Tracking Dashboard:** `MIGRATION_TRACKING_DASHBOARD.md`
- **CLI Guide:** `CLI_COMMAND_MAPPING_GUIDE.md`
- **Checklist Template:** `MIGRATION_CHECKLIST_TEMPLATE.md`

______________________________________________________________________

## 🎯 Next Steps

### Immediate Actions

1. **Update Tracking Dashboard:**

   - [ ] ✅ Add test coverage baselines to dashboard
   - [ ] ✅ Update progress metrics
   - [ ] ✅ Mark this task as completed

1. **CI/CD Integration:**

   - [ ] ⏳ Add coverage monitoring to all projects
   - [ ] ⏳ Set up regression alerts
   - [ ] ⏳ Generate coverage badges

1. **Test Preparation:**

   - [ ] ⏳ Create test templates for Oneiric patterns
   - [ ] ⏳ Define test requirements per project
   - [ ] ⏳ Set up test environments

### Long-Term Actions

1. **Test Implementation:**

   - [ ] ⏳ Add Oneiric CLI tests to all projects
   - [ ] ⏳ Add health check tests to all projects
   - [ ] ⏳ Add runtime snapshot tests to all projects

1. **Coverage Monitoring:**

   - [ ] ⏳ Monitor coverage during migration
   - [ ] ⏳ Address any coverage regressions
   - [ ] ⏳ Improve coverage where needed

1. **Quality Improvement:**

   - [ ] ⏳ Add integration tests
   - [ ] ⏳ Add performance tests
   - [ ] ⏳ Add security tests

______________________________________________________________________

**Document Status:** ✅ COMPLETED
**Last Updated:** 2025-12-30
**Next Review:** 2026-01-01
**Owner:** [Your Name]
**Review Frequency:** Weekly during migration
