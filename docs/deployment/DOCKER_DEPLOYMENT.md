# Docker Deployment Guide

**Version:** 1.0.0
**Last Updated:** 2025-11-26
**Target:** Oneiric v0.1.0+

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Production Dockerfile](#production-dockerfile)
3. [Docker Compose Setup](#docker-compose-setup)
4. [Environment Configuration](#environment-configuration)
5. [Secrets Management](#secrets-management)
6. [Volume Management](#volume-management)
7. [Health Checks](#health-checks)
8. [Monitoring Integration](#monitoring-integration)
9. [Security Hardening](#security-hardening)
10. [Troubleshooting](#troubleshooting)

---

## Quick Start

### Single Container Deployment

```bash
# Build production image
docker build -t oneiric:latest .

# Run with minimal configuration
docker run -d \
  --name oneiric \
  -p 8000:8000 \
  -e ONEIRIC_CONFIG=/app/settings \
  -v $(pwd)/settings:/app/settings:ro \
  -v oneiric-cache:/app/.oneiric_cache \
  oneiric:latest

# Check health
docker exec oneiric python -m oneiric.cli health --probe
```

### Multi-Service Orchestration

```bash
# Start all services (Oneiric + Prometheus + Grafana + Loki)
docker-compose up -d

# View logs
docker-compose logs -f oneiric

# Stop all services
docker-compose down
```

---

## Production Dockerfile

The production Dockerfile uses a multi-stage build optimized for security and size.

### Dockerfile Structure

```dockerfile
# syntax=docker/dockerfile:1.4

#######################################
# Stage 1: Builder
#######################################
FROM python:3.14-slim AS builder

# Install uv package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Set working directory
WORKDIR /build

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies (no dev dependencies)
RUN uv sync --frozen --no-dev --no-install-project

# Copy source code
COPY oneiric ./oneiric
COPY README.md ./

# Build wheel
RUN uv build --wheel --out-dir /build/dist

#######################################
# Stage 2: Runtime
#######################################
FROM python:3.14-slim AS runtime

# Install runtime dependencies only
RUN apt-get update && apt-get install -y \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r oneiric --gid=1000 && \
    useradd -r -g oneiric --uid=1000 --home-dir=/app --shell=/sbin/nologin oneiric

# Set working directory
WORKDIR /app

# Install uv for runtime
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy wheel from builder
COPY --from=builder /build/dist/*.whl /tmp/

# Install oneiric from wheel
RUN uv pip install --system /tmp/*.whl && rm /tmp/*.whl

# Create cache directory with correct permissions
RUN mkdir -p /app/.oneiric_cache && \
    chown -R oneiric:oneiric /app

# Copy default settings (optional)
COPY --chown=oneiric:oneiric settings /app/settings

# Switch to non-root user
USER oneiric

# Expose ports
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD python -m oneiric.cli health --probe || exit 1

# Default command (can be overridden)
CMD ["python", "-m", "oneiric.cli", "orchestrate", "--manifest", "/app/settings/manifest.yaml", "--refresh-interval", "120"]
```

### Build Arguments

```dockerfile
# Optional build arguments for customization
ARG PYTHON_VERSION=3.14
ARG UV_VERSION=latest
ARG ONEIRIC_VERSION=0.1.0

# Use in FROM statements
FROM python:${PYTHON_VERSION}-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:${UV_VERSION} /uv /usr/local/bin/uv
```

### Build Command

```bash
# Basic build
docker build -t oneiric:0.1.0 .

# Build with custom Python version
docker build \
  --build-arg PYTHON_VERSION=3.14 \
  --build-arg ONEIRIC_VERSION=0.1.0 \
  -t oneiric:0.1.0-py3.14 \
  .

# Multi-platform build
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t oneiric:0.1.0 \
  --push \
  .
```

---

## Docker Compose Setup

### Basic Configuration

**File:** `docker-compose.yml`

```yaml
version: '3.8'

services:
  oneiric:
    build:
      context: .
      dockerfile: Dockerfile
    image: oneiric:latest
    container_name: oneiric
    restart: unless-stopped

    # Environment variables
    environment:
      - ONEIRIC_CONFIG=/app/settings
      - ONEIRIC_STACK_ORDER=production:100,staging:50,default:0
      - OTEL_SERVICE_NAME=oneiric
      - OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4317

    # Volumes
    volumes:
      - ./settings:/app/settings:ro
      - oneiric-cache:/app/.oneiric_cache
      - ./logs:/app/logs

    # Ports
    ports:
      - "8000:8000"

    # Health check
    healthcheck:
      test: ["CMD", "python", "-m", "oneiric.cli", "health", "--probe"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

    # Resource limits
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2G
        reservations:
          cpus: '0.5'
          memory: 512M

    # Logging
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

    # Dependencies (if using monitoring stack)
    depends_on:
      - prometheus
      - loki

volumes:
  oneiric-cache:
    driver: local
  prometheus-data:
    driver: local
  grafana-data:
    driver: local
  loki-data:
    driver: local
```

### Full Monitoring Stack

**File:** `docker-compose.monitoring.yml`

```yaml
version: '3.8'

services:
  oneiric:
    # ... same as above
    environment:
      - PROMETHEUS_METRICS_PORT=9090
      - LOKI_ENDPOINT=http://loki:3100

  # Prometheus for metrics
  prometheus:
    image: prom/prometheus:latest
    container_name: prometheus
    restart: unless-stopped
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus-data:/prometheus
    ports:
      - "9090:9090"
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--web.console.libraries=/usr/share/prometheus/console_libraries'
      - '--web.console.templates=/usr/share/prometheus/consoles'

  # Grafana for visualization
  grafana:
    image: grafana/grafana:latest
    container_name: grafana
    restart: unless-stopped
    volumes:
      - grafana-data:/var/lib/grafana
      - ./monitoring/grafana-dashboards:/etc/grafana/provisioning/dashboards:ro
      - ./monitoring/grafana-datasources.yml:/etc/grafana/provisioning/datasources/datasources.yml:ro
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_USER=admin
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_PASSWORD:-changeme}
      - GF_USERS_ALLOW_SIGN_UP=false
    depends_on:
      - prometheus

  # Loki for logs
  loki:
    image: grafana/loki:latest
    container_name: loki
    restart: unless-stopped
    volumes:
      - ./monitoring/loki-config.yml:/etc/loki/local-config.yaml:ro
      - loki-data:/loki
    ports:
      - "3100:3100"
    command: -config.file=/etc/loki/local-config.yaml

  # Promtail for log shipping
  promtail:
    image: grafana/promtail:latest
    container_name: promtail
    restart: unless-stopped
    volumes:
      - ./monitoring/promtail-config.yml:/etc/promtail/config.yml:ro
      - ./logs:/var/log/oneiric:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
    command: -config.file=/etc/promtail/config.yml
    depends_on:
      - loki
```

---

## Environment Configuration

### Required Environment Variables

```bash
# Core configuration
ONEIRIC_CONFIG=/app/settings           # Path to config directory
ONEIRIC_STACK_ORDER=prod:100,dev:0     # Stack priority override

# Logging
LOG_LEVEL=INFO                          # DEBUG, INFO, WARNING, ERROR
ONEIRIC_LOG_FORMAT=json                 # json or console

# OpenTelemetry
OTEL_SERVICE_NAME=oneiric
OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4317

# Prometheus metrics (if enabled)
PROMETHEUS_METRICS_PORT=9090
```

### Optional Environment Variables

```bash
# Remote manifest settings
ONEIRIC_MANIFEST_URL=https://cdn.example.com/manifest.yaml
ONEIRIC_MANIFEST_REFRESH_INTERVAL=300  # seconds

# Cache settings
ONEIRIC_CACHE_DIR=/app/.oneiric_cache
ONEIRIC_CACHE_MAX_SIZE=1073741824      # 1GB in bytes

# Security
ONEIRIC_SIGNATURE_VERIFY=true
ONEIRIC_PUBLIC_KEY_PATH=/app/secrets/public_key.pem

# Performance tuning
ONEIRIC_MAX_WORKERS=4
ONEIRIC_REQUEST_TIMEOUT=30             # seconds
```

### Environment File Example

**File:** `.env`

```bash
# Oneiric Configuration
ONEIRIC_CONFIG=/app/settings
ONEIRIC_STACK_ORDER=production:100,staging:50,default:0

# Logging
LOG_LEVEL=INFO
ONEIRIC_LOG_FORMAT=json

# OpenTelemetry
OTEL_SERVICE_NAME=oneiric-production
OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4317

# Monitoring
PROMETHEUS_METRICS_PORT=9090

# Grafana Admin Password (override default)
GRAFANA_PASSWORD=secure_password_here
```

---

## Secrets Management

### Docker Secrets (Swarm Mode)

```bash
# Create secrets
echo "my-secret-key" | docker secret create oneiric_api_key -
echo "redis://user:pass@redis:6379" | docker secret create oneiric_redis_url -

# Use in docker-compose.yml
version: '3.8'
services:
  oneiric:
    secrets:
      - oneiric_api_key
      - oneiric_redis_url
    environment:
      - API_KEY_FILE=/run/secrets/oneiric_api_key
      - REDIS_URL_FILE=/run/secrets/oneiric_redis_url

secrets:
  oneiric_api_key:
    external: true
  oneiric_redis_url:
    external: true
```

### Environment Variables from Files

```bash
# Store secrets in files (mounted from secure location)
docker run -d \
  -e API_KEY_FILE=/run/secrets/api_key \
  -v /secure/path/api_key:/run/secrets/api_key:ro \
  oneiric:latest
```

### HashiCorp Vault Integration

```yaml
services:
  oneiric:
    environment:
      - VAULT_ADDR=https://vault.example.com
      - VAULT_TOKEN_FILE=/run/secrets/vault_token
    volumes:
      - /secure/vault/token:/run/secrets/vault_token:ro
```

---

## Volume Management

### Cache Volume

```bash
# Create named volume
docker volume create oneiric-cache

# Inspect volume
docker volume inspect oneiric-cache

# Backup volume
docker run --rm \
  -v oneiric-cache:/cache \
  -v $(pwd)/backups:/backups \
  alpine tar czf /backups/cache-$(date +%Y%m%d).tar.gz -C /cache .

# Restore volume
docker run --rm \
  -v oneiric-cache:/cache \
  -v $(pwd)/backups:/backups \
  alpine tar xzf /backups/cache-20251126.tar.gz -C /cache
```

### Settings Volume (Read-Only)

```bash
# Mount settings as read-only
docker run -d \
  -v $(pwd)/settings:/app/settings:ro \
  oneiric:latest
```

### Logs Volume

```bash
# Create logs volume
docker volume create oneiric-logs

# Tail logs
docker run --rm \
  -v oneiric-logs:/logs \
  alpine tail -f /logs/oneiric.log
```

---

## Health Checks

### Built-in Health Check

The Dockerfile includes a health check that runs every 30 seconds:

```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD python -m oneiric.cli health --probe || exit 1
```

### Manual Health Check

```bash
# Check container health
docker inspect --format='{{.State.Health.Status}}' oneiric

# View health check logs
docker inspect --format='{{range .State.Health.Log}}{{.Output}}{{end}}' oneiric

# Run health check manually
docker exec oneiric python -m oneiric.cli health --probe
```

### Custom Health Check Script

**File:** `scripts/healthcheck.sh`

```bash
#!/bin/sh
set -e

# Check if CLI responds
if ! python -m oneiric.cli health --probe; then
  echo "Health probe failed"
  exit 1
fi

# Check if cache directory is writable
if ! touch /app/.oneiric_cache/.healthcheck; then
  echo "Cache directory not writable"
  exit 1
fi
rm /app/.oneiric_cache/.healthcheck

# Check if settings are readable
if ! test -r /app/settings/app.yml; then
  echo "Settings not readable"
  exit 1
fi

echo "Health check passed"
exit 0
```

---

## Monitoring Integration

### Prometheus Metrics

Oneiric exposes metrics at `:9090/metrics` when `PROMETHEUS_METRICS_PORT` is set.

**Prometheus Configuration:** `monitoring/prometheus.yml`

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'oneiric'
    static_configs:
      - targets: ['oneiric:9090']
    metrics_path: '/metrics'
```

### Loki Log Aggregation

**Promtail Configuration:** `monitoring/promtail-config.yml`

```yaml
server:
  http_listen_port: 9080
  grpc_listen_port: 0

positions:
  filename: /tmp/positions.yaml

clients:
  - url: http://loki:3100/loki/api/v1/push

scrape_configs:
  - job_name: oneiric-logs
    static_configs:
      - targets:
          - localhost
        labels:
          job: oneiric
          __path__: /var/log/oneiric/*.log
    pipeline_stages:
      - json:
          expressions:
            level: level
            message: message
            domain: domain
            key: key
      - labels:
          level:
          domain:
```

### Grafana Dashboards

See `docs/monitoring/GRAFANA_DASHBOARDS.md` for dashboard JSON exports.

---

## Security Hardening

### Non-Root User

The Dockerfile runs as non-root user `oneiric:oneiric` (UID/GID 1000).

```dockerfile
# Create user
RUN groupadd -r oneiric --gid=1000 && \
    useradd -r -g oneiric --uid=1000 --home-dir=/app --shell=/sbin/nologin oneiric

# Switch to non-root
USER oneiric
```

### Minimal Base Image

Uses `python:3.14-slim` (Debian-based, minimal) instead of full `python:3.14`.

### Read-Only Root Filesystem

```yaml
services:
  oneiric:
    read_only: true
    tmpfs:
      - /tmp
      - /app/.oneiric_cache
```

### Security Options

```yaml
services:
  oneiric:
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    cap_add:
      - NET_BIND_SERVICE  # Only if binding to privileged ports
```

### Network Isolation

```yaml
services:
  oneiric:
    networks:
      - internal
      - monitoring

networks:
  internal:
    driver: bridge
    internal: true  # No internet access
  monitoring:
    driver: bridge
```

---

## Troubleshooting

### Container Won't Start

```bash
# Check logs
docker logs oneiric

# Check health status
docker inspect --format='{{.State.Health}}' oneiric

# Start with interactive shell
docker run -it --rm oneiric:latest /bin/bash
```

### Permission Errors

```bash
# Fix cache directory permissions
docker exec -u root oneiric chown -R oneiric:oneiric /app/.oneiric_cache

# Or mount with correct UID/GID
docker run -d \
  -v oneiric-cache:/app/.oneiric_cache:uid=1000,gid=1000 \
  oneiric:latest
```

### Out of Memory

```bash
# Check container memory usage
docker stats oneiric

# Increase memory limit
docker update --memory 4G --memory-swap 4G oneiric

# Or in docker-compose.yml
services:
  oneiric:
    deploy:
      resources:
        limits:
          memory: 4G
```

### Slow Performance

```bash
# Check CPU usage
docker stats oneiric

# Increase CPU allocation
docker update --cpus 4.0 oneiric

# Or in docker-compose.yml
services:
  oneiric:
    deploy:
      resources:
        limits:
          cpus: '4.0'
```

### Network Connectivity Issues

```bash
# Check network configuration
docker network inspect bridge

# Test DNS resolution
docker exec oneiric nslookup google.com

# Test connectivity to external services
docker exec oneiric curl -v https://api.example.com
```

---

## Next Steps

- [Kubernetes Deployment](./KUBERNETES_DEPLOYMENT.md) - Deploy to Kubernetes clusters
- [Systemd Service](./SYSTEMD_DEPLOYMENT.md) - Run as systemd service
- [Monitoring Setup](../monitoring/MONITORING_SETUP.md) - Configure Prometheus, Grafana, Loki
- [Runbooks](../runbooks/README.md) - Incident response and maintenance procedures
