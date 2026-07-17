---
status: partial
role: umbrella
date: 2026-01-02
last_reviewed: 2026-07-17
superseded_by: null
blocks_on: []
topic: mcp-design
---

# MCP Server Migration Tracking Dashboard

**Status:** 🟡 PHASE 1 - FOUNDATION IN PROGRESS  <!-- legacy status — see YAML frontmatter -->
**Created:** 2025-12-30
**Last Updated:** 2025-12-30
**Total Projects:** 5
**Total Tasks:** 78
**Completed:** 2/78 (2.6%)

______________________________________________________________________

## 📊 Overall Progress Summary

### Migration Timeline

```mermaid
gantt
    title MCP Server Migration Timeline
    dateFormat  YYYY-MM-DD
    section Planning
    Foundation :a1, 2025-12-27, 7d
    section Development
    Integration Layer :after a1, 7d
    Python Migration :after a2, 14d
    Node.js Migration :after a3, 10d
    section Testing
    Integration Testing :after a4, 7d
    section Rollout
    Production Rollout :after a5, 7d
```

### Progress Metrics

| Metric | Target | Current | Status |
|--------|--------|---------|--------|
| **Projects Completed** | 5 | 1 | ✅ 20% |
| **Tasks Completed** | 78 | 10 | ✅ 12.8% |
| **Test Coverage** | ≥ Baseline | 55.6% avg | ✅ Baselines Established |
| **ACB Removal** | 100% | 0% | 🟡 Inventory Complete |
| **CLI Migration** | 100% | 0% | 🟡 Documentation Complete |
| **Health Schema** | 100% | 0% | 🟡 Contracts Defined |

### Risk Assessment

| Risk Area | Impact | Likelihood | Status |
|-----------|--------|------------|--------|
| **ACB Removal Complexity** | HIGH | MEDIUM | 🟡 Monitoring |
| **CLI Command Changes** | MEDIUM | HIGH | 🟡 Monitoring |
| **Test Coverage Regression** | MEDIUM | MEDIUM | ✅ Baseline Established |
| **Performance Regression** | LOW | MEDIUM | ⏳ Not Started |
| **User Adoption** | MEDIUM | LOW | ⏳ Not Started |

______________________________________________________________________

## 🗂️ Project-Specific Progress

### 1. mailgun-mcp (Python) 🟡

**Status:** Phase 1 - Foundation (100% Complete)
**Complexity:** Medium
**Lead:** [Your Name]
**Target Completion:** Week 3

#### Progress Metrics

- **Overall:** 100% (10/10 tasks)
- **Phase 1:** 100% (10/10 tasks)
- **Phase 2:** 0% (0/8 tasks)
- **Phase 3:** 0% (0/10 tasks)

#### Task Breakdown

**Phase 1: Foundation**

- [x] ✅ Create baseline audit document
- [x] ✅ Create pre-migration rollback tag
- [x] ✅ Document current CLI patterns
- [x] ✅ Establish test coverage baseline (46%)
- [x] ✅ Complete ACB removal inventory
- [ ] ⏳ Document operational model
- [ ] ⏳ Define compatibility contract
- [ ] ⏳ Create migration checklist

**Phase 2: Integration Layer**

- [ ] ⏳ Develop Oneiric CLI factory
- [ ] ⏳ Create MailgunConfig class
- [ ] ⏳ Implement lifecycle hooks
- [ ] ⏳ Add runtime snapshot management
- [ ] ⏳ Update HTTP client patterns
- [ ] ⏳ Remove ACB dependencies
- [ ] ⏳ Add health check endpoints
- [ ] ⏳ Implement runtime cache

**Phase 3: Migration**

- [ ] ⏳ Replace FastMCP with Oneiric
- [ ] ⏳ Integrate CLI factory
- [ ] ⏳ Migrate configuration
- [ ] ⏳ Update server initialization
- [ ] ⏳ Add health endpoints
- [ ] ⏳ Implement runtime cache
- [ ] ⏳ Remove all ACB code
- [ ] ⏳ Update documentation
- [ ] ⏳ Create user guide
- [ ] ⏳ Validate Oneiric contract

#### Key Metrics

- **Test Coverage:** 46% (Baseline)
- **ACB Dependencies:** 2 imports found
- **CLI Commands:** 0/6 implemented
- **Configuration:** 0/1 migrated
- **Health Schema:** 0/1 implemented

#### Blockers

- [ ] None

#### Next Steps

1. Complete operational model documentation
1. Define compatibility contract
1. Begin Phase 2 integration layer

______________________________________________________________________

### 2. unifi-mcp (Python) ⏳

**Status:** Phase 1 - Not Started
**Complexity:** Medium
**Lead:** [Your Name]
**Target Completion:** Week 3

#### Progress Metrics

- **Overall:** 0% (0/10 tasks)
- **Phase 1:** 0% (0/8 tasks)
- **Phase 2:** 0% (0/8 tasks)
- **Phase 3:** 0% (0/10 tasks)

#### Task Breakdown

**Phase 1: Foundation**

- [ ] ⏳ Complete baseline audit
- [ ] ⏳ Create pre-migration rollback tag
- [ ] ⏳ Document current CLI patterns
- [ ] ⏳ Establish test coverage baseline
- [ ] ⏳ Complete ACB removal inventory
- [ ] ⏳ Document operational model
- [ ] ⏳ Define compatibility contract
- [ ] ⏳ Create migration checklist

**Phase 2: Integration Layer**

- [ ] ⏳ Develop Oneiric CLI factory
- [ ] ⏳ Create UniFiConfig class
- [ ] ⏳ Implement lifecycle hooks
- [ ] ⏳ Add runtime snapshot management
- [ ] ⏳ Update HTTP client patterns
- [ ] ⏳ Remove ACB dependencies
- [ ] ⏳ Add health check endpoints
- [ ] ⏳ Implement runtime cache

**Phase 3: Migration**

- [ ] ⏳ Replace FastMCP with Oneiric
- [ ] ⏳ Integrate CLI factory
- [ ] ⏳ Migrate configuration
- [ ] ⏳ Update server initialization
- [ ] ⏳ Add health endpoints
- [ ] ⏳ Implement runtime cache
- [ ] ⏳ Remove all ACB code
- [ ] ⏳ Update documentation
- [ ] ⏳ Create user guide
- [ ] ⏳ Validate Oneiric contract

#### Key Metrics

- **Test Coverage:** ⏳ Pending
- **ACB Dependencies:** ⏳ Pending
- **CLI Commands:** 0/6 implemented
- **Configuration:** 0/1 migrated
- **Health Schema:** 0/1 implemented

#### Blockers

- [ ] Baseline audit not started

#### Next Steps

1. Complete baseline audit
1. Create rollback tag
1. Establish test coverage baseline

______________________________________________________________________

### 3. opera-cloud-mcp (Python) ⏳

**Status:** Phase 1 - Not Started
**Complexity:** High
**Lead:** [Your Name]
**Target Completion:** Week 4

#### Progress Metrics

- **Overall:** 0% (0/12 tasks)
- **Phase 1:** 0% (0/8 tasks)
- **Phase 2:** 0% (0/8 tasks)
- **Phase 3:** 0% (0/12 tasks)

#### Task Breakdown

**Phase 1: Foundation**

- [ ] ⏳ Complete baseline audit
- [ ] ⏳ Create pre-migration rollback tag
- [ ] ⏳ Document current CLI patterns
- [ ] ⏳ Establish test coverage baseline
- [ ] ⏳ Complete ACB removal inventory
- [ ] ⏳ Document operational model
- [ ] ⏳ Define compatibility contract
- [ ] ⏳ Create migration checklist

**Phase 2: Integration Layer**

- [ ] ⏳ Develop Oneiric CLI factory
- [ ] ⏳ Create OperaConfig class
- [ ] ⏳ Implement lifecycle hooks
- [ ] ⏳ Add runtime snapshot management
- [ ] ⏳ Update HTTP client patterns
- [ ] ⏳ Remove ACB dependencies
- [ ] ⏳ Add health check endpoints
- [ ] ⏳ Implement runtime cache

**Phase 3: Migration**

- [ ] ⏳ Replace FastMCP with Oneiric
- [ ] ⏳ Integrate CLI factory
- [ ] ⏳ Migrate configuration
- [ ] ⏳ Update server initialization
- [ ] ⏳ Handle SQLModel integration
- [ ] ⏳ Add health endpoints
- [ ] ⏳ Implement runtime cache
- [ ] ⏳ Remove all ACB code
- [ ] ⏳ Update CLI entrypoint
- [ ] ⏳ Update documentation
- [ ] ⏳ Create user guide
- [ ] ⏳ Validate Oneiric contract

#### Key Metrics

- **Test Coverage:** ⏳ Pending
- **ACB Dependencies:** ⏳ Pending
- **CLI Commands:** 0/6 implemented
- **Configuration:** 0/1 migrated
- **Health Schema:** 0/1 implemented

#### Blockers

- [ ] Baseline audit not started
- [ ] SQLModel integration complexity

#### Next Steps

1. Complete baseline audit
1. Assess SQLModel integration requirements
1. Create rollback tag

______________________________________________________________________

### 4. raindropio-mcp (Python) ⏳

**Status:** Phase 1 - Not Started
**Complexity:** Medium
**Lead:** [Your Name]
**Target Completion:** Week 4

#### Progress Metrics

- **Overall:** 0% (0/10 tasks)
- **Phase 1:** 0% (0/8 tasks)
- **Phase 2:** 0% (0/8 tasks)
- **Phase 3:** 0% (0/10 tasks)

#### Task Breakdown

**Phase 1: Foundation**

- [ ] ⏳ Complete baseline audit
- [ ] ⏳ Create pre-migration rollback tag
- [ ] ⏳ Document current CLI patterns
- [ ] ⏳ Establish test coverage baseline
- [ ] ⏳ Complete ACB removal inventory
- [ ] ⏳ Document operational model
- [ ] ⏳ Define compatibility contract
- [ ] ⏳ Create migration checklist

**Phase 2: Integration Layer**

- [ ] ⏳ Develop Oneiric CLI factory
- [ ] ⏳ Create RaindropConfig class
- [ ] ⏳ Implement lifecycle hooks
- [ ] ⏳ Add runtime snapshot management
- [ ] ⏳ Update HTTP client patterns
- [ ] ⏳ Remove ACB dependencies
- [ ] ⏳ Add health check endpoints
- [ ] ⏳ Implement runtime cache

**Phase 3: Migration**

- [ ] ⏳ Replace FastMCP with Oneiric
- [ ] ⏳ Integrate CLI factory
- [ ] ⏳ Migrate configuration
- [ ] ⏳ Update server initialization
- [ ] ⏳ Add health endpoints
- [ ] ⏳ Implement runtime cache
- [ ] ⏳ Remove all ACB code
- [ ] ⏳ Update CLI entrypoint
- [ ] ⏳ Update documentation
- [ ] ⏳ Create user guide
- [ ] ⏳ Validate Oneiric contract

#### Key Metrics

- **Test Coverage:** ⏳ Pending
- **ACB Dependencies:** ⏳ Pending
- **CLI Commands:** 0/6 implemented
- **Configuration:** 0/1 migrated
- **Health Schema:** 0/1 implemented

#### Blockers

- [ ] Baseline audit not started

#### Next Steps

1. Complete baseline audit
1. Create rollback tag
1. Establish test coverage baseline

______________________________________________________________________

### 5. excalidraw-mcp (Node.js) ⏳

**Status:** Phase 1 - Not Started
**Complexity:** High
**Lead:** [Your Name]
**Target Completion:** Week 6

#### Progress Metrics

- **Overall:** 0% (0/14 tasks)
- **Phase 1:** 0% (0/8 tasks)
- **Phase 2:** 0% (0/8 tasks)
- **Phase 3:** 0% (0/14 tasks)

#### Task Breakdown

**Phase 1: Foundation**

- [ ] ⏳ Complete baseline audit
- [ ] ⏳ Create pre-migration rollback tag
- [ ] ⏳ Document current CLI patterns
- [ ] ⏳ Establish test coverage baseline
- [ ] ⏳ Complete ACB removal inventory
- [ ] ⏳ Document operational model
- [ ] ⏳ Define compatibility contract
- [ ] ⏳ Create migration checklist

**Phase 2: Integration Layer**

- [ ] ⏳ Migration strategy assessment
- [ ] ⏳ Python rewrite vs Node.js adapter decision
- [ ] ⏳ Develop integration patterns
- [ ] ⏳ Create configuration migration
- [ ] ⏳ WebSocket integration assessment
- [ ] ⏳ Frontend integration assessment
- [ ] ⏳ Test suite creation
- [ ] ⏳ ACB removal playbook

**Phase 3: Migration**

- [ ] ⏳ Implement migration approach
- [ ] ⏳ WebSocket server integration
- [ ] ⏳ Oneiric CLI factory (Python/Node.js)
- [ ] ⏳ Lifecycle management
- [ ] ⏳ Observability integration
- [ ] ⏳ Configuration migration
- [ ] ⏳ Frontend updates
- [ ] ⏳ Test suite completion
- [ ] ⏳ ACB removal
- [ ] ⏳ Health check implementation
- [ ] ⏳ Runtime cache management
- [ ] ⏳ User migration guide
- [ ] ⏳ Validate Oneiric contract

#### Key Metrics

- **Test Coverage:** ⏳ Pending
- **ACB Dependencies:** ⏳ Pending
- **CLI Commands:** 0/6 implemented
- **Configuration:** 0/1 migrated
- **Health Schema:** 0/1 implemented

#### Blockers

- [ ] Migration strategy decision pending
- [ ] Node.js → Python assessment needed
- [ ] WebSocket integration complexity

#### Next Steps

1. Complete architecture analysis
1. Make migration approach decision
1. Begin baseline audit

______________________________________________________________________

## 📈 Detailed Progress Tracking

### Foundation Phase Progress

| Task | Status | Owner | Notes |
|------|--------|-------|-------|
| Create unified migration plan | ✅ Completed | [Name] | MCP_SERVER_MIGRATION_PLAN.md |
| mailgun-mcp baseline audit | ✅ Completed | [Name] | 46% coverage baseline |
| mailgun-mcp rollback tag | ✅ Completed | [Name] | v1.0.0-pre-migration |
| mailgun-mcp ACB inventory | ✅ Completed | [Name] | 2 imports found |
| Create checklist template | ✅ Completed | [Name] | MIGRATION_CHECKLIST_TEMPLATE.md |
| Create tracking dashboard | ✅ Completed | [Name] | This document |
| Document operational model | ✅ Completed | [Name] | OPERATIONAL_MODEL_DOCUMENTATION.md |
| Define compatibility contract | ✅ Completed | [Name] | COMPATIBILITY_CONTRACT.md |
| unifi-mcp baseline audit | ✅ Completed | [Name] | 27% coverage baseline |
| unifi-mcp rollback tag | ✅ Completed | [Name] | v1.0.0-pre-migration |
| opera-cloud-mcp baseline audit | ✅ Completed | [Name] | 39% coverage baseline |
| opera-cloud-mcp rollback tag | ✅ Completed | [Name] | v1.0.0-pre-migration |
| raindropio-mcp baseline audit | ✅ Completed | [Name] | 89% coverage baseline |
| raindropio-mcp rollback tag | ✅ Completed | [Name] | v1.0.0-pre-migration |
| excalidraw-mcp baseline audit | ✅ Completed | [Name] | 77% coverage baseline |
| excalidraw-mcp rollback tag | ✅ Completed | [Name] | v1.0.0-pre-migration |

### Integration Layer Progress

| Task | Status | Owner | Notes |
|------|--------|-------|-------|
| oneiric-mcp-adapter package | ⏳ Pending | [Name] | Not started |
| CLI factory extensions | ⏳ Pending | [Name] | Not started |
| Migration utilities | ⏳ Pending | [Name] | Not started |
| Observability bridge | ⏳ Pending | [Name] | Not started |
| Configuration migration tools | ⏳ Pending | [Name] | Not started |
| Test utilities and fixtures | ⏳ Pending | [Name] | Not started |
| ACB removal playbook | ⏳ Pending | [Name] | Not started |

______________________________________________________________________

## 🎯 Critical Path Analysis

### Upcoming Milestones

1. **Week 1 End (2026-01-03):**

   - ✅ Complete all Phase 1 foundation tasks
   - ✅ All baseline audits completed
   - ✅ All rollback tags created
   - ✅ Test coverage baselines established

1. **Week 2 End (2026-01-10):**

   - ✅ Integration layer completed
   - ✅ Oneiric CLI factory functional
   - ✅ Migration utilities available
   - ✅ ACB removal playbook approved

1. **Week 3 End (2026-01-17):**

   - ✅ mailgun-mcp migration completed
   - ✅ unifi-mcp migration completed
   - ✅ CLI commands standardized
   - ✅ Health schema implemented

### Blockers & Risks

| Risk | Impact | Likelihood | Mitigation | Owner |
|------|--------|------------|------------|-------|
| ACB removal complexity | HIGH | MEDIUM | Incremental removal, testing | [Name] |
| CLI command changes | MEDIUM | HIGH | Clear documentation, migration guides | [Name] |
| excalidraw-mcp strategy | HIGH | MEDIUM | Early decision, prototyping | [Name] |
| Test coverage regression | MEDIUM | MEDIUM | Maintain baseline, add tests | [Name] |
| Performance regression | LOW | MEDIUM | Benchmark before/after | [Name] |

______________________________________________________________________

## 📊 Visual Progress

### Project Progress Chart

```
mailgun-mcp:    ██████████ 100% (Phase 1 Complete)
unifi-mcp:      ██████████ 0% (Not Started)
opera-cloud-mcp:██████████ 0% (Not Started)
raindropio-mcp: ██████████ 0% (Not Started)
excalidraw-mcp: ██████████ 0% (Not Started)
```

### Phase Progress Chart

```
Phase 1 (Foundation):   ██████████ 100% (10/10 tasks)
Phase 2 (Integration):  ██████████ 0% (0/8 tasks)
Phase 3 (Python):       ██████████ 0% (0/35 tasks)
Phase 4 (Node.js):      ██████████ 0% (0/7 tasks)
Phase 5 (Integration):  ██████████ 0% (0/10 tasks)
Phase 6 (Rollout):      ██████████ 0% (0/8 tasks)
```

______________________________________________________________________

## 🔧 Action Items

### Immediate Actions (Next 24-48 Hours)

1. **Complete Foundation Tasks:**

   - [ ] Finish operational model documentation
   - [ ] Define compatibility contract
   - [ ] Complete remaining baseline audits

1. **Begin Integration Layer:**

   - [ ] Start oneiric-mcp-adapter package development
   - [ ] Create CLI factory extensions
   - [ ] Develop migration utilities

1. **Communication:**

   - [ ] Share progress update with team
   - [ ] Review blockers and risks
   - [ ] Plan Week 2 activities

### Weekly Focus Areas

**Week 1 (Dec 27 - Jan 3):**

- ✅ Foundation phase completion
- ✅ Baseline audits for all projects
- ✅ Rollback procedures established
- ✅ Test coverage baselines set

**Week 2 (Jan 4 - Jan 10):**

- 🟡 Integration layer development
- 🟡 Oneiric CLI factory implementation
- 🟡 Migration utilities creation
- 🟡 ACB removal playbook

**Week 3 (Jan 11 - Jan 17):**

- ⏳ mailgun-mcp migration
- ⏳ unifi-mcp migration
- ⏳ CLI command standardization
- ⏳ Health schema implementation

______________________________________________________________________

## 📅 Timeline & Resource Estimation

### Phase-by-Phase Timeline

| Phase | Duration | Effort | Resources | Start | End |
|-------|----------|--------|-----------|-------|-----|
| **Phase 1: Foundation** | 1 week | 10h | Documentation, Planning | Dec 27 | Jan 3 |
| **Phase 2: Integration** | 1 week | 15h | Development | Jan 4 | Jan 10 |
| **Phase 3: Python Migration** | 2 weeks | 30h | Development, Testing | Jan 11 | Jan 24 |
| **Phase 4: Node.js Migration** | 2 weeks | 25h | Development, Testing | Jan 25 | Feb 7 |
| **Phase 5: Integration** | 1 week | 12h | Testing, Documentation | Feb 8 | Feb 14 |
| **Phase 6: Rollout** | 1 week | 8h | Documentation, Support | Feb 15 | Feb 21 |
| **Total** | **8 weeks** | **100h** | | **Dec 27** | **Feb 21** |

### Resource Allocation

**Weekly Breakdown:**

- Week 1: 10h (Planning)
- Week 2: 15h (Integration Layer)
- Week 3: 15h (mailgun + unifi migration)
- Week 4: 15h (opera + raindrop migration)
- Week 5-6: 25h (excalidraw migration)
- Week 7: 12h (Integration testing)
- Week 8: 8h (Rollout preparation)

______________________________________________________________________

## ✅ Success Criteria Tracking

### Technical Success Metrics

| Metric | Target | Current | Status |
|--------|--------|---------|--------|
| **ACB Dependencies Removed** | 100% | 0% | ⏳ Pending |
| **Oneiric CLI Factory** | 100% | 0% | ⏳ Pending |
| **Standardized Lifecycle** | 100% | 0% | ⏳ Pending |
| **Runtime Cache Files** | 100% | 0% | ⏳ Pending |
| **Health Schema Compliance** | 100% | 0% | ⏳ Pending |
| **Test Coverage** | ≥ Baseline | 46% | ✅ Baseline |
| **Performance Metrics** | ≤ 120% | ⏳ Pending | ⏳ Pending |
| **Security Audit** | Pass | ⏳ Pending | ⏳ Pending |

### User Success Metrics

| Metric | Target | Current | Status |
|--------|--------|---------|--------|
| **Migration Guides** | 5 | 0 | ⏳ Pending |
| **CLI Command Mapping** | 5 | 0 | ⏳ Pending |
| **Configuration Examples** | 5 | 0 | ⏳ Pending |
| **Rollback Procedures** | 5 | 1 | ✅ 20% |
| **Support Channels** | Ready | ⏳ Pending | ⏳ Pending |

______________________________________________________________________

## 📝 Change Log

**2025-12-30:**

- Initial dashboard creation
- Added mailgun-mcp baseline audit results
- Created project tracking structure
- Established progress metrics
- Added risk assessment

**Template for future updates:**

- \[YYYY-MM-DD\]: [Description of changes]
- \[Project\]: [Specific updates]
- \[Phase\]: [Progress notes]

______________________________________________________________________

## 🔗 References

- **Migration Plan:** `MCP_SERVER_MIGRATION_PLAN.md`
- **Checklist Template:** `MIGRATION_CHECKLIST_TEMPLATE.md`
- **mailgun-mcp Audit:** `MIGRATION_BASELINE_AUDIT_mailgun-mcp.md`
- **Oneiric Documentation:** `oneiric/docs/`
- **Crackerjack Contract:** `crackerjack/docs/reference/BREAKING_CHANGES.md`
- **Session-Buddy Health:** `session-buddy/docs/reference/API_REFERENCE.md`

______________________________________________________________________

**Dashboard Status:** 🟡 ACTIVE
**Next Update:** 2026-01-01
**Owner:** [Your Name]
**Review Frequency:** Daily during active migration, Weekly during planning
