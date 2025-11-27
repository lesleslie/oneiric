# Incident Response Runbooks for Oneiric

**Last Updated:** 2025-11-26
**Status:** Production Ready
**Maintainer:** Platform Team

---

## Table of Contents

1. [Overview](#overview)
2. [Incident Severity Levels](#incident-severity-levels)
3. [General Incident Response Process](#general-incident-response-process)
4. [Runbook Index](#runbook-index)
5. [Runbooks](#runbooks)
   - [1. Resolution Failures](#runbook-1-resolution-failures)
   - [2. Hot-Swap Failures](#runbook-2-hot-swap-failures)
   - [3. Remote Sync Failures](#runbook-3-remote-sync-failures)
   - [4. Cache Corruption](#runbook-4-cache-corruption)
   - [5. Memory Exhaustion](#runbook-5-memory-exhaustion)
6. [Post-Incident Review](#post-incident-review)
7. [Escalation Matrix](#escalation-matrix)

---

## Overview

This document provides step-by-step incident response procedures for common Oneiric operational issues. Each runbook includes:

- **Symptoms:** How to identify the incident
- **Diagnosis:** Tools and commands to investigate
- **Resolution:** Step-by-step fix procedures
- **Prevention:** How to avoid recurrence
- **Escalation:** When and who to contact

### Quick Access

| Alert | Runbook | Severity | Response Time |
|-------|---------|----------|---------------|
| `OneiricResolutionFailureRateHigh` | [#1](#runbook-1-resolution-failures) | Critical | < 5 min |
| `OneiricLifecycleSwapFailureRateHigh` | [#2](#runbook-2-hot-swap-failures) | Critical | < 5 min |
| `OneiricRemoteSyncConsecutiveFailures` | [#3](#runbook-3-remote-sync-failures) | Critical | < 15 min |
| `OneiricDigestVerificationFailed` | [#4](#runbook-4-cache-corruption) | Critical | < 5 min |
| `OneiricActiveInstancesExtremelyHigh` | [#5](#runbook-5-memory-exhaustion) | Critical | < 10 min |

---

## Incident Severity Levels

### P0 - Critical (SLA Impact)

- **Response Time:** < 5 minutes
- **Resolution Target:** < 1 hour
- **Notification:** Page on-call immediately
- **Examples:** Resolution failures > 5%, security breaches, system down

### P1 - High (Degraded Service)

- **Response Time:** < 15 minutes
- **Resolution Target:** < 4 hours
- **Notification:** Slack critical channel + email
- **Examples:** Swap failures, remote sync issues, high latency

### P2 - Medium (Limited Impact)

- **Response Time:** < 1 hour
- **Resolution Target:** < 8 hours
- **Notification:** Slack warning channel
- **Examples:** Health check failures, cache growth, warnings

### P3 - Low (Monitoring Issue)

- **Response Time:** < 4 hours
- **Resolution Target:** < 24 hours
- **Notification:** Slack info channel
- **Examples:** Info alerts, maintenance notifications

---

## General Incident Response Process

### Phase 1: Acknowledge (< 5 min)

1. **Acknowledge alert** in PagerDuty/AlertManager
2. **Join incident channel** (Slack #incident-response)
3. **Announce response:** "I'm investigating [INCIDENT]"
4. **Silence related alerts** to reduce noise

### Phase 2: Diagnose (< 15 min)

1. **Check monitoring:** Grafana dashboards, Prometheus alerts
2. **Review logs:** Loki queries for errors
3. **Identify root cause:** Use runbook diagnosis section
4. **Update incident channel** with findings

### Phase 3: Resolve (Variable)

1. **Follow runbook resolution steps**
2. **Document actions taken** in incident channel
3. **Verify fix:** Check metrics/logs for improvement
4. **Update stakeholders** on progress

### Phase 4: Verify (< 10 min)

1. **Confirm resolution:** Metrics/alerts return to normal
2. **Test functionality:** Run smoke tests
3. **Monitor for recurrence:** Watch for 30 minutes
4. **Remove silences** if stable

### Phase 5: Close (< 30 min)

1. **Update incident ticket** with resolution
2. **Schedule post-incident review** (within 48 hours)
3. **Document learnings** in incident log
4. **Close alerts** in AlertManager

---

## Runbook Index

| # | Runbook | Symptoms | Severity | Est. Time |
|---|---------|----------|----------|-----------|
| 1 | [Resolution Failures](#runbook-1-resolution-failures) | Components not resolving, errors | P0 | 15-30 min |
| 2 | [Hot-Swap Failures](#runbook-2-hot-swap-failures) | Swaps failing, rollbacks | P0 | 20-45 min |
| 3 | [Remote Sync Failures](#runbook-3-remote-sync-failures) | Cannot fetch manifests | P1 | 15-30 min |
| 4 | [Cache Corruption](#runbook-4-cache-corruption) | Digest mismatches | P0 | 10-20 min |
| 5 | [Memory Exhaustion](#runbook-5-memory-exhaustion) | OOMKilled, high memory | P0 | 20-40 min |

---

## Runbooks

---

## Runbook 1: Resolution Failures

**Alert:** `OneiricResolutionFailureRateHigh`
**Severity:** P0 - Critical
**Response Time:** < 5 minutes
**Owner:** Platform Team

### Symptoms

- Alert firing: "Oneiric resolution failure rate exceeds 5%"
- Components cannot be discovered/resolved
- Application errors: "No candidate found for domain/key"
- Grafana: Resolution success rate < 95%

### Impact

- **User Impact:** Application features broken, requests failing
- **SLA Impact:** High - service degradation
- **Affected Domains:** Varies (check alert labels)

### Diagnosis

**Step 1: Check Resolution Dashboard**

```bash
# Access Grafana Resolution Dashboard
open http://grafana:3000/d/oneiric-resolution

# Key metrics to review:
# - Resolution success rate (should be > 99%)
# - Resolution failures by domain
# - Recent error spikes
```

**Step 2: Query Failed Resolutions**

```promql
# Failed resolutions in last 5 minutes
sum(rate(oneiric_resolution_total{outcome="failed"}[5m])) by (domain, key)

# Resolution error rate
(1 - oneiric:resolution_success_rate_global:5m) * 100
```

**Step 3: Check Logs for Errors**

```logql
# Failed resolution logs
{app="oneiric"} | json | event="resolver-decision" | outcome="failed"

# Group by domain/key to find patterns
{app="oneiric"} | json | event="resolver-decision" | outcome="failed" | line_format "{{.domain}}/{{.key}}"
```

**Step 4: Check Registered Candidates**

```bash
# List all registered candidates
uv run python -m oneiric.cli list --domain adapter --json

# Check specific domain
uv run python -m oneiric.cli list --domain service --json

# Explain why resolution is failing
uv run python -m oneiric.cli explain status --domain service
```

**Step 5: Common Root Causes**

- ✅ **No candidates registered** - Check registration flow
- ✅ **All candidates shadowed** - Review stack_level/priority
- ✅ **Health check failures** - Investigate provider health
- ✅ **Config file errors** - Validate YAML syntax
- ✅ **Remote manifest issues** - Check remote sync status

### Resolution

#### Scenario A: No Candidates Registered

**Problem:** Resolver has no candidates for domain/key

```bash
# Step 1: Check if candidates are registered
uv run python -m oneiric.cli list --domain adapter

# Step 2: If empty, check registration flow
# - Verify plugins loaded
# - Check local config files exist
# - Verify remote manifest synced

# Step 3: Check plugin diagnostics
uv run python -m oneiric.cli plugins

# Step 4: Check remote sync status
uv run python -m oneiric.cli remote-status

# Step 5: Force remote sync if stale
uv run python -m oneiric.cli remote-sync --manifest <url>
```

**If plugins not loaded:**

```bash
# Check plugin entry points
python -c "import pkg_resources; print(list(pkg_resources.iter_entry_points('oneiric.adapters')))"

# Re-install plugins
uv pip install -e /path/to/plugin

# Restart Oneiric
docker restart oneiric
# OR
systemctl restart oneiric
```

#### Scenario B: All Candidates Shadowed

**Problem:** Candidates exist but all are shadowed (inactive)

```bash
# Step 1: List shadowed candidates
uv run python -m oneiric.cli list --domain adapter --show-shadowed

# Step 2: Check explain output for precedence
uv run python -m oneiric.cli explain status --domain service

# Step 3: Adjust selections in config
# Edit settings/<domain>.yml
vim settings/adapters.yml

# Add explicit selection:
# selections:
#   cache: redis  # Force redis provider

# Step 4: Reload config (watchers pick up changes automatically)
# Or restart if watchers disabled:
docker restart oneiric
```

**If stack_level issue:**

```bash
# Option 1: Adjust ONEIRIC_STACK_ORDER env var
export ONEIRIC_STACK_ORDER="myapp:20,oneiric:10,default:0"
docker restart oneiric

# Option 2: Edit metadata to increase stack_level
# (requires code change in adapter registration)
```

#### Scenario C: Health Check Failures

**Problem:** Candidates registered but health checks failing

```bash
# Step 1: Check lifecycle status
uv run python -m oneiric.cli status --domain adapter --key cache --json

# Step 2: Review recent health check failures
{app="oneiric"} | json | event="health-check-failed"

# Step 3: Probe specific instance
uv run python -m oneiric.cli health --probe --domain adapter --key cache

# Step 4: Check provider configuration
# Review settings/<domain>.yml for provider settings
vim settings/adapters.yml

# Step 5: Fix provider config (e.g., wrong Redis host)
# Update settings and reload
```

#### Scenario D: Config File Errors

**Problem:** Invalid YAML syntax in config files

```bash
# Step 1: Validate YAML syntax
python -c "import yaml; yaml.safe_load(open('settings/adapters.yml'))"

# Step 2: Check for common issues:
# - Missing colons
# - Incorrect indentation
# - Duplicate keys

# Step 3: Fix syntax errors
vim settings/adapters.yml

# Step 4: Verify fix
python -c "import yaml; yaml.safe_load(open('settings/adapters.yml'))"

# Step 5: Reload config
docker restart oneiric
```

### Verification

```bash
# Step 1: Check resolution success rate
curl 'http://prometheus:9090/api/v1/query?query=oneiric:resolution_success_rate_global:5m'
# Expected: > 0.99

# Step 2: Query recent resolutions
{app="oneiric"} | json | event="resolver-decision" | outcome="success"

# Step 3: Check Grafana dashboard
open http://grafana:3000/d/oneiric-resolution
# Verify success rate > 99%

# Step 4: Test resolution manually
uv run python -m oneiric.cli explain status --domain adapter

# Step 5: Monitor for 15 minutes to ensure stability
```

### Prevention

1. **Implement registration tests:** Unit tests verify candidates registered
2. **Config validation:** CI/CD validates YAML syntax before deploy
3. **Health check tuning:** Increase timeouts if providers slow to initialize
4. **Monitoring:** Alert on low candidate counts per domain
5. **Documentation:** Document registration process for each domain

### Escalation

- **Initial Response:** Platform engineer (on-call)
- **After 30 min:** Escalate to Platform Team Lead
- **After 1 hour:** Escalate to Engineering Manager
- **Contact:** platform-team@example.com, Slack #platform-oncall

---

## Runbook 2: Hot-Swap Failures

**Alert:** `OneiricLifecycleSwapFailureRateHigh`
**Severity:** P0 - Critical
**Response Time:** < 5 minutes
**Owner:** DevOps Team

### Symptoms

- Alert firing: "Oneiric swap failure rate exceeds 10%"
- Hot-swap operations failing
- Rollback operations occurring
- Configuration changes not applying

### Impact

- **User Impact:** Cannot deploy updates, stuck on old versions
- **SLA Impact:** High - deployment blocked
- **Affected Operations:** Configuration updates, version upgrades

### Diagnosis

**Step 1: Check Lifecycle Dashboard**

```bash
# Access Grafana Lifecycle Dashboard
open http://grafana:3000/d/oneiric-lifecycle

# Key metrics:
# - Swap success rate (should be > 95%)
# - Rollback rate
# - Swap failure reasons
```

**Step 2: Query Failed Swaps**

```promql
# Failed swaps in last 5 minutes
sum(rate(oneiric_lifecycle_swap_total{outcome="failed"}[5m])) by (domain, key, provider)

# Rollback rate
rate(oneiric_lifecycle_swap_total{outcome="rollback"}[5m])
```

**Step 3: Check Swap Logs**

```logql
# Failed swap logs
{app="oneiric"} | json | event="swap-failed"

# Rollback logs
{app="oneiric"} | json | event="swap-rollback"

# Extract error messages
{app="oneiric"} | json | event="swap-failed" | line_format "{{.domain}}/{{.key}}: {{.error}}"
```

**Step 4: Check Lifecycle Status**

```bash
# Get lifecycle status for specific component
uv run python -m oneiric.cli status --domain adapter --key cache --json

# Check recent swap history
{app="oneiric"} | json | event=~"swap-(complete|failed|rollback)" | line_format "{{.timestamp}}: {{.event}} {{.domain}}/{{.key}}"
```

**Step 5: Common Root Causes**

- ✅ **Health check failures** - New instance fails health probes
- ✅ **Factory errors** - Cannot instantiate new provider
- ✅ **Timeout** - Swap takes longer than configured timeout
- ✅ **Cleanup failures** - Old instance cleanup fails
- ✅ **Hook errors** - Pre/post swap hooks fail

### Resolution

#### Scenario A: Health Check Failures

**Problem:** New instance fails health check during swap

```bash
# Step 1: Review health check logs
{app="oneiric"} | json | event="health-check-failed" | line_format "{{.provider}}: {{.error}}"

# Step 2: Check provider configuration
vim settings/adapters.yml
# Verify connection strings, credentials, ports

# Step 3: Test provider connectivity manually
# Example for Redis:
redis-cli -h redis-host -p 6379 PING

# Step 4: Increase health check timeout if needed
# Edit oneiric/core/config.py
# lifecycle:
#   health_timeout: 30  # seconds

# Step 5: Retry swap with longer timeout
uv run python -m oneiric.cli swap --domain adapter --key cache --provider redis
```

**If provider dependency missing:**

```bash
# Install missing dependencies
uv pip install redis aioredis

# Restart Oneiric
docker restart oneiric
```

#### Scenario B: Factory Import Errors

**Problem:** Cannot import or instantiate provider factory

```bash
# Step 1: Check factory error logs
{app="oneiric"} | json | event="swap-failed" | error=~".*ImportError.*"

# Step 2: Verify factory path in metadata
# Check adapter registration code
grep -r "factory=" oneiric/adapters/*.py

# Step 3: Test import manually
python -c "from myapp.adapters.cache import RedisCache; print(RedisCache)"

# Step 4: Fix import path if incorrect
# Update adapter metadata registration
vim myapp/adapters/__init__.py

# Step 5: Restart and retry
docker restart oneiric
uv run python -m oneiric.cli swap --domain adapter --key cache --provider redis
```

#### Scenario C: Swap Timeout

**Problem:** Swap operation exceeds timeout

```bash
# Step 1: Check swap duration metrics
histogram_quantile(0.95, rate(oneiric_lifecycle_swap_duration_ms_bucket[5m]))

# Step 2: Review slow swap logs
{app="oneiric"} | json | event="swap-complete" | duration_ms > 10000

# Step 3: Increase swap timeout
# Edit settings
vim settings/app.yml

# Add lifecycle config:
# lifecycle:
#   activation_timeout: 60
#   health_timeout: 30
#   cleanup_timeout: 30

# Step 4: Restart with new config
docker restart oneiric

# Step 5: Retry swap
uv run python -m oneiric.cli swap --domain adapter --key cache --provider redis
```

#### Scenario D: Cleanup Failures

**Problem:** Old instance cleanup fails but new instance active

```bash
# Step 1: Check cleanup error logs
{app="oneiric"} | json | event="cleanup-failed"

# Step 2: Manually cleanup if safe
# (Depends on provider - be cautious)

# Step 3: Force swap to bypass cleanup
uv run python -m oneiric.cli swap --domain adapter --key cache --provider redis --force

# Step 4: Fix cleanup logic in provider
# (Requires code change)

# Step 5: Monitor for resource leaks
# Check active instances count
oneiric:system_active_instances_total:5m
```

### Verification

```bash
# Step 1: Check swap success rate
curl 'http://prometheus:9090/api/v1/query?query=oneiric:lifecycle_swap_success_rate:5m'
# Expected: > 0.95

# Step 2: Verify component active
uv run python -m oneiric.cli status --domain adapter --key cache
# Expected: state="ready", provider="redis"

# Step 3: Test functionality
# Run smoke test for swapped component

# Step 4: Monitor for 15 minutes
# Watch for rollbacks or failures
```

### Prevention

1. **Health check tuning:** Increase timeouts for slow-initializing providers
2. **Factory validation:** Unit tests verify factory imports work
3. **Staged rollout:** Test swaps in staging before production
4. **Monitoring:** Alert on high rollback rates
5. **Cleanup hardening:** Ensure cleanup logic handles errors gracefully

### Escalation

- **Initial Response:** DevOps engineer (on-call)
- **After 30 min:** Escalate to DevOps Team Lead
- **After 1 hour:** Escalate to Provider Owner
- **Contact:** devops-team@example.com, Slack #devops-oncall

---

## Runbook 3: Remote Sync Failures

**Alert:** `OneiricRemoteSyncConsecutiveFailures`
**Severity:** P1 - High
**Response Time:** < 15 minutes
**Owner:** Infrastructure Team

### Symptoms

- Alert firing: "Remote sync failed 3+ consecutive times"
- Cannot fetch remote manifests
- Stale component versions
- Remote sync duration high or timing out

### Impact

- **User Impact:** Missing security updates, cannot pull new components
- **SLA Impact:** Medium - stale versions but service operational
- **Affected Operations:** Remote artifact updates, manifest changes

### Diagnosis

**Step 1: Check Remote Sync Dashboard**

```bash
# Access Grafana Remote Dashboard
open http://grafana:3000/d/oneiric-remote

# Key metrics:
# - Sync success rate (should be > 99%)
# - Last sync time
# - Sync latency
```

**Step 2: Query Sync Status**

```bash
# Check remote sync status
uv run python -m oneiric.cli remote-status

# Expected output:
# - Last sync time
# - Success/failure count
# - Per-domain registrations
```

**Step 3: Check Sync Error Logs**

```logql
# Remote sync errors
{app="oneiric"} | json | event="remote-sync-error"

# Network errors
{app="oneiric"} | json | event="remote-sync-error" | error=~".*timeout.*|.*connection.*"

# Signature verification errors
{app="oneiric"} | json | event="signature-verification-failed"
```

**Step 4: Test Manifest URL**

```bash
# Manually fetch manifest
curl -v https://manifests.example.com/oneiric/manifest.yaml

# Check DNS resolution
nslookup manifests.example.com

# Check network connectivity
ping manifests.example.com
```

**Step 5: Common Root Causes**

- ✅ **Network issues** - DNS, firewall, proxy blocking
- ✅ **Signature verification failed** - Key rotation, manifest tampering
- ✅ **Digest mismatch** - Artifact corruption or modified
- ✅ **Circuit breaker open** - Too many consecutive failures
- ✅ **Manifest syntax error** - Invalid YAML

### Resolution

#### Scenario A: Network Issues

**Problem:** Cannot reach remote manifest URL

```bash
# Step 1: Check network connectivity
ping manifests.example.com
curl -v https://manifests.example.com/oneiric/manifest.yaml

# Step 2: Check DNS resolution
nslookup manifests.example.com
host manifests.example.com

# Step 3: Check firewall/proxy
# Verify egress rules allow HTTPS to manifest host

# Step 4: Test from Oneiric container
docker exec -it oneiric curl -v https://manifests.example.com/oneiric/manifest.yaml

# Step 5: If network OK, check circuit breaker
# Wait for circuit breaker reset (default 60s)
# Or restart to reset immediately
docker restart oneiric
```

**If behind corporate proxy:**

```bash
# Set proxy environment variables
export HTTP_PROXY=http://proxy.example.com:8080
export HTTPS_PROXY=http://proxy.example.com:8080
export NO_PROXY=localhost,127.0.0.1

# Restart Oneiric with proxy vars
docker restart oneiric
```

#### Scenario B: Signature Verification Failed

**Problem:** ED25519 signature verification failing

```bash
# Step 1: Check signature verification logs
{app="oneiric"} | json | event="signature-verification-failed"

# Step 2: Verify public key configured
# Check settings/app.yml
vim settings/app.yml
# remote:
#   public_key: "ed25519_public_key_here"

# Step 3: If key rotated, update config
# Get new public key from manifest publisher
# Update settings/app.yml
# Restart Oneiric

# Step 4: Temporarily disable signature verification (NOT RECOMMENDED)
# Only for emergency debugging
# remote:
#   require_signature: false

# Step 5: Re-sign manifest with correct key
# Contact manifest publisher/release engineer
```

**Security Note:** Signature verification failures may indicate:
- Key rotation (legitimate)
- MITM attack (security breach)
- Manifest corruption (integrity issue)

**If suspected security issue, escalate immediately to security team.**

#### Scenario C: Digest Mismatch

**Problem:** SHA256 digest doesn't match cached artifact

```bash
# Step 1: Check digest errors
{app="oneiric"} | json | event="digest-check-failed"

# Step 2: Clear cache for affected artifact
rm -rf .oneiric_cache/artifacts/<artifact_name>

# Step 3: Force re-download
uv run python -m oneiric.cli remote-sync --manifest <url>

# Step 4: Verify digest matches
# Download artifact manually and check SHA256
wget <artifact_url>
sha256sum <artifact_file>

# Step 5: If digest still mismatches, artifact corrupted
# Contact release engineer to re-upload
```

#### Scenario D: Circuit Breaker Open

**Problem:** Too many failures triggered circuit breaker

```bash
# Step 1: Check circuit breaker state
# Look for "circuit breaker open" in logs
{app="oneiric"} | json | circuit_breaker="open"

# Step 2: Wait for reset timeout (default 60s)
# Or restart to reset immediately
docker restart oneiric

# Step 3: Fix underlying issue first
# (network, signature, etc.)

# Step 4: Retry sync after breaker resets
uv run python -m oneiric.cli remote-sync --manifest <url>

# Step 5: Adjust circuit breaker settings if too sensitive
# Edit settings/app.yml
# remote:
#   failure_threshold: 5  # Increase from 3
#   reset_timeout: 120     # Increase from 60
```

### Verification

```bash
# Step 1: Check sync success rate
curl 'http://prometheus:9090/api/v1/query?query=oneiric:remote_sync_success_rate:5m'
# Expected: > 0.99

# Step 2: Verify recent sync succeeded
uv run python -m oneiric.cli remote-status
# Check last_sync time is recent

# Step 3: Verify artifacts registered
uv run python -m oneiric.cli list --domain adapter
# Should include remote-sourced candidates

# Step 4: Monitor for 30 minutes
# Watch for sync failures
```

### Prevention

1. **Network monitoring:** Alert on DNS failures, connection timeouts
2. **Key rotation process:** Document procedure, test before production
3. **Manifest validation:** CI/CD validates manifest syntax before publish
4. **Circuit breaker tuning:** Adjust thresholds based on network reliability
5. **Artifact integrity:** Implement checksum verification in upload pipeline

### Escalation

- **Initial Response:** Infrastructure engineer (on-call)
- **After 30 min:** Escalate to Infrastructure Team Lead
- **After 1 hour:** Escalate to Release Engineer
- **If security issue:** Immediately escalate to Security Team
- **Contact:** infrastructure-team@example.com, Slack #infra-oncall

---

## Runbook 4: Cache Corruption

**Alert:** `OneiricDigestVerificationFailed`
**Severity:** P0 - Critical (Security)
**Response Time:** < 5 minutes
**Owner:** Security Team + Platform Team

### Symptoms

- Alert firing: "Artifact digest verification failed"
- SHA256 mismatch errors
- Corrupted cache files
- Possible security breach indicators

### Impact

- **User Impact:** Potentially running corrupted/malicious code
- **Security Impact:** Critical - possible supply chain attack
- **SLA Impact:** Critical - immediate action required

### Diagnosis

**Step 1: Assess Security Risk**

```bash
# Check if widespread or isolated
{app="oneiric"} | json | event="digest-check-failed" | line_format "{{.artifact}}: {{.expected_digest}} != {{.actual_digest}}"

# Multiple artifacts affected? = Possible attack
# Single artifact? = Likely corruption

# Check if digest changed in manifest
curl https://manifests.example.com/oneiric/manifest.yaml | grep sha256
```

**Step 2: Isolate Affected Systems**

```bash
# If suspected attack:
# 1. Stop Oneiric immediately
docker stop oneiric
systemctl stop oneiric

# 2. Preserve evidence
cp -r .oneiric_cache /tmp/evidence-$(date +%Y%m%d-%H%M%S)

# 3. Notify security team
# Slack #security-incidents
```

**Step 3: Investigate Root Cause**

```bash
# Check disk errors (corruption)
dmesg | grep -i error
smartctl -a /dev/sda

# Check file system integrity
fsck /dev/sda1

# Check for unauthorized modifications
stat .oneiric_cache/artifacts/<artifact>
ls -la .oneiric_cache/artifacts/
```

**Step 4: Verify Manifest Integrity**

```bash
# Re-download manifest from trusted source
curl -o manifest-fresh.yaml https://manifests.example.com/oneiric/manifest.yaml

# Compare with cached version
diff .oneiric_cache/manifest.yaml manifest-fresh.yaml

# Verify signature
# (Oneiric does this automatically, but verify manually)
```

### Resolution

#### Scenario A: Single Artifact Corruption (Disk Error)

**Problem:** One artifact corrupted, likely disk issue

```bash
# Step 1: Clear corrupted artifact
rm -f .oneiric_cache/artifacts/<corrupted_artifact>

# Step 2: Force re-download
uv run python -m oneiric.cli remote-sync --manifest <url>

# Step 3: Verify new digest matches
{app="oneiric"} | json | event="digest-check-success" | artifact="<artifact>"

# Step 4: Check disk health
smartctl -a /dev/sda
dmesg | grep -i error

# Step 5: If disk failing, replace hardware
# Schedule maintenance window
```

#### Scenario B: Multiple Artifacts Corrupted (Possible Attack)

**Problem:** Many artifacts affected, possible security breach

```bash
# Step 1: STOP ALL ONEIRIC INSTANCES
docker stop $(docker ps -q --filter "name=oneiric")

# Step 2: Preserve evidence
tar czf /tmp/oneiric-cache-$(date +%Y%m%d-%H%M%S).tar.gz .oneiric_cache/

# Step 3: Notify security team immediately
# Slack #security-incidents
# Email: security@example.com
# Page: security-oncall

# Step 4: Security team investigates
# - Check manifest source for compromise
# - Verify signature chain
# - Analyze artifacts for malicious code

# Step 5: Once cleared, full cache rebuild
rm -rf .oneiric_cache/
uv run python -m oneiric.cli remote-sync --manifest <trusted_url>

# Step 6: Restart with clean cache
docker start oneiric
```

#### Scenario C: Manifest Tampering

**Problem:** Manifest digest changed, possible MITM

```bash
# Step 1: Verify manifest signature
# Oneiric logs signature verification result
{app="oneiric"} | json | event="signature-verification-failed"

# Step 2: If signature fails, DO NOT PROCEED
# This indicates manifest tampering or MITM attack

# Step 3: Notify security team
# Escalate to P0 security incident

# Step 4: Investigate network path
# Check for proxy, firewall, CDN issues
# Verify TLS certificates

# Step 5: Once resolved, update public key if rotated
# Or fix network issue if MITM
```

### Verification

```bash
# Step 1: Verify all digests match
curl 'http://prometheus:9090/api/v1/query?query=rate(oneiric_remote_digest_checks_total{outcome="failed"}[5m])'
# Expected: 0

# Step 2: Check recent digest verifications
{app="oneiric"} | json | event="digest-check-success"

# Step 3: List cached artifacts
ls -lh .oneiric_cache/artifacts/

# Step 4: Verify no security alerts
curl http://alertmanager:9093/api/v2/alerts | jq '.[] | select(.labels.component=="security")'
# Expected: empty

# Step 5: Monitor for 1 hour
# Watch for recurrence
```

### Prevention

1. **Disk monitoring:** Alert on disk errors, SMART failures
2. **Manifest signing:** Always verify ED25519 signatures
3. **Network security:** Use TLS, certificate pinning
4. **Access control:** Restrict who can publish manifests
5. **Audit logging:** Log all manifest/artifact changes
6. **Incident response drills:** Practice security scenarios

### Escalation

- **Initial Response:** Security engineer (on-call) + Platform engineer
- **Immediate:** Notify Security Team Lead
- **Immediately:** Notify CISO if widespread compromise suspected
- **Contact:** security@example.com, Slack #security-incidents
- **PagerDuty:** security-critical escalation policy

**NOTE:** This is a security incident. Follow your organization's security incident response procedures.

---

## Runbook 5: Memory Exhaustion

**Alert:** `OneiricActiveInstancesExtremelyHigh`
**Severity:** P0 - Critical
**Response Time:** < 10 minutes
**Owner:** Platform Team + SRE

### Symptoms

- Alert firing: "200+ active instances, risk of memory exhaustion"
- OOMKilled pods in Kubernetes
- High memory usage
- Application slowdown or crashes

### Impact

- **User Impact:** Application crash, service unavailability
- **SLA Impact:** Critical - service down risk
- **Affected Systems:** Entire Oneiric runtime

### Diagnosis

**Step 1: Check Memory Metrics**

```bash
# Access Grafana Performance Dashboard
open http://grafana:3000/d/oneiric-performance

# Check:
# - Active instances count
# - Memory usage estimate
# - Memory growth rate
```

**Step 2: Query Active Instances**

```promql
# Total active instances
oneiric:system_active_instances_total:5m

# By domain
sum(oneiric_lifecycle_active_instances) by (domain)

# Memory estimate (50MB per instance)
oneiric:system_memory_usage_estimate_bytes:5m / (1024^3)
```

**Step 3: Check System Memory**

```bash
# Container memory usage
docker stats oneiric

# Kubernetes pod memory
kubectl top pod -l app=oneiric -n oneiric

# System memory (bare metal)
free -h
vmstat 1
```

**Step 4: Identify Instance Leak**

```bash
# Check lifecycle status
uv run python -m oneiric.cli status --domain adapter --json

# List all active instances
{app="oneiric"} | json | event="instance-activated" | line_format "{{.domain}}/{{.key}}: {{.provider}}"

# Check for instances not being cleaned up
# Compare activation vs cleanup counts
sum(oneiric_lifecycle_swap_total) - sum(oneiric_lifecycle_cleanup_total)
```

### Resolution

#### Scenario A: Instance Leak (Cleanup Not Called)

**Problem:** Old instances not being cleaned up after swaps

```bash
# Step 1: Check cleanup logs
{app="oneiric"} | json | event=~"cleanup-(started|complete|failed)"

# Step 2: If cleanup not called, code bug
# Emergency: Restart to force cleanup
docker restart oneiric

# Step 3: Monitor instance count after restart
oneiric:system_active_instances_total:5m

# Step 4: Fix cleanup logic (code change required)
# Ensure lifecycle.swap() calls cleanup_old()

# Step 5: Deploy fix
# Build new image, deploy to production
```

#### Scenario B: Memory Leak in Provider

**Problem:** Provider holding references, not being garbage collected

```bash
# Step 1: Profile memory usage
# Install memray
uv pip install memray

# Step 2: Run with memory profiling
memray run --live-port 8000 -m oneiric.cli orchestrate

# Step 3: Access live dashboard
open http://localhost:8000

# Step 4: Identify leaking provider
# Look for increasing memory in flamegraph

# Step 5: Fix provider cleanup
# Ensure __del__() or cleanup() releases resources

# Step 6: Deploy fix
docker build -t oneiric:fixed .
docker stop oneiric && docker run -d --name oneiric oneiric:fixed
```

#### Scenario C: Too Many Domains/Keys

**Problem:** Legitimately high instance count, need more memory

```bash
# Step 1: Calculate required memory
# Formula: instances * 50MB + 500MB overhead
# 200 instances = 200 * 50 + 500 = 10.5GB

# Step 2: Increase memory limit (Docker)
docker update --memory 12g oneiric

# Step 3: Increase memory limit (Kubernetes)
kubectl patch deployment oneiric -p '{"spec":{"template":{"spec":{"containers":[{"name":"oneiric","resources":{"limits":{"memory":"12Gi"}}}]}}}}'

# Step 4: Increase memory limit (systemd)
sudo systemctl edit oneiric
# Add:
# [Service]
# MemoryMax=12G
sudo systemctl daemon-reload
sudo systemctl restart oneiric

# Step 5: Monitor memory usage
watch -n 5 'docker stats oneiric'
```

#### Scenario D: Rapid Swapping Loop

**Problem:** Components swapping rapidly, creating/destroying instances

```bash
# Step 1: Check swap rate
rate(oneiric_lifecycle_swap_total[5m])

# Step 2: Identify rapidly swapping components
sum(rate(oneiric_lifecycle_swap_total[5m])) by (domain, key)

# Step 3: Check for config watcher thrashing
# Look for rapid config file changes
{app="oneiric"} | json | event="config-changed" | line_format "{{.timestamp}}: {{.file}}"

# Step 4: Pause watchers temporarily
# Stop config watcher
# (Requires code change or CLI command)

# Step 5: Fix root cause
# - Debounce config changes
# - Increase watcher poll interval
# - Fix config that's changing rapidly
```

### Verification

```bash
# Step 1: Check instance count stabilized
curl 'http://prometheus:9090/api/v1/query?query=oneiric:system_active_instances_total:5m'
# Expected: < 100 (reasonable)

# Step 2: Check memory usage dropped
docker stats oneiric | head -2

# Step 3: Verify no OOMKills
# Docker:
docker inspect oneiric | jq '.[0].State.OOMKilled'
# Expected: false

# Kubernetes:
kubectl get events -n oneiric | grep OOMKilled
# Expected: no recent events

# Step 4: Monitor for 30 minutes
# Watch for memory growth
```

### Prevention

1. **Cleanup enforcement:** Unit tests verify cleanup called after swaps
2. **Memory limits:** Set appropriate limits per environment
3. **Monitoring:** Alert on high instance counts before critical
4. **Resource pooling:** Reuse instances where possible
5. **Profiling:** Regular memory profiling in staging

### Escalation

- **Initial Response:** Platform engineer (on-call)
- **After 20 min:** Escalate to SRE Team
- **After 1 hour:** Escalate to Engineering Manager
- **Contact:** platform-team@example.com, sre-team@example.com, Slack #platform-oncall

---

## Post-Incident Review

After resolving any P0 or P1 incident, schedule a post-incident review within 48 hours.

### PIR Template

```markdown
# Post-Incident Review: [INCIDENT NAME]

**Date:** 2025-11-26
**Incident ID:** INC-12345
**Severity:** P0 - Critical
**Duration:** 45 minutes
**Participants:** Alice (Platform), Bob (SRE), Carol (Engineering Manager)

## Summary

[1-2 sentence summary of incident]

## Timeline

| Time | Event |
|------|-------|
| 14:00 | Alert fired: OneiricResolutionFailureRateHigh |
| 14:02 | On-call acknowledged, began investigation |
| 14:10 | Root cause identified: config file syntax error |
| 14:15 | Fix deployed, config validated |
| 14:30 | Metrics returned to normal |
| 14:45 | Incident closed |

## Impact

- **User Impact:** 45 minutes of degraded service
- **Affected Users:** ~1,000 users
- **Revenue Impact:** ~$500 (estimated)

## Root Cause

[Detailed explanation of root cause]

## What Went Well

- Alert fired within 1 minute of issue
- On-call responded quickly (< 2 min)
- Runbook was accurate and helpful
- Fix deployed rapidly

## What Went Wrong

- Config validation not in CI/CD pipeline
- Lack of staging environment testing
- Insufficient monitoring of config changes

## Action Items

| Action | Owner | Due Date | Priority |
|--------|-------|----------|----------|
| Add config validation to CI/CD | Alice | 2025-12-01 | P0 |
| Implement staging environment | Bob | 2025-12-15 | P1 |
| Add config change monitoring | Carol | 2025-12-10 | P2 |

## Lessons Learned

[Key takeaways and learnings]
```

---

## Escalation Matrix

| Severity | Initial Response | After 30 min | After 1 hour | After 2 hours |
|----------|-----------------|--------------|--------------|---------------|
| **P0** | On-call engineer | Team Lead | Engineering Manager | Director of Engineering |
| **P1** | On-call engineer | Team Lead | Engineering Manager | - |
| **P2** | On-call engineer | Team Lead | - | - |
| **P3** | On-call engineer | - | - | - |

### Contact Information

| Team | Email | Slack | PagerDuty |
|------|-------|-------|-----------|
| **Platform** | platform@example.com | #platform-oncall | platform-escalation |
| **Security** | security@example.com | #security-incidents | security-critical |
| **DevOps** | devops@example.com | #devops-oncall | devops-escalation |
| **Infrastructure** | infra@example.com | #infra-oncall | infra-escalation |
| **SRE** | sre@example.com | #sre-oncall | sre-escalation |

---

## Additional Resources

- **Monitoring Dashboards:** http://grafana:3000/dashboards
- **Prometheus Alerts:** http://prometheus:9090/alerts
- **AlertManager:** http://alertmanager:9093
- **Loki Logs:** http://grafana:3000/explore (Loki datasource)
- **Maintenance Runbooks:** `docs/runbooks/MAINTENANCE.md`
- **Troubleshooting Guide:** `docs/runbooks/TROUBLESHOOTING.md`

---

**Document Version:** 1.0
**Last Reviewed:** 2025-11-26
**Next Review:** 2026-02-26
**Feedback:** platform-team@example.com
