# OpenTelemetry Integration & Device Discovery Analysis
**Date**: 2025-01-25
**Projects**: Mahavishnu, Oneiric, MCP Ecosystem

---

## 📋 Questions Answered

1. **Can Mahavishnu collect and store OTel logs for querying?**
2. **Does OTel collect logs (pull) or are logs pushed to it?**
3. **Should Oneiric devices announce themselves (push) or be polled (pull), or both?**

---

## Part 1: Mahavishnu OpenTelemetry Integration

### ✅ Current State: OTel Already Integrated!

**File**: `mahavishnu/core/observability.py` (350+ lines)

**OTel Components Already Implemented**:
```python
# OpenTelemetry imports (lines 12-23)
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.system_metrics import SystemMetricsInstrumentor
```

**Configuration** (`mahavishnu/core/config.py`):
```python
class MahavishnuSettings(BaseSettings):
    # Observability (lines 134-146)
    metrics_enabled: bool = Field(
        default=True,
        description="Enable OpenTelemetry metrics",
    )
    tracing_enabled: bool = Field(
        default=True,
        description="Enable distributed tracing",
    )
    otlp_endpoint: str = Field(
        default="http://localhost:4317",  # OTLP gRPC endpoint
        description="OTLP endpoint for metrics/traces",
    )
```

### What's Implemented:

**1. Metrics Collection** ✅
```python
# Counters
self.workflow_counter = self.meter.create_counter(
    "mahavishnu.workflows.executed",
    description="Number of workflows executed"
)

self.repo_counter = self.meter.create_counter(
    "mahavishnu.repositories.processed",
    description="Number of repositories processed"
)

self.error_counter = self.meter.create_counter(
    "mahavishnu.errors.count",
    description="Number of errors occurred"
)

# Histograms (distributions)
self.workflow_duration_histogram = self.meter.create_histogram(
    "mahavishnu.workflow.duration",
    description="Duration of workflow execution in seconds",
    unit="s"
)
```

**2. Distributed Tracing** ✅
```python
# Spans for distributed tracing
self.tracer = trace.get_tracer(__name__)

# Usage:
with self.tracer.start_as_current_span(
    "process_repository",
    attributes={"repo": repo_path}
) as span:
    span.set_attribute("status", "success")
    span.set_attribute("files_processed", file_count)
```

**3. System Metrics** ✅
```python
# Automatic system metrics collection
SystemMetricsInstrumentor().instrument()
```

**4. Log Correlation** ✅
```python
@dataclass
class LogEntry:
    timestamp: datetime
    level: LogLevel
    message: str
    attributes: Dict[str, Any]
    trace_id: Optional[str] = None  # Links logs to traces!
```

### OTLP Architecture: PUSH Model ✅

**Answer**: **Logs/metrics/traces are PUSHED to OTel collector**

**Flow**:
```
Mahavishnu Application
    ↓ (PUSH via OTLP)
OpenTelemetry Collector (localhost:4317)
    ↓ (export to)
Backend Storage (Jaeger, Prometheus, Elasticsearch, etc.)
    ↓ (query)
UI Grafana/Jaeger/Prometheus
```

**Protocol**: OTLP (OpenTelemetry Protocol)
- **Transport**: gRPC (port 4317) or HTTP (port 4318)
- **Format**: Protocol Buffers
- **Direction**: PUSH (application → collector)

### Can Mahavishnu Store & Query OTel Logs?

**Current**: **NO** - Mahavishnu pushes to external collector

**Options for Storage & Querying**:

**Option A: OpenTelemetry Collector + Backends** (Recommended)
```yaml
# otel-collector-config.yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317

processors:
  batch:

exporters:
  # Metrics storage
  prometheusremotewrite:
    endpoint: "http://prometheus:9090/api/v1/write"

  # Traces storage
  jaeger:
    endpoint: "jaeger:14250"
    tls:
      insecure: true

  # Logs storage
  elasticsearch:
    endpoints: ["http://elasticsearch:9200"]
    index: "mahavishnu-logs"

service:
  pipelines:
    metrics:
      receivers: [otlp]
      processors: [batch]
      exporters: [prometheusremotewrite]

    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [jaeger]

    logs:
      receivers: [otlp]
      processors: [batch]
      exporters: [elasticsearch]
```

**Query Interfaces**:
- **Metrics**: Prometheus UI / Grafana
- **Traces**: Jaeger UI
- **Logs**: Kibana (Elasticsearch)

**Option B: Direct Storage with Oneiric Adapters** (Future)

```python
# oneiric/adapters/observability/otel.py
class OTelStorageAdapter:
    """Store OTel data directly to databases."""

    async def store_metrics(
        self,
        metrics: List[MetricData]
    ) -> None:
        """Store metrics to PostgreSQL."""
        # Use PostgresDatabaseAdapter

    async def store_traces(
        self,
        traces: List[SpanData]
    ) -> None:
        """Store traces to pgvector for similarity search."""
        # Use PgvectorAdapter
```

**Option C: Lightweight Local Storage** (Development)

```python
# mahavishnu/core/observability.py
class ObservabilityManager:
    def __init__(self, config):
        # Internal storage for development
        self.logs: List[LogEntry] = []
        self.metrics: List[MetricData] = []
        self.traces: List[SpanData] = []

    async def query_logs(
        self,
        level: LogLevel | None = None,
        trace_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> List[LogEntry]:
        """Query stored logs."""
        results = self.logs

        if level:
            results = [l for l in results if l.level == level]

        if trace_id:
            results = [l for l in results if l.trace_id == trace_id]

        if start_time:
            results = [l for l in results if l.timestamp >= start_time]

        if end_time:
            results = [l for l in results if l.timestamp <= end_time]

        return results
```

### Recommended OTel Stack:

```
┌─────────────────────────────────────────────────┐
│          Mahavishnu Application                 │
│  - Metrics (counters, histograms)               │
│  - Traces (spans with trace_id)                 │
│  - Logs (correlated with trace_id)              │
└────────────┬────────────────────────────────────┘
             │ PUSH (OTLP/gRPC)
             ▼
┌─────────────────────────────────────────────────┐
│      OpenTelemetry Collector                    │
│  - Receives OTLP on port 4317                   │
│  - Batches and processes data                   │
│  - Routes to multiple backends                  │
└─────┬───────────┬───────────────┬────────────────┘
      │           │               │
      ▼           ▼               ▼
┌─────────┐ ┌─────────┐   ┌─────────────┐
│Prometheus│ │ Jaeger  │   │Elasticsearch│
│ Metrics  │ │ Traces  │   │    Logs     │
└────┬────┘ └────┬────┘   └──────┬──────┘
     │           │               │
     ▼           ▼               ▼
┌─────────┐ ┌─────────┐   ┌─────────────┐
│ Grafana │ │ Jaeger  │   │   Kibana    │
│  Query  │ │  Query  │   │   Query     │
└─────────┘ └─────────┘   └─────────────┘
```

### Quick Start: Local OTel Stack

**Docker Compose**:
```yaml
version: '3.8'
services:
  # OTel Collector
  otel-collector:
    image: otel/opentelemetry-collector:latest
    command: --config=/etc/otel-collector-config.yaml
    volumes:
      - ./otel-collector-config.yaml:/etc/otel-collector-config.yaml
    ports:
      - "4317:4317"  # OTLP gRPC receiver
      - "4318:4318"  # OTLP HTTP receiver
    depends_on:
      - jaeger
      - prometheus
      - elasticsearch

  # Jaeger (Traces)
  jaeger:
    image: jaegertracing/all-in-one:latest
    ports:
      - "16686:16686"  # Jaeger UI
      - "14250:14250"  # OTLP gRPC

  # Prometheus (Metrics)
  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"  # Prometheus UI
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml

  # Grafana (Visualization)
  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"  # Grafana UI
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin

  # Elasticsearch (Logs)
  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:8.11.0
    ports:
      - "9200:9200"
    environment:
      - discovery.type=single-node
      - xpack.security.enabled=false

  # Kibana (Logs UI)
  kibana:
    image: docker.elastic.co/kibana/kibana:8.11.0
    ports:
      - "5601:5601"  # Kibana UI
    depends_on:
      - elasticsearch
```

**Start**:
```bash
docker-compose up -d
```

**Configure Mahavishnu**:
```yaml
# settings/mahavishnu.yaml
metrics_enabled: true
tracing_enabled: true
otlp_endpoint: "http://localhost:4317"  # OTLP gRPC
```

**Access UIs**:
- Grafana: http://localhost:3000
- Jaeger: http://localhost:16686
- Prometheus: http://localhost:9090
- Kibana: http://localhost:5601

### Log Query Examples:

**Jaeger (Traces)**:
```
# Find all traces for a workflow
Service: mahavishnu
Operation: process_repository
Tags: repo="path/to/repo"

# Find slow operations
Duration: > 5s
```

**Grafana (Metrics)**:
```promql
# Workflow execution rate
rate(mahavishnu_workflows_executed_total[5m])

# Error rate
rate(mahavishnu_errors_count_total[5m])

# P95 workflow duration
histogram_quantile(0.95,
  rate(mahavishnu_workflow_duration_seconds_bucket[5m])
)
```

**Kibana (Logs)**:
```json
// Query logs with trace correlation
{
  "query": {
    "bool": {
      "must": [
        {"match": {"service.name": "mahavishnu"}},
        {"range": {"timestamp": {"gte": "now-1h"}}}
      ]
    }
  }
}
```

---

## Part 2: Oneiric Device Discovery

### Question: Push vs Pull vs Hybrid?

**Answer**: **Hybrid approach is best**

**Recommended Pattern**:
- **Announce (Push)**: Devices announce when they come online
- **Poll (Pull)**: Central coordinator queries for current state
- **Heartbeat**: Regular health checks

### Device Discovery Patterns:

**Pattern 1: Pure Push (Announcement)**
```
Device Startup → Broadcast "I'm here!" → Coordinator registers device
Pros: Fast discovery, low coordinator load
Cons: Missed announcements, stale data, no health checks
```

**Pattern 2: Pure Pull (Polling)**
```
Coordinator → Poll all devices → Devices respond → Coordinator updates state
Pros: Always current, reliable, health checks built-in
Cons: High coordinator load, slower discovery, network churn
```

**Pattern 3: Hybrid (Best of Both)** ⭐
```
1. Device Startup → Announce to coordinator
2. Coordinator → Registers device
3. Periodic → Coordinator polls for health/updates
4. Device State Changes → Push updates to coordinator
```

### Recommended Oneiric MCP Discovery Architecture:

```
┌─────────────────────────────────────────────────┐
│           Discovery Coordinator                  │
│  - Maintains device registry                    │
│  - Handles announcements                        │
│  - Polls for health checks                      │
│  - Pushes config updates                        │
└──────────┬───────────┬──────────────────┬────────┘
           │           │                  │
    ┌──────▼─────┐ ┌──▼──────┐  ┌───────▼──────┐
    │  Push API  │ │Pull API │  │  Registry DB │
    │ /announce  │ │/poll    │  │  (SQLite/    │
    │ /heartbeat │ │/query   │  │   PostgreSQL)│
    └─────────────┘ └─────────┘  └──────────────┘
           ▲                                        ▲
           │                                        │
    ┌──────┴─────────────────────────────────────┴───┐
    │               Oneiric Devices                  │
    │  ┌──────────┐  ┌──────────┐  ┌─────────────┐  │
    │  | Device 1 │  | Device 2 │  |  Device N   │  │
    │  | (MCP)    │  | (MCP)    │  |   (MCP)     │  │
    │  └──────────┘  └──────────┘  └─────────────┘  │
    └────────────────────────────────────────────────┘
```

### Implementation: MCP Discovery Server

**Oneiric MCP Server Tools**:

```python
# oneiric/mcp/server.py
@mcp.tool()
async def announce_device(
    device_id: str,
    device_type: str,
    capabilities: List[str],
    endpoint: str
) -> dict[str, Any]:
    """Announce a device to the coordinator.

    Called by devices when they come online.
    """
    device = {
        "device_id": device_id,
        "device_type": device_type,
        "capabilities": capabilities,
        "endpoint": endpoint,
        "last_seen": datetime.now(),
        "status": "online"
    }

    # Store in registry
    await registry.register_device(device)

    return {
        "status": "registered",
        "device_id": device_id,
        "heartbeat_interval": 30  # seconds
    }

@mcp.tool()
async def heartbeat(
    device_id: str,
    status: str = "online"
) -> dict[str, Any]:
    """Device heartbeat.

    Called periodically to update device health.
    """
    await registry.update_heartbeat(device_id, status)

    return {"status": "ok"}

@mcp.tool()
async def poll_devices(
    device_type: str | None = None,
    status: str = "online"
) -> List[dict[str, Any]]:
    """Poll for device list.

    Called by coordinator to get current device state.
    """
    devices = await registry.get_devices(
        device_type=device_type,
        status=status
    )

    return devices

@mcp.resource("devices://")
async def list_all_devices() -> List[dict[str, Any]]:
    """Get all devices as a resource."""
    return await registry.get_devices()

@mcp.resource("devices/{device_id}")
async def get_device(device_id: str) -> dict[str, Any]:
    """Get specific device info."""
    return await registry.get_device(device_id)
```

### Device-Side Implementation:

```python
# oneiric/device/client.py
class OneiricDeviceClient:
    """Client for Oneiric devices to announce themselves."""

    def __init__(
        self,
        device_id: str,
        device_type: str,
        coordinator_url: str
    ):
        self.device_id = device_id
        self.device_type = device_type
        self.coordinator = MCPClient(coordinator_url)

    async def announce(self) -> None:
        """Announce device to coordinator on startup."""
        await self.coordinator.call_tool(
            "announce_device",
            {
                "device_id": self.device_id,
                "device_type": self.device_type,
                "capabilities": self.get_capabilities(),
                "endpoint": self.get_endpoint()
            }
        )

        # Start heartbeat loop
        asyncio.create_task(self._heartbeat_loop())

    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeats."""
        while True:
            await asyncio.sleep(30)  # 30 seconds
            try:
                await self.coordinator.call_tool(
                    "heartbeat",
                    {
                        "device_id": self.device_id,
                        "status": "online"
                    }
                )
            except Exception as e:
                logger.error(f"Heartbeat failed: {e}")

    def get_capabilities(self) -> List[str]:
        """Return device capabilities."""
        # Implemented by subclasses
        return []

    def get_endpoint(self) -> str:
        """Return device endpoint URL."""
        # Implemented by subclasses
        return ""
```

### Registry Implementation:

```python
# oneiric/device/registry.py
class DeviceRegistry:
    """Registry for Oneiric devices."""

    def __init__(self, db_adapter: PostgresDatabaseAdapter):
        self.db = db_adapter

    async def register_device(self, device: dict) -> None:
        """Register or update a device."""
        await self.db.execute("""
            INSERT INTO devices (device_id, device_type, capabilities,
                                 endpoint, last_seen, status)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (device_id) DO UPDATE SET
                last_seen = EXCLUDED.last_seen,
                status = EXCLUDED.status,
                endpoint = EXCLUDED.endpoint
        """, device["device_id"], device["device_type"],
             device["capabilities"], device["endpoint"],
             device["last_seen"], device["status"])

    async def update_heartbeat(
        self,
        device_id: str,
        status: str
    ) -> None:
        """Update device heartbeat."""
        await self.db.execute("""
            UPDATE devices
            SET last_seen = NOW(), status = $2
            WHERE device_id = $1
        """, device_id, status)

    async def get_devices(
        self,
        device_type: str | None = None,
        status: str = "online"
    ) -> List[dict]:
        """Get devices matching criteria."""
        query = "SELECT * FROM devices WHERE status = $1"
        params = [status]

        if device_type:
            query += " AND device_type = $2"
            params.append(device_type)

        return await self.db.fetch_all(query, *params)

    async def get_stale_devices(
        self,
        timeout_seconds: int = 120
    ) -> List[dict]:
        """Find devices that haven't sent heartbeat recently."""
        return await self.db.fetch_all("""
            SELECT * FROM devices
            WHERE last_seen < NOW() - INTERVAL '1 second' * $1
            AND status = 'online'
        """, timeout_seconds)

    async def mark_devices_offline(
        self,
        device_ids: List[str]
    ) -> None:
        """Mark devices as offline."""
        await self.db.execute("""
            UPDATE devices
            SET status = 'offline'
            WHERE device_id = ANY($1)
        """, device_ids)
```

### Background Health Check Task:

```python
# oneiric/device/health_monitor.py
class DeviceHealthMonitor:
    """Background task to monitor device health."""

    def __init__(
        self,
        registry: DeviceRegistry,
        check_interval: int = 60
    ):
        self.registry = registry
        self.check_interval = check_interval

    async def start(self) -> None:
        """Start health check loop."""
        while True:
            await self._check_devices()
            await asyncio.sleep(self.check_interval)

    async def _check_devices(self) -> None:
        """Check for stale devices."""
        # Find devices that haven't sent heartbeat
        stale = await self.registry.get_stale_devices(
            timeout_seconds=120  # 2 minutes
        )

        if stale:
            stale_ids = [d["device_id"] for d in stale]
            await self.registry.mark_devices_offline(stale_ids)

            logger.warning(
                f"Marked {len(stale)} devices as offline: {stale_ids}"
            )
```

### Database Schema:

```sql
-- Oneiric device registry
CREATE TABLE IF NOT EXISTS devices (
    device_id VARCHAR PRIMARY KEY,
    device_type VARCHAR NOT NULL,
    capabilities JSONB,
    endpoint VARCHAR NOT NULL,
    last_seen TIMESTAMP NOT NULL,
    status VARCHAR NOT NULL,  -- online, offline, degraded
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_devices_type ON devices(device_type);
CREATE INDEX idx_devices_status ON devices(status);
CREATE INDEX idx_devices_last_seen ON devices(last_seen);

-- Device capabilities search
CREATE INDEX idx_devices_capabilities ON devices USING GIN(capabilities);
```

### Complete Discovery Flow:

**1. Device Startup**:
```python
# Device starts up
client = OneiricDeviceClient(
    device_id="fastblocks-dev-1",
    device_type="fastblocks-runtime",
    coordinator_url="http://localhost:3030"
)

# Announce to coordinator
await client.announce()
# Result: Device registered in database
```

**2. Coordinator Poll**:
```python
# Coordinator queries for devices
devices = await coordinator.call_tool(
    "poll_devices",
    {"device_type": "fastblocks-runtime", "status": "online"}
)
# Result: List of online FastBlocks devices
```

**3. Health Check**:
```python
# Background monitor runs every 60 seconds
await health_monitor._check_devices()
# Result: Stale devices marked offline
```

**4. Resource Query**:
```python
# Get all devices as resource
devices = await coordinator.get_resource("devices://")
# Result: All registered devices
```

### Comparison: Push vs Pull vs Hybrid

| Aspect | Push Only | Pull Only | Hybrid (Recommended) |
|--------|-----------|-----------|----------------------|
| **Discovery Speed** | Fast (immediate) | Slow (next poll) | Fast (immediate) |
| **Data Freshness** | Stale (miss updates) | Fresh (always current) | Fresh (both) |
| **Coordinator Load** | Low | High | Medium |
| **Network Traffic** | Burst (startup) | Steady (polling) | Balanced |
| **Health Checks** | Requires separate system | Built-in | Built-in |
| **Scalability** | Excellent | Poor | Good |
| **Reliability** | Low (miss msgs) | High | High |

### Best Practices:

**1. Heartbeat Interval**: 30 seconds
- Fast enough for quick detection
- Slow enough to avoid network churn

**2. Stale Timeout**: 120 seconds (4 heartbeats)
- Allows for temporary network issues
- Quick enough to detect failures

**3. Announcement Retry**: Exponential backoff
```python
async def announce_with_retry(self, max_retries=5):
    for attempt in range(max_retries):
        try:
            await self.announce()
            return
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)  # 1s, 2s, 4s, 8s
```

**4. Capability Discovery**: Rich metadata
```python
{
    "device_id": "fastblocks-dev-1",
    "device_type": "fastblocks-runtime",
    "capabilities": [
        "block_execution",
        "pipeline_orchestration",
        "metrics_export"
    ],
    "version": "1.0.0",
    "resources": {
        "cpu_cores": 4,
        "memory_gb": 16,
        "gpu": false
    }
}
```

---

## 📊 Summary

### OpenTelemetry:
- ✅ **Mahavishnu already has OTel integration**
- ✅ **PUSH model** (application → collector)
- ✅ **Can query via** Grafana, Jaeger, Kibana
- ✅ **Log-trace correlation** built-in
- **Recommendation**: Use OTel Collector + backend stack

### Device Discovery:
- ✅ **Hybrid approach** (push + pull)
- ✅ **Announce on startup** (fast discovery)
- ✅ **Heartbeat for health** (reliability)
- ✅ **Poll for state** (fresh data)
- ✅ **MCP-based** (standard protocol)
- **Recommendation**: Implement hybrid MCP discovery server

---

## 🚀 Next Steps

### OTel Integration (4 hours):
1. [ ] Deploy OTel Collector (Docker Compose)
2. [ ] Configure Jaeger, Prometheus, Elasticsearch
3. [ ] Set up Grafana dashboards
4. [ ] Verify Mahavishnu data flow

### Device Discovery (16 hours):
1. [ ] Create MCP discovery server (4h)
2. [ ] Implement device registry (4h)
3. [ ] Build device client library (4h)
4. [ ] Add health monitor (4h)

**Total**: 20 hours for both systems

Ready to implement? 🚀
