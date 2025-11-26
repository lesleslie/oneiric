# Oneiric Unified Implementation Roadmap

**Date:** 2025-11-25
**Version:** 0.1.0 (Alpha)
**Target:** Production-Ready (v1.0.0)
**Timeline:** 12-16 weeks

---

## Executive Summary

Oneiric has **excellent architectural foundations** (85/100) but suffers from **critical security vulnerabilities** (45/100) and **zero test coverage** (10/100), resulting in an overall quality score of **68/100 (Alpha)**. This roadmap integrates Phase 4-7 completion with mandatory security hardening and quality improvements to achieve production readiness.

**Key Insight:** We have a world-class design trapped in untested, insecure implementation. The path to v1.0 requires **disciplined focus on quality fundamentals** before adding new features.

### Critical Path to Production

```
Week 1-2:  🔴 Security Hardening (Blockers)
Week 3-6:  🟡 Test Coverage Foundation (60% minimum)
Week 7-9:  🟢 Documentation & API Stability
Week 10-12: 🔵 Production Hardening (Circuit breakers, retries)
Week 13-16: ⚪ Performance & Polish
```

---

## Phase Completion Status

### Implemented (Phases 1-3 + Partial 4-7)

| Phase | Status | Completeness | Notes |
|-------|--------|--------------|-------|
| **Phase 1: Core Resolution** | ✅ Complete | 100% | All spec requirements met |
| **Phase 2: Adapter Modularization** | ✅ Complete | 95% | Missing adapter-specific health checks |
| **Phase 3: Cross-Domain Alignment** | ✅ Complete | 100% | All 5 domains with unified API |
| **Phase 4: Plugins & Remote** | ⚠️ Partial | 80% | Missing signature verification, entry points |
| **Phase 5: Observability** | ⚠️ Partial | 70% | Missing circuit breakers, retry logic |
| **Phase 6: Lifecycle & Safety** | ⚠️ Partial | 85% | Missing cancellation-safe enforcement |
| **Phase 7: Tooling & UX** | ⚠️ Partial | 90% | **Missing all tests (critical)** |

### Implementation Gaps (By Priority)

#### 🔴 Critical Blockers (Must Fix for Beta)

1. **Arbitrary Code Execution** (`lifecycle.py:44-53`)
   - **Risk:** Remote manifest can import `os:system` and execute shell commands
   - **Fix:** Factory allowlist with safe module prefixes
   - **Effort:** 1 day
   - **Blocker:** Production deployment impossible

2. **Missing Signature Verification** (`remote/loader.py`)
   - **Risk:** MITM attacks can replace manifests even with HTTPS
   - **Fix:** Add cryptographic signature verification using `cryptography` library
   - **Effort:** 3 days
   - **Blocker:** Remote manifests unusable in hostile networks

3. **Zero Test Coverage** (No `tests/` directory)
   - **Risk:** Cannot verify correctness, refactoring breaks unknowingly
   - **Fix:** Minimum 60% coverage (50+ tests)
   - **Effort:** 2 weeks
   - **Blocker:** No confidence in stability

4. **Path Traversal** (`loader.py:52-54`)
   - **Risk:** Malicious URI like `../../etc/passwd` escapes cache directory
   - **Fix:** Path sanitization with `resolve()` checks
   - **Effort:** 2 hours
   - **Blocker:** File system compromise

5. **No HTTP Timeouts** (`loader.py:73`)
   - **Risk:** Hangs indefinitely on slow/malicious servers
   - **Fix:** Add `timeout=30.0` to `urllib.request.urlopen()`
   - **Effort:** 2 hours
   - **Blocker:** Availability issues in production

#### 🟡 High Priority (Beta Requirements)

6. **Race Conditions in Registry** (`resolution.py:118-135`)
   - **Issue:** No thread safety for concurrent registrations
   - **Fix:** Add `threading.Lock()` or document single-threaded constraint
   - **Effort:** 1 day

7. **Unbounded Instance Cache** (`lifecycle.py:113`)
   - **Issue:** Memory leak as instances accumulate without eviction
   - **Fix:** Implement LRU cache with max size or TTL-based eviction
   - **Effort:** 2 days

8. **Secrets Cache Never Invalidates** (`bridge.py:44, 59`)
   - **Issue:** Secrets cached forever, no rotation support
   - **Fix:** Add TTL or invalidate on config reload
   - **Effort:** 1 day

9. **Sequential Remote Entry Registration** (`loader.py:161-181`)
   - **Issue:** 100 manifest entries = 100× latency
   - **Fix:** Parallelize with `asyncio.gather()`
   - **Effort:** 2 days

#### 🟢 Medium Priority (Post-Beta)

10. **Entry Point Discovery** (Phase 4 deferred)
    - **Spec:** `discover_from_entry_points(group)` for pluggy-style plugins
    - **Status:** Enum exists (`CandidateSource.ENTRY_POINT`) but unused
    - **Effort:** 3 days

11. **Circuit Breaker Pattern** (Phase 5 deferred)
    - **Spec:** Protect remote sync from cascading failures
    - **Status:** Infinite retry in remote loop
    - **Effort:** 1 week

12. **Retry with Exponential Backoff** (Phase 5 deferred)
    - **Spec:** Graceful handling of transient remote failures
    - **Status:** Retries immediately on next interval
    - **Effort:** 2 days

13. **Capability Negotiation** (Optional early add)
    - **Spec:** Select candidates by features + priority
    - **Status:** Metadata dict exists, no resolver logic
    - **Effort:** 1 week

---

## Roadmap by Week

### Weeks 1-2: Security Hardening (CRITICAL)

**Goal:** Close all critical security vulnerabilities to enable beta testing

**Tasks:**

1. **Day 1: Factory Allowlist** (4 hours)
   ```python
   # Add to lifecycle.py
   ALLOWED_MODULE_PREFIXES = [
       "oneiric.",
       "myapp.",
       "builtins.",  # Allow basic types
   ]

   def resolve_factory(factory: str | FactoryCallable) -> FactoryCallable:
       if callable(factory):
           return factory
       module_path, _, attr = factory.partition(":")
       if not any(module_path.startswith(p) for p in ALLOWED_MODULE_PREFIXES):
           raise SecurityError(
               f"Factory module '{module_path}' not in allowlist. "
               f"Configure ONEIRIC_ALLOWED_FACTORY_MODULES to add trusted modules."
           )
       # ... rest of implementation
   ```

2. **Day 1: Path Sanitization** (2 hours)
   ```python
   # Add to loader.py
   filename = sha256 or Path(uri).name
   destination = (self.cache_dir / filename).resolve()
   if not destination.is_relative_to(self.cache_dir.resolve()):
       raise ValueError(f"Path traversal attempt blocked: {filename}")
   ```

3. **Day 1: HTTP Timeouts** (2 hours)
   ```python
   # Update loader.py:73, 234
   timeout = self.settings.http_timeout or 30.0  # seconds
   with urllib.request.urlopen(request, context=context, timeout=timeout) as response:
   ```

4. **Days 2-5: Signature Verification** (3 days)
   - Add dependencies: `cryptography>=42.0.0`
   - Extend `RemoteManifest` model:
     ```python
     signature: Optional[str] = None
     public_key: Optional[str] = None
     ```
   - Implement verification in `loader.py`:
     ```python
     from cryptography.hazmat.primitives import hashes, serialization
     from cryptography.hazmat.primitives.asymmetric import padding

     def verify_manifest_signature(
         manifest_bytes: bytes,
         signature: str,
         public_key_pem: str
     ) -> bool:
         public_key = serialization.load_pem_public_key(public_key_pem.encode())
         try:
             public_key.verify(
                 base64.b64decode(signature),
                 manifest_bytes,
                 padding.PSS(
                     mgf=padding.MGF1(hashes.SHA256()),
                     salt_length=padding.PSS.MAX_LENGTH
                 ),
                 hashes.SHA256()
             )
             return True
         except Exception:
             return False
     ```

5. **Days 6-8: Input Validation Hardening** (2 days)
   - Factory string format validation (regex: `^[\w.]+:\w+$`)
   - Domain/key format validation (alphanumeric + underscore/hyphen)
   - Stack level bounds checking (-1000 to 1000)
   - Priority bounds checking (-1000 to 1000)
   - Add `ValidationError` exception with detailed messages

6. **Days 9-10: Security Audit & Documentation** (2 days)
   - Run `bandit` security scanner
   - Document security assumptions (trusted network vs hostile)
   - Add `SECURITY.md` with responsible disclosure policy
   - Create security configuration guide

**Deliverables:**
- ✅ Factory allowlist enforced
- ✅ Path traversal blocked
- ✅ HTTP timeouts configured
- ✅ Signature verification implemented (optional but available)
- ✅ Input validation comprehensive
- ✅ Security documentation complete

**Success Criteria:** CRITICAL_AUDIT_REPORT.md security score rises from 45/100 to 80/100

---

### Weeks 3-6: Test Coverage Foundation (CRITICAL)

**Goal:** Achieve 60% test coverage minimum with focus on core logic and security

**Tasks:**

**Week 3: Test Infrastructure Setup** (5 days)

1. **Day 1: Test Framework Configuration**
   ```toml
   # pyproject.toml
   [project.optional-dependencies]
   test = [
       "pytest>=8.0",
       "pytest-asyncio>=0.23",
       "pytest-cov>=4.1",
       "pytest-mock>=3.12",
       "pytest-timeout>=2.2",
   ]

   [tool.pytest.ini_options]
   testpaths = ["tests"]
   asyncio_mode = "auto"
   timeout = 10
   markers = [
       "unit: Unit tests",
       "integration: Integration tests",
       "security: Security tests",
   ]

   [tool.coverage.run]
   source = ["oneiric"]
   omit = ["*/tests/*", "*/__pycache__/*"]

   [tool.coverage.report]
   exclude_lines = [
       "pragma: no cover",
       "def __repr__",
       "raise AssertionError",
       "raise NotImplementedError",
       "if TYPE_CHECKING:",
   ]
   ```

2. **Days 2-5: Core Test Suites** (20 tests)

   **Resolver Precedence Tests** (`tests/core/test_resolution.py` - 10 tests)
   ```python
   @pytest.mark.unit
   class TestResolverPrecedence:
       def test_override_beats_priority(self, resolver, settings):
           """Explicit config override should beat inferred priority"""

       def test_priority_beats_stack_level(self, resolver):
           """Higher priority should beat higher stack_level"""

       def test_stack_level_beats_registration_order(self, resolver):
           """Higher stack_level should beat later registration"""

       def test_registration_order_tiebreaker(self, resolver):
           """Last registered should win with equal priority/stack"""

       def test_explain_trace_complete(self, resolver):
           """Explain API should show full decision path"""

       # ... 5 more edge cases
   ```

   **Lifecycle Swap Tests** (`tests/core/test_lifecycle.py` - 10 tests)
   ```python
   @pytest.mark.asyncio
   class TestLifecycleSwaps:
       async def test_successful_swap_with_health_check(self, lifecycle):
           """Successful swap should call health, cleanup old, activate new"""

       async def test_failed_health_triggers_rollback(self, lifecycle):
           """Failed health check should rollback to previous instance"""

       async def test_force_flag_bypasses_health(self, lifecycle):
           """Force=True should skip health check and always swap"""

       async def test_cleanup_called_on_old_instance(self, lifecycle):
           """Old instance cleanup() should be called after successful swap"""

       async def test_pre_post_hooks_executed(self, lifecycle):
           """Pre/post swap hooks should execute in correct order"""

       # ... 5 more scenarios
   ```

**Week 4: Security & Remote Tests** (15 tests)

3. **Security Tests** (`tests/security/test_factory_validation.py` - 8 tests)
   ```python
   @pytest.mark.security
   class TestFactoryValidation:
       def test_malicious_factory_blocked(self, lifecycle):
           """Factory 'os:system' should raise SecurityError"""
           with pytest.raises(SecurityError, match="not in allowlist"):
               lifecycle.resolve_factory("os:system")

       def test_path_traversal_blocked(self, loader):
           """URI '../../etc/passwd' should raise ValueError"""

       def test_unbounded_priority_rejected(self, resolver):
           """Priority > 1000 should raise ValidationError"""

       # ... 5 more attack vectors
   ```

4. **Remote Manifest Tests** (`tests/remote/test_loader.py` - 7 tests)
   ```python
   @pytest.mark.asyncio
   class TestRemoteLoader:
       async def test_sha256_mismatch_raises(self, loader):
           """Incorrect SHA256 should raise IntegrityError"""

       async def test_signature_verification_success(self, loader, manifest):
           """Valid signature should pass verification"""

       async def test_network_timeout_handled(self, loader):
           """Slow server should timeout after configured duration"""

       # ... 4 more scenarios
   ```

**Week 5: Integration & Config Tests** (15 tests)

5. **Config Watcher Tests** (`tests/runtime/test_watchers.py` - 8 tests)
   ```python
   @pytest.mark.asyncio
   @pytest.mark.integration
   class TestConfigWatchers:
       async def test_detects_selection_changes(self, watcher, temp_config):
           """Changed provider should trigger swap"""

       async def test_respects_pause_state(self, watcher):
           """Paused key should skip swap even on config change"""

       async def test_poll_interval_timing(self, watcher):
           """Watcher should poll at configured interval"""

       # ... 5 more behaviors
   ```

6. **Domain Bridge Tests** (`tests/domains/test_bridges.py` - 7 tests)
   ```python
   @pytest.mark.asyncio
   class TestDomainBridges:
       async def test_service_activation(self, service_bridge):
           """ServiceBridge.use() should activate via lifecycle"""

       async def test_task_pause_drain(self, task_bridge):
           """TaskBridge should support pause/drain states"""

       # ... 5 more bridge behaviors
   ```

**Week 6: CLI & Edge Cases** (10 tests)

7. **CLI Command Tests** (`tests/test_cli.py` - 5 tests)
   ```python
   from typer.testing import CliRunner

   class TestCLI:
       def test_list_command_json_output(self, runner, demo_resolver):
           """list --json should return valid JSON"""

       def test_explain_command_shows_trace(self, runner):
           """explain should show full decision path"""

       # ... 3 more commands
   ```

8. **Concurrency Tests** (`tests/core/test_concurrency.py` - 5 tests)
   ```python
   @pytest.mark.asyncio
   class TestConcurrency:
       async def test_concurrent_registrations_safe(self, resolver):
           """Multiple threads registering same key should not corrupt registry"""

       async def test_concurrent_swaps_serialized(self, lifecycle):
           """Concurrent swaps for same key should serialize"""

       # ... 3 more scenarios
   ```

**Deliverables:**
- ✅ 60 tests covering core logic, security, and integration
- ✅ 60% code coverage minimum (target: 70%)
- ✅ CI/CD pipeline with automated testing
- ✅ Test fixtures for resolver, lifecycle, bridges

**Success Criteria:** `pytest --cov=oneiric --cov-report=term` shows 60%+ coverage

---

### Weeks 7-9: Documentation & API Stability

**Goal:** Complete API documentation and stabilize public interfaces for v1.0

**Tasks:**

**Week 7: API Documentation** (5 days)

1. **Days 1-2: Docstring Completion** (80% coverage target)
   - Add comprehensive docstrings to all public APIs
   - Include parameter types, return types, raises, examples
   - Use NumPy docstring format for consistency

   Example:
   ```python
   def resolve(
       self,
       domain: str,
       key: str,
       provider: Optional[str] = None
   ) -> Optional[Candidate]:
       """Resolve the active candidate for a domain/key pair.

       Applies precedence rules in order:
       1. Explicit config override
       2. Inferred priority from ONEIRIC_STACK_ORDER
       3. Candidate stack_level (higher wins)
       4. Registration order (last wins)

       Parameters
       ----------
       domain : str
           The domain to resolve (adapter, service, task, event, workflow)
       key : str
           The key within the domain (category, service_id, task_type, etc.)
       provider : str, optional
           Filter candidates to this provider only

       Returns
       -------
       Candidate | None
           The winning candidate, or None if no candidates registered

       Examples
       --------
       >>> resolver.resolve("adapter", "cache")
       Candidate(domain='adapter', key='cache', provider='redis', ...)

       >>> resolver.resolve("service", "payment", provider="stripe")
       Candidate(domain='service', key='payment', provider='stripe', ...)
       """
   ```

2. **Days 3-4: Architecture Documentation** (Update docs/)
   - Expand `README.md` with:
     - Quick start guide (5-minute tutorial)
     - Architecture overview diagram
     - Common patterns (registration, swapping, remote loading)
   - Create `docs/ARCHITECTURE.md`:
     - Component interaction diagrams
     - Data flow for resolution and swapping
     - Threading model and safety guarantees
   - Create `docs/API_REFERENCE.md`:
     - All public classes, methods, functions
     - Configuration options
     - Environment variables

3. **Day 5: Migration Guides**
   - `docs/MIGRATION_FROM_ACB.md` - For ACB users
   - `docs/UPGRADE_GUIDE.md` - Version upgrade path
   - `docs/SECURITY_GUIDE.md` - Security best practices

**Week 8: Example Projects** (5 days)

4. **Days 1-2: Simple Examples** (`examples/` directory)
   - `01_basic_adapter/` - Register and use an adapter
   - `02_hot_swapping/` - Runtime component swapping
   - `03_remote_manifest/` - Load components from remote
   - `04_multi_domain/` - Services, tasks, events together
   - `05_cli_usage/` - CLI diagnostics and troubleshooting

5. **Days 3-5: Advanced Examples**
   - `06_custom_domain/` - Create your own pluggable domain
   - `07_health_monitoring/` - Integrate with Prometheus/Grafana
   - `08_production_deploy/` - Docker, systemd, Kubernetes
   - `09_plugin_development/` - Write a third-party plugin
   - `10_testing_strategies/` - Test your Oneiric-based app

**Week 9: API Stability & Deprecation Policy** (5 days)

6. **Days 1-2: API Review**
   - Identify inconsistencies (e.g., `AdapterBridge.use(category=)` vs `DomainBridge.use(key=)`)
   - Deprecate redundant APIs (`LifecycleManager.activate()` vs `.swap()`)
   - Add `@deprecated` decorators with migration paths

7. **Days 3-4: Type Stubs & Protocol Definitions**
   - Extract protocols for bridges (avoid concrete class coupling)
   - Add generic type variables for factory returns
   - Create `oneiric/py.typed` marker for type checkers

8. **Day 5: Versioning Policy**
   - Document SemVer commitment (1.0 = stable API)
   - Define what's public vs private (underscore convention)
   - Add `__all__` exports to `__init__.py` files

**Deliverables:**
- ✅ 80% docstring coverage
- ✅ Comprehensive architecture documentation
- ✅ 10 working example projects
- ✅ API stability guarantees documented
- ✅ Type stubs for IDE support

**Success Criteria:** New contributor can build a plugin in < 30 minutes with docs alone

---

### Weeks 10-12: Production Hardening

**Goal:** Implement resiliency patterns for production reliability

**Tasks:**

**Week 10: Circuit Breaker & Retry Logic** (5 days)

1. **Days 1-2: Circuit Breaker Implementation**
   ```python
   # oneiric/remote/resilience.py
   from enum import Enum
   from dataclasses import dataclass
   from datetime import datetime, timedelta

   class CircuitState(Enum):
       CLOSED = "closed"      # Normal operation
       OPEN = "open"          # Failing, reject immediately
       HALF_OPEN = "half_open"  # Testing recovery

   @dataclass
   class CircuitBreakerConfig:
       failure_threshold: int = 5        # Failures before opening
       success_threshold: int = 2        # Successes to close
       timeout: timedelta = timedelta(seconds=60)  # Wait before half-open

   class CircuitBreaker:
       """Protect remote sync from cascading failures"""

       async def call(self, func: Callable, *args, **kwargs):
           if self.state == CircuitState.OPEN:
               if datetime.now() < self.opened_at + self.config.timeout:
                   raise CircuitBreakerOpenError("Circuit breaker is open")
               self.state = CircuitState.HALF_OPEN

           try:
               result = await func(*args, **kwargs)
               self._on_success()
               return result
           except Exception as e:
               self._on_failure()
               raise
   ```

2. **Days 3-4: Exponential Backoff**
   ```python
   # oneiric/remote/resilience.py
   import asyncio
   from typing import TypeVar, Callable

   T = TypeVar('T')

   async def retry_with_backoff(
       func: Callable[[], T],
       max_attempts: int = 3,
       initial_delay: float = 1.0,
       max_delay: float = 60.0,
       backoff_factor: float = 2.0,
       jitter: bool = True
   ) -> T:
       """Retry with exponential backoff and jitter"""
       for attempt in range(max_attempts):
           try:
               return await func()
           except Exception as e:
               if attempt == max_attempts - 1:
                   raise

               delay = min(initial_delay * (backoff_factor ** attempt), max_delay)
               if jitter:
                   delay *= (0.5 + random.random())  # 50-150% of delay

               logger.warning(
                   "retry-scheduled",
                   attempt=attempt + 1,
                   max_attempts=max_attempts,
                   delay=delay,
                   error=str(e)
               )
               await asyncio.sleep(delay)
   ```

3. **Day 5: Integration & Testing**
   - Wire circuit breaker into `RemoteLoader`
   - Add retry logic to manifest fetch
   - Write 10 tests for circuit breaker states
   - Write 5 tests for backoff timing

**Week 11: Performance Optimization** (5 days)

4. **Days 1-2: Profiling & Bottlenecks**
   - Profile resolver with 1000+ candidates
   - Profile lifecycle swaps under load (100 swaps/sec)
   - Identify hotspots with `cProfile` and `py-spy`

5. **Days 3-4: Optimization Implementations**
   - Parallelize remote entry registration (`asyncio.gather()`)
   - Add resolver result caching (LRU cache for resolve calls)
   - Batch snapshot persistence (queue writes, flush every 5s)
   - Config watcher: Check mtime before full reload

6. **Day 5: Benchmarking Suite**
   ```python
   # tests/benchmarks/test_performance.py
   import pytest
   from time import perf_counter

   @pytest.mark.benchmark
   class TestPerformance:
       def test_resolver_1000_candidates(self, benchmark, resolver):
           """Resolver should handle 1000 candidates in < 10ms"""
           # ... setup 1000 candidates

           def resolve_all():
               for key in keys:
                   resolver.resolve("adapter", key)

           result = benchmark(resolve_all)
           assert result.stats.mean < 0.01  # 10ms

       @pytest.mark.asyncio
       async def test_concurrent_swaps(self, benchmark, lifecycle):
           """100 concurrent swaps should complete in < 5s"""
   ```

**Week 12: Observability Enhancements** (5 days)

7. **Days 1-2: Metrics Expansion**
   - Add lifecycle state metrics (ready/failed/activating counts)
   - Add resolver decision latency histogram
   - Add remote sync latency percentiles (p50, p95, p99)
   - Add circuit breaker state changes counter

8. **Days 3-4: Structured Logging Improvements**
   - Add correlation IDs for swap chains
   - Add log sampling for verbose debug (1 in 100)
   - Add log level configuration via `ONEIRIC_LOG_LEVEL`
   - Add audit logging for security events (factory loads, signature checks)

9. **Day 5: Monitoring Integration Guide**
   - `docs/MONITORING.md` with Prometheus examples
   - Grafana dashboard JSON template
   - Sample alerting rules (circuit breaker open, high swap failure rate)

**Deliverables:**
- ✅ Circuit breaker protecting remote sync
- ✅ Exponential backoff with jitter
- ✅ Performance benchmarks (baseline established)
- ✅ Optimizations for 1000+ candidate resolution
- ✅ Comprehensive metrics for production monitoring

**Success Criteria:**
- Resolver handles 1000 candidates in < 10ms
- Remote sync survives 50% failure rate without cascading

---

### Weeks 13-16: Final Polish & Release Prep

**Goal:** Achieve production-ready v1.0.0 with full ecosystem

**Tasks:**

**Week 13: Missing Features Completion** (5 days)

1. **Days 1-3: Entry Point Discovery** (Phase 4 completion)
   ```python
   # oneiric/core/discovery.py
   from importlib.metadata import entry_points

   def discover_from_entry_points(group: str) -> List[Candidate]:
       """Discover candidates from Python package entry points.

       Example pyproject.toml:
       [project.entry-points."oneiric.adapters.cache"]
       redis = "mypackage.adapters:RedisAdapter"
       memcached = "mypackage.adapters:MemcachedAdapter"
       """
       candidates = []
       for entry_point in entry_points(group=group):
           domain, _, key = group.partition(".")[-1].partition(".")
           factory = entry_point.load()
           candidates.append(
               Candidate(
                   domain=domain,
                   key=key,
                   provider=entry_point.name,
                   factory=factory,
                   source=CandidateSource.ENTRY_POINT,
                   metadata={"entry_point": entry_point.name}
               )
           )
       return candidates
   ```

2. **Days 4-5: Capability Negotiation** (Optional early add)
   ```python
   # oneiric/core/resolution.py
   def resolve_by_capability(
       self,
       domain: str,
       key: str,
       required_capabilities: Set[str]
   ) -> Optional[Candidate]:
       """Resolve candidate requiring specific capabilities"""
       candidates = self._candidates.get((domain, key), [])

       # Filter to those with all required capabilities
       capable = [
           c for c in candidates
           if required_capabilities.issubset(
               c.metadata.get("capabilities", set())
           )
       ]

       if not capable:
           return None

       # Apply normal precedence among capable candidates
       return self._apply_precedence(capable)
   ```

**Week 14: Deployment Infrastructure** (5 days)

3. **Days 1-2: Docker & Kubernetes**
   - Create `Dockerfile` with multi-stage build
   - Create Kubernetes manifests (`k8s/deployment.yaml`, `k8s/configmap.yaml`)
   - Create Helm chart (`chart/oneiric/`)
   - Add health check endpoints for k8s probes

4. **Days 3-4: CI/CD Pipeline**
   - GitHub Actions workflow (`.github/workflows/ci.yml`)
     - Run tests on Python 3.13 and 3.14
     - Security scanning (bandit, safety)
     - Coverage enforcement (fail if < 60%)
     - Type checking (mypy --strict)
   - Release automation (`.github/workflows/release.yml`)
     - Tag-based releases
     - PyPI publishing
     - Docker image push to GHCR

5. **Day 5: Deployment Documentation**
   - `docs/DEPLOYMENT.md` with examples for:
     - Systemd service
     - Docker Compose
     - Kubernetes
     - Cloud Run / Lambda

**Week 15: Community & Ecosystem** (5 days)

6. **Days 1-2: Project Infrastructure**
   - `CONTRIBUTING.md` with development workflow
   - `CODE_OF_CONDUCT.md` (Contributor Covenant)
   - `CHANGELOG.md` with release notes
   - Issue templates (bug report, feature request, security)
   - Pull request template with checklist

7. **Days 3-4: Plugin Ecosystem Kickstart**
   - Create `oneiric-plugins` GitHub organization
   - Publish 3 reference plugins:
     - `oneiric-adapter-redis` (cache adapter)
     - `oneiric-service-auth` (JWT authentication service)
     - `oneiric-task-email` (email sending task)
   - Create plugin template repository

8. **Day 5: Community Launch**
   - Publish blog post announcing v1.0
   - Submit to Python Weekly, Python Bytes
   - Create Discord/Slack community
   - Write comparison guide: Oneiric vs setuptools entry points, vs stevedore

**Week 16: Final Hardening & Release** (5 days)

9. **Days 1-2: Security Audit**
   - Run automated security scanners (bandit, semgrep, snyk)
   - Manual code review of security-critical paths
   - Update `SECURITY.md` with audit results
   - Generate SBOM (Software Bill of Materials)

10. **Days 3-4: Load Testing**
    - Stress test with 10,000 candidates
    - Stress test with 1,000 concurrent swaps
    - Memory leak testing (24-hour soak test)
    - Remote sync resilience (network partition tests)

11. **Day 5: Release v1.0.0**
    - Final version bump
    - Generate release notes
    - Tag release on GitHub
    - Publish to PyPI
    - Update documentation site
    - Announce on social media

**Deliverables:**
- ✅ Entry point discovery implemented
- ✅ Capability negotiation available
- ✅ Docker/K8s deployment ready
- ✅ CI/CD pipeline complete
- ✅ 3 reference plugins published
- ✅ Community infrastructure established
- ✅ v1.0.0 released to PyPI

**Success Criteria:** v1.0.0 passes all quality gates and is production-deployed

---

## Technical Debt Management

### High-Priority Refactoring (During Weeks 7-12)

1. **Consolidate Bridge Duplication** (Week 8, 1 day)
   - `AdapterBridge` and `DomainBridge` share 90% code
   - Extract common logic to `BaseBridge` abstract class
   - Reduce maintenance burden

2. **Split CLI Monolith** (Week 9, 2 days)
   - 1000-line `cli.py` is hard to maintain
   - Refactor to `cli/commands/` package with subcommands
   - Improve testability and extensibility

3. **Extract Shared Utilities** (Week 7, 1 day)
   - Duplicate `_maybe_await()` in `lifecycle.py` and `config.py`
   - Create `oneiric/utils/async_helpers.py`
   - Add other common patterns (retry, timeout, context managers)

4. **Pydantic Model Inheritance** (Week 8, 1 day)
   - 15+ Pydantic models with no shared base
   - Create `BaseSettings` with common validation patterns
   - Ensure consistent error messages

### Design Improvements

1. **Protocol-Based Bridge Interface** (Week 9, 2 days)
   ```python
   # oneiric/domains/protocols.py
   from typing import Protocol, runtime_checkable

   @runtime_checkable
   class BridgeProtocol(Protocol):
       """Protocol for domain bridges (avoid concrete class coupling)"""

       async def use(self, key: str, provider: Optional[str] = None) -> Any:
           """Activate and return instance for key"""
           ...

       def active_candidates(self) -> List[Candidate]:
           """Return all active candidates"""
           ...

       def explain(self, key: str) -> str:
           """Explain resolution decision"""
           ...
   ```

2. **Result Type for Error Handling** (Week 10, 1 day)
   ```python
   # oneiric/core/result.py
   from typing import Generic, TypeVar, Union
   from dataclasses import dataclass

   T = TypeVar('T')
   E = TypeVar('E', bound=Exception)

   @dataclass
   class Ok(Generic[T]):
       value: T

   @dataclass
   class Err(Generic[E]):
       error: E

   Result = Union[Ok[T], Err[E]]

   # Use in lifecycle.swap() to avoid exceptions for control flow
   async def swap(self, ...) -> Result[Any, LifecycleError]:
       try:
           instance = await self._perform_swap(...)
           return Ok(instance)
       except Exception as e:
           return Err(LifecycleError(str(e)))
   ```

---

## Quality Gates & Success Criteria

### Beta Release (v0.5.0) - Week 6

**Blockers Cleared:**
- ✅ Factory allowlist enforced (arbitrary code execution blocked)
- ✅ Path traversal sanitization (file system compromise blocked)
- ✅ HTTP timeouts configured (availability protected)
- ✅ 60% test coverage minimum (core logic verified)

**Quality Scores:**
- Security: 80/100 (up from 45/100)
- Testing: 70/100 (up from 10/100)
- Overall: 78/100 (Beta Quality)

### Release Candidate (v0.9.0) - Week 12

**Additional Requirements:**
- ✅ Signature verification implemented (trusted remote manifests)
- ✅ Circuit breaker protecting remote sync
- ✅ Exponential backoff with jitter
- ✅ 80% documentation completeness
- ✅ Performance benchmarks established

**Quality Scores:**
- Security: 90/100
- Testing: 80/100
- Documentation: 90/100
- Overall: 85/100 (RC Quality)

### Production Release (v1.0.0) - Week 16

**Final Requirements:**
- ✅ 80% test coverage (comprehensive)
- ✅ Security audit passed
- ✅ Load testing completed (1000+ candidates, 1000 swaps/sec)
- ✅ API stability guarantees documented
- ✅ CI/CD pipeline fully automated
- ✅ Deployment documentation complete

**Quality Scores:**
- Architecture: 90/100
- Security: 95/100
- Testing: 90/100
- Documentation: 95/100
- Observability: 90/100
- Overall: 92/100 (Production Ready - matches ACB quality)

---

## Risk Management

### Critical Risks

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| **Security vulnerabilities discovered post-release** | HIGH | MEDIUM | Comprehensive security audit in Week 16, bug bounty program |
| **Performance degradation at scale** | HIGH | LOW | Load testing in Week 15, benchmarking in Week 11 |
| **API instability causing breaking changes** | HIGH | MEDIUM | API review in Week 9, deprecation policy, SemVer commitment |
| **Test coverage targets missed** | MEDIUM | LOW | Daily tracking, block merge if coverage drops |
| **Timeline slippage (16 weeks too aggressive)** | MEDIUM | MEDIUM | Build in 2-week buffer, prioritize P0 items first |

### Dependency Risks

| Dependency | Risk | Mitigation |
|------------|------|------------|
| **Pydantic v2** | Breaking changes in v3 | Pin to `pydantic>=2.0,<3.0`, monitor changelog |
| **OpenTelemetry** | API churn in SDK | Use stable API only, avoid experimental features |
| **Cryptography** | Vulnerability in signature verification | Security scanning in CI, update promptly |
| **Python 3.14** | Features not backportable to 3.13 | Test on both 3.13 and 3.14, avoid 3.14-only syntax |

---

## Resource Allocation

### Effort Breakdown (in person-weeks)

| Phase | Weeks | Focus |
|-------|-------|-------|
| Security Hardening | 2 | Factory allowlist, signature verification, input validation |
| Test Coverage | 4 | 60+ tests, fixtures, CI/CD pipeline |
| Documentation | 3 | Docstrings, guides, examples |
| Production Hardening | 3 | Circuit breaker, retry logic, performance optimization |
| Final Polish | 4 | Entry points, deployment, community launch |
| **Total** | **16 weeks** | **Full-time equivalent** |

### Team Structure (Recommended)

**Solo Developer:**
- 16 weeks full-time (realistic for alpha → production)
- Focus on P0 items first, defer P2 if time constrained

**Small Team (2-3 developers):**
- 8-10 weeks with parallel workstreams:
  - Developer 1: Security + core testing
  - Developer 2: Documentation + examples
  - Developer 3: Production hardening + deployment

**Large Team (4+ developers):**
- 6-8 weeks with specialized roles:
  - Security Engineer: Signature verification, audit
  - Backend Engineer: Circuit breaker, retry logic
  - DevOps Engineer: CI/CD, Kubernetes, monitoring
  - Technical Writer: Documentation, examples, guides

---

## Comparison with ACB Framework

### What Oneiric Does Better (Post-Roadmap)

1. **Resolution Sophistication**: 4-tier precedence vs ACB's 2-tier
2. **Hot-Swapping**: First-class runtime swaps vs manual reload
3. **Explain API**: Full decision traces vs implicit resolution
4. **CLI Diagnostics**: Comprehensive tooling vs none
5. **Remote-Native**: Built for distributed components from day one

### What ACB Still Does Better (Even Post-Roadmap)

1. **Production Maturity**: 31 releases, battle-tested vs greenfield
2. **Adapter Ecosystem**: 60+ implementations vs 3 reference plugins
3. **Full Platform**: Services, Tasks, Events, Workflows with implementations vs bridges only
4. **Community**: Established user base vs new project
5. **Integration**: FastBlocks framework, MCP server vs standalone

### Convergence Path

**Option 1: Oneiric as ACB v2.0 Foundation** (12-18 months post-1.0)
- ACB adopts Oneiric resolution layer for adapters
- Gradual migration over multiple ACB releases
- Backward compatibility maintained via shim layer

**Option 2: Parallel Evolution** (Immediate)
- Oneiric focuses on resolution layer excellence
- ACB continues as full application platform
- Cross-pollination of ideas (ACB adds explain API, Oneiric adds adapter implementations)

**Recommendation:** Option 2 initially, reassess Option 1 after Oneiric proves stability in production for 6-12 months.

---

## Appendix: Quick Reference

### Phase Dependency Graph

```
Phase 1 (Complete) → Phase 2 (Complete) → Phase 3 (Complete)
                                               ↓
Phase 4 (Partial) ← Security Hardening ←─────┘
       ↓
Phase 5 (Partial) ← Test Coverage
       ↓
Phase 6 (Partial) ← Documentation
       ↓
Phase 7 (Partial) ← Production Hardening
       ↓
   v1.0.0
```

### Critical Path Items (Cannot Parallelize)

1. **Week 1-2: Security** → Blocks beta testing
2. **Week 3-6: Tests** → Blocks refactoring confidence
3. **Week 7-9: Docs** → Blocks community adoption
4. **Week 10-12: Hardening** → Blocks production deployment
5. **Week 13-16: Polish** → Blocks v1.0.0 release

### Files Requiring Immediate Attention

| File | Issue | Priority | Effort |
|------|-------|----------|--------|
| `oneiric/core/lifecycle.py:44-53` | Arbitrary code execution | 🔴 P0 | 4 hours |
| `oneiric/remote/loader.py:52-54` | Path traversal | 🔴 P0 | 2 hours |
| `oneiric/remote/loader.py:73` | No HTTP timeout | 🔴 P0 | 2 hours |
| `tests/` | Missing directory | 🔴 P0 | 2 weeks |
| `oneiric/remote/loader.py` | No signature verification | 🟡 P1 | 3 days |
| `oneiric/core/resolution.py:118` | Race condition | 🟡 P1 | 1 day |

### Recommended Reading Order for New Contributors

1. `docs/NEW_ARCH_SPEC.md` - Understand the vision
2. `docs/RESOLUTION_LAYER_SPEC.md` - Core semantics
3. `docs/ACB_COMPARISON.md` - Learn from ACB's maturity
4. `docs/CRITICAL_AUDIT_REPORT.md` - Understand current gaps
5. **This document** (`UNIFIED_ROADMAP.md`) - Know what's next

---

## Conclusion

Oneiric has **world-class architectural vision** trapped in **alpha-quality implementation**. This roadmap provides a clear, disciplined path to production readiness by:

1. **Weeks 1-2:** Closing critical security vulnerabilities (factory allowlist, path sanitization, timeouts)
2. **Weeks 3-6:** Building test coverage foundation (60 tests minimum, 60% coverage)
3. **Weeks 7-9:** Completing documentation and stabilizing APIs
4. **Weeks 10-12:** Hardening for production (circuit breakers, retry logic, performance)
5. **Weeks 13-16:** Final polish and v1.0.0 release

**Key Insight:** We must resist the temptation to add new features (Phase 5-7 optional items) until we secure the foundation with tests and security fixes. **Every line is a liability** until it's tested and hardened.

**Success Definition:** Oneiric v1.0.0 achieves 92/100 quality score (matching ACB's production-readiness) with:
- Zero critical security vulnerabilities
- 80%+ test coverage
- Comprehensive documentation
- Production-proven resilience patterns
- Thriving plugin ecosystem

**Timeline:** 16 weeks to production-ready v1.0.0 (solo developer full-time, or 8-10 weeks with small team).

Let's build something **reliable, secure, and excellent**.

---

**Document Version:** 1.0
**Last Updated:** 2025-11-25
**Next Review:** After Week 6 (Beta Release)
**Owner:** Oneiric Core Team
