# Loki Log Aggregation Setup for Oneiric

**Last Updated:** 2025-11-26
**Status:** Production Ready
**Maintainer:** Platform Team

______________________________________________________________________

## Table of Contents

1. \[[#overview|Overview]\]
1. \[[#quick-start|Quick Start]\]
1. \[[#installation|Installation]\]
1. \[[#configuration|Configuration]\]
1. \[[#logql-queries|LogQL Queries]\]
1. \[[#grafana-integration|Grafana Integration]\]
1. \[[#troubleshooting|Troubleshooting]\]
1. \[[#best-practices|Best Practices]\]

______________________________________________________________________

## Overview

Loki aggregates structured logs from Oneiric for centralized querying and analysis. Combined with Promtail (log shipper) and Grafana (visualization), it provides powerful log exploration capabilities.

### Architecture

```
Oneiric (structlog JSON)
  → stdout/stderr
  → Promtail (scrapes logs)
  → Loki (stores/indexes)
  → Grafana (queries/visualizes)
```

### Key Features

- **Structured logs:** JSON format with domain/key/provider labels
- **Label-based indexing:** Fast queries without full-text search
- **Cost-effective storage:** Compressed chunks, S3-compatible
- **Grafana Explore:** Interactive log browsing
- **Alert integration:** LogQL alerts to AlertManager

______________________________________________________________________

## Quick Start

### Docker Compose (Recommended)

Already configured in `docker-compose.yml`:

```bash
# Start full stack
docker-compose up -d

# Access Grafana Explore
open http://localhost:3000/explore
# Select "Loki" datasource

# View recent logs
{app="oneiric"} | json
```

### Verify Logs Flowing

```bash
# Check Promtail is scraping
curl http://localhost:9080/ready

# Check Loki is receiving logs
curl http://localhost:3100/ready

# Query recent logs
curl -G 'http://localhost:3100/loki/api/v1/query' \
  --data-urlencode 'query={app="oneiric"}' | jq
```

______________________________________________________________________

## Installation

### Option 1: Docker Compose (Automatic)

Loki + Promtail already configured:

```yaml
services:
  loki:
    image: grafana/loki:2.9.0
    ports:
      - "3100:3100"
    volumes:
      - ./deployment/monitoring/loki:/etc/loki
      - loki-data:/loki
    command: -config.file=/etc/loki/loki-config.yml

  promtail:
    image: grafana/promtail:2.9.0
    volumes:
      - ./deployment/monitoring/loki:/etc/promtail
      - /var/log:/var/log:ro
      - /var/lib/docker/containers:/var/lib/docker/containers:ro
    command: -config.file=/etc/promtail/promtail-config.yml
    depends_on:
      - loki
```

### Option 2: Kubernetes (Helm)

```bash
# Install Loki stack
helm repo add grafana https://grafana.github.io/helm-charts
helm install loki grafana/loki-stack -n monitoring \
  --set promtail.enabled=true \
  --set loki.persistence.enabled=true \
  --set loki.persistence.size=50Gi
```

### Option 3: Binary Installation

```bash
# Download Loki
wget https://github.com/grafana/loki/releases/download/v2.9.0/loki-linux-amd64.zip
unzip loki-linux-amd64.zip
chmod +x loki-linux-amd64

# Download Promtail
wget https://github.com/grafana/loki/releases/download/v2.9.0/promtail-linux-amd64.zip
unzip promtail-linux-amd64.zip
chmod +x promtail-linux-amd64

# Start Loki
./loki-linux-amd64 -config.file=loki-config.yml &

# Start Promtail
./promtail-linux-amd64 -config.file=promtail-config.yml &
```

______________________________________________________________________

## Configuration

### Loki Configuration

**File:** `deployment/monitoring/loki/loki-config.yml`

```yaml
# Loki Configuration for Oneiric
# Version: 1.0

auth_enabled: false

server:
  http_listen_port: 3100
  grpc_listen_port: 9096
  log_level: info

# Ingester configuration (write path)
ingester:
  lifecycler:
    address: 127.0.0.1
    ring:
      kvstore:
        store: inmemory
      replication_factor: 1
    final_sleep: 0s
  chunk_idle_period: 5m
  chunk_retain_period: 30s
  max_chunk_age: 1h
  chunk_target_size: 1048576
  chunk_encoding: snappy
  wal:
    enabled: true
    dir: /loki/wal

# Schema configuration (how logs are indexed)
schema_config:
  configs:
    - from: 2024-01-01
      store: boltdb-shipper
      object_store: filesystem
      schema: v11
      index:
        prefix: index_
        period: 24h

# Storage configuration
storage_config:
  boltdb_shipper:
    active_index_directory: /loki/boltdb-shipper-active
    cache_location: /loki/boltdb-shipper-cache
    cache_ttl: 24h
    shared_store: filesystem
  filesystem:
    directory: /loki/chunks

# Compactor (reduces storage size)
compactor:
  working_directory: /loki/compactor
  shared_store: filesystem
  compaction_interval: 10m
  retention_enabled: true
  retention_delete_delay: 2h
  retention_delete_worker_count: 150

# Limits configuration
limits_config:
  enforce_metric_name: false
  reject_old_samples: true
  reject_old_samples_max_age: 168h  # 1 week
  ingestion_rate_mb: 10
  ingestion_burst_size_mb: 20
  max_streams_per_user: 10000
  max_query_length: 721h  # 30 days
  max_query_parallelism: 32
  max_entries_limit_per_query: 5000

# Querier configuration (read path)
querier:
  max_concurrent: 20

# Query frontend (caching/splitting)
query_range:
  align_queries_with_step: true
  max_retries: 5
  cache_results: true
  results_cache:
    cache:
      embedded_cache:
        enabled: true
        max_size_mb: 100

# Ruler (LogQL alerts)
ruler:
  storage:
    type: local
    local:
      directory: /loki/rules
  rule_path: /loki/rules-temp
  alertmanager_url: http://alertmanager:9093
  ring:
    kvstore:
      store: inmemory
  enable_api: true
  enable_alertmanager_v2: true

# Table manager (retention)
table_manager:
  retention_deletes_enabled: true
  retention_period: 720h  # 30 days
```

### Promtail Configuration

**File:** `deployment/monitoring/loki/promtail-config.yml`

```yaml
# Promtail Configuration for Oneiric
# Version: 1.0

server:
  http_listen_port: 9080
  grpc_listen_port: 0
  log_level: info

# Where to send logs
clients:
  - url: http://loki:3100/loki/api/v1/push
    backoff_config:
      min_period: 100ms
      max_period: 10s
      max_retries: 10
    timeout: 10s

positions:
  filename: /tmp/positions.yaml

# Scrape configurations
scrape_configs:
  # Oneiric Docker container logs
  - job_name: oneiric
    docker_sd_configs:
      - host: unix:///var/run/docker.sock
        refresh_interval: 30s

    relabel_configs:
      # Only scrape Oneiric container
      - source_labels: ['__meta_docker_container_name']
        regex: '/(oneiric|oneiric-.*)'
        action: keep

      # Add container name label
      - source_labels: ['__meta_docker_container_name']
        regex: '/(.*)'
        target_label: 'container'

      # Add app label
      - replacement: 'oneiric'
        target_label: 'app'

      # Add environment label (customize per deployment)
      - replacement: 'production'
        target_label: 'environment'

    pipeline_stages:
      # Parse JSON logs (structlog format)
      - json:
          expressions:
            timestamp: timestamp
            level: level
            event: event
            logger: logger
            domain: domain
            key: key
            provider: provider
            outcome: outcome
            duration_ms: duration_ms
            error: error

      # Extract labels from JSON
      - labels:
          level:
          event:
          domain:
          key:
          provider:
          outcome:

      # Add timestamp
      - timestamp:
          source: timestamp
          format: RFC3339

      # Drop non-Oneiric logs
      - match:
          selector: '{app!="oneiric"}'
          action: drop

  # Oneiric systemd journal logs
  - job_name: oneiric-systemd
    journal:
      max_age: 12h
      labels:
        job: oneiric-systemd

    relabel_configs:
      # Only scrape oneiric service
      - source_labels: ['__journal__systemd_unit']
        regex: 'oneiric.service'
        action: keep

      - source_labels: ['__journal__systemd_unit']
        target_label: 'unit'

      - replacement: 'oneiric'
        target_label: 'app'

    pipeline_stages:
      - json:
          expressions:
            level: level
            event: event
            domain: domain
      - labels:
          level:
          event:
          domain:

  # Oneiric log files (if using file logging)
  - job_name: oneiric-files
    static_configs:
      - targets:
          - localhost
        labels:
          job: oneiric-files
          app: oneiric
          __path__: /var/log/oneiric/*.log

    pipeline_stages:
      - json:
          expressions:
            timestamp: timestamp
            level: level
            event: event
            domain: domain
            key: key
            provider: provider
      - labels:
          level:
          event:
          domain:
      - timestamp:
          source: timestamp
          format: RFC3339
```

______________________________________________________________________

## LogQL Queries

### Basic Queries

```logql
# All Oneiric logs (last 5 minutes)
{app="oneiric"}

# Parse JSON and show structured fields
{app="oneiric"} | json

# Filter by log level
{app="oneiric"} | json | level="error"

# Filter by event type
{app="oneiric"} | json | event="swap-complete"

# Filter by domain
{app="oneiric"} | json | domain="adapter"
```

### Resolution Layer Queries

```logql
# Resolution decisions
{app="oneiric"} |= "resolver-decision" | json

# Successful resolutions
{app="oneiric"} | json | event="resolver-decision" | outcome="success"

# Failed resolutions
{app="oneiric"} | json | event="resolver-decision" | outcome="failed"

# Resolution latency (extract duration_ms)
{app="oneiric"} | json | event="resolver-decision" | line_format "{{.duration_ms}}ms"

# Top resolved components (aggregate by key)
sum by (key) (count_over_time({app="oneiric"} | json | event="resolver-decision" [5m]))
```

### Lifecycle Queries

```logql
# All swap operations
{app="oneiric"} |= "swap-" | json

# Successful swaps
{app="oneiric"} | json | event="swap-complete" | outcome="success"

# Failed swaps
{app="oneiric"} | json | event="swap-failed" | json

# Rollback operations
{app="oneiric"} | json | event="swap-rollback"

# Health check failures
{app="oneiric"} | json | event="health-check-failed"

# Slow swaps (> 5 seconds)
{app="oneiric"} | json | event="swap-complete" | duration_ms > 5000
```

### Remote Sync Queries

```logql
# All remote sync events
{app="oneiric"} |= "remote-sync" | json

# Successful syncs
{app="oneiric"} | json | event="remote-sync-complete" | outcome="success"

# Failed syncs
{app="oneiric"} | json | event="remote-sync-error"

# Digest verification failures (SECURITY)
{app="oneiric"} | json | event="digest-check-failed"

# Signature verification failures (CRITICAL SECURITY)
{app="oneiric"} | json | event="signature-verification-failed"

# Slow remote syncs (> 30s latency budget)
{app="oneiric"} | json | event="remote-sync-complete" | duration_ms > 30000
```

### Activity State Queries

```logql
# Pause events
{app="oneiric"} | json | event="component-paused"

# Resume events
{app="oneiric"} | json | event="component-resumed"

# Drain events
{app="oneiric"} | json | event="component-draining"

# Activity state with reasons
{app="oneiric"} | json | event=~"component-(paused|draining)" | line_format "{{.domain}}/{{.key}}: {{.note}}"
```

### Error Analysis

```logql
# All errors
{app="oneiric"} | json | level="error"

# Errors by domain
sum by (domain) (count_over_time({app="oneiric"} | json | level="error" [1h]))

# Error rate (errors/minute)
rate({app="oneiric"} | json | level="error" [5m])

# Top error events
topk(10, sum by (event) (count_over_time({app="oneiric"} | json | level="error" [1h])))

# Errors with stack traces
{app="oneiric"} | json | level="error" | error != ""
```

### Aggregation Queries

```logql
# Log volume by level
sum by (level) (rate({app="oneiric"} | json [5m]))

# Events per second
rate({app="oneiric"} | json [5m])

# Resolution throughput by domain
sum by (domain) (rate({app="oneiric"} | json | event="resolver-decision" [5m]))

# Swap operations per hour
sum(count_over_time({app="oneiric"} | json | event="swap-complete" [1h]))

# Average swap latency
avg_over_time({app="oneiric"} | json | event="swap-complete" | unwrap duration_ms [5m])
```

______________________________________________________________________

## Grafana Integration

### Add Loki Datasource

**Already configured in docker-compose.yml:**

```yaml
# Automatically provisioned
datasources:
  - name: Loki
    type: loki
    access: proxy
    url: http://loki:3100
```

**Manual configuration:**

1. **Configuration → Data Sources → Add data source**
1. **Select "Loki"**
1. **URL:** `http://loki:3100`
1. **Save & Test**

### Grafana Explore

```
http://localhost:3000/explore?orgId=1&left={"datasource":"Loki","queries":[{"expr":"{app=\"oneiric\"}","refId":"A"}]}
```

**Features:**

- **Live tail:** Real-time log streaming
- **Log context:** View surrounding lines
- **Label browser:** Explore available labels
- **Query builder:** Build LogQL visually

### Dashboard Log Panels

Add log panels to dashboards:

```json
{
  "type": "logs",
  "title": "Recent Errors",
  "targets": [
    {
      "expr": "{app=\"oneiric\"} | json | level=\"error\"",
      "refId": "A"
    }
  ],
  "options": {
    "showTime": true,
    "wrapLogMessage": true,
    "sortOrder": "Descending",
    "enableLogDetails": true
  }
}
```

### Alerts from Logs

Create alerts using LogQL:

```yaml
# Alert on high error rate
- alert: OneiricHighErrorRate
  expr: |
    sum(rate({app="oneiric"} | json | level="error" [5m])) > 1
  for: 5m
  annotations:
    summary: "Oneiric error rate is {{ $value }}/sec"
```

______________________________________________________________________

## Troubleshooting

### No Logs in Loki

**Problem:** Grafana Explore shows no logs

**Diagnosis:**

```bash
# Check Promtail is running
curl http://localhost:9080/ready

# Check Loki is running
curl http://localhost:3100/ready

# Check Promtail targets
curl http://localhost:9080/targets

# View Promtail logs
docker logs promtail
```

**Solutions:**

1. **Promtail not scraping:**

   - Verify Docker socket mounted: `/var/run/docker.sock`
   - Check container label filters in `promtail-config.yml`
   - Restart Promtail: `docker restart promtail`

1. **Loki not receiving:**

   - Check network connectivity: `docker network inspect`
   - Verify Loki URL in Promtail config
   - Check Loki logs: `docker logs loki`

1. **Oneiric not logging:**

   - Verify Oneiric is running
   - Check log output: `docker logs oneiric`
   - Ensure structlog configured correctly

______________________________________________________________________

### Slow Queries

**Problem:** LogQL queries timeout or take too long

**Solutions:**

1. **Add time range filter:**

   ```logql
   # BAD: No time range
   {app="oneiric"} | json

   # GOOD: Limited time range
   {app="oneiric"} | json | __timestamp__ >= 1h
   ```

1. **Use label filters (indexed):**

   ```logql
   # FAST: Label filter
   {app="oneiric", level="error"}

   # SLOW: Line filter
   {app="oneiric"} |= "error"
   ```

1. **Reduce query parallelism:**

   ```yaml
   # loki-config.yml
   limits_config:
     max_query_parallelism: 16  # Reduce from 32
   ```

1. **Enable caching:**

   ```yaml
   # loki-config.yml
   query_range:
     cache_results: true
   ```

______________________________________________________________________

### High Storage Usage

**Problem:** Loki disk usage growing rapidly

**Solutions:**

1. **Enable compaction:**

   ```yaml
   compactor:
     retention_enabled: true
     retention_delete_delay: 2h
   ```

1. **Reduce retention period:**

   ```yaml
   table_manager:
     retention_period: 168h  # 7 days instead of 30
   ```

1. **Implement log sampling:**

   ```yaml
   # promtail-config.yml
   pipeline_stages:
     - match:
         selector: '{level="debug"}'
         action: drop  # Drop debug logs
   ```

1. **Use S3 storage (production):**

   ```yaml
   storage_config:
     aws:
       s3: s3://my-bucket/loki
       region: us-east-1
   ```

______________________________________________________________________

## Best Practices

### 1. Structured Logging

Always use structured logs (JSON):

```python
# GOOD: Structured
logger.info(
    "swap-complete", domain="adapter", key="cache", provider="redis", duration_ms=234
)

# BAD: Unstructured
logger.info("Swapped adapter cache to redis in 234ms")
```

### 2. Label Cardinality

**Keep label cardinality low** (< 10 values per label):

```yaml
# GOOD: Low cardinality
labels:
  - level  # 5 values (debug, info, warn, error, critical)
  - domain  # 5 values (adapter, service, task, event, workflow)
  - event  # ~20 values

# BAD: High cardinality
labels:
  - request_id  # Millions of unique values (use line filter instead)
```

### 3. Query Optimization

- **Use label filters** for indexed search: `{level="error"}`
- **Use line filters** for content search: `|= "timeout"`
- **Combine filters** for efficiency: `{level="error"} |= "database"`
- **Add time ranges** to all queries

### 4. Retention Policy

- **Production:** 30 days (balance cost vs compliance)
- **Staging:** 7 days
- **Development:** 3 days

### 5. Log Sampling

Sample high-volume logs:

```yaml
# Drop 90% of debug logs
- match:
    selector: '{level="debug"}'
    drop_ratio: 0.9
```

### 6. Security

- **Encrypt logs in transit:** TLS between Promtail → Loki
- **Sanitize sensitive data:** Drop/mask secrets in pipeline
- **Access control:** Enable auth in Loki config

### 7. Monitoring Loki

Monitor Loki itself:

```promql
# Loki metrics
loki_ingester_chunks_created_total
loki_ingester_memory_chunks
loki_request_duration_seconds
```

______________________________________________________________________

## Next Steps

1. **Deploy Loki + Promtail:** Follow installation section
1. **Verify logs flowing:** Check Grafana Explore
1. **Create log panels:** Add to Grafana dashboards
1. **Set up log alerts:** Configure LogQL alerts
1. **Tune retention:** Adjust based on storage constraints

______________________________________________________________________

## Additional Resources

- **Loki Documentation:** https://grafana.com/docs/loki/
- **LogQL Reference:** https://grafana.com/docs/loki/latest/logql/
- **Promtail Documentation:** https://grafana.com/docs/loki/latest/clients/promtail/
- **Grafana Explore:** https://grafana.com/docs/grafana/latest/explore/
- **Oneiric Prometheus Setup:** `docs/monitoring/PROMETHEUS_SETUP.md`

______________________________________________________________________

**Document Version:** 1.0
**Last Reviewed:** 2025-11-26
**Next Review:** 2026-02-26
