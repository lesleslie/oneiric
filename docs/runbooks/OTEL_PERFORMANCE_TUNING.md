# OTel Storage Adapter - Performance Tuning Guide

## Baseline Performance

### Expected Query Times (100K traces)

- Vector similarity: ~50ms (with IVFFlat)
- Error search: ~20ms
- Trace context: ~30ms
- Batch insert (100 traces): ~200ms

### Performance Targets

- p50 latency: \<30ms
- p95 latency: \<100ms
- p99 latency: \<500ms
- Throughput: 1000 traces/second

## Common Performance Issues

### Slow Vector Similarity Search

**Symptoms:**

- Vector queries taking >500ms
- High CPU usage on database

**Diagnosis:**

```sql
EXPLAIN ANALYZE
SELECT * FROM otel_traces
ORDER BY embedding <=> '[...384-dim vector...]'
LIMIT 10;
```

**Solutions:**

1. **Create IVFFlat index** (see Index Management Guide)
1. **Increase similarity threshold** (reduce result set)
1. **Limit search scope** (add time range filter)

### Slow Error Search

**Symptoms:**

- Error queries taking >200ms
- Full table scans

**Diagnosis:**

```sql
EXPLAIN ANALYZE
SELECT * FROM otel_traces
WHERE attributes->>'error.message' LIKE '%timeout%';
```

**Solutions:**

1. **Add composite index:** `(start_time, status)`
1. **Use GIN index** on attributes (automatic)
1. **Reduce time range** (add start/end filters)

### High Memory Usage

**Symptoms:**

- Adapter process using >2GB RAM
- OOM kills

**Solutions:**

1. **Reduce buffer size:** Set `batch_size=50` in settings
1. **Reduce flush interval:** Set `batch_interval_seconds=3`
1. **Limit trace history:** Partition old data

### Slow Batch Inserts

**Symptoms:**

- Buffer flush taking >1 second
- Write backlog growing

**Diagnosis:**

```sql
SELECT count(*), min(start_time), max(start_time)
FROM otel_traces;
```

**Solutions:**

1. **Use unlogged tables** (if durability not critical)
1. **Increase connection pool:** Set `max_retries=10`
1. **Batch in parallel** (multiple insert workers)

## Tuning Parameters

### Settings Configuration

```python
OTelStorageSettings(
    # Increase for high write throughput
    batch_size=500,  # Default: 100
    batch_interval_seconds=10,  # Default: 5

    # Decrease for lower latency
    max_retries=5,  # Default: 3 (pool size)

    # Vector search tuning
    similarity_threshold=0.85,  # Reduce to speed up
)
```

### PostgreSQL Configuration

```ini
# postgresql.conf

shared_buffers = 4GB  # 25% of RAM
effective_cache_size = 12GB  # 75% of RAM
work_mem = 256MB  # Per-operation memory
maintenance_work_mem = 1GB

# Pgvector tuning
ivfflat.probes = 1  # Faster queries, less accuracy
```

## Load Testing

### Generate Synthetic Traces

```python
import asyncio
import numpy as np
from datetime import datetime, UTC
from oneiric.adapters.observability.otel import OTelStorageAdapter

async def load_test(num_traces=10000):
    adapter = OTelStorageAdapter(settings=...)
    await adapter.init()

    for batch_start in range(0, num_traces, 100):
        batch = []
        for i in range(100):
            trace = {
                "trace_id": f"load-{batch_start + i}",
                "name": f"operation_{i % 50}",
                "start_time": datetime.now(UTC),
                "status": "OK",
                "attributes": {},
            }
            batch.append(trace)

        for trace in batch:
            await adapter.store_trace(trace)

    await adapter.cleanup()

asyncio.run(load_test(10000))
```

### Monitor During Load Test

```bash
# Database connections
psql -c "SELECT count(*) FROM pg_stat_activity;"

# Index usage
psql -c "SELECT idx_scan FROM pg_stat_user_indexes WHERE indexname LIKE '%ivfflat%';"

# Table size
psql -c "SELECT pg_size_pretty(pg_total_relation_size('otel_traces'));"
```

## Performance Monitoring

### Enable Query Logging

```python
import logging
logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)
```

### Export Metrics

The adapter exports metrics via Structlog:

```python
from oneiric.adapters.observability.monitoring import OTelMetrics

metrics = adapter._query_service._metrics
summary = metrics.get_metrics_summary()
print(summary)
# {"query_counts": {"find_similar_traces": 150}, ...}
```

## Performance Checklist

Before production deployment:

- [ ] IVFFlat index created (1000+ traces)
- [ ] Query optimization indexes created
- [ ] Baseline benchmarks established
- [ ] Load testing completed (10K+ traces)
- [ ] Monitoring configured
- [ ] Runbooks reviewed
- [ ] Rollback plan documented
