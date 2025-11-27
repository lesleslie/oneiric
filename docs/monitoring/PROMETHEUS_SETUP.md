# Prometheus Monitoring Setup for Oneiric

**Last Updated:** 2025-11-26
**Status:** Production Ready
**Maintainer:** Platform Team

---

## Table of Contents

1. [Overview](#overview)
2. [Quick Start](#quick-start)
3. [Installation](#installation)
4. [Configuration](#configuration)
5. [Metrics Reference](#metrics-reference)
6. [Recording Rules](#recording-rules)
7. [Alert Rules](#alert-rules)
8. [Troubleshooting](#troubleshooting)
9. [Best Practices](#best-practices)

---

## Overview

This guide configures Prometheus to monitor Oneiric's resolution layer, lifecycle operations, remote sync, and activity state management. The setup includes:

- **Scrape Configuration:** Oneiric metrics endpoint (`:8000/metrics`)
- **Recording Rules:** Pre-aggregated metrics for dashboards
- **Alert Rules:** Critical and warning alerts for operational issues
- **Service Discovery:** Kubernetes/Docker/systemd integration

### Key Metrics Categories

| Category | Metrics | Purpose |
|----------|---------|---------|
| **Resolution** | `oneiric_resolution_*` | Component discovery and selection |
| **Lifecycle** | `oneiric_lifecycle_*` | Hot-swap operations and health |
| **Activity** | `oneiric_activity_*` | Pause/drain state management |
| **Remote Sync** | `oneiric_remote_*` | Manifest loading and artifacts |
| **System** | `oneiric_system_*` | Runtime health and resources |

---

## Quick Start

### Docker Compose

```bash
# Start Oneiric + Prometheus + Grafana
cd /path/to/oneiric
docker-compose up -d

# Verify Prometheus is scraping Oneiric
curl http://localhost:9090/api/v1/targets

# View metrics
curl http://localhost:8000/metrics
```

### Kubernetes

```bash
# Deploy ServiceMonitor (Prometheus Operator)
kubectl apply -f k8s/prometheus-servicemonitor.yaml

# Verify scraping
kubectl get servicemonitor oneiric -n oneiric
```

### Standalone

```bash
# Start Prometheus with custom config
prometheus --config.file=deployment/monitoring/prometheus/prometheus.yml
```

---

## Installation

### Option 1: Docker Compose (Recommended)

Already configured in `docker-compose.yml`:

```yaml
services:
  prometheus:
    image: prom/prometheus:v2.48.0
    ports:
      - "9090:9090"
    volumes:
      - ./deployment/monitoring/prometheus:/etc/prometheus
      - prometheus-data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--web.console.libraries=/usr/share/prometheus/console_libraries'
      - '--web.console.templates=/usr/share/prometheus/consoles'
```

### Option 2: Kubernetes (Prometheus Operator)

```bash
# Install Prometheus Operator
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install prometheus prometheus-community/kube-prometheus-stack -n monitoring

# Deploy Oneiric ServiceMonitor
kubectl apply -f k8s/prometheus-servicemonitor.yaml
```

### Option 3: Binary Installation

```bash
# Download Prometheus
wget https://github.com/prometheus/prometheus/releases/download/v2.48.0/prometheus-2.48.0.linux-amd64.tar.gz
tar xvfz prometheus-*.tar.gz
cd prometheus-*

# Copy config
cp /path/to/oneiric/deployment/monitoring/prometheus/prometheus.yml ./

# Start Prometheus
./prometheus --config.file=prometheus.yml
```

---

## Configuration

### Prometheus Configuration

**File:** `deployment/monitoring/prometheus/prometheus.yml`

```yaml
# Global configuration
global:
  scrape_interval: 15s  # Scrape every 15 seconds
  evaluation_interval: 15s  # Evaluate rules every 15 seconds
  external_labels:
    cluster: 'oneiric-prod'
    environment: 'production'

# Alertmanager configuration
alerting:
  alertmanagers:
    - static_configs:
        - targets:
            - 'alertmanager:9093'

# Load rules
rule_files:
  - 'rules/*.yml'

# Scrape configurations
scrape_configs:
  # Oneiric application metrics
  - job_name: 'oneiric'
    static_configs:
      - targets: ['oneiric:8000']
        labels:
          service: 'oneiric'
          app: 'oneiric'
    metrics_path: /metrics
    scrape_interval: 10s  # Frequent scraping for real-time visibility

  # Prometheus self-monitoring
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

  # Optional: Node exporter (system metrics)
  - job_name: 'node'
    static_configs:
      - targets: ['node-exporter:9100']
```

### Kubernetes ServiceMonitor

**File:** `k8s/prometheus-servicemonitor.yaml`

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: oneiric
  namespace: oneiric
  labels:
    app: oneiric
    release: prometheus
spec:
  selector:
    matchLabels:
      app: oneiric
  endpoints:
    - port: http
      path: /metrics
      interval: 10s
      scrapeTimeout: 5s
```

### Docker Service Discovery

For Docker Swarm or dynamic containers:

```yaml
scrape_configs:
  - job_name: 'oneiric-docker'
    docker_sd_configs:
      - host: unix:///var/run/docker.sock
        refresh_interval: 30s
    relabel_configs:
      - source_labels: [__meta_docker_container_name]
        regex: '/(.*)'
        target_label: container
      - source_labels: [__meta_docker_container_label_com_docker_compose_service]
        target_label: service
```

---

## Metrics Reference

### Resolution Metrics

#### `oneiric_resolution_total`

**Type:** Counter
**Labels:** `domain`, `key`, `provider`, `outcome`
**Description:** Total number of resolution attempts

```promql
# Successful resolutions by domain
rate(oneiric_resolution_total{outcome="success"}[5m])

# Failed resolutions
rate(oneiric_resolution_total{outcome="failed"}[5m])

# Resolution success rate
sum(rate(oneiric_resolution_total{outcome="success"}[5m]))
/ sum(rate(oneiric_resolution_total[5m]))
```

#### `oneiric_resolution_duration_seconds`

**Type:** Histogram
**Labels:** `domain`, `key`
**Buckets:** `0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0`
**Description:** Resolution latency distribution

```promql
# P50 resolution latency
histogram_quantile(0.5, rate(oneiric_resolution_duration_seconds_bucket[5m]))

# P99 resolution latency (SLO: < 100ms)
histogram_quantile(0.99, rate(oneiric_resolution_duration_seconds_bucket[5m]))

# Average resolution time
rate(oneiric_resolution_duration_seconds_sum[5m])
/ rate(oneiric_resolution_duration_seconds_count[5m])
```

#### `oneiric_resolution_shadowed_total`

**Type:** Gauge
**Labels:** `domain`, `key`, `provider`
**Description:** Number of shadowed (inactive) candidates

```promql
# Shadowed candidates by domain
sum(oneiric_resolution_shadowed_total) by (domain)
```

---

### Lifecycle Metrics

#### `oneiric_lifecycle_swap_total`

**Type:** Counter
**Labels:** `domain`, `key`, `outcome`
**Description:** Total hot-swap operations

```promql
# Successful swaps
rate(oneiric_lifecycle_swap_total{outcome="success"}[5m])

# Failed swaps (requires investigation)
rate(oneiric_lifecycle_swap_total{outcome="failed"}[5m])

# Rollback operations
rate(oneiric_lifecycle_swap_total{outcome="rollback"}[5m])
```

#### `oneiric_lifecycle_swap_duration_ms`

**Type:** Histogram
**Labels:** `domain`, `key`
**Buckets:** `10, 50, 100, 500, 1000, 5000, 10000`
**Description:** Swap operation latency in milliseconds

```promql
# P95 swap latency (SLO: < 5s)
histogram_quantile(0.95, rate(oneiric_lifecycle_swap_duration_ms_bucket[5m]))

# Slow swaps (> 10s)
sum(rate(oneiric_lifecycle_swap_duration_ms_bucket{le="10000"}[5m]))
```

#### `oneiric_lifecycle_health_check_failures_total`

**Type:** Counter
**Labels:** `domain`, `key`, `provider`
**Description:** Failed health checks during activation/swap

```promql
# Health check failure rate
rate(oneiric_lifecycle_health_check_failures_total[5m])

# Top failing providers
topk(5, sum(rate(oneiric_lifecycle_health_check_failures_total[5m])) by (provider))
```

#### `oneiric_lifecycle_active_instances`

**Type:** Gauge
**Labels:** `domain`, `key`, `provider`
**Description:** Currently active component instances

```promql
# Active instances by domain
sum(oneiric_lifecycle_active_instances) by (domain)

# Memory usage estimate (assume 50MB per instance)
sum(oneiric_lifecycle_active_instances) * 50 * 1024 * 1024
```

---

### Activity Metrics

#### `oneiric_activity_pause_events_total`

**Type:** Counter
**Labels:** `domain`, `state`
**Description:** Pause state transitions

```promql
# Recent pause events
rate(oneiric_activity_pause_events_total{state="paused"}[5m])

# Resume events
rate(oneiric_activity_pause_events_total{state="resumed"}[5m])
```

#### `oneiric_activity_drain_events_total`

**Type:** Counter
**Labels:** `domain`, `state`
**Description:** Drain state transitions

```promql
# Draining operations
rate(oneiric_activity_drain_events_total{state="draining"}[5m])
```

#### `oneiric_activity_paused_components`

**Type:** Gauge
**Labels:** `domain`
**Description:** Number of currently paused components

```promql
# Total paused components
sum(oneiric_activity_paused_components)

# Paused by domain
sum(oneiric_activity_paused_components) by (domain)
```

#### `oneiric_activity_draining_components`

**Type:** Gauge
**Labels:** `domain`
**Description:** Number of currently draining components

---

### Remote Sync Metrics

#### `oneiric_remote_sync_total`

**Type:** Counter
**Labels:** `source`, `outcome`
**Description:** Remote manifest sync operations

```promql
# Successful syncs
rate(oneiric_remote_sync_total{outcome="success"}[5m])

# Failed syncs (critical)
rate(oneiric_remote_sync_total{outcome="failed"}[5m])

# Sync success rate (SLO: > 99%)
sum(rate(oneiric_remote_sync_total{outcome="success"}[5m]))
/ sum(rate(oneiric_remote_sync_total[5m]))
```

#### `oneiric_remote_sync_duration_seconds`

**Type:** Histogram
**Labels:** `source`
**Buckets:** `0.5, 1, 2, 5, 10, 30, 60`
**Description:** Remote sync latency

```promql
# P99 sync latency (latency budget)
histogram_quantile(0.99, rate(oneiric_remote_sync_duration_seconds_bucket[5m]))

# Slow syncs (> 30s)
rate(oneiric_remote_sync_duration_seconds_bucket{le="30"}[5m])
```

#### `oneiric_remote_digest_checks_total`

**Type:** Counter
**Labels:** `outcome`
**Description:** Artifact digest verification results

```promql
# Digest verification failures (security concern)
rate(oneiric_remote_digest_checks_total{outcome="failed"}[5m])
```

#### `oneiric_remote_signature_verifications_total`

**Type:** Counter
**Labels:** `outcome`
**Description:** Manifest signature verification results

```promql
# Signature verification failures (critical security)
rate(oneiric_remote_signature_verifications_total{outcome="failed"}[5m])
```

#### `oneiric_remote_artifacts_cached`

**Type:** Gauge
**Description:** Number of artifacts in local cache

```promql
# Cache size trend
oneiric_remote_artifacts_cached

# Cache growth rate
deriv(oneiric_remote_artifacts_cached[1h])
```

---

### System Metrics

#### `oneiric_system_info`

**Type:** Gauge
**Labels:** `version`, `python_version`, `platform`
**Description:** System information (constant 1)

#### `oneiric_system_uptime_seconds`

**Type:** Gauge
**Description:** Application uptime in seconds

```promql
# Uptime in hours
oneiric_system_uptime_seconds / 3600
```

#### `oneiric_system_cache_size_bytes`

**Type:** Gauge
**Description:** Cache directory size in bytes

```promql
# Cache size in GB
oneiric_system_cache_size_bytes / (1024^3)

# Cache growth rate (MB/hour)
rate(oneiric_system_cache_size_bytes[1h]) / (1024^2)
```

---

## Recording Rules

**File:** `deployment/monitoring/prometheus/rules/recording_rules.yml`

```yaml
groups:
  - name: oneiric_resolution_aggregates
    interval: 30s
    rules:
      # Resolution success rate by domain
      - record: oneiric:resolution_success_rate:5m
        expr: |
          sum(rate(oneiric_resolution_total{outcome="success"}[5m])) by (domain)
          / sum(rate(oneiric_resolution_total[5m])) by (domain)

      # P99 resolution latency by domain
      - record: oneiric:resolution_latency_p99:5m
        expr: |
          histogram_quantile(0.99,
            rate(oneiric_resolution_duration_seconds_bucket[5m])
          )

      # Resolution throughput (req/sec)
      - record: oneiric:resolution_throughput:5m
        expr: |
          sum(rate(oneiric_resolution_total[5m])) by (domain)

  - name: oneiric_lifecycle_aggregates
    interval: 30s
    rules:
      # Swap success rate
      - record: oneiric:lifecycle_swap_success_rate:5m
        expr: |
          sum(rate(oneiric_lifecycle_swap_total{outcome="success"}[5m]))
          / sum(rate(oneiric_lifecycle_swap_total[5m]))

      # P95 swap latency
      - record: oneiric:lifecycle_swap_latency_p95:5m
        expr: |
          histogram_quantile(0.95,
            rate(oneiric_lifecycle_swap_duration_ms_bucket[5m])
          )

      # Health check failure rate
      - record: oneiric:lifecycle_health_failures:5m
        expr: |
          rate(oneiric_lifecycle_health_check_failures_total[5m])

  - name: oneiric_remote_aggregates
    interval: 30s
    rules:
      # Remote sync success rate
      - record: oneiric:remote_sync_success_rate:5m
        expr: |
          sum(rate(oneiric_remote_sync_total{outcome="success"}[5m]))
          / sum(rate(oneiric_remote_sync_total[5m]))

      # P99 sync latency
      - record: oneiric:remote_sync_latency_p99:5m
        expr: |
          histogram_quantile(0.99,
            rate(oneiric_remote_sync_duration_seconds_bucket[5m])
          )

      # Digest verification failure rate
      - record: oneiric:remote_digest_failure_rate:5m
        expr: |
          rate(oneiric_remote_digest_checks_total{outcome="failed"}[5m])

  - name: oneiric_activity_aggregates
    interval: 30s
    rules:
      # Total paused components
      - record: oneiric:activity_paused_total:5m
        expr: |
          sum(oneiric_activity_paused_components)

      # Total draining components
      - record: oneiric:activity_draining_total:5m
        expr: |
          sum(oneiric_activity_draining_components)

      # Pause/drain event rate
      - record: oneiric:activity_events:5m
        expr: |
          sum(rate(oneiric_activity_pause_events_total[5m])) +
          sum(rate(oneiric_activity_drain_events_total[5m]))
```

---

## Alert Rules

**File:** `deployment/monitoring/prometheus/rules/alert_rules.yml`

```yaml
groups:
  - name: oneiric_critical_alerts
    interval: 15s
    rules:
      # Critical: High resolution failure rate
      - alert: OneiricResolutionFailureRateHigh
        expr: |
          (1 - oneiric:resolution_success_rate:5m) > 0.05
        for: 2m
        labels:
          severity: critical
          component: resolver
        annotations:
          summary: "Oneiric resolution failure rate is {{ $value | humanizePercentage }}"
          description: "Resolution failures exceed 5% threshold (domain: {{ $labels.domain }})"
          runbook: "https://docs.oneiric.io/runbooks/resolution-failures"

      # Critical: Lifecycle swap failures
      - alert: OneiricLifecycleSwapFailureRateHigh
        expr: |
          (1 - oneiric:lifecycle_swap_success_rate:5m) > 0.10
        for: 2m
        labels:
          severity: critical
          component: lifecycle
        annotations:
          summary: "Oneiric swap failure rate is {{ $value | humanizePercentage }}"
          description: "Swap failures exceed 10% threshold"
          runbook: "https://docs.oneiric.io/runbooks/swap-failures"

      # Critical: Remote sync failures
      - alert: OneiricRemoteSyncConsecutiveFailures
        expr: |
          oneiric_remote_sync_total{outcome="failed"}
          - oneiric_remote_sync_total{outcome="failed"} offset 5m >= 3
        for: 1m
        labels:
          severity: critical
          component: remote
        annotations:
          summary: "Oneiric remote sync has failed 3+ consecutive times"
          description: "Remote manifest sync failures (source: {{ $labels.source }})"
          runbook: "https://docs.oneiric.io/runbooks/remote-sync-failures"

      # Critical: Digest verification failures
      - alert: OneiricDigestVerificationFailed
        expr: |
          rate(oneiric_remote_digest_checks_total{outcome="failed"}[5m]) > 0
        for: 1m
        labels:
          severity: critical
          component: security
        annotations:
          summary: "Oneiric artifact digest verification failed"
          description: "Possible cache corruption or supply chain attack"
          runbook: "https://docs.oneiric.io/runbooks/cache-corruption"

      # Critical: Signature verification failures
      - alert: OneiricSignatureVerificationFailed
        expr: |
          rate(oneiric_remote_signature_verifications_total{outcome="failed"}[5m]) > 0
        for: 1m
        labels:
          severity: critical
          component: security
        annotations:
          summary: "Oneiric manifest signature verification failed"
          description: "Possible manifest tampering or key rotation needed"
          runbook: "https://docs.oneiric.io/runbooks/signature-verification"

  - name: oneiric_warning_alerts
    interval: 30s
    rules:
      # Warning: High resolution latency
      - alert: OneiricResolutionLatencyHigh
        expr: |
          oneiric:resolution_latency_p99:5m > 0.1
        for: 5m
        labels:
          severity: warning
          component: resolver
        annotations:
          summary: "Oneiric P99 resolution latency is {{ $value }}s"
          description: "Resolution latency exceeds 100ms SLO"
          runbook: "https://docs.oneiric.io/runbooks/high-latency"

      # Warning: Slow swaps
      - alert: OneiricSwapDurationHigh
        expr: |
          oneiric:lifecycle_swap_latency_p95:5m > 5000
        for: 5m
        labels:
          severity: warning
          component: lifecycle
        annotations:
          summary: "Oneiric P95 swap latency is {{ $value }}ms"
          description: "Swap operations exceed 5s threshold"
          runbook: "https://docs.oneiric.io/runbooks/slow-swaps"

      # Warning: Health check failures
      - alert: OneiricHealthCheckFailuresHigh
        expr: |
          rate(oneiric_lifecycle_health_check_failures_total[5m]) > 0.1
        for: 5m
        labels:
          severity: warning
          component: lifecycle
        annotations:
          summary: "Oneiric health check failure rate is {{ $value }}/sec"
          description: "Health checks failing frequently (provider: {{ $labels.provider }})"
          runbook: "https://docs.oneiric.io/runbooks/health-check-failures"

      # Warning: Remote sync slow
      - alert: OneiricRemoteSyncSlow
        expr: |
          oneiric:remote_sync_latency_p99:5m > 30
        for: 5m
        labels:
          severity: warning
          component: remote
        annotations:
          summary: "Oneiric P99 remote sync latency is {{ $value }}s"
          description: "Remote sync exceeds latency budget (source: {{ $labels.source }})"
          runbook: "https://docs.oneiric.io/runbooks/slow-remote-sync"

      # Warning: Cache size growing rapidly
      - alert: OneiricCacheSizeGrowingRapidly
        expr: |
          rate(oneiric_system_cache_size_bytes[1h]) > 100 * 1024 * 1024
        for: 30m
        labels:
          severity: warning
          component: system
        annotations:
          summary: "Oneiric cache growing at {{ $value | humanize }}B/sec"
          description: "Cache growth exceeds 100MB/hour, cleanup may be needed"
          runbook: "https://docs.oneiric.io/runbooks/cache-cleanup"

      # Warning: High number of shadowed components
      - alert: OneiricShadowedComponentsHigh
        expr: |
          sum(oneiric_resolution_shadowed_total) > 50
        for: 10m
        labels:
          severity: warning
          component: resolver
        annotations:
          summary: "Oneiric has {{ $value }} shadowed components"
          description: "Large number of inactive candidates, review registrations"

  - name: oneiric_info_alerts
    interval: 60s
    rules:
      # Info: Application restarted
      - alert: OneiricRestarted
        expr: |
          oneiric_system_uptime_seconds < 300
        for: 1m
        labels:
          severity: info
          component: system
        annotations:
          summary: "Oneiric application restarted"
          description: "Uptime is {{ $value }}s, recently restarted"

      # Info: Components paused
      - alert: OneiricComponentsPaused
        expr: |
          oneiric:activity_paused_total:5m > 0
        for: 5m
        labels:
          severity: info
          component: activity
        annotations:
          summary: "{{ $value }} Oneiric components are paused"
          description: "Components in maintenance mode"
```

---

## Troubleshooting

### No Metrics Visible

**Problem:** Prometheus shows no Oneiric metrics

**Diagnosis:**

```bash
# Check if Oneiric metrics endpoint is accessible
curl http://localhost:8000/metrics

# Verify Prometheus scrape targets
curl http://localhost:9090/api/v1/targets

# Check Prometheus logs
docker logs prometheus
# OR
journalctl -u prometheus -f
```

**Solutions:**

1. **Oneiric not exposing metrics:**
   - Check Oneiric is running: `docker ps` or `systemctl status oneiric`
   - Verify port 8000 is accessible
   - Check firewall rules

2. **Prometheus not scraping:**
   - Verify `prometheus.yml` configuration
   - Check network connectivity: `docker network inspect`
   - Restart Prometheus: `docker-compose restart prometheus`

3. **Wrong service name/port:**
   - Update `scrape_configs` in `prometheus.yml`
   - Reload config: `curl -X POST http://localhost:9090/-/reload`

---

### Metrics Missing Labels

**Problem:** Metrics exist but missing `domain`, `key`, or `provider` labels

**Diagnosis:**

```promql
# Check raw metrics
up{job="oneiric"}

# Inspect label cardinality
count(oneiric_resolution_total) by (domain, key, provider)
```

**Solutions:**

1. **Ensure Oneiric emits labels:**
   - Check `oneiric/core/observability.py` metric definitions
   - Verify OpenTelemetry instrumentation

2. **Relabeling config:**
   - Add `relabel_configs` in Prometheus scrape config
   - Drop unnecessary labels to reduce cardinality

---

### High Cardinality Warnings

**Problem:** Prometheus warns about high cardinality

**Diagnosis:**

```bash
# Check series count
curl http://localhost:9090/api/v1/status/tsdb

# Identify high-cardinality metrics
curl http://localhost:9090/api/v1/label/__name__/values
```

**Solutions:**

1. **Drop high-cardinality labels:**

```yaml
metric_relabel_configs:
  - source_labels: [__name__]
    regex: 'oneiric_.*'
    action: labeldrop
    regex: 'instance_id'  # Drop unique identifiers
```

2. **Use recording rules:**
   - Pre-aggregate metrics with recording rules
   - Reduces query load and storage

3. **Increase retention:**
   - Adjust `--storage.tsdb.retention.time=30d`

---

### Alerts Not Firing

**Problem:** Expected alerts not triggering

**Diagnosis:**

```bash
# Check alert rules loaded
curl http://localhost:9090/api/v1/rules

# Manually evaluate alert expression
curl 'http://localhost:9090/api/v1/query?query=<expr>'

# Check AlertManager
curl http://localhost:9093/api/v1/alerts
```

**Solutions:**

1. **Verify alert expression:**
   - Test query in Prometheus UI (`:9090/graph`)
   - Check `for` duration (may be too long)

2. **Reload rules:**
   ```bash
   curl -X POST http://localhost:9090/-/reload
   ```

3. **Check AlertManager configuration:**
   - Verify routing rules
   - Test notification channels

---

## Best Practices

### 1. Scrape Interval

- **Default:** 15s (good balance)
- **High-traffic:** 10s (real-time visibility)
- **Low-traffic:** 30s (reduce storage)

```yaml
scrape_configs:
  - job_name: 'oneiric'
    scrape_interval: 10s  # Real-time
```

### 2. Recording Rules

Use recording rules for:
- Frequently queried aggregations
- Complex PromQL expressions in dashboards
- Reducing query latency

```yaml
# Example: Pre-compute P99 latency
- record: oneiric:resolution_latency_p99:5m
  expr: histogram_quantile(0.99, rate(oneiric_resolution_duration_seconds_bucket[5m]))
```

### 3. Alert Tuning

- **Critical alerts:** < 2min `for` duration, page on-call
- **Warning alerts:** 5-10min `for` duration, notify team channel
- **Info alerts:** 15min+ `for` duration, log only

### 4. Retention Policy

- **Production:** 30 days minimum
- **Staging:** 7-14 days
- **Development:** 3-7 days

```bash
prometheus \
  --storage.tsdb.retention.time=30d \
  --storage.tsdb.retention.size=50GB
```

### 5. High Availability

For HA Prometheus setup:

```yaml
# prometheus-1.yml
global:
  external_labels:
    replica: 'prom-1'

# prometheus-2.yml
global:
  external_labels:
    replica: 'prom-2'
```

Use Thanos or Cortex for long-term storage.

### 6. Security

- **Authentication:** Enable basic auth or use reverse proxy
- **TLS:** Encrypt scrape traffic
- **Network policies:** Restrict access to metrics endpoint

```yaml
# Basic auth for Prometheus
basic_auth:
  username: admin
  password_file: /etc/prometheus/.htpasswd
```

---

## Next Steps

1. **Deploy Prometheus:** Follow installation section
2. **Verify metrics:** Check `/metrics` endpoint and Prometheus targets
3. **Configure alerts:** Deploy alert rules and connect AlertManager
4. **Create dashboards:** Import Grafana dashboards (see `GRAFANA_DASHBOARDS.md`)
5. **Set up log aggregation:** Configure Loki (see `LOKI_SETUP.md`)

---

## Additional Resources

- **Prometheus Documentation:** https://prometheus.io/docs/
- **PromQL Cheat Sheet:** https://promlabs.com/promql-cheat-sheet/
- **Oneiric Runbooks:** `docs/runbooks/INCIDENT_RESPONSE.md`
- **Grafana Dashboards:** `docs/monitoring/GRAFANA_DASHBOARDS.md`
- **Alert Rules Reference:** `deployment/monitoring/prometheus/rules/alert_rules.yml`

---

**Document Version:** 1.0
**Last Reviewed:** 2025-11-26
**Next Review:** 2026-02-26
