# Stage 5: Hardening & Completion Implementation Plan

**Status:** 🔄 In Progress (50% → 100%)
**Target Completion:** 1-2 weeks
**Priority:** P0 (Required for beta launch)

---

## Executive Summary

Stage 5 finalizes Oneiric for production deployment by creating operational guides, monitoring infrastructure, and incident response runbooks. This stage transforms Oneiric from a well-tested codebase into a **fully operational production system**.

**Current State (50% complete):**
- ✅ Full CLI demo functional (`main.py` + 11 commands)
- ✅ `uv run pytest` with 83% coverage
- ✅ All 5 P0 security issues resolved
- ✅ Production deployment guides (Docker, Kubernetes, systemd) - **COMPLETE**
- ❌ Monitoring/alerting setup missing
- ❌ Runbook documentation missing

**Target State (100% complete):**
- ✅ Production-ready deployment guides (Kubernetes, Docker, systemd)
- ✅ Monitoring/alerting infrastructure (Prometheus, Grafana, Loki)
- ✅ Comprehensive runbooks (incidents, troubleshooting, maintenance)
- ✅ Final audit and sign-off

**Note:** ACB migration/deprecation documentation has been removed from scope - project is for internal use only with no backward compatibility requirements.

---

## Stage 5 Tasks Breakdown

### Task 1: Production Deployment Guide ✅ **COMPLETE**

**Status:** ✅ 100% Complete (2025-11-26)
**Completion Summary:** See `docs/STAGE5_TASK1_COMPLETION.md`

Create comprehensive deployment guides for all major platforms.

#### 1.1 Docker Deployment Guide (2 days)

**File:** `docs/deployment/DOCKER_DEPLOYMENT.md`

**Deliverables:**
- Multi-stage Dockerfile optimized for production
- Docker Compose setup for local/staging
- Environment variable configuration
- Health check integration
- Volume management for cache/logs
- Security hardening (non-root user, minimal image)

**Contents:**
```markdown
# Docker Deployment Guide

## Quick Start
- Single-container deployment
- Multi-service orchestration with Docker Compose
- Environment configuration

## Production Dockerfile
- Multi-stage build (builder + runtime)
- UV package manager integration
- Security best practices
- Health checks

## Configuration
- Environment variables reference
- Secrets management (Docker secrets)
- Volume mounts

## Monitoring Integration
- Prometheus metrics exposure
- Loki log shipping
- Health check endpoints
```

#### 1.2 Kubernetes Deployment Guide (2 days)

**File:** `docs/deployment/KUBERNETES_DEPLOYMENT.md`

**Deliverables:**
- Complete Kubernetes manifests (Deployment, Service, ConfigMap, Secret)
- Helm chart (optional but recommended)
- Horizontal Pod Autoscaler (HPA) configuration
- Ingress configuration
- PersistentVolumeClaim for cache
- ServiceMonitor for Prometheus integration

**Contents:**
```markdown
# Kubernetes Deployment Guide

## Architecture
- Deployment strategy (rolling updates)
- Resource limits and requests
- Pod affinity/anti-affinity

## Manifests
- Deployment manifest (replicas, health checks)
- Service manifest (ClusterIP, LoadBalancer)
- ConfigMap (configuration)
- Secret (credentials)
- PVC (persistent cache)

## Helm Chart
- Values.yaml configuration
- Chart templates
- Installation instructions

## Autoscaling
- HPA based on CPU/memory
- Custom metrics (queue depth, latency)

## Monitoring
- ServiceMonitor for Prometheus
- Grafana dashboards
```

#### 1.3 Systemd Service Guide (1 day)

**File:** `docs/deployment/SYSTEMD_DEPLOYMENT.md`

**Deliverables:**
- Systemd unit file
- Installation script
- Log rotation configuration
- Automatic restart policies

**Contents:**
```markdown
# Systemd Deployment Guide

## Service Unit File
- ExecStart configuration
- Restart policies
- Resource limits (CPUQuota, MemoryMax)

## Installation
- User/group setup
- Directory permissions
- Service enablement

## Log Management
- Journald integration
- Log rotation
- Remote logging (rsyslog)

## Maintenance
- Service restart
- Log inspection
- Status monitoring
```

---

### Task 2: Monitoring & Alerting Setup (4 days)

Create production-ready monitoring infrastructure.

#### 2.1 Prometheus Configuration (1.5 days)

**File:** `docs/monitoring/PROMETHEUS_SETUP.md`

**Deliverables:**
- Prometheus scrape configuration
- Recording rules for aggregated metrics
- Alert rules for critical conditions
- Grafana dashboard JSON

**Key Metrics to Monitor:**
```yaml
# Resolution metrics
oneiric_resolution_total{domain, key, provider}
oneiric_resolution_duration_seconds{domain, key}

# Lifecycle metrics
oneiric_lifecycle_swap_total{domain, key, outcome}
oneiric_lifecycle_swap_duration_ms{domain, key}
oneiric_lifecycle_health_check_failures_total{domain, key}

# Activity metrics
oneiric_activity_pause_events_total{domain, state}
oneiric_activity_drain_events_total{domain, state}

# Remote sync metrics
oneiric_remote_sync_total{source, outcome}
oneiric_remote_sync_duration_seconds{source}
oneiric_remote_digest_checks_total
```

**Alert Rules:**
```yaml
# Critical alerts
- oneiric_resolution_failures > 10/min
- oneiric_lifecycle_swap_failures > 5/min
- oneiric_health_check_failures > threshold
- oneiric_remote_sync_failures > 3 consecutive

# Warning alerts
- oneiric_resolution_latency_p99 > 100ms
- oneiric_lifecycle_swap_duration > 30s
- oneiric_cache_disk_usage > 80%
```

#### 2.2 Grafana Dashboards (1 day)

**File:** `docs/monitoring/GRAFANA_DASHBOARDS.md` + JSON exports

**Deliverables:**
- Overview dashboard (health, traffic, errors)
- Resolution dashboard (by domain, provider, latency)
- Lifecycle dashboard (swaps, health checks, rollbacks)
- Remote sync dashboard (sync status, artifacts, signatures)

**Dashboard Panels:**
1. **Health Overview:** Up/down status, error rates, latency
2. **Traffic Patterns:** Resolutions/sec by domain, provider distribution
3. **Lifecycle Operations:** Swaps, health checks, activation failures
4. **Remote Sync:** Last sync time, sync errors, artifact downloads
5. **Resource Usage:** CPU, memory, disk, cache size

#### 2.3 Loki Log Aggregation (1 day)

**File:** `docs/monitoring/LOKI_SETUP.md`

**Deliverables:**
- Loki configuration for structlog JSON logs
- Promtail configuration for log shipping
- LogQL query examples
- Grafana Explore integration

**Log Queries:**
```logql
# Resolution errors
{app="oneiric"} |= "resolver-decision" | json | decision="failed"

# Lifecycle swaps
{app="oneiric"} |= "swap-complete" | json | domain="adapter"

# Remote sync errors
{app="oneiric"} |= "remote-sync-error" | json

# Health check failures
{app="oneiric"} |= "health-check-failed" | json
```

#### 2.4 Alerting Configuration (0.5 days)

**File:** `docs/monitoring/ALERTING_SETUP.md`

**Deliverables:**
- AlertManager configuration
- Alert routing rules
- Notification channels (Slack, PagerDuty, email)
- Escalation policies

---

### Task 3: Runbook Documentation (3 days)

Create incident response and maintenance runbooks.

#### 3.1 Incident Response Runbooks (1.5 days)

**File:** `docs/runbooks/INCIDENT_RESPONSE.md`

**Runbooks to Create:**

**1. Resolution Failures**
```markdown
## Symptom
Resolver returning None for valid domain/key combinations

## Diagnosis
1. Check registration status: `oneiric.cli list --domain <domain>`
2. Verify candidates registered: Check resolver explain output
3. Review recent swaps: Check lifecycle status
4. Check logs: `{app="oneiric"} |= "resolver-decision"`

## Resolution
1. If no candidates: Register missing providers
2. If shadowed: Adjust stack_level/priority
3. If stale cache: Clear and re-sync
4. If config error: Fix selection in <domain>.yml

## Escalation
Contact: Platform team
SLO: P1 - 1 hour response
```

**2. Hot-Swap Failures**
```markdown
## Symptom
Lifecycle swap fails, rollback to previous provider

## Diagnosis
1. Check swap logs: `{app="oneiric"} |= "swap-failed"`
2. Verify new provider health: Check health check logs
3. Review factory errors: Check instantiation logs

## Resolution
1. If health check fails: Fix provider configuration
2. If factory error: Check import paths
3. If timeout: Increase health check timeout
4. Force swap: Use `--force` flag (with caution)

## Escalation
Contact: Provider owner (check metadata)
SLO: P2 - 4 hour response
```

**3. Remote Sync Failures**
```markdown
## Symptom
Remote manifest sync errors, stale components

## Diagnosis
1. Check sync status: `oneiric.cli remote-status`
2. Verify manifest URL: Check config
3. Test signature: Validate public key
4. Check network: Curl manifest URL

## Resolution
1. If signature invalid: Re-sign manifest
2. If digest mismatch: Re-upload artifact
3. If network error: Check firewall/DNS
4. If circuit breaker open: Wait for reset

## Escalation
Contact: Release engineering
SLO: P2 - 4 hour response
```

**4. Cache Corruption**
```markdown
## Symptom
Artifact digest mismatches, corrupted cache files

## Diagnosis
1. List cache contents: `ls .oneiric_cache/`
2. Check digest errors: `{app="oneiric"} |= "SHA256 mismatch"`
3. Verify disk space: `df -h`

## Resolution
1. Clear cache: `rm -rf .oneiric_cache/`
2. Re-sync: `oneiric.cli remote-sync --manifest <url>`
3. If disk full: Expand volume or implement cleanup

## Escalation
Contact: Infrastructure team
SLO: P3 - 8 hour response
```

**5. Memory Exhaustion**
```markdown
## Symptom
OOMKilled pods, high memory usage

## Diagnosis
1. Check memory metrics: Grafana dashboard
2. Review lifecycle instances: Active component count
3. Check cache size: `du -sh .oneiric_cache/`

## Resolution
1. If too many instances: Implement cleanup
2. If cache too large: Implement LRU eviction
3. If memory leak: Profile with memray
4. Emergency: Restart with increased limits

## Escalation
Contact: Platform team + SRE
SLO: P1 - 1 hour response
```

#### 3.2 Maintenance Runbooks (1 day)

**File:** `docs/runbooks/MAINTENANCE.md`

**Maintenance Tasks:**

**1. Version Upgrade**
```markdown
## Preparation
1. Review changelog
2. Test in staging environment
3. Create backup of config/cache

## Upgrade Process
1. Pull new version: `docker pull <image>:<tag>`
2. Update manifests: `kubectl apply -f deployment.yaml`
3. Monitor rollout: `kubectl rollout status deployment/oneiric`
4. Verify health: Check metrics/logs

## Rollback
1. If issues: `kubectl rollout undo deployment/oneiric`
2. Investigate: Review logs and metrics
3. Report: Create incident ticket
```

**2. Cache Cleanup**
```markdown
## Schedule
Weekly or when cache > 5GB

## Process
1. Pause remote sync: Set refresh_interval=0
2. Identify old artifacts: `find .oneiric_cache/ -mtime +30`
3. Remove stale files: Implement LRU cleanup
4. Resume sync: Restore refresh_interval

## Verification
1. Check cache size: `du -sh .oneiric_cache/`
2. Verify components: `oneiric.cli list --all`
3. Test resolution: `oneiric.cli explain <key>`
```

**3. Secret Rotation**
```markdown
## Schedule
Quarterly or on compromise

## Process
1. Generate new secrets
2. Update secret stores (K8s secrets, env vars)
3. Restart services: `kubectl rollout restart deployment/oneiric`
4. Verify: Test adapter connections

## Validation
1. Check adapter health: Monitor health check success rate
2. Review logs: Look for authentication errors
3. Test operations: Run smoke tests
```

#### 3.3 Troubleshooting Guide (0.5 days)

**File:** `docs/runbooks/TROUBLESHOOTING.md`

**Common Issues:**
- Resolution returns None
- Swap fails repeatedly
- Remote sync hangs
- High latency (p99 > 100ms)
- Cache disk full
- Health checks failing

**Each issue includes:**
- Symptoms
- Diagnostic commands
- Log queries
- Resolution steps
- Prevention tips

---

### ~~Task 4: ACB Migration & Deprecation~~ (SKIPPED)

**Status:** ❌ Removed from scope per user feedback - internal use only, no backward compatibility requirements.

---

### Task 4: Final Audit & Documentation Updates (2 days)

#### 4.1 Comprehensive Final Audit (1 day)

**File:** `docs/FINAL_AUDIT_STAGE5.md`

**Audit Checklist:**

**1. Functionality Audit**
- [ ] All 11 CLI commands functional
- [ ] All 18 adapters working
- [ ] All 14 actions working
- [ ] Remote manifest loading works
- [ ] Hot-swapping works across all domains
- [ ] Health checks functional
- [ ] Pause/drain state management works

**2. Security Audit**
- [ ] All P0 vulnerabilities resolved
- [ ] Factory allowlist enforced
- [ ] Signature verification working
- [ ] Path traversal prevented
- [ ] HTTP timeouts configured
- [ ] Input validation comprehensive

**3. Testing Audit**
- [ ] 83%+ test coverage maintained
- [ ] All 566+ tests passing
- [ ] Security tests comprehensive
- [ ] Integration tests complete
- [ ] Performance benchmarks acceptable

**4. Documentation Audit**
- [ ] README up to date
- [ ] Architecture docs complete
- [ ] Deployment guides exist
- [ ] Runbooks comprehensive
- [ ] Migration guide clear

**5. Operational Audit**
- [ ] Monitoring configured
- [ ] Alerting rules defined
- [ ] Runbooks tested
- [ ] Deployment guides validated
- [ ] Migration path clear

#### 4.2 Documentation Updates (1 day)

**Files to Update:**

**1. README.md**
- Add "Production Ready" badge
- Update installation instructions
- Add deployment quick links
- Add migration notice

**2. CLAUDE.md**
- Update status from Alpha to Beta
- Add Stage 5 completion notes
- Update score from 68/100 to 95/100

**3. NEW_ARCH_SPEC.md**
- Mark all phases complete
- Add production deployment section
- Add monitoring integration notes

**4. ROADMAP_SUMMARY.md**
- Mark Stages 0-5 complete
- Add v1.0 roadmap
- Add deprecation timeline

---

## Timeline & Milestones

### Week 1: Deployment & Monitoring
- **Days 1-2:** Docker deployment guide + Dockerfile
- **Day 3:** Kubernetes deployment guide + manifests
- **Day 4:** Systemd deployment guide
- **Day 5:** Prometheus setup + alert rules

### Week 2: Monitoring & Runbooks
- **Day 1:** Grafana dashboards + Loki setup
- **Day 2:** AlertManager configuration
- **Days 3-4:** Incident response runbooks (5 scenarios)
- **Day 5:** Maintenance runbooks + troubleshooting guide

### Week 3: Migration & Audit
- **Days 1-2:** ACB migration guide + deprecation notices
- **Day 3:** Final comprehensive audit
- **Day 4:** Documentation updates (README, specs, roadmaps)
- **Day 5:** Beta launch preparation + announcement

**Total:** 15 working days (3 calendar weeks)

---

## Success Criteria

**Stage 5 is complete when:**

1. ✅ Production deployment guides exist for Docker, Kubernetes, systemd
2. ✅ Monitoring infrastructure configured (Prometheus, Grafana, Loki)
3. ✅ Alerting rules defined with escalation policies
4. ✅ Runbooks cover 5+ incident scenarios
5. ✅ ACB migration guide complete with timeline
6. ✅ Final audit shows 95/100 quality score
7. ✅ All documentation updated and consistent

**Beta Launch Checklist:**
- [ ] Stage 5 100% complete
- [ ] Security review passed
- [ ] Performance benchmarks met
- [ ] Documentation peer-reviewed
- [ ] Migration guide validated with pilot users

---

## Deliverables Summary

| Category | Files | Lines | Status |
|----------|-------|-------|--------|
| **Deployment Guides** | 3 | 1,500 | Pending |
| **Monitoring Docs** | 4 | 1,200 | Pending |
| **Runbooks** | 3 | 1,000 | Pending |
| **Migration Guides** | 2 | 800 | Pending |
| **Audit Reports** | 1 | 300 | Pending |
| **Doc Updates** | 4 | 200 | Pending |
| **Total** | **17** | **5,000** | **0% → 100%** |

---

## Next Action

Start with Task 1.1: Create Docker deployment guide and Dockerfile.

This is the foundation for all other deployment modes and will establish
the production deployment patterns.

---

**Plan Created:** 2025-11-26
**Target Completion:** 2025-12-20 (3 weeks)
**Priority:** P0 - Required for Beta Launch
