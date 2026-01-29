# OTel Storage Adapter - Index Management Guide

## Overview

The OTel Storage Adapter uses IVFFlat vector indexing for fast similarity search. This guide covers index creation, monitoring, and maintenance.

## Index Types

### IVFFlat Vector Index

- **Purpose:** Fast vector similarity search (10-50x improvement)
- **Trigger:** Automatic creation after 1000+ traces
- **Location:** `ix_traces_embedding_ivfflat`
- **Maintenance:** Reindex after significant data changes

### B-Tree Indexes

- **Purpose:** Standard queries (trace_id, time ranges, status)
- **Created:** Automatically during schema creation
- **Maintenance:** PostgreSQL autovacuum handles

### GIN Index

- **Purpose:** JSON attribute queries
- **Location:** `ix_traces_attributes_gin`
- **Maintenance:** Periodic REINDEX recommended

### Composite Index

- **Purpose:** Time-range error queries
- **Location:** `ix_traces_start_time_status`
- **Maintenance:** PostgreSQL autovacuum handles

## Manual Index Creation

If automatic creation fails, create manually:

```sql
-- IVFFlat index
CREATE INDEX CONCURRENTLY ix_traces_embedding_ivfflat
ON otel_traces
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- Query optimization indexes
CREATE INDEX CONCURRENTLY ix_traces_start_time_status
ON otel_traces (start_time, status);

CREATE INDEX CONCURRENTLY ix_traces_attributes_gin
ON otel_traces USING GIN (attributes);
```

## Index Monitoring

Check index usage:

```sql
-- Index size
SELECT indexname, pg_size_pretty(pg_relation_size(indexrelid))
FROM pg_indexes
WHERE tablename = 'otel_traces';

-- Index usage statistics
SELECT schemaname, tablename, indexname, idx_scan, idx_tup_read
FROM pg_stat_user_indexes
WHERE tablename = 'otel_traces'
ORDER BY idx_scan DESC;

-- IVFFlat index effectiveness
SELECT
    COUNT(*) as total_traces,
    COUNT(*) FILTER (WHERE embedding IS NOT NULL) as indexed_traces
FROM otel_traces;
```

## Troubleshooting

### Index Not Created

**Symptom:** Vector queries still slow after 1000+ traces

**Check:**

```sql
SELECT indexname FROM pg_indexes
WHERE tablename = 'otel_traces' AND indexname LIKE '%ivfflat%';
```

**Solution:** Run manual creation (see above)

### Index Bloat

**Symptom:** Write performance degraded

**Check:**

```sql
SELECT
    indexname,
    pg_size_pretty(pg_relation_size(indexrelid)) as size
FROM pg_indexes
WHERE tablename = 'otel_traces'
ORDER BY pg_relation_size(indexrelid) DESC;
```

**Solution:**

```sql
REINDEX INDEX CONCURRENTLY ix_traces_embedding_ivfflat;
```

### High Index Maintenance Overhead

**Symptom:** Index taking >5% write time

**Solutions:**

1. Increase `lists` parameter (try 200 or 300)
1. Reduce data ingestion rate
1. Consider partitioning by time
