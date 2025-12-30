# MCP Server Migration to Oneiric - Unified Implementation Plan

**Status:** 🟡 READY AFTER FOUNDATION GATES
**Created:** 2025-12-27
**Timeline:** 8 weeks
**Total Effort:** ~100 hours
**Risk Level:** MODERATE-HIGH
**Reversibility:** YES (feature flags + rollback procedures)

---

## Executive Summary

### Goals

Migrate 5 MCP server projects to Oneiric runtime management, replacing **ACB + FastMCP** and other legacy patterns with standardized Oneiric lifecycle, configuration, and observability:

1. **Integrate Oneiric CLI Factory** - Adopt standard MCP lifecycle commands (`start`, `stop`, `restart`, `status`, `health`)
2. **Standardize Runtime Management** - Use Oneiric patterns for configuration, secrets, and lifecycle
3. **Enhance Observability** - Replace custom monitoring with Oneiric telemetry + external dashboards
4. **Unify Configuration** - Consolidate settings using Oneiric configuration patterns
5. **Remove Legacy Dependencies** - Eliminate ACB and legacy lifecycle stacks

### Projects to Migrate

| Project | Language | Current Framework | Complexity | Notes |
|---------|----------|-------------------|------------|-------|
| **excalidraw-mcp** | Node.js/TypeScript | Custom WebSocket + HTTP | HIGH | Only Node.js project, requires special handling |
| **mailgun-mcp** | Python | FastMCP + mcp-common | MEDIUM | Simple email API wrapper |
| **unifi-mcp** | Python | FastMCP + mcp-common | MEDIUM | Network management API |
| **opera-cloud-mcp** | Python | FastMCP + mcp-common | HIGH | Complex hospitality system |
| **raindropio-mcp** | Python | FastMCP + mcp-common | MEDIUM | Bookmark management API |

### Quick Stats

| Metric | Value |
|--------|-------|
| **Timeline** | 8 weeks |
| **Total Effort** | ~100 hours |
| **Projects** | 5 MCP servers |
| **Language Migration** | 1 Node.js → Python assessment |
| **Python Projects** | 4 FastMCP → Oneiric |
| **CLI Commands** | 20+ to standardize |
| **Test Coverage** | No regression vs baseline; per-repo targets set in Phase 1 |

---

## Current State Analysis

### Project Architecture Overview

#### excalidraw-mcp (Node.js/TypeScript)
- **Framework**: Custom Express + WebSocket server
- **Transport**: HTTP + WebSocket (real-time canvas sync)
- **Dependencies**: `@modelcontextprotocol/sdk`, Express, WS, Zod
- **Build**: TypeScript → JavaScript via Vite
- **Complexity**: High (real-time sync, frontend integration)
- **Current CLI**: `npm run canvas`, `npm run dev`

#### mailgun-mcp (Python)
- **Framework**: FastMCP
- **Transport**: HTTP only
- **Dependencies**: fastmcp, mcp-common
- **Complexity**: Medium (email API wrapper)
- **Current CLI**: Python module entrypoint

#### unifi-mcp (Python)
- **Framework**: FastMCP
- **Transport**: HTTP only
- **Dependencies**: fastmcp, mcp-common, pydantic
- **Complexity**: Medium (network management)
- **Current CLI**: Python module entrypoint

#### opera-cloud-mcp (Python)
- **Framework**: FastMCP
- **Transport**: HTTP only
- **Dependencies**: fastmcp, mcp-common, httpx, sqlmodel
- **Complexity**: High (hospitality system with 45+ tools)
- **Current CLI**: `opera-cloud-mcp` console script

#### raindropio-mcp (Python)
- **Framework**: FastMCP
- **Transport**: HTTP only
- **Dependencies**: fastmcp, mcp-common, httpx
- **Complexity**: Medium (bookmark management)
- **Current CLI**: `raindropio-mcp` console script

### Repository Locations & Scope

All MCP server projects remain in their **own directories** as sibling repos under `/Users/les/Projects`:

| Project | Local Path |
|---------|------------|
| excalidraw-mcp | `/Users/les/Projects/excalidraw-mcp` |
| mailgun-mcp | `/Users/les/Projects/mailgun-mcp` |
| unifi-mcp | `/Users/les/Projects/unifi-mcp` |
| opera-cloud-mcp | `/Users/les/Projects/opera-cloud-mcp` |
| raindropio-mcp | `/Users/les/Projects/raindropio-mcp` |
| oneiric | `/Users/les/Projects/oneiric` |

### Dependency Analysis

```mermaid
graph TD
    subgraph CurrentState
        excalidraw[excalidraw-mcp] -->|Node.js| express
        excalidraw --> websocket
        excalidraw --> modelcontext_sdk
        
        mailgun[mailgun-mcp] --> fastmcp
        mailgun --> mcp_common
        
        unifi[unifi-mcp] --> fastmcp
        unifi --> mcp_common
        
        opera[opera-cloud-mcp] --> fastmcp
        opera --> mcp_common
        opera --> sqlmodel
        
        raindrop[raindropio-mcp] --> fastmcp
        raindrop --> mcp_common
    end
    
    subgraph TargetState
        all --> oneiric[Oneiric Runtime]
        oneiric --> mcp_common_new[mcp-common enhanced]
        oneiric --> cli_factory[CLI Factory]
        oneiric --> observability[Telemetry]
        oneiric --> lifecycle[Lifecycle Mgmt]
    end
    
    CurrentState -->|Migration| TargetState
```

### CLI Command Inventory

**Current Commands (to be standardized):**

| Project | Current Command | New Oneiric Command |
|---------|-----------------|---------------------|
| excalidraw-mcp | `npm run canvas` | `excalidraw-mcp start` |
| excalidraw-mcp | `npm run dev` | `excalidraw-mcp dev` |
| mailgun-mcp | `python -m mailgun_mcp` | `mailgun-mcp start` |
| unifi-mcp | `python -m unifi_mcp` | `unifi-mcp start` |
| opera-cloud-mcp | `opera-cloud-mcp` | `opera-cloud-mcp start` |
| raindropio-mcp | `raindropio-mcp` | `raindropio-mcp start` |

**New Standard Commands (all projects):**
- `start` - Start the MCP server
- `stop` - Stop the running server
- `restart` - Restart the server
- `status` - Show server status
- `health` - Health check endpoint
- `health --probe` - Live health probe

### Operational Model (Source of Truth: Crackerjack + Session-Buddy)

**Lifecycle command shape (Crackerjack):**
- Commands use **subcommand syntax** (`start`, `stop`, `restart`, `status`, `health`, `health --probe`) instead of legacy flags. (See `crackerjack/docs/MIGRATION_GUIDE_0.47.0.md`, `crackerjack/docs/reference/BREAKING_CHANGES.md`)
- Lifecycle commands are provided via `MCPServerCLIFactory` integration. (See `crackerjack/docs/PHASE_5-7_COMPLETION.md`)

**Health + status semantics (Crackerjack):**
- `health` returns **passive snapshot** data from Oneiric runtime cache. (See `crackerjack/docs/reference/BREAKING_CHANGES.md`)
- `health --probe` is a **live probe** intended for production monitoring and systemd integration. (See `crackerjack/docs/reference/BREAKING_CHANGES.md`)
- `status` should read Oneiric runtime snapshot(s) and PID metadata; Crackerjack reads `.oneiric_cache/runtime_health.json`, `.oneiric_cache/runtime_telemetry.json`, and PID state. (See `crackerjack/docs/archive/implementation-plans/ONEIRIC_MIGRATION_EXECUTION_PLAN.md`)

**Runtime cache + instance isolation (Crackerjack):**
- Oneiric uses `.oneiric_cache/` for runtime snapshots; multi-instance uses `--instance-id` with per-instance cache folders (e.g., `.oneiric_cache/worker-1/server.pid`). (See `crackerjack/docs/reference/BREAKING_CHANGES.md`)
- WebSocket monitoring is **removed**; dashboards are replaced by Oneiric snapshots + external observability tools. (See `crackerjack/docs/reference/BREAKING_CHANGES.md`, `crackerjack/docs/archive/implementation-plans/ONEIRIC_MIGRATION_EXECUTION_PLAN.md`)

**Health data contract (Session-Buddy / mcp-common):**
- Use `mcp_common.health` primitives (`HealthStatus`, `ComponentHealth`, `HealthCheckResponse`) as the canonical schema for component and aggregate health. (See `session-buddy/docs/reference/API_REFERENCE.md`)

---

## Migration Strategy

### Guiding Principles

1. **Incremental Migration** - Never big-bang changes (learned from session-buddy)
2. **ACB Removal** - Remove ACB patterns, deps, and docs across all repos
3. **Feature Flags** - Enable gradual rollout and easy rollback
4. **Comprehensive Testing** - Maintain baseline coverage; no regressions without sign-off
5. **Clear Documentation** - Migration guides for users and developers

### Compatibility Contract (Crackerjack + Session-Buddy Baseline)

**CLI / Lifecycle:**
- Commands and semantics must match Crackerjack’s Oneiric CLI contract: `start`, `stop`, `restart`, `status`, `health`, `health --probe`. (See `crackerjack/docs/MIGRATION_GUIDE_0.47.0.md`, `crackerjack/docs/reference/BREAKING_CHANGES.md`)

**Runtime Cache + Status:**
- `status`/`health` must read Oneiric runtime snapshots from `.oneiric_cache/` (and per-instance cache when `--instance-id` is used). (See `crackerjack/docs/reference/BREAKING_CHANGES.md`, `crackerjack/docs/archive/implementation-plans/ONEIRIC_MIGRATION_EXECUTION_PLAN.md`)

**Health Schema:**
- Health checks should emit/aggregate `ComponentHealth`/`HealthCheckResponse` with `HealthStatus` enums (Session-Buddy’s mcp-common contract). (See `session-buddy/docs/reference/API_REFERENCE.md`)

**Observability:**
- Telemetry is provided by Oneiric; no custom WebSocket monitoring is expected in migrated servers. (See `crackerjack/docs/reference/BREAKING_CHANGES.md`, `crackerjack/docs/archive/implementation-plans/ONEIRIC_MIGRATION_EXECUTION_PLAN.md`)

### CLI + Runtime Cache Contract (Per-Repo)

Each MCP server must implement the same CLI + runtime cache behavior as Crackerjack, with **no legacy/compat flags**:

**Command surface (all repos):**
- `start`, `stop`, `restart`, `status`, `health`, `health --probe`
- `--instance-id <id>` (optional) for multi-instance isolation

**Runtime cache files (default instance):**
- `.oneiric_cache/server.pid`
- `.oneiric_cache/runtime_health.json`
- `.oneiric_cache/runtime_telemetry.json`

**Runtime cache files (multi-instance):**
- `.oneiric_cache/<instance-id>/server.pid`
- `.oneiric_cache/<instance-id>/runtime_health.json`
- `.oneiric_cache/<instance-id>/runtime_telemetry.json`

**Per-repo implementation checklist (all MCP servers):**
- [ ] `start` writes `server.pid` and initializes runtime snapshots
- [ ] `status` reads snapshot + PID state
- [ ] `health` reads cached `runtime_health.json`
- [ ] `health --probe` performs live checks
- [ ] `runtime_telemetry.json` emitted by Oneiric telemetry
- [ ] `ComponentHealth` / `HealthCheckResponse` schema used in health payloads

### Runtime Health Snapshot Schema (Oneiric + mcp-common)

The `runtime_health.json` payload must conform to the mcp-common health schema used by Session-Buddy:

**Required fields (top-level):**
- `status`: `HEALTHY` | `DEGRADED` | `UNHEALTHY`
- `components`: array of component health objects
- `timestamp`: ISO 8601 datetime

**Component object fields:**
- `name`: string identifier (e.g., `database`, `http_client`, `external_api`)
- `status`: `HEALTHY` | `DEGRADED` | `UNHEALTHY`
- `message`: human-readable status
- `latency_ms`: number or null
- `metadata`: object with additional context

**Contract notes:**
- `status` should reflect the **worst** component status.
- `health --probe` returns the same schema but must be **live** (no cached reads).

**Applies to:**
- `excalidraw-mcp` (`/Users/les/Projects/excalidraw-mcp`)
- `mailgun-mcp` (`/Users/les/Projects/mailgun-mcp`)
- `unifi-mcp` (`/Users/les/Projects/unifi-mcp`)
- `opera-cloud-mcp` (`/Users/les/Projects/opera-cloud-mcp`)
- `raindropio-mcp` (`/Users/les/Projects/raindropio-mcp`)

### Technical Approach

#### For Python Projects (mailgun, unifi, opera, raindrop)

```mermaid
graph LR
    A[Current FastMCP] --> B[Add Oneiric CLI Factory]
    B --> C[Integrate Lifecycle Hooks]
    C --> D[Update Configuration]
    D --> E[Add Observability]
    E --> F[Update Tests]
    F --> G[Migrated to Oneiric]
```

#### For Node.js Project (excalidraw)

```mermaid
graph LR
    A[Current Node.js] --> B[Migration Assessment]
    B -->|Option 1| C[Create Python Equivalent]
    B -->|Option 2| D[Node.js Adapter Layer]
    C --> E[Integrate Oneiric Patterns]
    D --> E[Integrate Oneiric Patterns]
    E --> F[Migrated to Oneiric]
```

### Integration Patterns

**CLI Factory Integration:**
```python
# Before (FastMCP)
from fastmcp import MCPServer

if __name__ == "__main__":
    server = MCPServer(config=config)
    server.run()

# After (Oneiric)
from oneiric.core.cli import MCPServerCLIFactory

if __name__ == "__main__":
    cli_factory = MCPServerCLIFactory(
        server_class=MailgunMCPServer,
        config_class=MailgunConfig
    )
    cli_factory.run()
```

**Lifecycle Management:**
```python
# Before (Custom)
class MailgunServer:
    def start(self):
        # Custom startup logic
        pass

# After (Oneiric)
class MailgunServer(OneiricMCPServer):
    async def on_startup(self):
        await super().on_startup()
        # Server-specific startup
        
    async def on_shutdown(self):
        # Server-specific cleanup
        await super().on_shutdown()
```

**Configuration Migration:**
```python
# Before (Custom)
class Config:
    http_port: int = 3039
    api_key: str

# After (Oneiric)
class MailgunConfig(OneiricMCPConfig):
    http_port: int = Field(default=3039, env="MAILGUN_HTTP_PORT")
    api_key: str = Field(..., env="MAILGUN_API_KEY")
    
    class Config:
        env_prefix = "MAILGUN_"
```

---

## Phase-by-Phase Implementation

### Phase 1: Foundation & Planning (Week 1)

**Objective:** Establish migration infrastructure and baseline

**Tasks:**
- [x] ✅ Create unified migration tracking document
- [ ] Baseline audit for each project (dependencies, tests, CLI)
- [ ] Create migration checklist template for each project
- [ ] Set up migration tracking dashboard
- [ ] Document current CLI commands and Oneiric equivalents
- [ ] Establish test coverage baselines
- [ ] Create rollback procedures template
- [ ] Document operational model (Crackerjack + Session-Buddy contract)
- [ ] Define compatibility contract (CLI, cache paths, health schema)
- [ ] Create pre-migration rollback tags in each repo
- [ ] ACB removal inventory (deps, imports, docs, tests) per repo

**Deliverables:**
- `MCP_SERVER_MIGRATION_PLAN.md` (this document)
- Baseline audit reports for each project
- Migration checklist templates
- CLI command mapping guide
- Test coverage baselines
- Operational model + compatibility contract
- Pre-migration rollback tags (per repo)
- ACB removal inventory per repo

**Success Criteria:**
- All projects have comprehensive baseline documentation
- Migration tracking system operational
- Rollback procedures defined
- Operational model documented and agreed
- Compatibility contract approved
- Rollback tags created in each repo
- ACB removal inventory reviewed

---

### Phase 2: Oneiric Integration Layer (Week 2)

**Objective:** Create common integration patterns and utilities

**Tasks:**
- [ ] Develop `oneiric-mcp-adapter` package for common MCP patterns
- [ ] Create Oneiric CLI factory extensions for MCP servers
- [ ] Implement standard lifecycle hooks (start, stop, health, status)
- [ ] Develop migration utilities for FastMCP → Oneiric transitions
- [ ] Integrate Oneiric telemetry + runtime snapshots (no custom dashboards)
- [ ] Build configuration migration tools
- [ ] Create test utilities for migrated servers
- [ ] Define ACB removal playbook (deps, DI, config, docs, tests)

**Deliverables:**
- `oneiric-mcp-adapter` Python package
- CLI factory extensions with MCP-specific features
- Migration utility scripts
- Oneiric telemetry + runtime snapshot integration
- Configuration migration tools
- Test utilities and fixtures
- ACB removal playbook

**Success Criteria:**
- Integration layer tested with sample MCP server
- Migration utilities functional
- Oneiric telemetry + snapshot integration validated
- ACB removal playbook approved

---

### Phase 3: Python MCP Server Migration (Weeks 3-4)

**Objective:** Migrate Python-based MCP servers to Oneiric

#### 3.1 mailgun-mcp Migration (Week 3 - Day 1-2)

**Tasks:**
- [ ] Replace FastMCP CLI with Oneiric CLI factory
- [ ] Integrate Oneiric lifecycle management
- [ ] Update configuration to use Oneiric patterns
- [ ] Add Oneiric observability and telemetry
- [ ] Update tests to use Oneiric test patterns
- [ ] Remove ACB dependencies, docs, and tests
- [ ] Create migration guide for users
- [ ] Validate Oneiric-only CLI + runtime cache contract

**Deliverables:**
- Migrated mailgun-mcp package
- Updated documentation
- User migration guide
- Test suite validation

#### 3.2 unifi-mcp Migration (Week 3 - Day 3-4)

**Tasks:**
- [ ] Replace FastMCP CLI with Oneiric CLI factory
- [ ] Integrate Oneiric lifecycle management
- [ ] Update configuration to use Oneiric patterns
- [ ] Add Oneiric observability and telemetry
- [ ] Update tests to use Oneiric test patterns
- [ ] Remove ACB dependencies, docs, and tests
- [ ] Create migration guide for users
- [ ] Validate Oneiric-only CLI + runtime cache contract

**Deliverables:**
- Migrated unifi-mcp package
- Updated documentation
- User migration guide
- Test suite validation

#### 3.3 opera-cloud-mcp Migration (Week 4 - Day 1-3)

**Tasks:**
- [ ] Replace FastMCP CLI with Oneiric CLI factory
- [ ] Integrate Oneiric lifecycle management
- [ ] Update configuration to use Oneiric patterns
- [ ] Add Oneiric observability and telemetry
- [ ] Update CLI entrypoint to use Oneiric patterns
- [ ] Update tests to use Oneiric test patterns
- [ ] Handle SQLModel integration with Oneiric
- [ ] Remove ACB dependencies, docs, and tests
- [ ] Create migration guide for users
- [ ] Validate Oneiric-only CLI + runtime cache contract

**Deliverables:**
- Migrated opera-cloud-mcp package
- Updated CLI entrypoint
- SQLModel integration validated
- User migration guide
- Test suite validation

#### 3.4 raindropio-mcp Migration (Week 4 - Day 4-5)

**Tasks:**
- [ ] Replace FastMCP CLI with Oneiric CLI factory
- [ ] Integrate Oneiric lifecycle management
- [ ] Update configuration to use Oneiric patterns
- [ ] Add Oneiric observability and telemetry
- [ ] Update CLI entrypoint to use Oneiric patterns
- [ ] Update tests to use Oneiric test patterns
- [ ] Remove ACB dependencies, docs, and tests
- [ ] Create migration guide for users
- [ ] Validate Oneiric-only CLI + runtime cache contract

**Deliverables:**
- Migrated raindropio-mcp package
- Updated CLI entrypoint
- User migration guide
- Test suite validation

**Phase 3 Success Criteria:**
- All Python MCP servers using Oneiric CLI factory
- Standardized lifecycle management across all servers
- Observability integrated and functional
- Test coverage at or above per-repo baseline
- User migration guides available
- ACB dependencies removed across Python MCP servers

---

### Phase 4: Node.js MCP Server Migration (Weeks 5-6)

**Objective:** Migrate excalidraw-mcp (special case - Node.js)

#### 4.1 Migration Strategy Assessment (Week 5 - Day 1)

**Tasks:**
- [ ] Analyze excalidraw-mcp architecture in depth
- [ ] Evaluate Option 1: Python rewrite using Oneiric patterns
- [ ] Evaluate Option 2: Node.js adapter layer for Oneiric integration
- [ ] Assess WebSocket integration requirements
- [ ] Evaluate frontend integration impact
- [ ] Create cost/benefit analysis
- [ ] Make final migration approach decision

**Deliverables:**
- Architecture analysis document
- Migration approach recommendation
- Cost/benefit analysis
- Implementation plan for chosen approach

#### 4.2 Implementation (Week 5 - Day 2 to Week 6 - Day 4)

**Option 1: Python Rewrite (if chosen)**
- [ ] Create Python equivalent of excalidraw-mcp
- [ ] Implement WebSocket server using Oneiric patterns
- [ ] Port HTTP API endpoints
- [ ] Integrate with Oneiric CLI factory
- [ ] Add Oneiric lifecycle management
- [ ] Implement observability and telemetry
- [ ] Update frontend integration
- [ ] Create comprehensive test suite
- [ ] Remove ACB dependencies, docs, and tests (if present)

**Option 2: Node.js Adapter Layer (if chosen)**
- [ ] Create Node.js ↔ Oneiric bridge
- [ ] Implement Oneiric CLI factory in Node.js
- [ ] Add lifecycle management hooks
- [ ] Integrate observability bridge
- [ ] Update configuration patterns
- [ ] Maintain existing WebSocket functionality
- [ ] Create test suite for bridge
- [ ] Remove ACB dependencies, docs, and tests (if present)

**Deliverables:**
- Migrated excalidraw-mcp (Python or Node.js with adapter)
- WebSocket integration validated
- Frontend integration updated
- Comprehensive test suite
- User migration guide

**Success Criteria:**
- excalidraw-mcp using Oneiric patterns
- WebSocket functionality preserved
- Frontend integration working
- Observability integrated
- Test coverage maintained
- ACB dependencies removed (if present)

---

### Phase 5: Integration & Testing (Week 7)

**Objective:** Ensure all migrations work together seamlessly

**Tasks:**
- [ ] Cross-project integration testing
- [ ] End-to-end workflow validation
- [ ] Performance benchmarking (before/after)
- [ ] Security audit of migrated servers
- [ ] Configuration compatibility testing
- [ ] CLI command consistency validation
- [ ] Observability dashboard integration
- [ ] Documentation consolidation
- [ ] Create integration test suite
- [ ] ACB dependency audit across all repos (must be zero)

**Deliverables:**
- Integration test suite
- Performance benchmark reports
- Security audit report
- Consolidated documentation
- Observability dashboard setup

**Success Criteria:**
- All servers work together without conflicts
- Performance metrics meet or exceed baselines
- Security audit passes
- Documentation complete and accurate
- Zero ACB dependencies across all repos

---

### Phase 6: Rollout & Monitoring (Week 8)

**Objective:** Production deployment and monitoring

**Tasks:**
- [ ] Create rollout plan for each project
- [ ] Implement feature flags for gradual migration
- [ ] Set up monitoring and alerting
- [ ] Create rollback procedures for each project
- [ ] Develop user migration guides
- [ ] Create announcement materials
- [ ] Set up user support channels
- [ ] Plan migration webinars/workshops

**Deliverables:**
- Rollout plan document
- Feature flag implementation
- Monitoring and alerting setup
- Rollback procedures for each project
- User migration guides
- Announcement materials
- Support documentation

**Success Criteria:**
- Rollout plan approved
- Monitoring operational
- Rollback procedures tested
- User documentation complete
- Support channels ready

---

## Migration Progress Tracker

### Overall Status

**Updated:** 2025-12-27

| Metric | Value |
|--------|-------|
| **Total Projects** | 5 |
| **Completed** | 0/5 (0%) |
| **In Progress** | 0/5 (0%) |
| **Pending** | 5/5 (100%) |
| **Total Tasks** | 78 |
| **Completed Tasks** | 1/78 (1.3%) |
| **Estimated Completion** | 2026-02-21 |

### Project-Specific Status

| Project | Status | Start Date | Expected Completion | Blockers | Progress |
|---------|--------|------------|---------------------|----------|----------|
| **mailgun-mcp** | ⏳ Pending | - | Week 3 | None | 0% |
| **unifi-mcp** | ⏳ Pending | - | Week 3 | None | 0% |
| **opera-cloud-mcp** | ⏳ Pending | - | Week 4 | None | 0% |
| **raindropio-mcp** | ⏳ Pending | - | Week 4 | None | 0% |
| **excalidraw-mcp** | ⏳ Pending | - | Week 6 | Migration strategy decision | 0% |

### Phase Progress

| Phase | Status | Start | End | Tasks | Completed |
|-------|--------|-------|-----|-------|-----------|
| **Phase 1: Foundation** | ✅ In Progress | Week 1 | Week 1 | 10 | 1 (10%) |
| **Phase 2: Integration** | ⏳ Pending | Week 2 | Week 2 | 8 | 0 (0%) |
| **Phase 3: Python Migration** | ⏳ Pending | Week 3 | Week 4 | 35 | 0 (0%) |
| **Phase 4: Node.js Migration** | ⏳ Pending | Week 5 | Week 6 | 7 | 0 (0%) |
| **Phase 5: Integration** | ⏳ Pending | Week 7 | Week 7 | 10 | 0 (0%) |
| **Phase 6: Rollout** | ⏳ Pending | Week 8 | Week 8 | 8 | 0 (0%) |

### Detailed Task Breakdown

#### Foundation Tasks (Phase 1)
- [x] ✅ Create migration plan document (this file)
- [ ] Baseline audit for each project
- [ ] Migration checklist templates
- [ ] Migration tracking dashboard
- [ ] CLI command mapping guide
- [ ] Test coverage baselines
- [ ] Rollback procedures template
- [ ] Operational model documentation (Crackerjack + Session-Buddy)
- [ ] Compatibility contract definition (CLI, cache paths, health schema)
- [ ] Pre-migration rollback tags (per repo)

#### Integration Layer Tasks (Phase 2)
- [ ] oneiric-mcp-adapter package
- [ ] CLI factory extensions
- [ ] Migration utilities
- [ ] Observability bridge
- [ ] Configuration migration tools
- [ ] Test utilities and fixtures
- [ ] Integration layer testing

#### Python Migration Tasks (Phase 3)
**mailgun-mcp:**
- [ ] Replace FastMCP CLI
- [ ] Integrate lifecycle hooks
- [ ] Update configuration
- [ ] Add observability
- [ ] Update tests
- [ ] User migration guide
- [ ] Oneiric-only CLI + runtime cache validation

**unifi-mcp:**
- [ ] Replace FastMCP CLI
- [ ] Integrate lifecycle hooks
- [ ] Update configuration
- [ ] Add observability
- [ ] Update tests
- [ ] User migration guide
- [ ] Oneiric-only CLI + runtime cache validation

**opera-cloud-mcp:**
- [ ] Replace FastMCP CLI
- [ ] Integrate lifecycle hooks
- [ ] Update configuration
- [ ] Add observability
- [ ] Update CLI entrypoint
- [ ] Update tests
- [ ] SQLModel integration
- [ ] User migration guide
- [ ] Oneiric-only CLI + runtime cache validation

**raindropio-mcp:**
- [ ] Replace FastMCP CLI
- [ ] Integrate lifecycle hooks
- [ ] Update configuration
- [ ] Add observability
- [ ] Update CLI entrypoint
- [ ] Update tests
- [ ] User migration guide
- [ ] Oneiric-only CLI + runtime cache validation

#### Node.js Migration Tasks (Phase 4)
- [ ] Architecture analysis
- [ ] Migration approach decision
- [ ] Implementation (Python rewrite or Node.js adapter)
- [ ] WebSocket integration
- [ ] Frontend updates
- [ ] Test suite creation
- [ ] User migration guide

#### Integration Tasks (Phase 5)
- [ ] Cross-project testing
- [ ] Performance benchmarking
- [ ] Security audit
- [ ] Configuration testing
- [ ] CLI consistency validation
- [ ] Observability integration
- [ ] Documentation consolidation
- [ ] Integration test suite

#### Rollout Tasks (Phase 6)
- [ ] Rollout plan
- [ ] Feature flags
- [ ] Monitoring setup
- [ ] Rollback procedures
- [ ] User migration guides
- [ ] Announcement materials
- [ ] Support documentation
- [ ] Migration workshops

---

## Risk Assessment & Mitigation

### High Risk Areas

| Risk Area | Impact | Likelihood | Mitigation Strategy |
|-----------|--------|------------|---------------------|
| **excalidraw-mcp migration** | HIGH | MEDIUM | Thorough assessment, prototype both approaches |
| **CLI command changes** | MEDIUM | HIGH | Clear migration guides; remove legacy flags |
| **Observability integration** | MEDIUM | MEDIUM | Bridge pattern, dual reporting during transition |
| **Configuration migration** | LOW | HIGH | Automated migration tools, validation scripts |
| **Dependency conflicts** | MEDIUM | LOW | Isolated testing, dependency resolution guides |
| **Operational model drift** | MEDIUM | MEDIUM | Lock to Crackerjack + Session-Buddy contract; validate against runtime cache + health schema |

### Mitigation Strategies

**Feature Flags:** Not used for legacy support. Use flags only for safe rollout sequencing if needed.

**Rollback Procedures:**
```bash
# Rollback template for each project
git checkout v1.0.0-pre-migration
pip install -e .
# Verify Oneiric functionality
project-name start
```

**Legacy Support:** None. Remove all legacy CLI flags and ACB execution paths.

---

## Timeline & Resource Estimation

### Phase-by-Phase Timeline

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

### Effort Estimation

| Phase | Duration | Effort | Resources |
|-------|----------|--------|-----------|
| **Phase 1: Foundation** | 1 week | 10h | Documentation, Planning |
| **Phase 2: Integration** | 1 week | 15h | Development |
| **Phase 3: Python Migration** | 2 weeks | 30h | Development, Testing |
| **Phase 4: Node.js Migration** | 2 weeks | 25h | Development, Testing |
| **Phase 5: Integration** | 1 week | 12h | Testing, Documentation |
| **Phase 6: Rollout** | 1 week | 8h | Documentation, Support |
| **Total** | **8 weeks** | **100h** | |

### Resource Allocation

**Weekly Breakdown:**
- Week 1: 10h (Planning)
- Week 2: 15h (Integration Layer)
- Week 3: 15h (mailgun + unifi migration)
- Week 4: 15h (opera + raindrop migration)
- Week 5-6: 25h (excalidraw migration)
- Week 7: 12h (Integration testing)
- Week 8: 8h (Rollout preparation)

---

## Success Criteria

### Technical Success Metrics

**Mandatory:**
- [ ] All MCP servers use Oneiric CLI factory
- [ ] Standardized lifecycle management across all servers
- [ ] Integrated observability and telemetry
- [ ] Test coverage at or above per-repo baseline
- [ ] Breaking changes documented and communicated
- [ ] Configuration migration tools functional
- [ ] Rollback procedures tested and working
- [ ] Zero ACB dependencies across all repos (deps, imports, docs, tests)

**Performance:**
- [ ] Startup time ≤ 120% of baseline
- [ ] Memory usage ≤ 110% of baseline
- [ ] Response time ≤ 105% of baseline
- [ ] No performance regressions in production

**Quality:**
- [ ] All tests passing; coverage at or above baseline
- [ ] Security audit passes
- [ ] No critical vulnerabilities introduced
- [ ] Code quality metrics maintained

### User Success Metrics

**Migration Experience:**
- [ ] Clear migration guides for each project
- [ ] Minimal disruption to existing workflows
- [ ] Feature flags enable gradual transition
- [ ] Rollback procedures documented and tested

**Documentation:**
- [ ] Comprehensive user migration guides
- [ ] Updated README files for all projects
- [ ] CLI command reference (old → new)
- [ ] Configuration migration examples
- [ ] Troubleshooting guides

**Support:**
- [ ] Migration workshops/webinars conducted
- [ ] Support channels established
- [ ] FAQ documentation available
- [ ] Issue templates for migration problems

---

## Migration Patterns & Best Practices

### Lessons from Successful Projects

**From Crackerjack:**
- Phased approach with clear decision gates
- Comprehensive baseline audits
- Migration status tracking dashboard
- Rollback procedures for each phase

**From Session-Buddy:**
- Incremental migration (never big-bang)
- Bridge patterns for gradual transition
- Comprehensive migration guides
- ACB removal and Oneiric-only lifecycle

**From MCP-Common:**
- CLI factory standardization
- Lifecycle management patterns
- Observability integration
- Configuration consolidation

### Recommended Practices

**Configuration Migration:**
```python
# Use Oneiric's configuration patterns
class ProjectConfig(OneiricMCPConfig):
    # Standard Oneiric fields
    http_port: int = 3039
    enable_telemetry: bool = True
    
    # Project-specific fields
    api_key: str = Field(..., env="PROJECT_API_KEY")
    
    class Config:
        env_prefix = "PROJECT_"
        env_file = ".env.project"
```

**Lifecycle Management:**
```python
class ProjectServer(OneiricMCPServer):
    async def on_startup(self):
        await super().on_startup()
        # Initialize project-specific resources
        
    async def on_shutdown(self):
        # Clean up project-specific resources
        await super().on_shutdown()
    
    async def health_check(self) -> dict:
        base_health = await super().health_check()
        project_health = {
            "api_connection": self.check_api_connection(),
            "cache_status": self.check_cache_status()
        }
        return {**base_health, **project_health}
```

**CLI Integration:**
```python
# Standard CLI factory pattern
def create_cli():
    return MCPServerCLIFactory(
        server_class=ProjectServer,
        config_class=ProjectConfig,
        name="project-mcp",
        description="Project MCP Server",
        version="1.0.0"
    )

if __name__ == "__main__":
    create_cli().run()
```

---

## Appendices

### Appendix A: CLI Command Mapping

**Standard Command Mapping:**

| Old Command | New Command | Notes |
|-------------|-------------|-------|
| `python -m project` | `project-mcp start` | Standard startup |
| `project --start` | `project-mcp start` | Legacy flag |
| `project --stop` | `project-mcp stop` | Stop command |
| `project --restart` | `project-mcp restart` | Restart command |
| `project --status` | `project-mcp status` | Status check |
| `project --health` | `project-mcp health` | Health check |
| N/A | `project-mcp health --probe` | Live probe |
| `project --config` | `project-mcp config show` | Config display |
| `project --version` | `project-mcp --version` | Version info |

### Appendix B: Configuration Migration Examples

**Before (Custom):**
```python
# config.py
class Config:
    def __init__(self):
        self.http_port = int(os.getenv("HTTP_PORT", "3039"))
        self.api_key = os.getenv("API_KEY")
```

**After (Oneiric):**
```python
# config.py
from oneiric.core.config import OneiricMCPConfig
from pydantic import Field

class ProjectConfig(OneiricMCPConfig):
    http_port: int = Field(default=3039, env="HTTP_PORT")
    api_key: str = Field(..., env="API_KEY")
    
    class Config:
        env_prefix = "PROJECT_"
```

### Appendix C: Testing Strategies

**Test Migration Approach:**
1. **Baseline Capture**: Run full test suite before migration
2. **Incremental Testing**: Test after each migration step
3. **Regression Testing**: Ensure no functionality lost
4. **Integration Testing**: Test cross-project interactions
5. **Performance Testing**: Compare before/after metrics

**Test Coverage Requirements:**
- Unit tests: ≥ baseline per repo (target set in Phase 1)
- Integration tests: ≥ baseline per repo (target set in Phase 1)
- End-to-end tests: Critical paths covered; baseline recorded
- Performance tests: Baseline comparisons

### Appendix D: Rollback Procedures

**Standard Rollback Template:**

```bash
# 1. Identify current version
git tag

# 2. Checkout pre-migration version
git checkout v1.0.0-pre-migration

# 3. Reinstall dependencies
pip install -e .

# 4. Verify Oneiric functionality
project-name start

# 5. Run server tests
pytest tests/

# 6. Confirm rollback success
project-name --status
```

**Project-Specific Rollback Notes:**
- Document any project-specific rollback considerations
- Note configuration file changes
- Document database migration rollback procedures
- List any manual steps required

### Appendix E: ACB Removal Checklist (Template)

Use this checklist per repo to ensure **ACB is fully removed** (deps, imports, docs, tests).

**Dependencies (pyproject / requirements):**
- [ ] Remove ACB packages from dependency lists
- [ ] Remove ACB extras or optional groups

**Imports / DI:**
- [ ] Replace `acb.depends` usage with Oneiric patterns
- [ ] Remove ACB adapters, registries, and lifecycle hooks
- [ ] Replace any ACB DI initialization or container wiring

**CLI / Lifecycle:**
- [ ] Remove ACB CLI flags and command wiring
- [ ] Ensure Oneiric `MCPServerCLIFactory` is the only lifecycle entry

**Docs:**
- [ ] Remove or update any ACB references in README / docs / guides
- [ ] Update architecture diagrams to Oneiric lifecycle
- [ ] Document Oneiric CLI + runtime cache behavior

**Tests:**
- [ ] Delete or migrate ACB-specific tests
- [ ] Add/adjust tests for Oneiric lifecycle + runtime snapshots
- [ ] Ensure health schema tests use `mcp_common.health` primitives

---

## Change Log

**2025-12-27:**
- Initial plan creation
- Foundation phase tasks defined
- Progress tracking system established
- Risk assessment completed
- Timeline and resource estimation added

**Template for future updates:**
- [YYYY-MM-DD]: [Description of changes]
- [Project]: [Specific updates]
- [Phase]: [Progress notes]

---

## Next Steps

### Immediate Actions
1. **Complete Foundation Phase** (Week 1)
   - Finish baseline audits for all projects
   - Create migration checklist templates
   - Set up tracking dashboard
   - Document CLI command mappings

2. **Begin Integration Layer** (Week 2)
   - Develop oneiric-mcp-adapter package
   - Create CLI factory extensions
   - Build migration utilities

3. **Start Python Migration** (Week 3)
   - Begin with mailgun-mcp (simplest)
   - Then unifi-mcp
   - Follow with opera-cloud-mcp and raindropio-mcp

4. **Assess Node.js Migration** (Week 5)
   - Complete excalidraw-mcp architecture analysis
   - Make migration approach decision
   - Begin implementation

### Long-Term Actions
1. **Monitor Migration Progress**
   - Update progress tracker weekly
   - Adjust timeline as needed
   - Address blockers promptly

2. **Ensure Quality**
   - Maintain test coverage
   - Conduct security audits
   - Validate performance

3. **Prepare for Rollout**
   - Develop user migration guides
   - Set up monitoring
   - Plan rollout sequence

---

## Conclusion

This unified migration plan provides a comprehensive roadmap for migrating all 5 MCP server projects to Oneiric runtime management. By following the phased approach and leveraging lessons from successful migrations (Crackerjack, Session-Buddy, MCP-Common), we can ensure a smooth transition with minimal disruption to users.

The plan includes robust progress tracking, risk mitigation strategies, and clear success criteria to measure our progress. With proper execution, this migration will standardize our MCP server infrastructure, improve observability, and provide a solid foundation for future development.

**Expected Completion:** 2026-02-21
**Total Effort:** ~100 hours
**Risk Level:** Moderate-High (managed with mitigation strategies)

---

## References

**Successful Migration Examples:**
- Crackerjack: `../crackerjack/docs/archive/implementation-plans/ONEIRIC_MIGRATION_EXECUTION_PLAN.md`
- Session-Buddy: `../session-buddy/docs/ACB_MIGRATION_COMPLETE.md`
- MCP-Common: `../mcp-common/docs/ONEIRIC_CLI_FACTORY_IMPLEMENTATION.md`
- FastBlocks: `../fastblocks/docs/TYPE_SYSTEM_MIGRATION.md`

**Oneiric Documentation:**
- CLI Patterns: `oneiric/core/cli.py`
- Configuration: `oneiric/core/config.py`
- Lifecycle Management: `oneiric/core/lifecycle.py`
- Observability: `oneiric/core/observability.py`

**Operational Model Sources:**
- Crackerjack CLI + lifecycle: `../crackerjack/docs/MIGRATION_GUIDE_0.47.0.md`
- Crackerjack breaking changes + runtime cache: `../crackerjack/docs/reference/BREAKING_CHANGES.md`
- Crackerjack Oneiric execution plan (status/telemetry snapshots): `../crackerjack/docs/archive/implementation-plans/ONEIRIC_MIGRATION_EXECUTION_PLAN.md`
- Session-Buddy health schema (mcp-common): `../session-buddy/docs/reference/API_REFERENCE.md`

**Project References:**
- excalidraw-mcp: `../excalidraw-mcp/`
- mailgun-mcp: `../mailgun-mcp/`
- unifi-mcp: `../unifi-mcp/`
- opera-cloud-mcp: `../opera-cloud-mcp/`
- raindropio-mcp: `../raindropio-mcp/`
