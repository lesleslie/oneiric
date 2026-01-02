# MCP Server Migration Checklist Template

**Project Name:** [PROJECT_NAME]  
**Migration Lead:** [YOUR_NAME]  
**Target Completion:** [TARGET_DATE]  
**Status:** ⏳ Not Started | 🟡 In Progress | ✅ Completed | ❌ Blocked

---

## 📋 Migration Overview

### Project Details
- **Repository:** [REPO_PATH]
- **Current Version:** [CURRENT_VERSION]
- **Target Version:** [TARGET_VERSION]
- **Language:** [Python/Node.js]
- **Framework:** [FastMCP/Custom]
- **Complexity:** [Low/Medium/High]

### Key Contacts
- **Technical Lead:** [NAME]  
- **QA Lead:** [NAME]  
- **Documentation:** [NAME]  
- **Support:** [NAME]

---

## 🎯 Migration Phases

### Phase 1: Foundation & Planning ✅

**Objective:** Establish migration infrastructure and baseline

- [ ] ✅ Create project-specific migration plan
- [ ] ✅ Complete baseline audit (dependencies, tests, CLI)
- [ ] ✅ Create pre-migration rollback tag (`v1.0.0-pre-migration`)
- [ ] ✅ Document current CLI commands and Oneiric equivalents
- [ ] ✅ Establish test coverage baseline ([XX]%)
- [ ] ✅ Complete ACB removal inventory
- [ ] ✅ Document operational model (Crackerjack + Session-Buddy contract)
- [ ] ✅ Define compatibility contract (CLI, cache paths, health schema)

**Deliverables:**
- [ ] Baseline audit document
- [ ] CLI command mapping guide
- [ ] ACB removal inventory
- [ ] Test coverage baseline report

**Success Criteria:**
- [ ] All foundation tasks completed
- [ ] Rollback procedures defined
- [ ] Operational model documented

---

### Phase 2: Oneiric Integration Layer 🟡

**Objective:** Create common integration patterns and utilities

- [ ] Develop Oneiric CLI factory integration
- [ ] Create project-specific config class (`[Project]Config`)
- [ ] Implement standard lifecycle hooks (start, stop, health, status)
- [ ] Add runtime snapshot management
- [ ] Update HTTP client to Oneiric patterns
- [ ] Remove ACB dependencies
- [ ] Add health check endpoints
- [ ] Implement runtime cache management

**Deliverables:**
- [ ] Oneiric CLI factory implementation
- [ ] Configuration migration
- [ ] Lifecycle management integration
- [ ] Health check implementation

**Success Criteria:**
- [ ] Integration layer tested
- [ ] Oneiric patterns functional
- [ ] ACB dependencies removed

---

### Phase 3: Migration Implementation 🔄

**Objective:** Migrate to Oneiric runtime management

#### 3.1 Framework Migration
- [ ] Replace FastMCP with OneiricMCPServer
- [ ] Integrate Oneiric CLI factory
- [ ] Update server initialization
- [ ] Migrate tool registration

#### 3.2 Configuration Migration
- [ ] Create OneiricMCPConfig subclass
- [ ] Migrate environment variables
- [ ] Update configuration loading
- [ ] Add validation

#### 3.3 CLI Migration
- [ ] Implement `start` command
- [ ] Implement `stop` command
- [ ] Implement `restart` command
- [ ] Implement `status` command
- [ ] Implement `health` command
- [ ] Implement `health --probe` command

#### 3.4 Observability Migration
- [ ] Add runtime health snapshots
- [ ] Implement telemetry
- [ ] Add health check endpoints
- [ ] Remove custom dashboards

#### 3.5 ACB Removal
- [ ] Remove ACB imports
- [ ] Remove ACB dependency injection
- [ ] Remove ACB adapters
- [ ] Update HTTP client patterns
- [ ] Remove ACB from dependencies

**Deliverables:**
- [ ] Migrated server implementation
- [ ] Oneiric CLI integration
- [ ] Configuration migration
- [ ] Observability integration
- [ ] ACB removal complete

**Success Criteria:**
- [ ] All Oneiric patterns implemented
- [ ] CLI commands functional
- [ ] Configuration working
- [ ] Zero ACB dependencies

---

### Phase 4: Testing & Validation 🧪

**Objective:** Ensure migration quality and compatibility

#### 4.1 Test Coverage
- [ ] Maintain ≥[BASELINE]% test coverage
- [ ] Add Oneiric-specific tests
- [ ] Update existing tests for Oneiric patterns
- [ ] Add CLI command tests
- [ ] Add health check tests

#### 4.2 Integration Testing
- [ ] Test CLI commands
- [ ] Test runtime snapshots
- [ ] Test health schema compliance
- [ ] Test configuration loading
- [ ] Test lifecycle management

#### 4.3 Performance Testing
- [ ] Measure startup time (≤120% of baseline)
- [ ] Measure memory usage (≤110% of baseline)
- [ ] Measure response time (≤105% of baseline)
- [ ] Test under load

#### 4.4 Security Testing
- [ ] Security audit
- [ ] Dependency vulnerability scan
- [ ] Configuration security review
- [ ] API key handling verification

**Deliverables:**
- [ ] Test coverage report
- [ ] Integration test results
- [ ] Performance benchmark report
- [ ] Security audit report

**Success Criteria:**
- [ ] All tests passing
- [ ] Coverage ≥ baseline
- [ ] Performance metrics acceptable
- [ ] Security audit passed

---

### Phase 5: Rollout & Monitoring 🚀

**Objective:** Production deployment and monitoring

#### 5.1 Rollout Preparation
- [ ] Create rollout plan
- [ ] Implement feature flags (if needed)
- [ ] Set up monitoring and alerting
- [ ] Create rollback procedures

#### 5.2 Documentation
- [ ] Create user migration guide
- [ ] Update README with Oneiric instructions
- [ ] Update CLI command reference
- [ ] Add configuration examples
- [ ] Create troubleshooting guide

#### 5.3 User Communication
- [ ] Create announcement materials
- [ ] Set up support channels
- [ ] Plan migration workshops
- [ ] Create FAQ documentation

**Deliverables:**
- [ ] Rollout plan document
- [ ] User migration guide
- [ ] Updated documentation
- [ ] Monitoring setup
- [ ] Support documentation

**Success Criteria:**
- [ ] Rollout plan approved
- [ ] Documentation complete
- [ ] Monitoring operational
- [ ] Support channels ready

---

## 📊 Migration Progress Tracker

### Overall Progress
- **Total Tasks:** [TOTAL_TASKS]
- **Completed:** [COMPLETED]/[TOTAL_TASKS] ([PERCENT]%)
- **In Progress:** [IN_PROGRESS]
- **Pending:** [PENDING]
- **Blocked:** [BLOCKED]

### Phase Progress
- **Phase 1 (Foundation):** [X]/[Y] ([Z]%)
- **Phase 2 (Integration):** [X]/[Y] ([Z]%)
- **Phase 3 (Migration):** [X]/[Y] ([Z]%)
- **Phase 4 (Testing):** [X]/[Y] ([Z]%)
- **Phase 5 (Rollout):** [X]/[Y] ([Z]%)

### Critical Path Items
- [ ] ✅ Baseline audit completed
- [ ] ⏳ Oneiric CLI factory integration
- [ ] ⏳ ACB removal completed
- [ ] ⏳ Health check implementation
- [ ] ⏳ Test coverage maintained
- [ ] ⏳ User migration guide created

---

## 🔧 Technical Details

### CLI Command Mapping

| Old Command | New Command | Status |
|-------------|-------------|--------|
| `python -m [project]` | `[project]-mcp start` | ⏳ Pending |
| `[project] --start` | `[project]-mcp start` | ⏳ Pending |
| `[project] --stop` | `[project]-mcp stop` | ⏳ Pending |
| `[project] --status` | `[project]-mcp status` | ⏳ Pending |
| `[project] --health` | `[project]-mcp health` | ⏳ Pending |
| N/A | `[project]-mcp health --probe` | ⏳ New |

### Configuration Migration

**Before (Current):**
```python
# Environment variables
os.environ.get("API_KEY")

# Custom config class
class Config:
    http_port = 3039
```

**After (Oneiric):**
```python
from oneiric.core.config import OneiricMCPConfig
from pydantic import Field

class ProjectConfig(OneiricMCPConfig):
    http_port: int = Field(default=3039, env="PROJECT_HTTP_PORT")
    api_key: str = Field(..., env="PROJECT_API_KEY")

    class Config:
        env_prefix = "PROJECT_"
```

### Runtime Cache Structure

```
.oneiric_cache/
├── server.pid                  # PID file
├── runtime_health.json         # Health snapshot
└── runtime_telemetry.json      # Telemetry data
```

### Health Schema Compliance

**Required Schema:**
```python
from mcp_common.health import HealthStatus, ComponentHealth, HealthCheckResponse

HealthCheckResponse(
    status=HealthStatus.HEALTHY,  # HEALTHY|DEGRADED|UNHEALTHY
    components=[
        ComponentHealth(
            name="component_name",
            status=HealthStatus.HEALTHY,
            message="Human-readable status",
            latency_ms=120,
            metadata={...}
        )
    ],
    timestamp="ISO_8601_datetime"
)
```

---

## 🚨 Risk Assessment

### High Risk Areas
- **ACB Removal:** Complex dependency changes
- **CLI Migration:** User-facing command changes
- **Configuration:** Environment variable changes
- **Performance:** Potential regressions

### Mitigation Strategies
- **Feature Flags:** Gradual rollout
- **Rollback Procedures:** Tested rollback paths
- **Test Coverage:** Maintain baseline
- **Performance Testing:** Benchmark before/after

---

## ✅ Success Criteria

### Technical Success
- [ ] All ACB dependencies removed
- [ ] Oneiric CLI factory implemented
- [ ] Standardized lifecycle management
- [ ] Runtime cache files created
- [ ] Health schema compliance
- [ ] Test coverage ≥ baseline
- [ ] Performance metrics acceptable
- [ ] Security audit passed

### User Success
- [ ] Clear migration guide provided
- [ ] CLI command mapping documented
- [ ] Configuration migration examples
- [ ] Rollback procedures tested
- [ ] Support channels established

---

## 📅 Timeline

| Phase | Duration | Start Date | End Date |
|-------|----------|------------|----------|
| Phase 1 | 1 week | [START] | [END] |
| Phase 2 | 1 week | [START] | [END] |
| Phase 3 | 2 weeks | [START] | [END] |
| Phase 4 | 1 week | [START] | [END] |
| Phase 5 | 1 week | [START] | [END] |

---

## 📝 Notes & Issues

### Open Issues
- [ ] [Issue description] - [Owner] - [Status]
- [ ] [Issue description] - [Owner] - [Status]

### Decisions Made
- [ ] [Decision] - [Date] - [Rationale]
- [ ] [Decision] - [Date] - [Rationale]

### Lessons Learned
- [ ] [Lesson] - [Impact] - [Action]
- [ ] [Lesson] - [Impact] - [Action]

---

## 🔗 References

- **Migration Plan:** `MCP_SERVER_MIGRATION_PLAN.md`
- **Oneiric Documentation:** `oneiric/docs/`
- **Crackerjack Contract:** `crackerjack/docs/reference/BREAKING_CHANGES.md`
- **Session-Buddy Health:** `session-buddy/docs/reference/API_REFERENCE.md`

---

**Checklist Created:** [DATE]  
**Last Updated:** [DATE]  
**Status:** ⏳ Not Started | 🟡 In Progress | ✅ Completed | ❌ Blocked