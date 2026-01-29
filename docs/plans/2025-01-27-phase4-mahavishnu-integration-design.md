# Phase 4: Mahavishnu Integration Design

**Date:** 2025-01-27
**Status:** Approved Design
**Implementing:** Connect OTelStorageAdapter with Mahavishnu ObservabilityManager

______________________________________________________________________

## Executive Summary

Phase 4 integrates OTelStorageAdapter with Mahavishnu's ObservabilityManager to enable automatic OTel telemetry capture with intelligent PostgreSQL querying capabilities. This provides Mahavishnu with semantic trace search, error pattern matching, and distributed trace correlation.

**Key Features:**

- Dual export strategy (OTLP + PostgreSQL)
- Configurable storage backend selector
- Granular control (traces, metrics, logs)
- Circuit breaker + retry with exponential backoff
- Transformation layer (Mahavishnu → OTel format)
- Non-blocking async operations

**Design Decisions:**

- **Storage backend:** Configurable via `otel_storage_backend` ("otlp", "postgresql", "both")
- **Granular flags:** Separate control for traces, metrics, logs
- **Transformation layer:** Clean separation of concerns
- **Resilience:** Retry (3 attempts) + Circuit breaker (5 failures in 60s)
- **Non-blocking:** All storage operations async, never block workflows

______________________________________________________________________

## Architecture Overview

### Modified ObservabilityManager

**Current State:**

```
ObservabilityManager
    └── OTLP Exporter → Grafana / Datadog / New Relic
```

**After Integration:**

```
ObservabilityManager
    ├── OTLP Exporter (existing) → External platforms
    └── OTelStorageAdapter (new) → PostgreSQL with Pgvector
            ├── store_trace() ✓ (Phase 2)
            ├── store_metrics() ← To implement
            ├── store_log() ← To implement
            └── QueryService ✓ (Phase 3)
```

### Data Flow (Dual Export)

```
Mahavishnu Workflow Execution
    ↓
ObservabilityManager.log_info() / record_metric()
    ↓
┌─────────────────────┴─────────────────────┐
│                                              │
OTLP Exporter (existing)     OTelStorageAdapter (new)
│                                              │
→ Grafana Cloud                        → PostgreSQL
→ Datadog                             → Vector similarity search
→ New Relic                            → Trace correlation
→ Other OTLP-compatible platforms      → Error pattern search
                                              │
└─────────────────────┬─────────────────────┘
                      ↓
    Both exports happen independently
    - OTLP failure doesn't affect PostgreSQL
    - PostgreSQL failure doesn't affect OTLP
    - Circuit breaker protects against cascading failures
```

### Component Interaction

```
Mahavishnu Workflow
    ↓
ObservabilityManager
    ├── log_info(message, trace_id, attributes)
    │   ├── OTLP: Export to external platform
    │   └── PostgreSQL: Store via OTelStorageAdapter
    │       ├── Transform: Mahavishnu LogEntry → OTel format
    │       ├── Circuit breaker: Check state
    │       ├── Retry: 3 attempts with exponential backoff
    │       └── Store: async store_log()
    └── record_metric(name, value, labels)
        ├── OTLP: Export to external platform
        └── PostgreSQL: Store via OTelStorageAdapter
            ├── Transform: Mahavishnu Metric → OTel format
            ├── Circuit breaker protection
            ├── Retry with backoff
            └── Store: async store_metrics()
```

______________________________________________________________________

## Configuration

### Add to MahavishnuSettings

**File:** `/Users/les/Projects/mahavishnu/mahavishnu/core/config.py`

```python
class MahavishnuSettings(MCPServerSettings):
    # ... existing fields ...

    # OTel Storage Configuration
    otel_storage_backend: str = Field(
        default="otlp",
        description="Storage backend: 'otlp', 'postgresql', or 'both'"
    )
    otel_storage_connection_string: str | None = Field(
        default="postgresql://postgres:postgres@localhost:5432/otel",
        description="PostgreSQL connection string"
    )

    # Granular storage flags
    store_traces: bool = Field(
        default=True,
        description="Store traces in PostgreSQL"
    )
    store_metrics: bool = Field(
        default=True,
        description="Store metrics in PostgreSQL"
    )
    store_logs: bool = Field(
        default=True,
        description="Store logs in PostgreSQL"
    )

    # Circuit breaker configuration
    otel_storage_circuit_breaker_failures: int = Field(
        default=5,
        ge=1,
        le=100,
        description="Failures before opening circuit breaker"
    )
    otel_storage_circuit_breaker_timeout: int = Field(
        default=60,
        ge=10,
        le=600,
        description="Seconds in OPEN state before HALF_OPEN"
    )
    otel_storage_retry_max_attempts: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Max retry attempts"
    )
    otel_storage_retry_backoff_ms: int = Field(
        default=100,
        ge=0,
        le=5000,
        description="Initial retry backoff in milliseconds"
    )
```

### Configuration Examples

**Development (PostgreSQL only):**

```yaml
# settings/local.yaml
otel_storage_backend: "postgresql"
store_traces: true
store_metrics: false  # Skip metrics in dev
store_logs: true
```

**Production (Dual export):**

```yaml
# settings/mahavishnu.yaml
otel_storage_backend: "both"
store_traces: true
store_metrics: true
store_logs: true
```

**Minimal (OTLP only - no change):**

```yaml
# settings/mahavishnu.yaml
otel_storage_backend: "otlp"  # Default behavior
```

### Environment Variables

```bash
export MAHAVISHNU_OTEL_STORAGE_BACKEND=both
export MAHAVISHNU_STORE_TRACES=true
export MAHAVISHNU_STORE_METRICS=false
export MAHAVISHNU_STORE_LOGS=true
```

______________________________________________________________________

## Circuit Breaker Design

### State Machine

```
        ┌─────────────┐
        │   CLOSED    │ ← Normal operation
        └──────┬──────┘
               │
        5 failures
        in 60 seconds
               ↓
        ┌─────────────┐
        │    OPEN     │ ← Fail fast
        └──────┬──────┘
               │
        60 seconds
        elapsed
               ↓
        ┌─────────────┐
        │ HALF_OPEN   │ ← Test recovery
        └──────┬──────┘
               │
        Success    Failure
        │           │
        ↓           ↓
     CLOSED      OPEN
```

### Implementation

**File:** `oneiric/adapters/observability/circuit_breaker.py`

```python
class CircuitBreaker:
    """Circuit breaker for protecting against cascading failures."""

    CLOSED: str = "CLOSED"
    HALF_OPEN: str = "HALF_OPEN"
    OPEN: str = "OPEN"

    def __init__(
        self,
        failure_threshold: int = 5,
        timeout_seconds: int = 60
    ):
        self.state = self.CLOSED
        self.failure_count = 0
        self.last_failure_time = None
        self._threshold = failure_threshold
        self._timeout = timeout_seconds

    async def call(self, func: Callable, *args, **kwargs):
        """Execute function with circuit breaker protection.

        Args:
            func: Async function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Function result

        Raises:
            CircuitBreakerOpenError: If circuit breaker is OPEN
        """
        if self.state == self.OPEN:
            if self._should_attempt_reset():
                self.state = self.HALF_OPEN
            else:
                raise CircuitBreakerOpenError(
                    f"Circuit breaker is OPEN (opens in {self._timeout - (time.time() - self.last_failure_time):.0f}s)"
                )

        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as exc:
            self._on_failure()
            raise

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset."""
        return (
            self.last_failure_time and
            time.time() - self.last_failure_time >= self._timeout
        )

    def _on_success(self):
        """Handle successful call."""
        if self.state == self.HALF_OPEN:
            self.state = self.CLOSED
            self.failure_count = 0

    def _on_failure(self):
        """Handle failed call."""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self._threshold:
            self.state = self.OPEN
```

### Retry Strategy

**Using tenacity library:**

```python
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type
)

def with_retry(max_attempts: int = 3):
    """Decorator for retrying with exponential backoff.

    Retries on:
    - ConnectionError
    - TimeoutError

    Backoff:
    - Initial: 100ms
    - Multiplier: 2x
    - Max: 1000ms
    """
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=100, max=1000),
        retry=retry_if_exception_type((ConnectionError, TimeoutError))
    )
```

**Usage:**

```python
# In ObservabilityManager
@with_retry(max_attempts=3)
async def store_log_with_retry(self, otel_log: dict):
    """Store log with retry."""
    await self.otel_adapter.store_log(otel_log)
```

______________________________________________________________________

## Transformation Layer

### Mahavishnu → OTel Format Mapping

**Log Transformation:**

```python
# Input: Mahavishnu LogEntry
mahavishnu_log = LogEntry(
    timestamp=datetime.now(UTC),
    level=LogLevel.INFO,
    message="Workflow completed successfully",
    attributes={
        "workflow_id": "abc123",
        "workflow_name": "process_repository"
    },
    trace_id="trace-xyz"
)

# Output: OTel format
otel_log = {
    "trace_id": "trace-xyz",
    "span_id": None,  # Generated by database
    "name": "log_entry",
    "kind": "INTERNAL",
    "start_time": mahavishnu_log.timestamp,
    "end_time": mahavishnu_log.timestamp,
    "status": "OK",
    "service": "mahavishnu",
    "operation": "log_info",
    "duration_ms": 0,
    "attributes": {
        "log.level": "INFO",
        "log.message": "Workflow completed successfully",
        "workflow_id": "abc123",
        "workflow_name": "process_repository"
    }
}
```

**Metric Transformation:**

```python
# Input: Mahavishnu metric data
metric_data = {
    "name": "mahavishnu.workflows.executed",
    "value": 1,
    "labels": {
        "workflow.id": "abc123",
        "workflow.adapter": "llamaindex"
    }
}

# Output: OTel MetricData format
otel_metric = {
    "name": "mahavishnu.workflows.executed",
    "type": "counter",
    "value": 1,
    "unit": None,
    "labels": {
        "workflow.id": "abc123",
        "workflow.adapter": "llamaindex"
    },
    "timestamp": datetime.now(UTC)
}
```

______________________________________________________________________

## Error Handling

### Failure Scenarios

1. **PostgreSQL connection fails**

   - **Action:** Log error, set `self.otel_adapter = None`, continue with OTLP
   - **Log:** ERROR: "otel-storage-init-failed"

1. **Storage operation fails transiently**

   - **Action:** Retry 3x with exponential backoff
   - **Log:** WARNING: "otel-storage-retryable"

1. **Storage operation fails persistently**

   - **Action:** Circuit breaker records failure
   - **After 5 failures:** Circuit breaker opens
   - **Log:** ERROR: "circuit-breaker-open"

1. **Circuit breaker opens**

   - **Action:** Stop PostgreSQL storage for 60 seconds
   - **OTLP continues:** Unaffected
   - **Log:** ERROR: "otel-storage-paused"

1. **Circuit breaker recovers**

   - **Action:** Successful request closes circuit
   - **PostgreSQL storage resumes**
   - **Log:** INFO: "circuit-breaker-closed"

### Error Types

```python
class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is OPEN and blocking requests."""
    pass

class OTelStorageInitializationError(Exception):
    """Raised when OTel adapter fails to initialize."""
    pass
```

______________________________________________________________________

## Testing Strategy

### Unit Tests (Fast, No Database)

**File:** `tests/unit/test_circuit_breaker.py` (8 tests)

1. `test_circuit_closed_passes_requests` - Normal operation
1. `test_circuit_opens_after_threshold` - 5 failures triggers OPEN
1. `test_circuit_half_opens_after_timeout` - Time reset
1. `test_circuit_closes_after_half_open_success` - Recovery
1. `test_circuit_remains_open_without_timeout` - Not enough time
1. `test_circuit_resets_on_success` - Success resets counter
1. `test_circuit_error_in_open_state` - Raises immediately
1. `test_circuit_consecutive_failures` - State transitions

**File:** `tests/unit/test_transformations.py` (4 tests)

1. `test_convert_log_to_otel_success` - LogEntry → OTel format
1. `test_convert_log_with_trace_id` - Preserves trace correlation
1. `test_convert_metric_to_otel_success` - Metric → OTel format
1. `test_convert_metric_attributes` - Labels → attributes mapping

### Integration Tests (Slow, Requires PostgreSQL + Mahavishnu)

**File:** `tests/integration/test_mahavishnu_otel_integration.py` (6 tests)

1. `test_observability_manager_creates_adapter` - Adapter initialized
1. `test_store_log_persists_to_db` - Log stored correctly
1. `test_store_log_with_trace_correlation` - trace_id preserved
1. `test_store_metrics_persists_to_db` - Metrics stored
1. `test_dual_export_both_backends` - OTLP + PostgreSQL both work
1. `test_circuit_breaker_opens_on_failures` - Protection works

**Test Fixtures:**

```python
@pytest.fixture
async def mahavishnu_with_otel_storage():
    """Create Mahavishnu with OTel storage enabled."""
    from mahavishnu.core.observability import ObservabilityManager
    from mahavishnu.core.config import MahavishnuSettings

    settings = MahavishnuSettings(
        otel_storage_backend="postgresql",
        otel_storage_connection_string="postgresql://postgres:postgres@localhost:5432/otel_test"
    )

    obs_manager = ObservabilityManager(settings)
    await obs_manager.otel_adapter.init()

    yield obs_manager

    await obs_manager.otel_adapter.cleanup()
```

______________________________________________________________________

## Implementation Plan

### Task Breakdown

1. **Create circuit breaker** (1 hour)

   - Implement CircuitBreaker class
   - State machine: CLOSED → HALF_OPEN → OPEN
   - Tests for all state transitions

1. **Create resilience utilities** (30 min)

   - Retry decorator with exponential backoff
   - Custom exception types
   - Tests for retry logic

1. **Modify MahavishnuSettings** (30 min)

   - Add OTel storage configuration fields
   - Add circuit breaker configuration fields
   - Validation and defaults

1. **Update ObservabilityManager** (1 hour)

   - Import and initialize OTelStorageAdapter
   - Add transformation methods
   - Implement concrete store_metrics(), store_log()
   - Integrate circuit breaker + retry

1. **Testing** (1 hour)

   - Unit tests for circuit breaker
   - Unit tests for transformation
   - Integration tests for Mahavishnu
   - End-to-end workflow tests

1. **Documentation** (30 min)

   - Update Mahavishnu README
   - Add configuration examples
   - Document circuit breaker behavior

**Estimated Time:** 4 hours

______________________________________________________________________

## Success Criteria

### Functional

- ✅ OTelStorageAdapter integrates with ObservabilityManager
- ✅ Dual export works (OTLP + PostgreSQL)
- ✅ store_metrics() stores metrics in PostgreSQL
- ✅ store_log() stores logs with trace correlation
- ✅ Circuit breaker protects against failures
- ✅ Retry with exponential backoff

### Resilience

- ✅ Circuit breaker opens after 5 failures in 60s
- ✅ Circuit breaker recovers after successful request
- ✅ Retry attempts: 3 with exponential backoff (100ms → 1000ms)
- ✅ OTLP failure doesn't affect PostgreSQL
- ✅ PostgreSQL failure doesn't affect OTLP

### Quality

- ✅ Type hints on all functions
- ✅ Docstrings on all public methods
- ✅ 100% test coverage (circuit breaker)
- ✅ 80%+ coverage (integration)
- ✅ No suppress(Exception)

### Configuration

- ✅ Backend selector: "otlp" | "postgresql" | "both"
- ✅ Granular flags: store_traces, store_metrics, store_logs
- ✅ Circuit breaker thresholds configurable
- ✅ Environment variable overrides work

______________________________________________________________________

## Next Steps

After design approval:

1. Create git worktree for Phase 4
1. Implement circuit breaker and retry logic
1. Modify MahavishnuSettings and ObservabilityManager
1. Create transformation layer
1. Integration tests
1. Update documentation

______________________________________________________________________

**Status:** Ready for implementation approval
**Estimated Time:** 4 hours
**Complexity:** Medium (circuit breaker, retry logic, async patterns)
**Dependencies:** tenacity (retry), existing OTelStorageAdapter
