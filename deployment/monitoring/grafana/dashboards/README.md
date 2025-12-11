# Oneiric Grafana Dashboards

This directory contains production-ready Grafana dashboard definitions for monitoring Oneiric.

## Dashboard Files

The following dashboard JSON files should be created based on the specifications in `/Users/les/Projects/oneiric/docs/monitoring/GRAFANA_DASHBOARDS.md`:

### Core Dashboards

1. **oneiric-overview.json** - System health at a glance

   - UID: `oneiric-overview`
   - Refresh: 30s
   - Panels: 8 (status, traffic, errors, latency, alerts, resources, distribution, activity)

1. **oneiric-resolution.json** - Component resolution deep dive

   - UID: `oneiric-resolution`
   - Refresh: 10s
   - Panels: 8 (success rate, throughput, heatmap, percentiles, top components, failures, shadowed, errors)

1. **oneiric-lifecycle.json** - Hot-swap operations monitoring

   - UID: `oneiric-lifecycle`
   - Refresh: 10s
   - Panels: 9 (success rate, timeline, latency, heatmap, instances, health failures, reasons, rollbacks, state transitions)

1. **oneiric-remote.json** - Remote manifest and artifact tracking

   - UID: `oneiric-remote`
   - Refresh: 30s
   - Panels: 10 (success rate, last sync, latency budget, frequency, cache, digest, signature, sources, errors, cache ops)

1. **oneiric-activity.json** - Pause/drain state management

   - UID: `oneiric-activity`
   - Refresh: 30s
   - Panels: 7 (summary, paused table, draining table, events, distribution, timeline, long-running alert)

1. **oneiric-performance.json** - Performance analysis and SLO tracking

   - UID: `oneiric-performance`
   - Refresh: 10s
   - Panels: 8 (SLO score, SLI compliance, latency breakdown, throughput, error budget, capacity, utilization, query performance)

## Quick Start

### Option 1: Docker Compose (Automatic)

Dashboards are auto-loaded when using `docker-compose.yml`:

```bash
docker-compose up -d grafana
open http://localhost:3000
# Login: admin/admin (change on first login)
```

### Option 2: Manual Import

1. Access Grafana: http://localhost:3000
1. Navigate to: Dashboards → Import
1. Upload JSON file from this directory
1. Select "Prometheus" as data source
1. Import

### Option 3: Kubernetes ConfigMap

```bash
kubectl create configmap oneiric-dashboards \
  --from-file=. \
  -n monitoring

kubectl label configmap oneiric-dashboards \
  grafana_dashboard=1 -n monitoring
```

## Dashboard Structure

All dashboards follow this structure:

```json
{
  "dashboard": {
    "title": "Oneiric - <Component>",
    "uid": "oneiric-<component>",
    "tags": ["oneiric", "<component>"],
    "timezone": "browser",
    "schemaVersion": 38,
    "refresh": "30s",
    "time": {
      "from": "now-1h",
      "to": "now"
    },
    "panels": [...]
  }
}
```

## Common Query Patterns

### Resolution Metrics

```promql
# Success rate
oneiric:resolution_success_rate_global:5m

# P99 latency
oneiric:resolution_latency_p99:5m

# Throughput
oneiric:resolution_throughput_global:5m
```

### Lifecycle Metrics

```promql
# Swap success rate
oneiric:lifecycle_swap_success_rate:5m

# P95 swap latency
oneiric:lifecycle_swap_latency_p95:5m

# Active instances
oneiric:system_active_instances_total:5m
```

### Remote Sync Metrics

```promql
# Sync success rate
oneiric:remote_sync_success_rate:5m

# P99 sync latency
oneiric:remote_sync_latency_p99:5m

# Cache size
oneiric_system_cache_size_bytes
```

## Panel Types

### Stat Panels

- Single value metrics (success rate, uptime, instance count)
- Color thresholds: Green > 95%, Yellow > 90%, Red < 90%

### Graph Panels

- Time series (latency, throughput, error rates)
- Multiple series with legend
- SLO threshold lines

### Table Panels

- Detailed component lists
- Sortable columns
- Value formatting

### Heatmap Panels

- Latency distribution
- Color gradient by frequency

### Gauge Panels

- Progress indicators
- Capacity metrics
- Percentage values

## Variables

All dashboards support these template variables:

- **`$domain`** - Filter by domain (adapter, service, task, event, workflow)
- **`$interval`** - Query resolution interval (auto, 1m, 5m, 15m)
- **`$__rate_interval`** - Auto-adjusted rate interval

Usage in queries:

```promql
oneiric_resolution_total{domain=~"$domain"}
```

## Annotations

Dashboards include annotations for important events:

1. **Critical Alerts**

   ```promql
   ALERTS{alertname=~"Oneiric.*",severity="critical"}
   ```

1. **Deployments**

   - Restart events (uptime < 5min)
   - Version changes

1. **Pause/Resume Events**

   - Activity state changes

## Customization

### Adjust Thresholds

Edit panel JSON to change color thresholds:

```json
{
  "fieldConfig": {
    "defaults": {
      "thresholds": {
        "mode": "absolute",
        "steps": [
          {"color": "red", "value": null},
          {"color": "yellow", "value": 0.90},
          {"color": "green", "value": 0.95}
        ]
      }
    }
  }
}
```

### Add Custom Panels

1. Edit dashboard
1. Add panel
1. Configure query/visualization
1. Save dashboard
1. Export JSON
1. Commit to version control

## Troubleshooting

### "No data" in panels

**Check:**

1. Prometheus datasource configured: Configuration → Data Sources
1. Metrics exist: `curl http://localhost:9090/api/v1/label/__name__/values | grep oneiric`
1. Time range includes data
1. Oneiric is running: `docker ps | grep oneiric`

### Slow dashboard loading

**Solutions:**

1. Use recording rules (already configured in Prometheus)
1. Reduce time range (e.g., 1h instead of 24h)
1. Increase Prometheus memory: `docker-compose.yml` → `memory: 4G`

### Panels showing errors

**Common errors:**

- "Exceeded maximum resolution" → Decrease time range or use recording rules
- "Timeout" → Increase Prometheus query timeout in datasource config
- "Invalid expression" → Check PromQL syntax

## Best Practices

1. **Use recording rules** for frequently queried metrics (already configured)
1. **Set appropriate refresh rates**: 10s for real-time, 30s for overview, 1m for trends
1. **Include SLO lines** on latency/error rate graphs
1. **Add annotations** for deployments and incidents
1. **Version control** dashboard JSON in Git
1. **Test dashboards** after Prometheus rule changes
1. **Document custom panels** in comments

## Maintenance

### Updating Dashboards

1. Edit dashboard in Grafana UI
1. Save changes
1. Export JSON: Dashboard settings → JSON Model
1. Save to this directory
1. Commit to Git

### Backup

```bash
# Export all dashboards
for dash in $(ls *.json); do
  echo "Backing up $dash"
  cp "$dash" "$dash.backup.$(date +%Y%m%d)"
done
```

### Validation

```bash
# Validate JSON syntax
for dash in *.json; do
  echo "Validating $dash"
  jq empty "$dash" && echo "✓ Valid" || echo "✗ Invalid"
done
```

## Additional Resources

- **Dashboard Specifications:** `/docs/monitoring/GRAFANA_DASHBOARDS.md`
- **Prometheus Setup:** `/docs/monitoring/PROMETHEUS_SETUP.md`
- **Grafana Documentation:** https://grafana.com/docs/grafana/latest/dashboards/
- **PromQL Guide:** https://prometheus.io/docs/prometheus/latest/querying/basics/

______________________________________________________________________

**Note:** Full dashboard JSON files are large (5000-10000 lines each). Generate them using Grafana UI based on the panel specifications in the main documentation, then export and save here.
