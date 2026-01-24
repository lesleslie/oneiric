# Netdata Monitoring Adapter for Oneiric

The Netdata monitoring adapter allows Oneiric to integrate with Netdata for system and application monitoring. This adapter enables sending metrics from Oneiric components to a Netdata server for visualization and alerting.

## Installation

To use the Netdata adapter, install Oneiric with the monitoring-netdata extra:

```bash
uv add "oneiric[monitoring-netdata]"
```

## Configuration

The Netdata adapter can be configured using the following settings:

- `base_url`: Base URL for the Netdata server (default: "http://127.0.0.1:19999")
- `api_key`: API key for Netdata authentication (optional, falls back to NETDATA_API_KEY env var)
- `hostname`: Hostname to associate with metrics (optional, defaults to system hostname)
- `environment`: Deployment environment tag (default: "development")
- `enable_metrics_collection`: Enable collection and reporting of Oneiric metrics (default: True)
- `metrics_refresh_interval`: Interval in seconds between metric collection cycles (default: 30.0)
- `timeout`: Request timeout in seconds for Netdata API calls (default: 10.0)

## Usage

### Registering the Adapter

Register the Netdata adapter in your Oneiric configuration:

```python
from oneiric.adapters.monitoring.netdata import NetdataMonitoringAdapter, NetdataMonitoringSettings

# Configure the adapter
settings = NetdataMonitoringSettings(
    base_url="http://your-netdata-server:19999",
    environment="production",
    enable_metrics_collection=True
)

# Register the adapter with Oneiric's resolver
resolver.register(
    Candidate(
        domain="adapter",
        key="monitoring.netdata",
        provider="netdata",
        factory=lambda: NetdataMonitoringAdapter(settings),
        stack_level=28,
        priority=215
    )
)
```

### Sending Custom Metrics

You can send custom metrics to Netdata using the adapter:

```python
# Assuming you have access to the Netdata adapter instance
success = await adapter.send_custom_metric(
    chart_name="oneiric.components",
    dimension="active",
    value=42.0,
    units="count"
)
```

## Capabilities

The Netdata adapter provides the following capabilities:

- Metrics collection and reporting
- System monitoring integration
- Application performance visualization
- Custom metric support

## Troubleshooting

If you encounter issues with the Netdata adapter:

1. Verify that your Netdata server is accessible at the configured base URL
2. Check that any required API keys are correctly configured
3. Ensure the Netdata API client library is properly installed
4. Review Oneiric logs for any error messages related to the adapter