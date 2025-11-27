# Oneiric Testing Strategy & Coverage Audit

**Audit Date:** 2025-11-26
**Auditor:** Claude (pytest-hypothesis-specialist)
**Project:** Oneiric v0.1.0 (Alpha)

## Executive Summary

**CRITICAL FINDING:** Documentation is severely outdated - claims "only 1 test file exists" when there are actually **56 test files with 505 test cases achieving 83% coverage**.

### Overall Assessment
- **Current State:** Excellent test coverage for an alpha project
- **Test Count:** 505 tests (502 passing, 3 skipped)
- **Overall Coverage:** 83% (6,051 statements, 1,003 uncovered)
- **Test Quality:** High - well-structured, comprehensive unit and integration tests
- **Critical Gaps:** 2 modules with 0% coverage, security testing needs expansion

### Key Strengths ✅
1. **Comprehensive core coverage** - Resolution (99%), Lifecycle (94%), Security (100%)
2. **Security-first approach** - Dedicated security test suite with factory validation
3. **Integration testing** - Full E2E workflows and edge case coverage
4. **Async-first** - All tests properly use pytest-asyncio
5. **Good test architecture** - Clear separation of unit, integration, and security tests

### Critical Weaknesses ❌
1. **Zero property-based testing** - Hypothesis not used despite being installed
2. **Runtime helpers untested** - `core/runtime.py` at 0% coverage
3. **Mock/stub heavy** - 330+ mock instances, may hide integration issues
4. **Limited performance testing** - No benchmarks or load testing
5. **Outdated documentation** - README claims inadequate testing

---

## Detailed Coverage Analysis

### 1. Test Inventory by Module

```
tests/
├── actions/          11 files, ~45 tests    - Action system (compression, data, http, etc.)
├── adapters/         19 files, ~95 tests    - Adapter implementations (cache, db, queue, etc.)
├── cli/              1 file,   ~35 tests    - CLI commands
├── core/             4 files,  ~120 tests   - Core systems (resolution, lifecycle, logging)
├── domains/          2 files,  ~40 tests    - Domain bridges (services, tasks, events)
├── integration/      2 files,  ~45 tests    - E2E workflows and edge cases
├── remote/           3 files,  ~35 tests    - Remote manifest loading and security
├── runtime/          3 files,  ~40 tests    - Orchestrator, watchers, health
├── security/         4 files,  ~50 tests    - Security validation (factory, input, path)
└── conftest.py       -         -            - Shared fixtures (15 fixtures)

Total: 56 test files, 505 test cases
```

### 2. Coverage by Component

#### Excellent Coverage (>90%)
| Module | Coverage | Uncovered | Notes |
|--------|----------|-----------|-------|
| `core/resolution.py` | **99%** | 2/181 | Excellent - core system well tested |
| `core/security.py` | **100%** | 0/60 | Perfect - all security paths covered |
| `core/lifecycle.py` | **94%** | 19/302 | Very good - lifecycle management solid |
| `domains/base.py` | **99%** | 1/96 | Excellent - domain bridge well tested |
| `adapters/bridge.py` | **99%** | 1/94 | Excellent - adapter bridge solid |
| `plugins.py` | **91%** | 10/113 | Good - plugin system tested |

#### Good Coverage (70-90%)
| Module | Coverage | Uncovered | Notes |
|--------|----------|-----------|-------|
| `remote/loader.py` | **81%** | 44/236 | Good - error paths need work |
| `runtime/health.py` | **98%** | 1/62 | Excellent - health checks solid |
| `runtime/orchestrator.py` | **91%** | 10/107 | Good - orchestration tested |
| `runtime/activity.py` | **91%** | 8/93 | Good - pause/drain tested |
| `cli.py` | **76%** | 144/598 | Fair - CLI needs more coverage |
| `core/logging.py` | **84%** | 16/97 | Good - logging infrastructure |
| `core/config.py` | **70%** | 47/159 | Fair - config loading needs work |

#### Critical Gaps (0% or <70%)
| Module | Coverage | Uncovered | Priority | Notes |
|--------|----------|-----------|----------|-------|
| **`core/runtime.py`** | **0%** | 59/59 | **CRITICAL** | TaskGroup helpers completely untested |
| **`remote/samples.py`** | **0%** | 37/37 | Low | Demo code, low priority |
| `adapters/database/sqlite.py` | **32%** | 45/66 | High | DB adapter needs tests |
| `runtime/watchers.py` | **66%** | 25/73 | Medium | Config watchers partially tested |
| `core/resiliency.py` | **69%** | 20/65 | Medium | Circuit breaker needs tests |

---

## Test Quality Assessment

### Testing Patterns Used

#### ✅ Good Patterns
1. **Class-based organization** - Tests grouped by feature/component
   ```python
   class TestLifecycleActivation:
       async def test_activate_new_instance(...)
       async def test_activate_with_health_check(...)
   ```

2. **Comprehensive fixtures** - 15 reusable fixtures in conftest.py
   ```python
   @pytest.fixture
   def resolver() -> Resolver:
       return Resolver()

   @pytest.fixture
   def lifecycle_manager(resolver, temp_dir):
       return LifecycleManager(resolver, ...)
   ```

3. **Mock components for testing** - Clean test doubles
   ```python
   class MockComponent:
       def __init__(self, should_fail_health=False):
           self.initialized = False
           self.should_fail_health = should_fail_health
   ```

4. **Async testing** - Proper use of pytest-asyncio
   ```python
   @pytest.mark.asyncio
   async def test_swap_with_rollback(self, lifecycle_manager):
       ...
   ```

5. **Security-focused** - Dedicated security test suite
   - Factory validation (os.system, subprocess blocking)
   - Path traversal prevention
   - Input validation
   - Signature verification

6. **Integration tests** - Full E2E workflows
   - Complete lifecycle: register → resolve → activate → swap
   - Multi-domain orchestration
   - Remote manifest sync

#### ⚠️ Anti-Patterns Found

1. **Heavy mocking** (330+ instances)
   - May hide real integration issues
   - Example: Mocking entire external services instead of using test doubles
   - Risk: Tests pass but production fails

2. **No property-based testing**
   - Hypothesis installed but never used
   - Missing: invariant testing, fuzz testing
   - Opportunity: Resolution precedence rules are perfect for property tests

3. **Limited parametrization**
   - Few uses of `@pytest.mark.parametrize`
   - Many similar tests could be combined

4. **Skipped network tests**
   ```python
   @pytest.mark.skip(reason="Network tests are flaky")
   ```
   - Instead of skipping, should use mock servers (e.g., aioresponses)

5. **No benchmark testing**
   - pytest-benchmark installed but unused
   - Performance regressions won't be caught

---

## Critical Testing Gaps

### 1. Core Runtime (0% Coverage) - **CRITICAL**

**File:** `oneiric/core/runtime.py` (59 uncovered statements)

**Impact:** High - async task management is core infrastructure

**Missing Tests:**
```python
# RuntimeTaskGroup lifecycle
async with RuntimeTaskGroup(name="test") as group:
    task = group.start_soon(async_work())
    await group.cancel_all()
    results = group.results()

# Task nursery pattern
async with task_nursery(name="test") as nursery:
    nursery.start_soon(coro1())
    nursery.start_soon(coro2())

# Concurrent execution
results = await run_with_taskgroup(coro1(), coro2(), name="test")

# Sync runner
result = run_sync(async_main)
```

**Recommended Tests:**
1. TaskGroup enter/exit lifecycle
2. Task creation and tracking
3. Cancellation propagation
4. Error handling in tasks
5. Results collection
6. Nursery pattern
7. Concurrent execution
8. Sync runner with event loop

**Priority:** **CRITICAL** - Schedule for immediate implementation

---

### 2. Property-Based Testing Opportunities

**Current State:** Hypothesis installed, **zero usage**

**High-Value Targets:**

#### Resolution Precedence (Perfect for Properties)
```python
from hypothesis import given, strategies as st
from hypothesis.stateful import RuleBasedStateMachine

# Property: Tier 1 always wins
@given(
    priority=st.integers(min_value=-100, max_value=100),
    stack_level=st.integers(min_value=-10, max_value=10)
)
def test_selection_override_always_wins(priority, stack_level):
    """Property: Explicit override beats any priority/stack_level."""
    resolver = Resolver()

    # Register candidates with various priorities
    resolver.register(Candidate(..., priority=priority, stack_level=stack_level))
    resolver.register(Candidate(..., provider="override"))

    # Set explicit selection
    settings = LayerSettings(selections={"cache": "override"})

    # Override MUST win regardless of priority/stack_level
    resolved = resolver.resolve("adapter", "cache", settings)
    assert resolved.provider == "override"

# Stateful testing for lifecycle
class LifecycleStateMachine(RuleBasedStateMachine):
    """Test lifecycle state transitions with property-based testing."""

    def __init__(self):
        super().__init__()
        self.lifecycle = LifecycleManager(Resolver())
        self.active_instances = {}

    @rule(domain=st.sampled_from(["adapter", "service"]),
          key=st.text(min_size=1, max_size=20))
    async def activate(self, domain, key):
        instance = await self.lifecycle.activate(domain, key)
        self.active_instances[(domain, key)] = instance

    @rule(domain=st.sampled_from(["adapter", "service"]),
          key=st.text(min_size=1, max_size=20))
    async def swap(self, domain, key):
        if (domain, key) in self.active_instances:
            instance = await self.lifecycle.swap(domain, key)
            self.active_instances[(domain, key)] = instance

    @invariant()
    def lifecycle_status_consistent(self):
        """Invariant: Active instances must have 'ready' status."""
        for (domain, key), instance in self.active_instances.items():
            status = self.lifecycle.get_status(domain, key)
            assert status.state == "ready"
```

**Recommended Property Tests:**

1. **Resolution invariants**
   - Higher priority always wins over lower
   - Selection override always wins
   - Stack level order is stable

2. **Lifecycle state machine**
   - Valid state transitions only
   - No orphaned instances
   - Cleanup always called on swap

3. **Security validation**
   - All path traversal attempts blocked
   - All blocked modules rejected
   - Allowlist prefix matching

4. **Config parsing**
   - Round-trip serialization preserves data
   - Invalid YAML always rejected

**Priority:** High - Implement for Phase 8 (security hardening)

---

### 3. Benchmark Testing (Missing)

**Impact:** Medium - Performance regressions won't be caught

**Recommended Benchmarks:**

```python
import pytest

def test_resolution_performance(benchmark):
    """Benchmark resolution with 1000 registered candidates."""
    resolver = Resolver()

    # Register 1000 candidates
    for i in range(1000):
        resolver.register(
            Candidate(
                domain="adapter",
                key=f"cache-{i}",
                provider=f"provider-{i}",
                factory=lambda: None,
                stack_level=i % 10
            )
        )

    # Benchmark resolution
    result = benchmark(resolver.resolve, "adapter", "cache-500")
    assert result is not None

@pytest.mark.asyncio
async def test_lifecycle_swap_performance(benchmark, lifecycle_manager):
    """Benchmark hot-swap speed."""

    async def swap_adapter():
        return await lifecycle_manager.swap("adapter", "cache", provider="redis")

    result = await benchmark(swap_adapter)
    assert result is not None

def test_remote_manifest_parse_performance(benchmark):
    """Benchmark manifest parsing with 100 entries."""
    manifest_yaml = generate_large_manifest(entry_count=100)

    result = benchmark(parse_remote_manifest, manifest_yaml)
    assert len(result.entries) == 100
```

**Priority:** Low-Medium - Add during optimization phase

---

### 4. Adapter Coverage Gaps

Several adapter implementations have low coverage:

| Adapter | Coverage | Gap |
|---------|----------|-----|
| SQLite | 32% | Connection pooling, transactions |
| Redis Streams | 75% | Error handling, stream management |
| AWS Secrets | 71% | Boto3 integration, credential rotation |
| Azure Storage | 72% | Blob operations, SAS tokens |
| GCS | 73% | Bucket operations, signed URLs |
| S3 | 74% | Multipart upload, lifecycle |

**Recommendation:**
- Add integration tests with real services (using testcontainers)
- Or use comprehensive mocks for cloud SDKs

**Priority:** Medium - Not blocking alpha, but needed for beta

---

## Fixture Strategy Assessment

### Current Fixtures (conftest.py)

**Well-designed:**
```python
@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create temporary directory - GOOD: Automatic cleanup"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)

@pytest.fixture
def resolver() -> Resolver:
    """Fresh resolver - GOOD: Isolation between tests"""
    return Resolver()

@pytest.fixture
def lifecycle_manager(resolver: Resolver, temp_dir: Path):
    """Manager with dependencies - GOOD: Composition"""
    snapshot_path = temp_dir / "lifecycle_status.json"
    return LifecycleManager(resolver, status_snapshot_path=str(snapshot_path))
```

### Missing Fixtures

**Recommended additions:**

```python
# 1. Factory fixture for common test data
@pytest.fixture
def candidate_factory(resolver):
    """Factory for creating test candidates."""
    created = []

    def _create(domain="adapter", key="test", provider="test", **kwargs):
        candidate = Candidate(domain=domain, key=key, provider=provider, **kwargs)
        resolver.register(candidate)
        created.append(candidate)
        return candidate

    yield _create
    # Cleanup after test
    for c in created:
        resolver.unregister(c.domain, c.key, c.provider)

# 2. Mock HTTP server fixture
@pytest.fixture
async def mock_remote_server():
    """Mock remote manifest server."""
    from aioresponses import aioresponses
    with aioresponses() as m:
        yield m

# 3. Event loop fixture with proper cleanup
@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

# 4. Scoped cache directory
@pytest.fixture(scope="session")
def cache_dir_session(tmp_path_factory):
    """Session-scoped cache for performance."""
    return tmp_path_factory.mktemp("cache")
```

---

## Edge Cases & Error Paths

### Well-Tested Edge Cases ✅

1. **Concurrent operations** (test_edge_cases.py)
   - Concurrent registration (100 parallel)
   - Concurrent resolution (100 parallel)
   - Resource leak prevention

2. **Failure scenarios** (test_lifecycle.py)
   - Health check failures
   - Rollback on swap failure
   - Cleanup errors

3. **Security attacks** (security/*.py)
   - RCE attempts (os.system, subprocess)
   - Path traversal (../../evil)
   - Malformed inputs

### Missing Edge Cases ❌

1. **Network failures**
   - Timeout handling
   - Connection pool exhaustion
   - DNS failures

2. **Filesystem issues**
   - Disk full
   - Permission errors
   - Corrupted cache files

3. **Race conditions**
   - Simultaneous swaps
   - Config file changes during read
   - Status snapshot corruption

4. **Resource limits**
   - Memory exhaustion
   - Too many open files
   - Queue overflow

**Recommendation:** Add chaos engineering tests with fault injection

---

## Integration vs Unit Test Balance

### Current Distribution
- **Unit tests:** ~70% (isolated component testing)
- **Integration tests:** ~25% (E2E workflows, orchestration)
- **Security tests:** ~5% (dedicated security suite)

### Assessment
**Balance is good** for alpha stage. As project matures:

1. **Increase integration tests** to 35-40%
   - More cross-component scenarios
   - Real external service testing (testcontainers)

2. **Add contract tests**
   - Adapter interface compliance
   - Domain bridge contracts
   - Plugin protocol validation

3. **Performance testing** tier
   - Load tests for orchestrator
   - Stress tests for resolution
   - Memory profiling

---

## Test Organization & Architecture

### Current Structure ✅
```
tests/
├── conftest.py           # Shared fixtures
├── actions/              # Action system tests
├── adapters/             # Adapter implementation tests
├── cli/                  # CLI command tests
├── core/                 # Core system tests (resolution, lifecycle)
├── domains/              # Domain bridge tests
├── integration/          # E2E workflows
├── remote/               # Remote manifest tests
├── runtime/              # Orchestrator tests
└── security/             # Security validation tests
```

**Strengths:**
- Clear separation by component
- Security tests isolated
- Integration tests separate

**Recommendations:**

1. **Add performance/ directory**
   ```
   tests/performance/
   ├── test_resolution_benchmarks.py
   ├── test_lifecycle_benchmarks.py
   └── test_remote_sync_benchmarks.py
   ```

2. **Add contract/ directory**
   ```
   tests/contract/
   ├── test_adapter_interface.py
   ├── test_domain_bridge_interface.py
   └── test_plugin_protocol.py
   ```

3. **Add chaos/ directory** (future)
   ```
   tests/chaos/
   ├── test_network_failures.py
   ├── test_resource_exhaustion.py
   └── test_filesystem_errors.py
   ```

---

## Recommended Test Priorities

### CRITICAL (Implement Immediately)

**Priority 1: Core Runtime Tests** (0% → 90%+)
- **Effort:** 4-6 hours
- **Impact:** High - fundamental infrastructure
- **Tests needed:** ~20 tests
```python
tests/core/test_runtime.py
- test_task_group_lifecycle
- test_task_cancellation
- test_nursery_pattern
- test_concurrent_execution
- test_error_propagation
- test_results_collection
```

**Priority 2: Property-Based Tests for Resolution**
- **Effort:** 6-8 hours
- **Impact:** High - catches precedence bugs
- **Tests needed:** ~15 property tests
```python
tests/core/test_resolution_properties.py
- test_tier1_always_wins (property)
- test_priority_ordering (property)
- test_stack_level_ordering (property)
- lifecycle_state_machine (stateful)
```

**Priority 3: Security Expansion**
- **Effort:** 3-4 hours
- **Impact:** High - alpha → beta blocker
- **Tests needed:** ~10 tests
```python
tests/security/test_path_traversal.py (expand)
- test_symlink_attacks
- test_absolute_path_injection
- test_unicode_normalization

tests/security/test_dos_prevention.py (new)
- test_manifest_size_limits
- test_recursion_depth_limits
- test_rate_limiting
```

### HIGH (Implement for Beta)

**Priority 4: Adapter Integration Tests**
- **Effort:** 10-12 hours
- **Impact:** Medium - production readiness
- **Tests needed:** ~30 tests across adapters
```python
tests/adapters/integration/
- test_sqlite_real_db.py (testcontainers)
- test_redis_real_cache.py (testcontainers)
- test_postgres_real_db.py (testcontainers)
```

**Priority 5: Benchmark Suite**
- **Effort:** 4-6 hours
- **Impact:** Medium - performance regression detection
- **Tests needed:** ~10 benchmarks
```python
tests/performance/
- test_resolution_benchmarks.py
- test_lifecycle_benchmarks.py
- test_remote_sync_benchmarks.py
```

### MEDIUM (Implement for v1.0)

**Priority 6: Chaos/Fault Injection**
- **Effort:** 8-10 hours
- **Impact:** Low-Medium - stability testing
```python
tests/chaos/
- test_network_failures.py
- test_filesystem_errors.py
- test_resource_exhaustion.py
```

**Priority 7: Contract Tests**
- **Effort:** 6-8 hours
- **Impact:** Low-Medium - interface stability
```python
tests/contract/
- test_adapter_interface_compliance.py
- test_domain_bridge_contracts.py
```

---

## Testing Anti-Patterns to Avoid

### 1. Over-Mocking
**Current:** 330+ mock instances

**Risk:** Tests pass but production fails

**Example of over-mocking:**
```python
# BAD - Too much mocking
@patch('oneiric.adapters.cache.redis.Redis')
@patch('oneiric.adapters.queue.nats.NATS')
@patch('httpx.AsyncClient')
async def test_workflow(mock_http, mock_nats, mock_redis):
    # This test tells us nothing about real integration
    ...
```

**Better approach:**
```python
# GOOD - Use test doubles or real services
async def test_workflow_with_real_services():
    # Use testcontainers for Redis, NATS
    async with Redis.from_url("redis://localhost:6379") as redis:
        async with NATS.connect("nats://localhost:4222") as nats:
            # Test with real services
            ...
```

### 2. Test Interdependence
**Risk:** Test order matters, flaky tests

**Bad:**
```python
# BAD - Tests depend on each other
class TestWorkflow:
    instance = None

    def test_1_create(self):
        self.instance = create_instance()

    def test_2_use(self):
        # Breaks if test_1_create fails
        result = self.instance.process()
```

**Good:**
```python
# GOOD - Tests are independent
class TestWorkflow:
    def test_create(self, workflow_factory):
        instance = workflow_factory()
        assert instance is not None

    def test_process(self, workflow_factory):
        instance = workflow_factory()
        result = instance.process()
        assert result is not None
```

### 3. Assertion Roulette
**Risk:** Hard to debug failures

**Bad:**
```python
# BAD - Multiple assertions without context
def test_candidate(candidate):
    assert candidate.domain == "adapter"
    assert candidate.key == "cache"
    assert candidate.provider == "redis"
    assert candidate.priority == 10
    # Which assertion failed? Who knows!
```

**Good:**
```python
# GOOD - Descriptive assertions
def test_candidate(candidate):
    assert candidate.domain == "adapter", "Domain should be 'adapter'"
    assert candidate.key == "cache", "Key should be 'cache'"
    assert candidate.provider == "redis", "Provider should be 'redis'"
    assert candidate.priority == 10, "Priority should be 10"
```

---

## pytest Configuration Review

### Current Config (pyproject.toml)
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"                    # ✅ Good - auto-detects async tests
testpaths = ["tests"]                    # ✅ Good - explicit test directory
python_files = ["test_*.py"]             # ✅ Good - standard naming
python_classes = ["Test*"]               # ✅ Good - standard naming
python_functions = ["test_*"]            # ✅ Good - standard naming
addopts = [
    "-v",                                # ✅ Good - verbose output
    "--strict-markers",                  # ✅ Good - catch typos in markers
    "--cov=oneiric",                     # ✅ Good - coverage enabled
    "--cov-report=term-missing",         # ✅ Good - show uncovered lines
    "--cov-report=html",                 # ✅ Good - HTML report
    "--cov-report=xml",                  # ✅ Good - CI integration
]
markers = [
    "security: Security-related tests",  # ✅ Good
    "integration: Integration tests",    # ✅ Good
    "slow: Slow-running tests",          # ✅ Good
]
```

### Recommended Additions
```toml
[tool.pytest.ini_options]
# Existing config...
addopts = [
    # ... existing ...
    "--strict-config",                   # Fail on unknown config
    "--tb=short",                        # Shorter tracebacks
    "--cov-fail-under=85",              # Enforce minimum coverage
    "--durations=10",                    # Show 10 slowest tests
    "--hypothesis-show-statistics",      # Show Hypothesis stats
]
markers = [
    # ... existing ...
    "benchmark: Performance benchmark tests",
    "property: Property-based tests",
    "chaos: Chaos/fault injection tests",
    "contract: Contract/interface tests",
]
filterwarnings = [
    "error",                             # Treat warnings as errors
    "ignore::DeprecationWarning:pkg_resources",  # Known safe deprecations
]
timeout = 300                            # 5 minute test timeout
```

---

## Hypothesis Integration Plan

### Phase 1: Basic Properties (Week 1)
```python
# tests/core/test_resolution_properties.py
from hypothesis import given, strategies as st

@given(
    domain=st.sampled_from(["adapter", "service", "task"]),
    key=st.text(min_size=1, max_size=50, alphabet=st.characters(blacklist_characters="/.\\:")),
    priority=st.integers(min_value=-100, max_value=100)
)
def test_registration_roundtrip(domain, key, priority):
    """Property: Register then resolve returns same candidate."""
    resolver = Resolver()
    original = Candidate(
        domain=domain,
        key=key,
        provider="test",
        factory=lambda: None,
        priority=priority
    )
    resolver.register(original)

    resolved = resolver.resolve(domain, key)
    assert resolved is not None
    assert resolved.domain == domain
    assert resolved.key == key
    assert resolved.priority == priority
```

### Phase 2: Stateful Testing (Week 2)
```python
from hypothesis.stateful import RuleBasedStateMachine, rule, invariant

class LifecycleStateMachine(RuleBasedStateMachine):
    """Stateful testing of lifecycle manager."""

    def __init__(self):
        super().__init__()
        self.resolver = Resolver()
        self.lifecycle = LifecycleManager(self.resolver)
        self.active = {}

    @rule(
        domain=st.sampled_from(["adapter", "service"]),
        key=st.text(min_size=1, max_size=20),
        provider=st.text(min_size=1, max_size=20)
    )
    async def activate(self, domain, key, provider):
        """Activate a component."""
        self.resolver.register(
            Candidate(domain=domain, key=key, provider=provider, factory=lambda: {})
        )
        instance = await self.lifecycle.activate(domain, key)
        self.active[(domain, key)] = provider

    @invariant()
    def active_instances_have_ready_status(self):
        """All active instances must have 'ready' status."""
        for (domain, key), provider in self.active.items():
            status = self.lifecycle.get_status(domain, key)
            assert status.state == "ready", f"Expected ready, got {status.state}"

TestLifecycle = LifecycleStateMachine.TestCase
```

### Phase 3: Complex Properties (Week 3)
```python
@given(
    candidates=st.lists(
        st.tuples(
            st.text(min_size=1, max_size=20),  # provider
            st.integers(min_value=-100, max_value=100),  # priority
            st.integers(min_value=-10, max_value=10)  # stack_level
        ),
        min_size=1,
        max_size=20
    )
)
def test_resolution_precedence_invariants(candidates):
    """Property: Precedence rules are always honored."""
    resolver = Resolver()

    for provider, priority, stack_level in candidates:
        resolver.register(
            Candidate(
                domain="adapter",
                key="test",
                provider=provider,
                factory=lambda: None,
                priority=priority,
                stack_level=stack_level
            )
        )

    resolved = resolver.resolve("adapter", "test")

    # Winner must have highest precedence score
    winner = (resolved.provider, resolved.priority, resolved.stack_level)

    for provider, priority, stack_level in candidates:
        candidate = (provider, priority, stack_level)
        if candidate != winner:
            # Winner must beat or tie this candidate
            assert precedence_score(winner) >= precedence_score(candidate)
```

---

## Test Data Management

### Current Approach
- **Inline test data** in test files
- **Fixture-based** component creation
- **Factory functions** for complex objects

### Recommendations

**1. Add test data directory**
```
tests/
├── data/
│   ├── manifests/
│   │   ├── valid_manifest.yaml
│   │   ├── invalid_signature.yaml
│   │   └── malicious_manifest.yaml
│   ├── configs/
│   │   ├── minimal_config.yml
│   │   └── full_config.yml
│   └── fixtures/
│       ├── candidates.json
│       └── component_states.json
```

**2. Use pytest-datafiles for file-based tests**
```python
import pytest
from pytest_datafiles import DataFiles

@pytest.mark.datafiles("tests/data/manifests/valid_manifest.yaml")
def test_manifest_parsing(datafiles):
    manifest_path = datafiles / "valid_manifest.yaml"
    manifest = parse_manifest(manifest_path)
    assert manifest.version == "1.0"
```

**3. Factory Boy for complex objects** (optional)
```python
# tests/factories.py
import factory

class CandidateFactory(factory.Factory):
    class Meta:
        model = Candidate

    domain = "adapter"
    key = factory.Sequence(lambda n: f"test-{n}")
    provider = "test"
    factory = lambda: {}
    priority = 0
    stack_level = 0
```

---

## Coverage Targets by Phase

### Alpha (Current: 83%)
- **Target:** 85%+
- **Focus:** Core systems (resolution, lifecycle, security)
- **Gap:** Runtime helpers (0% → 90%)

### Beta (Target: 90%+)
- **Focus:** All adapters >80%, integration tests
- **Add:** Property-based tests, benchmarks
- **Gap:** Adapter implementations (32-75% → 85%+)

### Release Candidate (Target: 95%+)
- **Focus:** Edge cases, error paths, chaos testing
- **Add:** Contract tests, fault injection
- **Gap:** CLI (76% → 95%), Config (70% → 95%)

### v1.0 Production (Target: 97%+)
- **Focus:** Mission-critical paths at 100%
- **Add:** Mutation testing, fuzzing
- **Maintain:** Continuous coverage monitoring

---

## Continuous Testing Strategy

### Pre-commit Hooks
```bash
# .pre-commit-config.yaml
- repo: local
  hooks:
    - id: pytest-fast
      name: Fast unit tests
      entry: pytest tests/core tests/domains -x --ff
      language: system
      pass_filenames: false
      always_run: true
```

### CI/CD Integration
```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Run tests
        run: |
          uv run pytest --cov --cov-fail-under=85
          uv run pytest tests/security -x  # Fail fast on security

  property-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Extended property testing
        run: |
          # Run with more examples in CI
          HYPOTHESIS_MAX_EXAMPLES=1000 uv run pytest tests/core/test_*_properties.py
```

### Coverage Monitoring
```bash
# Track coverage over time
uv run pytest --cov --cov-report=json
python scripts/track_coverage.py coverage.json
```

---

## Summary & Action Items

### Documentation Update
**IMMEDIATE:** Update README and CLAUDE.md to reflect **actual** test status:
- 56 test files (not "only 1")
- 505 test cases
- 83% coverage
- Excellent security testing

### Critical Path (Next 2 Weeks)

**Week 1:**
1. ✅ Add `test_runtime.py` - Core runtime helpers (20 tests)
2. ✅ Expand security tests - DOS prevention (10 tests)
3. ✅ Property tests for resolution - Precedence invariants (15 tests)

**Week 2:**
4. ✅ SQLite adapter integration tests (15 tests)
5. ✅ Benchmark suite foundation (10 benchmarks)
6. ✅ Update documentation (README, docs, CLAUDE.md)

### Success Metrics
- **Coverage:** 83% → 90%+ (by beta)
- **Test count:** 505 → 600+ (comprehensive)
- **Property tests:** 0 → 30+ (invariant coverage)
- **Benchmarks:** 0 → 15+ (performance tracking)

---

## Conclusion

**Verdict:** Testing is **far better than documented** - 83% coverage with 505 tests is excellent for alpha.

**Key Strengths:**
1. Strong core system coverage (resolution 99%, lifecycle 94%)
2. Security-first testing with dedicated suite
3. Good test architecture and organization
4. Comprehensive async testing

**Critical Gaps:**
1. Runtime helpers at 0% (CRITICAL - fix immediately)
2. No property-based testing (HIGH - missed opportunity)
3. No performance benchmarking (MEDIUM - needed for optimization)

**Overall Assessment:** With runtime tests added and property-based testing integrated, Oneiric will have **world-class test coverage** for an infrastructure library. The foundation is solid - just needs the final pieces.

**Recommendation:** Focus next sprint on:
1. Runtime helpers (CRITICAL)
2. Property-based tests (HIGH value/effort ratio)
3. Documentation accuracy (user trust)
