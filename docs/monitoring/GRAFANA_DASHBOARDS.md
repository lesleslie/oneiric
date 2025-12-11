# Grafana Dashboards for Oneiric

**Last Updated:** 2025-11-26
**Status:** Production Ready
**Maintainer:** Platform Team

______________________________________________________________________

## Table of Contents

1. \[[#overview|Overview]\]
1. \[[#quick-start|Quick Start]\]
1. \[[#dashboard-catalog|Dashboard Catalog]\]
1. \[[#installation|Installation]\]
1. \[[#dashboard-details|Dashboard Details]\]
1. \[[#custom-queries|Custom Queries]\]
1. \[[#alerting-integration|Alerting Integration]\]
1. \[[#troubleshooting|Troubleshooting]\]
1. \[[#best-practices|Best Practices]\]

______________________________________________________________________

## Overview

This guide provides production-ready Grafana dashboards for monitoring Oneiric's resolution layer, lifecycle operations, remote sync, and system health.

### Dashboard Suite

| Dashboard | Purpose | Metrics | Alerts |
|-----------|---------|---------|--------|
| **Overview** | System health at a glance | All | Critical |
| **Resolution** | Component discovery/selection | Resolution | Resolution SLO |
| **Lifecycle** | Hot-swap operations | Lifecycle | Swap failures |
| **Remote Sync** | Manifest loading/artifacts | Remote | Sync/security |
| **Activity** | Pause/drain state | Activity | State transitions |
| **Performance** | Latency/throughput analysis | All | SLO breaches |

______________________________________________________________________

## Quick Start

### Import Dashboards (Docker Compose)

```bash
# Grafana already configured in docker-compose.yml
docker-compose up -d grafana

# Access Grafana
open http://localhost:3000
# Default credentials: admin/admin (change on first login)

# Dashboards auto-provisioned from:
# - deployment/monitoring/grafana/dashboards/*.json
```

### Import Dashboards (Manual)

1. **Login to Grafana:** http://localhost:3000
1. **Navigate:** Dashboards → Import
1. **Upload JSON:** Select dashboard file from `deployment/monitoring/grafana/dashboards/`
1. **Configure:**
   - Select Prometheus data source
   - Set folder (e.g., "Oneiric")
1. **Import**

### Kubernetes Deployment

```yaml
# ConfigMap with dashboards
apiVersion: v1
kind: ConfigMap
metadata:
  name: oneiric-dashboards
  namespace: monitoring
  labels:
    grafana_dashboard: "1"
data:
  oneiric-overview.json: |-
    {{ .Files.Get "dashboards/oneiric-overview.json" | nindent 4 }}
```

______________________________________________________________________

## Dashboard Catalog

### 1. Oneiric Overview Dashboard

**File:** `deployment/monitoring/grafana/dashboards/oneiric-overview.json`
**UID:** `oneiric-overview`
**Refresh:** 30s

**Purpose:** Executive summary of Oneiric health and performance

**Panels:**

1. **System Status** (Stat)

   - Current state: UP/DOWN
   - Uptime
   - Active instances
   - SLO health score

1. **Traffic Overview** (Graph)

   - Resolution throughput (req/sec)
   - Swap operations (ops/min)
   - Remote sync frequency

1. **Error Rates** (Graph)

   - Resolution failures
   - Swap failures
   - Health check failures
   - Remote sync failures

1. **Latency P99** (Graph)

   - Resolution latency
   - Swap duration
   - Remote sync duration

1. **Recent Alerts** (Alert List)

   - Critical alerts (last 24h)
   - Warning alerts (last 24h)

1. **Resource Usage** (Gauge)

   - Active instances
   - Cache size
   - Memory estimate

1. **Component Distribution** (Pie Chart)

   - Active by domain
   - Shadowed count

1. **Activity State** (Table)

   - Paused components
   - Draining components

**Target Audience:** SRE, Platform Team, Management

______________________________________________________________________

### 2. Resolution Dashboard

**File:** `deployment/monitoring/grafana/dashboards/oneiric-resolution.json`
**UID:** `oneiric-resolution`
**Refresh:** 10s

**Purpose:** Deep dive into component resolution behavior

**Panels:**

1. **Resolution Success Rate** (Gauge + Graph)

   - Current: 99.5%
   - Target: > 99%
   - Trend (24h)

1. **Resolution Throughput by Domain** (Stacked Graph)

   - adapter
   - service
   - task
   - event
   - workflow

1. **Resolution Latency Heatmap** (Heatmap)

   - P50, P95, P99 distribution
   - Color-coded by latency bands

1. **Resolution Latency Percentiles** (Graph)

   - P50 (green)
   - P95 (yellow)
   - P99 (red, SLO line at 100ms)

1. **Top Resolved Components** (Table)

   - Domain
   - Key
   - Provider
   - Requests/sec
   - Avg latency

1. **Resolution Failures by Domain** (Bar Gauge)

   - Failure count per domain

1. **Shadowed Components** (Table)

   - Domain
   - Key
   - Shadowed provider
   - Stack level
   - Priority

1. **Resolution Errors Over Time** (Graph)

   - Failed resolutions (line)
   - Error annotations

**Target Audience:** Backend Developers, Platform Engineers

______________________________________________________________________

### 3. Lifecycle Dashboard

**File:** `deployment/monitoring/grafana/dashboards/oneiric-lifecycle.json`
**UID:** `oneiric-lifecycle`
**Refresh:** 10s

**Purpose:** Monitor hot-swap operations and component health

**Panels:**

1. **Swap Success Rate** (Gauge + Graph)

   - Current: 98%
   - Target: > 95%
   - Trend (24h)

1. **Swap Operations Timeline** (Graph)

   - Successful swaps (green)
   - Failed swaps (red)
   - Rollbacks (yellow)

1. **Swap Latency Percentiles** (Graph)

   - P50 (green)
   - P95 (yellow, SLO line at 5s)
   - P99 (red)

1. **Swap Duration Heatmap** (Heatmap)

   - Distribution across domains
   - Color-coded by duration (ms)

1. **Active Instances by Domain** (Stacked Graph)

   - adapter
   - service
   - task
   - event
   - workflow

1. **Health Check Failures** (Graph)

   - Failures/sec by provider
   - Threshold line

1. **Swap Failure Reasons** (Table)

   - Domain
   - Key
   - Provider
   - Error type
   - Last occurrence

1. **Rollback Events** (Timeline)

   - Rollback annotations
   - Reason
   - Domain/key

1. **Lifecycle State Transitions** (Sankey Diagram)

   - pending → activating → ready
   - activating → failed → rollback

**Target Audience:** DevOps, SRE, Platform Engineers

______________________________________________________________________

### 4. Remote Sync Dashboard

**File:** `deployment/monitoring/grafana/dashboards/oneiric-remote.json`
**UID:** `oneiric-remote`
**Refresh:** 30s

**Purpose:** Monitor remote manifest loading and artifact security

**Panels:**

1. **Sync Success Rate** (Gauge + Graph)

   - Current: 99.8%
   - Target: > 99%
   - Trend (24h)

1. **Last Sync Status** (Stat)

   - Last sync time
   - Duration
   - Status (success/failed)

1. **Sync Latency vs Budget** (Graph)

   - P99 sync latency
   - Latency budget (30s line)
   - Budget violations highlighted

1. **Sync Frequency** (Graph)

   - Syncs/hour
   - Refresh interval setting

1. **Artifacts Cached** (Graph + Stat)

   - Total artifacts
   - Cache size (GB)
   - Growth rate

1. **Digest Verification Status** (Table)

   - Artifact
   - SHA256
   - Status
   - Verification time

1. **Signature Verification** (Graph)

   - Successful verifications (green)
   - Failed verifications (red, critical)

1. **Remote Sources** (Table)

   - Source URL
   - Last sync
   - Success rate
   - Avg latency

1. **Sync Errors** (Logs Panel)

   - Error messages from Loki
   - Filter: `{app="oneiric"} |= "remote-sync-error"`

1. **Cache Operations** (Graph)

   - Cache hits
   - Cache misses
   - Evictions

**Target Audience:** Security Team, SRE, Platform Engineers

______________________________________________________________________

### 5. Activity State Dashboard

**File:** `deployment/monitoring/grafana/dashboards/oneiric-activity.json`
**UID:** `oneiric-activity`
**Refresh:** 30s

**Purpose:** Track pause/drain state management

**Panels:**

1. **Activity Summary** (Stats Row)

   - Total paused
   - Total draining
   - Active (normal)

1. **Paused Components** (Table)

   - Domain
   - Key
   - Reason/note
   - Paused since
   - Duration

1. **Draining Components** (Table)

   - Domain
   - Key
   - Reason/note
   - Draining since
   - Duration

1. **Pause/Drain Events Over Time** (Graph)

   - Pause events
   - Resume events
   - Drain started
   - Drain completed

1. **Activity State Distribution** (Pie Chart)

   - Active
   - Paused
   - Draining

1. **Activity Timeline** (Annotations)

   - Pause/resume events
   - Maintenance windows

1. **Long-Running Paused Components** (Alert)

   - Paused > 1 hour
   - May indicate forgotten maintenance mode

**Target Audience:** Operations, SRE, Platform Engineers

______________________________________________________________________

### 6. Performance Dashboard

**File:** `deployment/monitoring/grafana/dashboards/oneiric-performance.json`
**UID:** `oneiric-performance`
**Refresh:** 10s

**Purpose:** Detailed performance analysis and SLO tracking

**Panels:**

1. **SLO Health Score** (Gauge)

   - Overall system health (0-100%)
   - Based on all SLIs
   - Color thresholds: Green > 95%, Yellow > 90%, Red < 90%

1. **SLI Compliance** (Stat Panels Row)

   - Resolution latency SLI: ✓/✗
   - Resolution success SLI: ✓/✗
   - Lifecycle swap latency SLI: ✓/✗
   - Lifecycle swap success SLI: ✓/✗
   - Remote sync latency SLI: ✓/✗
   - Remote sync success SLI: ✓/✗

1. **Latency Breakdown** (Graph)

   - Resolution P99
   - Swap P95
   - Remote sync P99
   - SLO lines overlaid

1. **Throughput Metrics** (Graph)

   - Resolution req/sec
   - Swap ops/min
   - Remote sync syncs/hour

1. **Error Budget Consumption** (Graph)

   - Resolution error budget remaining
   - Lifecycle error budget remaining
   - Remote error budget remaining

1. **Capacity Metrics** (Graph)

   - Active instances
   - Memory usage estimate
   - Cache size

1. **Resource Utilization** (Gauges Row)

   - CPU (from cAdvisor)
   - Memory (from cAdvisor)
   - Disk I/O
   - Network I/O

1. **Query Performance** (Table)

   - Top slowest operations
   - Domain
   - Operation
   - P99 latency
   - Frequency

**Target Audience:** Performance Engineers, SRE, Architects

______________________________________________________________________

## Installation

### Option 1: Auto-Provisioning (Docker Compose)

Already configured in `docker-compose.yml`:

```yaml
services:
  grafana:
    image: grafana/grafana:10.2.0
    ports:
      - "3000:3000"
    volumes:
      - ./deployment/monitoring/grafana/provisioning:/etc/grafana/provisioning
      - ./deployment/monitoring/grafana/dashboards:/var/lib/grafana/dashboards
      - grafana-data:/var/lib/grafana
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
      - GF_INSTALL_PLUGINS=grafana-piechart-panel
```

Dashboards auto-loaded from `deployment/monitoring/grafana/dashboards/`.

### Option 2: Manual Import

1. **Download dashboard JSON**
1. **Login to Grafana:** http://localhost:3000
1. **Import:**
   - Click **+** → Import
   - Upload JSON file
   - Select Prometheus data source
   - Set folder: "Oneiric"
1. **Save**

### Option 3: Terraform Provisioning

```hcl
resource "grafana_dashboard" "oneiric_overview" {
  config_json = file("${path.module}/dashboards/oneiric-overview.json")
  folder      = grafana_folder.oneiric.id
}

resource "grafana_folder" "oneiric" {
  title = "Oneiric"
}
```

### Option 4: Kubernetes ConfigMap

```bash
# Create ConfigMap from dashboard files
kubectl create configmap oneiric-dashboards \
  --from-file=deployment/monitoring/grafana/dashboards/ \
  -n monitoring

# Label for Grafana sidecar discovery
kubectl label configmap oneiric-dashboards \
  grafana_dashboard=1 -n monitoring
```

______________________________________________________________________

## Custom Queries

### Resolution Queries

```promql
# Top 10 most-resolved components
topk(10, sum(rate(oneiric_resolution_total[5m])) by (domain, key))

# Resolution success rate by domain (last hour)
sum(rate(oneiric_resolution_total{outcome="success"}[1h])) by (domain)
/ sum(rate(oneiric_resolution_total[1h])) by (domain)

# Resolution latency by provider
histogram_quantile(0.99,
  sum(rate(oneiric_resolution_duration_seconds_bucket[5m])) by (provider, le)
)

# Failed resolutions with reasons
sum(rate(oneiric_resolution_total{outcome="failed"}[5m])) by (domain, key)
```

### Lifecycle Queries

```promql
# Swap success rate trend (24h)
sum(rate(oneiric_lifecycle_swap_total{outcome="success"}[24h]))
/ sum(rate(oneiric_lifecycle_swap_total[24h]))

# Slowest swaps by domain
max(oneiric_lifecycle_swap_duration_ms) by (domain, key)

# Health check failure rate by provider
rate(oneiric_lifecycle_health_check_failures_total[5m]) by (provider)

# Active instances memory estimate (GB)
sum(oneiric_lifecycle_active_instances) * 50 / 1024
```

### Remote Sync Queries

```promql
# Sync success rate by source
sum(rate(oneiric_remote_sync_total{outcome="success"}[5m])) by (source)
/ sum(rate(oneiric_remote_sync_total[5m])) by (source)

# Digest verification failures (security alert)
rate(oneiric_remote_digest_checks_total{outcome="failed"}[5m])

# Cache growth rate (MB/hour)
rate(oneiric_system_cache_size_bytes[1h]) / (1024^2)

# Artifacts by domain
sum(oneiric_remote_artifacts_cached) by (domain)
```

### Activity Queries

```promql
# Total paused components
sum(oneiric_activity_paused_components)

# Pause duration by domain
time() - oneiric_activity_pause_timestamp_seconds

# Draining completion estimate
oneiric_activity_draining_operations_remaining / rate(oneiric_activity_draining_operations_completed[5m])
```

______________________________________________________________________

## Alerting Integration

### Dashboard Alerts

Each dashboard can include embedded alerts that link to AlertManager:

```json
{
  "alert": {
    "name": "Resolution Latency High",
    "message": "P99 resolution latency exceeds 100ms",
    "frequency": "1m",
    "handler": 1,
    "conditions": [
      {
        "evaluator": {
          "params": [0.1],
          "type": "gt"
        },
        "query": {
          "datasourceId": 1,
          "model": {
            "expr": "oneiric:resolution_latency_p99:5m"
          }
        }
      }
    ]
  }
}
```

### Alert Annotations

Dashboards automatically show alert firing events as annotations:

```json
{
  "annotations": {
    "list": [
      {
        "datasource": "Prometheus",
        "enable": true,
        "expr": "ALERTS{alertname=~\"Oneiric.*\",severity=\"critical\"}",
        "iconColor": "red",
        "name": "Critical Alerts",
        "step": "60s",
        "tagKeys": "alertname,severity",
        "textFormat": "{{ alertname }}: {{ summary }}",
        "titleFormat": "Alert"
      }
    ]
  }
}
```

______________________________________________________________________

## Troubleshooting

### Dashboard Not Loading

**Problem:** Dashboard shows "Panel plugin not found"

**Solution:**

```bash
# Install missing plugins
docker exec -it grafana grafana-cli plugins install grafana-piechart-panel
docker exec -it grafana grafana-cli plugins install grafana-polystat-panel

# Restart Grafana
docker restart grafana
```

### No Data in Panels

**Problem:** Panels show "No data"

**Diagnosis:**

1. **Check Prometheus data source:**

   - Configuration → Data Sources → Prometheus
   - Test connection (should show "Data source is working")

1. **Verify metrics exist:**

   ```bash
   curl http://localhost:9090/api/v1/label/__name__/values | grep oneiric
   ```

1. **Check time range:**

   - Ensure dashboard time range includes data
   - Try "Last 5 minutes"

**Solutions:**

- **Prometheus not scraping:** Check Prometheus targets `:9090/targets`
- **Metrics not emitted:** Verify Oneiric is running and exposing `/metrics`
- **Wrong data source:** Edit panel, select correct Prometheus data source

### Queries Timing Out

**Problem:** Panel queries time out or load slowly

**Solutions:**

1. **Use recording rules:**

   - Pre-compute expensive queries
   - Reduce dashboard query load

1. **Decrease time range:**

   - Use shorter time windows (e.g., 1h instead of 24h)

1. **Increase Prometheus resources:**

   ```yaml
   # docker-compose.yml
   services:
     prometheus:
       deploy:
         resources:
           limits:
             memory: 4G
   ```

1. **Optimize queries:**

   - Use `rate()` instead of `irate()` for smoother graphs
   - Add `by (label)` to reduce cardinality

### Incorrect Percentile Values

**Problem:** Latency percentiles seem wrong

**Diagnosis:**

```promql
# Check bucket distribution
oneiric_resolution_duration_seconds_bucket
```

**Solutions:**

- **Verify histogram buckets** in `oneiric/core/observability.py`
- **Increase bucket resolution** for finer-grained percentiles
- **Use recording rules** to avoid repeated heavy calculations

______________________________________________________________________

## Best Practices

### 1. Dashboard Organization

- **Folder structure:**

  ```
  Oneiric/
  ├── Overview (default)
  ├── Deep Dive/
  │   ├── Resolution
  │   ├── Lifecycle
  │   ├── Remote Sync
  │   └── Activity
  └── Performance/
      └── Performance Dashboard
  ```

- **Consistent naming:** `Oneiric - <Component>` (e.g., "Oneiric - Resolution")

### 2. Panel Design

- **Use consistent colors:**

  - Green: Success/healthy
  - Yellow: Warning
  - Red: Critical/error
  - Blue: Informational

- **Add SLO lines:** Overlay target thresholds on graphs

- **Include units:** Always specify units (ms, req/sec, GB)

- **Tooltips:** Enable shared crosshair for time-series comparison

### 3. Variables

Use dashboard variables for dynamic filtering:

```json
{
  "templating": {
    "list": [
      {
        "name": "domain",
        "type": "query",
        "query": "label_values(oneiric_resolution_total, domain)",
        "multi": true,
        "includeAll": true
      }
    ]
  }
}
```

Usage in queries:

```promql
oneiric_resolution_total{domain=~"$domain"}
```

### 4. Time Range Presets

Configure useful presets:

- Last 5 minutes (real-time)
- Last 1 hour (recent trends)
- Last 24 hours (daily view)
- Last 7 days (weekly trends)

### 5. Refresh Intervals

- **Overview:** 30s (balance freshness vs load)
- **Deep dive:** 10s (near real-time)
- **Performance:** 10s (catch spikes)
- **Trends:** 1m (historical analysis)

### 6. Alerts on Dashboards

- **Embed critical alerts** in dashboards
- **Link to runbooks** in alert annotations
- **Show recent alert history** (last 24h)

### 7. Accessibility

- **Color-blind friendly palettes**
- **Text annotations** for important events
- **High-contrast mode** support

______________________________________________________________________

## Next Steps

1. **Import dashboards:** Follow installation section
1. **Customize:** Adjust thresholds/colors for your environment
1. **Set up alerts:** Configure AlertManager (see `ALERTING_SETUP.md`)
1. **Create custom views:** Add panels specific to your use case
1. **Export & version control:** Save dashboard JSON to Git

______________________________________________________________________

## Additional Resources

- **Grafana Documentation:** https://grafana.com/docs/
- **PromQL Guide:** https://prometheus.io/docs/prometheus/latest/querying/basics/
- **Oneiric Prometheus Setup:** `docs/monitoring/PROMETHEUS_SETUP.md`
- **Oneiric Runbooks:** `docs/runbooks/INCIDENT_RESPONSE.md`
- **Dashboard JSON Files:** `deployment/monitoring/grafana/dashboards/`

______________________________________________________________________

**Document Version:** 1.0
**Last Reviewed:** 2025-11-26
**Next Review:** 2026-02-26
