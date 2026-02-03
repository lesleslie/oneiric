# Monitoring Documentation

**Complete observability setup and configuration for Oneiric.**

This directory contains comprehensive guides for setting up production-grade monitoring, alerting, and observability for Oneiric deployments.

## Table of Contents

### Core Components

1. **[Prometheus Setup](PROMETHEUS_SETUP.md)** - Metrics collection and querying
   - Installation and configuration
   - Oneiric metrics integration
   - Query examples and dashboards
   - Best practices for production

2. **[Grafana Dashboards](GRAFANA_DASHBOARDS.md)** - Visualization and monitoring
   - Pre-built dashboard configurations
   - Custom dashboard creation
   - Panel setup and queries
   - Alerting rules

3. **[Loki Setup](LOKI_SETUP.md)** - Log aggregation and analysis
   - Loki installation
   - Structured logging integration
   - Log querying with LogQL
   - Retention policies

4. **[Alerting Setup](ALERTING_SETUP.md)** - Proactive monitoring
   - AlertManager configuration
   - Alert rule definitions
   - Notification channels (PagerDuty, Slack, email)
   - Alert routing and grouping

## Quick Start

```bash
# 1. Start Prometheus (docker-compose)
docker-compose -f docker/monitoring/docker-compose.yml up -d prometheus

# 2. Start Grafana
docker-compose -f docker/monitoring/docker-compose.yml up -d grafana

# 3. Start Loki
docker-compose -f docker/monitoring/docker-compose.yml up -d loki

# 4. Verify endpoints
curl http://localhost:9090/-/healthy  # Prometheus
curl http://localhost:3000/api/health  # Grafana
curl http://localhost:3100/ready       # Loki
```

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Oneiric    │     │  Prometheus │     │   Grafana   │
│             ├────>│             ├────>│             │
│  App + OTel │     │  Metrics    │     │  Dashboards │
└─────────────┘     └─────────────┘     └─────────────┘
       │                                      │
       │                                      │
       v                                      v
┌─────────────┐                       ┌─────────────┐
│    Loki     │<──────────────────────│  Alerts     │
│  Logs       │    Visualization      │             │
└─────────────┘    & Alerting         └─────────────┘
```

## Key Metrics

Oneiric exposes the following key metrics:

- **Resolution Performance**: `oneiric_resolve_duration_seconds`
- **Hot-Swap Success Rate**: `oneiric_swap_success_total`
- **Health Check Status**: `oneiric_health_check_status`
- **Remote Sync Errors**: `oneiric_remote_sync_errors_total`
- **Active Instances**: `oneiric_active_instances_count`

## Integration Guides

### OpenTelemetry Integration

Oneiric uses OpenTelemetry for automatic instrumentation:

```python
from oneiric.core.observability import setup_telemetry

# Initialize OTel (auto-extracts from OTEL_* env vars)
setup_telemetry(
    service_name="oneiric",
    metrics_exporter="prometheus",
    traces_exporter="otlp",
)
```

See individual setup guides for detailed configuration.

## Support

For issues or questions:
- Check troubleshooting guides in `../runbooks/`
- Review [TROUBLESHOOTING.md](../runbooks/TROUBLESHOOTING.md)
- Open an issue on GitHub

## Related Documentation

- [Deployment Guides](../deployment/) - Production deployment
- [Runbooks](../runbooks/) - Operational procedures
- [Architecture Spec](../NEW_ARCH_SPEC.md) - System design
