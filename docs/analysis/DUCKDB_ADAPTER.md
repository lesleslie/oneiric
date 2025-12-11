# DuckDB Database Adapter

**Status:** Production Ready
**Date:** 2025-11-27
**Category:** database

---

## Overview

DuckDB is an in-process SQL OLAP (Online Analytical Processing) database management system. It's designed for analytical workloads and provides excellent performance for complex queries on structured data.

**Key Features:**
- ✅ **In-Memory & File-Based** - Support for both :memory: and persistent databases
- ✅ **Columnar Storage** - Optimized for analytical queries
- ✅ **Extensions** - Modular functionality (httpfs, postgres_scanner, etc.)
- ✅ **Arrow Integration** - Native Apache Arrow support
- ✅ **Pandas Integration** - Direct DataFrame export
- ✅ **PRAGMA Configuration** - Fine-grained control
- ✅ **Read-Only Mode** - Safe concurrent access

---

## Use Cases

DuckDB is ideal for:

1. **Data Analytics** - Fast aggregations, window functions, complex joins
2. **Data Pipelines** - ETL/ELT processing with minimal infrastructure
3. **Data Science** - Seamless integration with pandas and Arrow
4. **Embedded Analytics** - No server required, embedded in application
5. **Development/Testing** - Fast in-memory database for tests
6. **Data Warehousing** - Lightweight alternative to large-scale warehouses

**Not Suitable For:**
- High-concurrency write workloads (use PostgreSQL/MySQL)
- Distributed systems (DuckDB is single-node)
- Real-time OLTP (use traditional RDBMS)

---

## Configuration

### Basic Configuration

```yaml
# settings/adapters.yml
database: duckdb
```

```python
from oneiric.adapters.database import DuckDBDatabaseSettings

# In-memory database (fastest)
settings = DuckDBDatabaseSettings(
    database_url="duckdb:///:memory:",
)

# File-based database (persistent)
settings = DuckDBDatabaseSettings(
    database_url="duckdb:///data/warehouse.duckdb",
)

# Read-only mode (safe concurrent reads)
settings = DuckDBDatabaseSettings(
    database_url="duckdb:///data/warehouse.duckdb",
    read_only=True,
)
```

### Advanced Configuration

```python
from oneiric.adapters.database import DuckDBDatabaseSettings

settings = DuckDBDatabaseSettings(
    database_url="duckdb:///data/warehouse.duckdb",

    # Performance tuning
    threads=4,  # Number of threads for query execution
    pragmas={
        "memory_limit": "4GB",     # Max memory usage
        "temp_directory": "/tmp",  # Spill-to-disk location
        "enable_profiling": "true", # Query profiling
    },

    # Extensions
    extensions=[
        "httpfs",           # Read from HTTP/S3
        "postgres_scanner", # Query PostgreSQL databases
        "json",            # JSON functions
        "parquet",         # Parquet file support
    ],

    # Temporary directory (spill-to-disk)
    temp_directory="/tmp/duckdb",
)
```

---

## Usage

### Basic Queries

```python
from oneiric.core.lifecycle import LifecycleManager

# Activate adapter
adapter = await lifecycle.activate("adapter", "database")

# Create table
await adapter.execute("""
    CREATE TABLE users (
        id INTEGER PRIMARY KEY,
        name VARCHAR,
        age INTEGER,
        department VARCHAR
    )
""")

# Insert data
await adapter.execute(
    "INSERT INTO users VALUES (?, ?, ?, ?)",
    1, "Alice", 30, "Engineering"
)

# Fetch all rows
rows = await adapter.fetch_all("SELECT * FROM users WHERE age > ?", 25)
for row in rows:
    print(row)

# Fetch one row
row = await adapter.fetch_one("SELECT * FROM users WHERE id = ?", 1)
print(row)
```

### Analytical Queries

```python
# Complex aggregation
result = await adapter.fetch_all("""
    SELECT
        department,
        COUNT(*) as employee_count,
        AVG(age) as avg_age,
        MAX(age) as max_age
    FROM users
    GROUP BY department
    ORDER BY employee_count DESC
""")

# Window functions
result = await adapter.fetch_all("""
    SELECT
        name,
        age,
        department,
        ROW_NUMBER() OVER (PARTITION BY department ORDER BY age DESC) as rank
    FROM users
""")

# CTEs (Common Table Expressions)
result = await adapter.fetch_all("""
    WITH dept_stats AS (
        SELECT department, AVG(age) as avg_age
        FROM users
        GROUP BY department
    )
    SELECT u.*, d.avg_age as dept_avg_age
    FROM users u
    JOIN dept_stats d ON u.department = d.department
""")
```

### Pandas Integration

```python
# Execute query and get DataFrame
df = await adapter.fetch_df("SELECT * FROM users")
print(df.head())

# Use DataFrame for further analysis
import pandas as pd
print(df.groupby("department")["age"].mean())

# Write DataFrame back to DuckDB
await adapter.execute("CREATE TABLE results AS SELECT * FROM df")
```

### Arrow Integration

```python
# Get results as Arrow table
arrow_table = await adapter.fetch_arrow("SELECT * FROM users")

# Arrow table can be used with other systems
# - Write to Parquet
# - Stream to other databases
# - Process with Arrow compute functions

import pyarrow.parquet as pq
pq.write_table(arrow_table, "users.parquet")
```

---

## Extensions

DuckDB extensions provide modular functionality. Extensions are automatically installed and loaded during `init()`.

### Common Extensions

```python
settings = DuckDBDatabaseSettings(
    database_url="duckdb:///data/warehouse.duckdb",
    extensions=[
        # File formats
        "parquet",    # Parquet files
        "json",       # JSON functions
        "excel",      # Excel files

        # Remote access
        "httpfs",     # HTTP/HTTPS/S3 access
        "postgres_scanner",  # Query PostgreSQL
        "sqlite_scanner",    # Query SQLite
        "mysql_scanner",     # Query MySQL

        # Analytics
        "fts",        # Full-text search
        "spatial",    # Geospatial functions
        "tpch",       # TPC-H benchmark queries

        # Machine learning
        "ml",         # ML models
    ],
)
```

### Using Extensions

```python
# Read from S3 (requires httpfs extension)
await adapter.execute("""
    CREATE TABLE data AS
    SELECT * FROM read_parquet('s3://bucket/data.parquet')
""")

# Query PostgreSQL (requires postgres_scanner extension)
await adapter.execute("""
    CREATE TABLE pg_data AS
    SELECT * FROM postgres_scan('host=localhost dbname=mydb', 'public', 'users')
""")

# Full-text search (requires fts extension)
await adapter.execute("""
    CREATE TABLE documents (id INTEGER, content TEXT)
""")
await adapter.execute("""
    CREATE INDEX idx_fts ON documents USING fts(content)
""")
rows = await adapter.fetch_all("""
    SELECT * FROM documents WHERE content MATCH 'search term'
""")
```

---

## Performance Tuning

### Memory Management

```python
settings = DuckDBDatabaseSettings(
    pragmas={
        # Set memory limit
        "memory_limit": "8GB",  # Max memory before spilling to disk

        # Set temp directory for spill-to-disk
        "temp_directory": "/fast-ssd/duckdb-temp",

        # Enable memory profiling
        "enable_profiling": "true",
    },
)
```

### Threading

```python
settings = DuckDBDatabaseSettings(
    threads=8,  # Use 8 threads for parallel execution
    pragmas={
        "threads": "8",  # Alternative way to set threads
    },
)

# Query DuckDB's thread usage
rows = await adapter.fetch_all("PRAGMA threads")
print(rows)  # [(8,)]
```

### Query Optimization

```python
# Enable query profiling
await adapter.execute("PRAGMA enable_profiling='json'")
await adapter.execute("PRAGMA profiling_output='/tmp/profile.json'")

# Run your query
await adapter.fetch_all("SELECT * FROM large_table WHERE condition = true")

# Check profiling output
import json
with open("/tmp/profile.json") as f:
    profile = json.load(f)
    print(profile)
```

### Indexes

```python
# Create indexes for faster lookups
await adapter.execute("CREATE INDEX idx_user_name ON users(name)")
await adapter.execute("CREATE INDEX idx_user_dept ON users(department)")

# Use EXPLAIN to check query plan
rows = await adapter.fetch_all("EXPLAIN SELECT * FROM users WHERE name = 'Alice'")
for row in rows:
    print(row)
```

---

## File Formats

DuckDB can directly query various file formats without loading them into tables first.

### Parquet Files

```python
# Read Parquet file
rows = await adapter.fetch_all("""
    SELECT * FROM read_parquet('data.parquet')
    WHERE age > 25
""")

# Write to Parquet
await adapter.execute("""
    COPY (SELECT * FROM users) TO 'users.parquet' (FORMAT 'parquet')
""")

# Read multiple files (glob pattern)
rows = await adapter.fetch_all("""
    SELECT * FROM read_parquet('data/*.parquet')
""")
```

### CSV Files

```python
# Read CSV
rows = await adapter.fetch_all("""
    SELECT * FROM read_csv('data.csv', header=true)
""")

# Write to CSV
await adapter.execute("""
    COPY (SELECT * FROM users) TO 'users.csv' (HEADER, DELIMITER ',')
""")
```

### JSON Files

```python
# Read JSON
rows = await adapter.fetch_all("""
    SELECT * FROM read_json('data.json')
""")

# Write to JSON
await adapter.execute("""
    COPY (SELECT * FROM users) TO 'users.json'
""")
```

---

## Transactions

DuckDB supports ACID transactions:

```python
# Begin transaction
await adapter.execute("BEGIN TRANSACTION")

try:
    # Multiple operations
    await adapter.execute("INSERT INTO users VALUES (?, ?, ?, ?)", 2, "Bob", 35, "Sales")
    await adapter.execute("UPDATE users SET age = age + 1 WHERE id = 1")

    # Commit
    await adapter.execute("COMMIT")
except Exception as exc:
    # Rollback on error
    await adapter.execute("ROLLBACK")
    raise
```

---

## Health Checks & Lifecycle

```python
from oneiric.core.lifecycle import LifecycleManager

lifecycle = LifecycleManager(resolver)

# Activate
adapter = await lifecycle.activate("adapter", "database")

# Health check
is_healthy = await lifecycle.probe_instance_health("adapter", "database")
print(is_healthy)  # True

# Get status
status = lifecycle.get_status("adapter", "database")
print(status.state)  # "ready"

# Cleanup
await lifecycle.cleanup_instance("adapter", "database")
```

---

## Testing

DuckDB is excellent for testing due to in-memory mode:

```python
import pytest
from oneiric.adapters.database import DuckDBDatabaseSettings

@pytest.fixture
async def duckdb_adapter(lifecycle):
    """In-memory DuckDB for testing."""
    settings = DuckDBDatabaseSettings(
        database_url="duckdb:///:memory:",
    )

    adapter = await lifecycle.activate("adapter", "database")

    # Setup test schema
    await adapter.execute("""
        CREATE TABLE test_users (
            id INTEGER PRIMARY KEY,
            name VARCHAR
        )
    """)

    yield adapter

    # Cleanup
    await lifecycle.cleanup_instance("adapter", "database")


@pytest.mark.asyncio
async def test_query(duckdb_adapter):
    """Test DuckDB queries."""
    # Insert
    await duckdb_adapter.execute(
        "INSERT INTO test_users VALUES (?, ?)",
        1, "Alice"
    )

    # Query
    rows = await duckdb_adapter.fetch_all("SELECT * FROM test_users")
    assert len(rows) == 1
    assert rows[0][1] == "Alice"
```

---

## Comparison with Other Databases

| Feature              | DuckDB       | SQLite       | PostgreSQL   |
|---------------------|-------------|--------------|--------------|
| **Analytics**       | Excellent   | Poor         | Good         |
| **OLTP**            | Poor        | Good         | Excellent    |
| **Concurrency**     | Read-heavy  | Limited      | Excellent    |
| **Memory Usage**    | Configurable| Low          | High         |
| **Setup**           | Embedded    | Embedded     | Server       |
| **Extensions**      | Yes         | Limited      | Yes          |
| **Arrow/Pandas**    | Native      | Manual       | Manual       |

**Use DuckDB when:**
- Analytical queries are primary workload
- Embedded database is preferred
- Working with DataFrames/Arrow
- Need fast aggregations and joins

**Use SQLite when:**
- Simple OLTP workload
- Very low memory footprint
- Minimal dependencies

**Use PostgreSQL when:**
- High write concurrency needed
- Production OLTP workload
- Multi-user environment

---

## Migration from SQLite

DuckDB can read SQLite databases directly:

```python
# Attach SQLite database
await adapter.execute("ATTACH 'data.sqlite' AS sqlite_db")

# Query SQLite tables
rows = await adapter.fetch_all("SELECT * FROM sqlite_db.users")

# Copy to DuckDB
await adapter.execute("""
    CREATE TABLE users AS
    SELECT * FROM sqlite_db.users
""")

# Detach
await adapter.execute("DETACH sqlite_db")
```

---

## References

- **DuckDB Docs:** https://duckdb.org/docs/
- **Extensions:** https://duckdb.org/docs/extensions/overview
- **ADAPTER_STRATEGY.md** - Adapter porting roadmap
- **ACB Comparison:** `docs/ACB_COMPARISON.md`

---

## Summary

- ✅ **DuckDB adapter** production-ready
- ✅ **Analytics-optimized** for OLAP workloads
- ✅ **Extensions support** (httpfs, postgres_scanner, etc.)
- ✅ **Arrow/Pandas integration** for data science
- ✅ **Lifecycle integration** with health checks
- 🎯 **Perfect for:** Data pipelines, analytics, embedded warehouses
