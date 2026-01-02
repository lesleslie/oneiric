# Maintenance Runbooks for Oneiric

**Last Updated:** 2025-11-26
**Status:** Production Ready
**Maintainer:** Platform Team

______________________________________________________________________

## Table of Contents

1. \[[#overview|Overview]\]
1. \[[#maintenance-windows|Maintenance Windows]\]
1. \[[#pre-maintenance-checklist|Pre-Maintenance Checklist]\]
1. \[[#runbooks|Runbooks]\]
   - \[[#runbook-1-version-upgrade|1. Version Upgrade]\]
   - \[[#runbook-2-cache-cleanup|2. Cache Cleanup]\]
   - \[[#runbook-3-secret-rotation|3. Secret Rotation]\]
1. \[[#post-maintenance-checklist|Post-Maintenance Checklist]\]
1. \[[#rollback-procedures|Rollback Procedures]\]

______________________________________________________________________

## Overview

This document provides step-by-step procedures for planned maintenance operations on Oneiric. All maintenance should be performed during scheduled maintenance windows with proper communication and rollback plans.

### Maintenance Runbook Index

| # | Runbook | Frequency | Duration | Downtime |
|---|---------|-----------|----------|----------|
| 1 | \[[#runbook-1-version-upgrade|Version Upgrade]\] | Monthly | 30-60 min | 0-5 min |
| 2 | \[[#runbook-2-cache-cleanup|Cache Cleanup]\] | Weekly | 15-30 min | 0 min |
| 3 | \[[#runbook-3-secret-rotation|Secret Rotation]\] | Quarterly | 30-45 min | 5-10 min |

______________________________________________________________________

## Maintenance Windows

### Standard Windows

| Environment | Day | Time (UTC) | Duration | Notification |
|-------------|-----|------------|----------|--------------|
| **Production** | Tuesday | 02:00-04:00 | 2 hours | 72h advance |
| **Staging** | Monday | 18:00-20:00 | 2 hours | 24h advance |
| **Development** | Anytime | - | - | No notice |

### Emergency Maintenance

- **Trigger:** P0 security vulnerability, critical bug
- **Approval:** Engineering Manager + On-call Lead
- **Notification:** 1 hour advance (if possible)
- **Communication:** Status page + Slack + Email

______________________________________________________________________

## Pre-Maintenance Checklist

**Timing:** Complete 24 hours before maintenance

### 1. Communication

```markdown
- [ ] Schedule announced in Slack #engineering (72h advance)
- [ ] Email sent to stakeholders (72h advance)
- [ ] Status page updated (24h advance)
- [ ] On-call schedule confirmed
- [ ] Stakeholders acknowledged
```

### 2. Preparation

```bash
# Backup current configuration
tar czf oneiric-config-backup-$(date +%Y%m%d).tar.gz settings/

# Backup database/state
tar czf oneiric-cache-backup-$(date +%Y%m%d).tar.gz .oneiric_cache/

# Document current state
uv run python -m oneiric.cli status --json > pre-maintenance-status.json

# Test rollback procedure in staging
# (Run planned maintenance in staging first)
```

### 3. Monitoring

```bash
# Create silence for expected alerts
curl -X POST http://alertmanager:9093/api/v2/silences -d '{
  "matchers": [{"name": "alertname", "value": "Oneiric.*", "isRegex": true}],
  "startsAt": "2025-11-26T02:00:00Z",
  "endsAt": "2025-11-26T04:00:00Z",
  "createdBy": "platform-team",
  "comment": "Scheduled maintenance: Version upgrade"
}'

# Verify silences
curl http://alertmanager:9093/api/v2/silences | jq
```

### 4. Access

```bash
# Verify access to production
systemctl status oneiric      # Systemd

# Verify rollback artifacts available
ls -lh /backups/oneiric/

# Test communication channels
# Send test message to Slack #maintenance-updates
```

______________________________________________________________________

## Runbooks

______________________________________________________________________

## Runbook 1: Version Upgrade

**Frequency:** Monthly (or as needed)
**Duration:** 30-60 minutes
**Downtime:** 0-5 minutes (rolling update) or 5-10 minutes (full restart)
**Owner:** Platform Team

### Objective

Upgrade Oneiric to a new version while maintaining service availability and data integrity.

### Prerequisites

- ✅ Changelog reviewed and breaking changes identified
- ✅ New version tested in staging environment
- ✅ Backup of current config and cache created
- ✅ Rollback plan documented
- ✅ Maintenance window scheduled

### Procedure

```bash
# Set version variables for this run
CURRENT_VERSION="0.3.3"
TARGET_VERSION="0.2.4"
PREVIOUS_VERSION="0.2.2"
```

#### Step 1: Pre-Upgrade Validation (10 min)

```bash
# 1.1: Check current version
uv run python -m oneiric.cli --version
# Record: Current version = v${CURRENT_VERSION}

# 1.2: Check system health
uv run python -m oneiric.cli health --probe
# Verify: All checks passing

# 1.3: Document active components
uv run python -m oneiric.cli list --all > pre-upgrade-components.txt

# 1.4: Check metrics baseline
curl 'http://prometheus:9090/api/v1/query?query=oneiric:resolution_success_rate_global:5m'
# Record: Success rate = 99.8%

# 1.5: Review recent errors
{app="oneiric"} | json | level="error" | __timestamp__ > 1h
# Verify: No unexpected errors
```

#### Step 2: Staging Deployment (Test in Staging First)

```bash
# 2.1: Deploy to staging
  -v $(pwd)/settings:/app/settings \
  oneiric:${TARGET_VERSION}-staging


# 2.2: Smoke test staging
uv run python -m oneiric.cli health --probe --environment staging
# Verify: All checks pass

# 2.3: Load test staging (optional)
# Run automated test suite
pytest tests/integration/

# 2.4: Monitor staging for 30 minutes
# Check metrics, logs, alerts
# Decision: Proceed to production or rollback
```

#### Step 3: Production Deployment (Actual Upgrade)

Use the Cloud Run build/deploy flow in `docs/deployment/CLOUD_RUN_BUILD.md` for serverless upgrades. For local agents, follow the systemd path below.

**Option C: Systemd Service Update (Brief Downtime)**

```bash
# 3.1: Update service file if needed
sudo vim /etc/systemd/system/oneiric.service
# Update ExecStart path if changed

# 3.2: Install new version
uv pip install oneiric==${TARGET_VERSION}

# 3.3: Reload systemd
sudo systemctl daemon-reload

# 3.4: Restart service
sudo systemctl restart oneiric
# Downtime: ~5-10 seconds

# 3.5: Verify service running
sudo systemctl status oneiric
# Expected: active (running)
```

#### Step 4: Post-Upgrade Validation (15 min)

```bash
# 4.1: Verify version updated
uv run python -m oneiric.cli --version
# Expected: v${TARGET_VERSION}

# 4.2: Health check
uv run python -m oneiric.cli health --probe
# Expected: All checks passing

# 4.3: Check active components
uv run python -m oneiric.cli list --all
# Compare with pre-upgrade-components.txt
# Verify: Same components active

# 4.4: Check metrics
curl 'http://prometheus:9090/api/v1/query?query=oneiric:resolution_success_rate_global:5m'
# Expected: > 99%

# 4.5: Review logs for errors
{app="oneiric"} | json | level="error" | __timestamp__ > 5m
# Expected: No critical errors

# 4.6: Test key functionality
# Resolution
uv run python -m oneiric.cli explain status --domain adapter

# Swapping
uv run python -m oneiric.cli swap --domain adapter --key cache --provider redis --dry-run

# Remote sync
uv run python -m oneiric.cli remote-status
```

#### Step 5: Monitor and Stabilize (30 min)

```bash
# 5.1: Watch Grafana dashboards
open http://grafana:3000/d/oneiric-overview
# Monitor: Success rates, latency, errors

# 5.2: Monitor AlertManager
open http://alertmanager:9093
# Expected: No firing alerts

# 5.3: Stream logs
{app="oneiric"} | json
# Watch for: Errors, warnings, unusual patterns

# 5.4: Check resource usage
# Verify: CPU/memory within normal range

# 5.5: If stable after 30 min, remove silence
curl -X DELETE http://alertmanager:9093/api/v2/silence/<silence-id>
```

### Rollback Procedure

**If upgrade causes issues, rollback immediately:**

```bash
# 1. Stop new version


# 3. Start old version

# 4. Verify health
uv run python -m oneiric.cli health --probe
# 1. Rollback deployment

# 2. Verify rollback

# 3. Check pods
```

**Systemd:**

```bash
# 1. Reinstall old version
uv pip install oneiric==${PREVIOUS_VERSION}

# 2. Restart service
sudo systemctl restart oneiric

# 3. Verify version
uv run python -m oneiric.cli --version
```

### Success Criteria

- ✅ New version running (verified with --version)
- ✅ All health checks passing
- ✅ Resolution success rate > 99%
- ✅ No critical errors in logs
- ✅ Same components active as pre-upgrade
- ✅ Monitoring shows normal metrics
- ✅ No customer complaints/issues

### Post-Maintenance Tasks

```bash
# 1. Update documentation
echo "v${TARGET_VERSION} deployed to production on $(date)" >> CHANGELOG.md

# 2. Remove backup after 7 days (if stable)
# (Schedule cleanup)

# 3. Update deployment tracking
# (Update deployment tracker/spreadsheet)

# 4. Announce completion
# Slack: "Oneiric upgraded to v${TARGET_VERSION} successfully"
```

______________________________________________________________________

## Runbook 2: Cache Cleanup

**Frequency:** Weekly (or when cache > 5GB)
**Duration:** 15-30 minutes
**Downtime:** 0 minutes
**Owner:** Platform Team

### Objective

Clean up old cached artifacts to prevent disk space exhaustion while maintaining recent/active artifacts.

### Prerequisites

- ✅ Cache size exceeds 5GB or cleanup scheduled
- ✅ Remote manifest available for re-sync if needed
- ✅ Maintenance window scheduled (low-traffic period)

### Procedure

#### Step 1: Cache Assessment (5 min)

```bash
# 1.1: Check current cache size
du -sh .oneiric_cache/
# Example: 7.2G

# 1.2: Check cache breakdown
du -h .oneiric_cache/ | sort -rh | head -20
# Identify large directories

# 1.3: List cached artifacts
ls -lh .oneiric_cache/artifacts/
# Note: artifact names, sizes, dates

# 1.4: Check artifact age
find .oneiric_cache/artifacts/ -type f -mtime +30
# Files not accessed in 30+ days

# 1.5: Check disk usage
df -h /  # Total disk usage
# Ensure cleanup won't cause issues if artifacts re-downloaded
```

#### Step 2: Pause Remote Sync (Optional)

```bash
# 2.1: Temporarily stop remote refresh loop
# Option A: Set refresh_interval to 0 (requires restart)
# Edit settings/app.yml:
# remote:
#   refresh_interval: 0

# Option B: Create pause file (if supported)
touch .oneiric_cache/.pause_sync

# Option C: Stop orchestrator (if running standalone)
```

#### Step 3: Identify Cleanup Candidates (5 min)

```bash
# 3.1: List old artifacts (> 30 days)
find .oneiric_cache/artifacts/ -type f -mtime +30 -ls > old-artifacts.txt

# 3.2: Check if any are still in use
# Compare with current manifest
curl https://manifests.example.com/oneiric/manifest.yaml | grep -A 5 "artifacts:"

# 3.3: Identify safe-to-delete artifacts
# Artifacts NOT in current manifest AND > 30 days old

# 3.4: Calculate space savings
find .oneiric_cache/artifacts/ -type f -mtime +30 -exec du -ch {} + | tail -1
# Example: 3.5GB can be freed
```

#### Step 4: Perform Cleanup (10 min)

```bash
# 4.1: Backup artifacts being deleted (optional, if cautious)
mkdir -p /tmp/oneiric-cache-backup-$(date +%Y%m%d)
find .oneiric_cache/artifacts/ -type f -mtime +30 -exec cp {} /tmp/oneiric-cache-backup-$(date +%Y%m%d)/ \;

# 4.2: Delete old artifacts
find .oneiric_cache/artifacts/ -type f -mtime +30 -delete
# Alternative: Move to trash first
find .oneiric_cache/artifacts/ -type f -mtime +30 -exec mv {} /tmp/trash/ \;

# 4.3: Clean up old manifest snapshots (keep last 10)
ls -t .oneiric_cache/manifest-*.yaml | tail -n +11 | xargs rm -f

# 4.4: Clean up old logs (if file logging enabled)
find /var/log/oneiric/ -name "*.log" -mtime +7 -delete

# 4.5: Optimize cache directory structure
# Remove empty directories
find .oneiric_cache/ -type d -empty -delete
```

#### Step 5: Resume Operations (5 min)

```bash
# 5.1: Resume remote sync
# Option A: Restore refresh_interval
# Edit settings/app.yml:
# remote:
#   refresh_interval: 300  # 5 minutes

# Option B: Remove pause file
rm -f .oneiric_cache/.pause_sync

# Option C: Restart orchestrator

# 5.2: Force immediate sync to re-download if needed
uv run python -m oneiric.cli remote-sync --manifest https://manifests.example.com/oneiric/manifest.yaml

# 5.3: Verify cache size reduced
du -sh .oneiric_cache/
# Expected: ~3.7G (down from 7.2G)

# 5.4: Check components still work
uv run python -m oneiric.cli list --all
# Verify: All components still registered

# 5.5: Monitor for re-downloads
{app="oneiric"} | json | event="artifact-download"
```

### Automated Cleanup (Recommended)

**Create cron job for automatic cleanup:**

```bash
# Add to crontab
crontab -e

# Run cleanup weekly on Sunday at 2am
0 2 * * 0 /usr/local/bin/oneiric-cache-cleanup.sh

# Cleanup script:
#!/bin/bash
# /usr/local/bin/oneiric-cache-cleanup.sh

CACHE_DIR="/app/.oneiric_cache"
MAX_AGE_DAYS=30
LOG_FILE="/var/log/oneiric/cache-cleanup.log"

echo "$(date): Starting cache cleanup" >> $LOG_FILE

# Delete old artifacts
DELETED=$(find $CACHE_DIR/artifacts/ -type f -mtime +$MAX_AGE_DAYS -delete -print | wc -l)

echo "$(date): Deleted $DELETED old artifacts" >> $LOG_FILE

# Check new cache size
NEW_SIZE=$(du -sh $CACHE_DIR | cut -f1)
echo "$(date): Cache size now: $NEW_SIZE" >> $LOG_FILE
```

### Success Criteria

- ✅ Cache size reduced (e.g., 7.2GB → 3.7GB)
- ✅ Disk space freed up
- ✅ All active components still registered
- ✅ No resolution failures after cleanup
- ✅ Remote sync resumed successfully

### Troubleshooting

**Problem:** Deleted artifact still needed

```bash
# Re-download from manifest
uv run python -m oneiric.cli remote-sync --manifest <url>

# Or restore from backup
cp /tmp/oneiric-cache-backup-20251126/<artifact> .oneiric_cache/artifacts/
```

______________________________________________________________________

## Runbook 3: Secret Rotation

**Frequency:** Quarterly (or on compromise)
**Duration:** 30-45 minutes
**Downtime:** 5-10 minutes (brief restart)
**Owner:** Security Team + Platform Team

### Objective

Rotate secrets (database passwords, API keys, signing keys) to maintain security posture and comply with policies.

### Prerequisites

- ✅ New secrets generated and validated
- ✅ Rollback plan documented
- ✅ Maintenance window scheduled
- ✅ Security team notified

### Procedure

#### Step 1: Prepare New Secrets (10 min)

```bash
# 1.1: Generate new secrets
# Database password (example)
NEW_DB_PASSWORD=$(openssl rand -base64 32)

# API keys
NEW_API_KEY=$(uuidgen)

# ED25519 key pair for manifest signing
ssh-keygen -t ed25519 -f /tmp/oneiric-signing-key-new -N ""
NEW_PUBLIC_KEY=$(cat /tmp/oneiric-signing-key-new.pub)
NEW_PRIVATE_KEY=$(cat /tmp/oneiric-signing-key-new)

# 1.2: Validate new secrets format
# Ensure compatible with providers

# 1.3: Store in secret management system
  --from-literal=db-password="$NEW_DB_PASSWORD" \
  --from-literal=api-key="$NEW_API_KEY" \
  --from-literal=signing-public-key="$NEW_PUBLIC_KEY" \
  -n oneiric

# Vault:
vault kv put secret/oneiric/secrets-new \
  db-password="$NEW_DB_PASSWORD" \
  api-key="$NEW_API_KEY"

cat > .env.new <<EOF
DB_PASSWORD=$NEW_DB_PASSWORD
API_KEY=$NEW_API_KEY
SIGNING_PUBLIC_KEY=$NEW_PUBLIC_KEY
EOF

# 1.4: Backup old secrets
```

#### Step 2: Update External Systems (10 min)

```bash
# 2.1: Update database with new credentials
# PostgreSQL example:
psql -h db-host -U admin -d postgres -c "ALTER USER oneiric_user WITH PASSWORD '$NEW_DB_PASSWORD';"

# 2.2: Update API provider with new keys
# (Depends on provider - example: Slack webhook)
# Update webhook URL in provider dashboard

# 2.3: Update manifest signing key in registry
# Upload new public key to manifest server
scp /tmp/oneiric-signing-key-new.pub registry:/etc/oneiric/signing-keys/

# 2.4: Re-sign manifests with new private key
# (On manifest publisher)
./sign-manifest.sh --key /tmp/oneiric-signing-key-new manifest.yaml

# 2.5: Verify new secrets work
# Test database connection:
psql -h db-host -U oneiric_user -d oneiric_db -c "SELECT 1;"
# Expected: Success
```

#### Step 3: Update Oneiric Configuration (15 min)

```bash
# 3.1: Stop Oneiric
# Downtime starts

# 3.2: Update environment file
mv .env .env.old
mv .env.new .env

# 3.3: Start with new secrets
# Downtime ends

# 3.4: Verify startup
# Check for: "Successfully connected to database"
# 3.1: Update secret reference in deployment
  -p '{"spec":{"template":{"spec":{"containers":[{"name":"oneiric","envFrom":[{"secretRef":{"name":"oneiric-secrets-new"}}]}]}}}}' \
  -n oneiric

# 3.2: Trigger rolling update

# 3.3: Watch rollout

# 3.4: Verify pods healthy
# Expected: All Running, READY 1/1
```

**Systemd:**

```bash
# 3.1: Update environment file
sudo mv /etc/oneiric/.env /etc/oneiric/.env.old
sudo cp .env.new /etc/oneiric/.env
sudo chmod 600 /etc/oneiric/.env

# 3.2: Restart service
sudo systemctl restart oneiric
# Downtime: ~5-10 seconds

# 3.3: Verify service running
sudo systemctl status oneiric
# Expected: active (running)
```

#### Step 4: Validation (10 min)

```bash
# 4.1: Health check
uv run python -m oneiric.cli health --probe
# Expected: All checks passing

# 4.2: Test database connection
{app="oneiric"} | json | event="database-connected"
# Expected: Recent log entry

# 4.3: Test external API calls
# (Depends on adapters - example: test cache adapter)
uv run python -m oneiric.cli explain status --domain adapter --key cache

# 4.4: Verify remote sync with new signing key
uv run python -m oneiric.cli remote-sync --manifest https://manifests.example.com/oneiric/manifest.yaml
# Expected: Success, signature verified

# 4.5: Check for authentication errors
{app="oneiric"} | json | level="error" | error=~".*auth.*|.*credential.*"
# Expected: No errors

# 4.6: Monitor metrics
curl 'http://prometheus:9090/api/v1/query?query=oneiric:resolution_success_rate_global:5m'
# Expected: > 99%
```

#### Step 5: Cleanup Old Secrets (After 7 days)

```bash
# Wait 7 days to ensure rollback not needed

# 5.1: Delete old secrets from secret store
# Rename new secrets to standard name

# 5.2: Rotate old signing keys out
# Remove from registry
ssh registry "rm /etc/oneiric/signing-keys/old-key.pub"

# 5.3: Document rotation
echo "$(date): Rotated secrets successfully" >> /var/log/oneiric/secret-rotation.log

# 5.4: Update secret rotation schedule
# Next rotation: Add 90 days to calendar
```

### Rollback Procedure

**If new secrets cause issues:**

```bash
# 1. Stop Oneiric
sudo systemctl stop oneiric  # Systemd

# 2. Restore old secrets
sudo cp /etc/oneiric/.env.old /etc/oneiric/.env  # Systemd

# 3. Restore old database password (if changed)
psql -h db-host -U admin -c "ALTER USER oneiric_user WITH PASSWORD '$OLD_DB_PASSWORD';"

# 4. Restart with old secrets
sudo systemctl start oneiric  # Systemd

# 5. Verify health
uv run python -m oneiric.cli health --probe
```

### Success Criteria

- ✅ New secrets applied successfully
- ✅ Oneiric running with new credentials
- ✅ Database connection works
- ✅ External API calls succeed
- ✅ Remote sync signature verification passes
- ✅ No authentication errors in logs
- ✅ Monitoring shows normal metrics

### Emergency Secret Rotation

**If secrets compromised, rotate immediately (skip maintenance window):**

```bash
# 1. Generate new secrets immediately
# (Follow Step 1 above)

# 2. Update external systems in parallel
# (Coordinate with Security team)

# 3. Apply new secrets with minimal downtime
# (Use blue-green deployment if possible)

# 4. Invalidate old secrets immediately
# (Revoke in secret management system)

# 5. Notify Security team
# Slack: #security-incidents
# Email: security@example.com
```

______________________________________________________________________

## Post-Maintenance Checklist

**Timing:** Complete within 1 hour of maintenance completion

### 1. Verification

```bash
# System health
uv run python -m oneiric.cli health --probe

# Metrics normal
curl 'http://prometheus:9090/api/v1/query?query=oneiric:resolution_success_rate_global:5m'

# No critical errors
{app="oneiric"} | json | level="error" | __timestamp__ > 1h

# Remove alert silences
curl -X DELETE http://alertmanager:9093/api/v2/silence/<silence-id>
```

### 2. Documentation

```markdown
- [ ] Maintenance log updated with completion time
- [ ] Changes documented in CHANGELOG.md
- [ ] Any issues/learnings recorded
- [ ] Runbook updated if steps changed
- [ ] Configuration changes committed to Git
```

### 3. Communication

```markdown
- [ ] Slack announcement: "Maintenance complete"
- [ ] Status page updated: "All systems operational"
- [ ] Email sent to stakeholders
- [ ] Incident ticket closed (if created)
```

### 4. Monitoring

```bash
# Monitor for 24 hours post-maintenance
# Watch: Metrics, logs, alerts
# Ensure: No degradation or issues
```

______________________________________________________________________

## Rollback Procedures

### General Rollback Decision Tree

```
Issue detected during/after maintenance
  │
  ├─ P0 Critical (service down, data loss risk)
  │  └─> ROLLBACK IMMEDIATELY
  │      (No approval needed, notify after)
  │
  ├─ P1 High (degraded service, < 99% success rate)
  │  └─> Attempt fix for 15 minutes
  │      └─> If not resolved: ROLLBACK
  │
  ├─ P2 Medium (warnings, < 100% success rate)
  │  └─> Attempt fix for 30 minutes
  │      └─> If not resolved: ROLLBACK or forward-fix
  │
  └─ P3 Low (cosmetic, no user impact)
     └─> Forward-fix during business hours
```

### Rollback Contacts

| Maintenance | Approval Needed | Contact |
|-------------|----------------|---------|
| **Version Upgrade** | Platform Lead | platform-lead@example.com |
| **Cache Cleanup** | None (safe operation) | - |
| **Secret Rotation** | Security Lead + Platform Lead | security-lead@example.com |

______________________________________________________________________

## Additional Resources

- **Incident Response Runbooks:** `docs/runbooks/INCIDENT_RESPONSE.md`
- **Troubleshooting Guide:** `docs/runbooks/TROUBLESHOOTING.md`
- **Deployment Documentation:** `docs/deployment/`
- **Monitoring Dashboards:** http://grafana:3000/dashboards
- **On-Call Schedule:** https://pagerduty.com/schedules

______________________________________________________________________

**Document Version:** 1.0
**Last Reviewed:** 2025-11-26
**Next Review:** 2026-02-26
**Feedback:** platform-team@example.com
