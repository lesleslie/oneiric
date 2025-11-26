# Critical Audit Report: Oneiric Project

**Audit Date:** 2025-11-25
**Project Version:** 0.1.0
**Python Version:** 3.14
**Code Base:** 3,795 lines across 30 Python files
**Test Coverage:** Minimal (no test suite found)

---

## Executive Summary

Oneiric is an ambitious universal resolution layer for pluggable components with multi-domain support (adapters, services, tasks, events, workflows). The project demonstrates **solid architectural foundations** and **impressive feature completeness** for Phase 1-4+ implementation, but suffers from **critical gaps in testing, security validation, and production hardening**.

**Overall Assessment:** 68/100 (Alpha Quality - Not Production Ready)

**Key Findings:**
- Strong: Architecture alignment with specs, clean code structure, comprehensive observability
- Critical: Zero test coverage, missing signature verification, insufficient input validation
- Moderate: Documentation gaps, type hint inconsistencies, missing error recovery patterns

---

## 1. Architecture & Design Quality (Score: 85/100)

### 1.1 Alignment with Specifications

**Excellent Alignment** with NEW_ARCH_SPEC.md and RESOLUTION_LAYER_SPEC.md:

#### Core Resolution Layer (✓ Complete)
- `/oneiric/core/resolution.py` implements all spec requirements:
  - `Candidate` model with all required fields (domain, key, provider, priority, stack_level, factory, metadata, source, health)
  - `CandidateRegistry` with active/shadowed tracking
  - Precedence rules correctly implemented (override > priority > stack_level > registration order)
  - `explain()` API provides decision traces
- Priority inference from `ONEIRIC_STACK_ORDER` env variable (lines 208-222)
- `register_pkg()` with path-based priority hints (lines 238-255)

#### Lifecycle Management (✓ Complete)
- `/oneiric/core/lifecycle.py` implements full hot-swap flow:
  - Pre/post swap hooks (lines 29-42)
  - Health checks before activation (lines 227-239)
  - Rollback on failure (lines 274-286)
  - Cleanup of old instances (lines 252-262)
  - Status persistence to JSON snapshots (lines 331-359)

#### Domain Integration (✓ Complete for 5 domains)
- Adapter bridge: `/oneiric/adapters/bridge.py`
- Service/Task/Event/Workflow bridges: `/oneiric/domains/*.py`
- All domains use unified `DomainBridge` base pattern (lines 27-165 in `domains/base.py`)
- Consistent API across domains (use, active_candidates, shadowed_candidates, explain)

#### Remote Manifest Support (✓ Complete)
- `/oneiric/remote/loader.py` implements:
  - Manifest fetching (HTTP/local file)
  - SHA256 digest verification (lines 272-275)
  - Artifact caching (lines 45-83)
  - Async refresh loop (lines 111-143)
  - Telemetry tracking (lines 194-212)

### 1.2 Module Organization (Score: 90/100)

**Strengths:**
- Clean separation of concerns across packages:
  - `core/`: resolution, lifecycle, config, observability, runtime
  - `domains/`: service/task/event/workflow bridges
  - `adapters/`: adapter-specific bridge and metadata
  - `remote/`: manifest loading and telemetry
  - `runtime/`: orchestrator, watchers, health, activity tracking
- Small, focused modules (largest is cli.py at ~1000 lines, reasonable for CLI)
- Clear dependency flow: core → adapters/domains → remote → runtime

**Weaknesses:**
- Circular import potential between `core.config` and `oneiric.runtime.health` (line 16 in config.py)
- `cli.py` mixes concerns (initialization, demo data, command implementations) - could split into cli/commands/
- Missing dedicated `exceptions.py` - errors scattered across modules

### 1.3 API Design Consistency (Score: 85/100)

**Strengths:**
- Unified bridge pattern across all domains
- Consistent async/await usage throughout
- Clear separation of sync/async methods
- All bridges expose same core methods: `use()`, `active_candidates()`, `shadowed_candidates()`, `explain()`

**Weaknesses:**
- Inconsistent naming: `AdapterBridge.use(category=)` vs `DomainBridge.use(key=)` - should standardize
- `LifecycleManager.activate()` and `.swap()` are aliases (line 124) - confusing, should deprecate one
- Factory resolution accepts both callables and strings (line 44 lifecycle.py) but error messages unclear

### 1.4 Design Pattern Usage (Score: 80/100)

**Well-Executed Patterns:**
- **Registry Pattern**: CandidateRegistry with active/shadowed tracking
- **Bridge Pattern**: Domain bridges abstract resolver/lifecycle integration
- **Factory Pattern**: Configurable factory resolution with lazy instantiation
- **Observer Pattern**: Config watchers monitor for changes
- **Strategy Pattern**: Multiple candidate sources (local, remote, entry_point)

**Concerns:**
- **No Circuit Breaker**: Remote sync failures could cascade (Phase 5 feature, spec line 91 in NEW_ARCH_SPEC.md)
- **No Retry Logic**: Network failures in remote loader lack exponential backoff (Phase 5 gap)
- **Tight Coupling**: Bridges directly depend on lifecycle manager - should use protocol/interface

---

## 2. Code Quality (Score: 75/100)

### 2.1 Python 3.14 Feature Usage (Score: 85/100)

**Excellent Modern Idioms:**
- Type hints with `|` union syntax (e.g., `str | None` throughout)
- `from __future__ import annotations` in all modules
- `datetime.now(timezone.utc)` avoiding naive datetimes
- Proper use of `asyncio.TaskGroup` (runtime.py lines 18-68)
- `tomllib` for TOML parsing (config.py line 182)
- Pydantic v2 models with `ConfigDict`

**Underutilized Features:**
- No use of Python 3.14 type parameter syntax (PEP 695) - could improve generic types
- Missing dataclass `slots=True` for memory efficiency
- Could use `typing.Self` for fluent interfaces (e.g., Candidate.with_priority)

### 2.2 Type Hints Completeness (Score: 70/100)

**Coverage Analysis:**
- 234 function definitions total
- ~85% have return type annotations
- ~90% have parameter type annotations

**Issues Found:**
1. **Missing Return Types:**
   - `lifecycle.py:56` - `_maybe_await()` returns `Any` but could be more specific with `TypeVar`
   - `config.py:205` - `_maybe_await()` duplicate implementation, inconsistent typing

2. **Overly Broad Types:**
   - `resolution.py:18` - `FactoryType = Callable[..., Any] | str` - `...` is too permissive
   - `lifecycle.py:19` - `FactoryCallable = Callable[..., Any]` - should specify no-args callable

3. **Missing Generic Constraints:**
   - `domains/base.py:25` - `settings: Any` should be `BaseModel | dict[str, Any]`
   - `bridges` returns untyped dict - should use TypedDict or Protocol

**Recommendations:**
- Add `mypy --strict` to CI pipeline (currently missing)
- Use `Protocol` classes for bridge interfaces
- Add generic type variables for factory return types

### 2.3 Error Handling Patterns (Score: 65/100)

**Strengths:**
- Custom exception types: `LifecycleError`, `TaskGroupError`
- Proper exception chaining with `raise ... from exc`
- Rollback logic on swap failures (lifecycle.py lines 274-286)
- Graceful degradation in remote sync (continues on error, logs warnings)

**Critical Gaps:**

1. **Insufficient Input Validation:**
```python
# loader.py:278 - Validation too simplistic
def _validate_entry(entry: RemoteManifestEntry) -> Optional[str]:
    if entry.domain not in VALID_DOMAINS:
        return f"unsupported domain '{entry.domain}'"
    # Missing: factory string format validation
    # Missing: key format validation (could inject malicious paths)
    # Missing: stack_level bounds checking
```

2. **Unsafe Import Resolution:**
```python
# lifecycle.py:44-53 - No security checks on import paths
def resolve_factory(factory: str | FactoryCallable) -> FactoryCallable:
    module_path, _, attr = factory.partition(":")
    module = importlib.import_module(module_path)  # SECURITY: Can import arbitrary modules!
    return getattr(module, attr)
```
**Risk:** Remote manifests could specify `factory: "os:system"` and execute arbitrary code.

3. **Missing Timeouts:**
```python
# loader.py:73 - No timeout on HTTP requests
with urllib.request.urlopen(request, context=context) as response:
    # Could hang indefinitely on slow/malicious server
```

4. **Unchecked File Operations:**
```python
# lifecycle.py:355-359 - Temp file cleanup missing error handling
tmp_path.write_text(json.dumps(payload))
tmp_path.replace(path)  # Could fail silently if permissions change
```

### 2.4 Async/Await Usage (Score: 90/100)

**Excellent Patterns:**
- Proper `async with` context managers (RuntimeOrchestrator, SelectionWatcher)
- Correct use of `asyncio.create_task()` with named tasks
- Graceful cancellation with `asyncio.gather(..., return_exceptions=True)`
- `_maybe_await()` helper for optional async (lifecycle.py:56, config.py:205)

**Minor Issues:**
- `remote/loader.py:145` - Sync function wrapped in async (could use `asyncio.to_thread`)
- No structured concurrency enforcement - tasks could leak if exceptions occur mid-creation

### 2.5 Documentation Quality (Score: 60/100)

**Module-Level Docstrings:** Present but terse (e.g., "Resolver and candidate registry" - could explain purpose/usage)

**Function Docstrings:** **Mostly Missing** - Critical gap:
```python
# resolution.py:137 - No docstring
def resolve(self, domain: str, key: str, provider: Optional[str] = None) -> Optional[Candidate]:
    # What does provider filter do? What's the precedence?
    # Should document: "Returns active candidate for domain/key. If provider specified,
    # filters candidates to match provider. Returns None if no candidate found."
```

**Type Hints as Documentation:** Good, but insufficient without docstrings explaining behavior

**README.md:** Shows CLI usage but lacks:
- Architecture overview
- Quick start guide for library usage (not just CLI)
- Troubleshooting section
- Contributing guidelines

---

## 3. Implementation Completeness (Score: 75/100)

### 3.1 Comparison: BUILD_PROGRESS.md vs Actual Implementation

**Phase 1: Core Resolution Layer** (✓ 100% Complete)
- ✓ Candidate model, registry, precedence
- ✓ Active/shadowed tracking
- ✓ Explain/trace API
- ✓ Hot-swap with pre/post hooks
- ✓ Config bridge for selections

**Phase 2: Adapter Modularization** (✓ 95% Complete)
- ✓ Metadata-driven registration
- ✓ Adapter bridge with lifecycle
- ✓ Config watcher triggering swaps
- ✓ CLI for active/shadowed views
- ⚠ Missing: Adapter-specific health checks (generic health works, but no adapter categories with special health)

**Phase 3: Cross-Domain Alignment** (✓ 100% Complete)
- ✓ Services, tasks, events, workflows on resolver
- ✓ Activation flags and swap hooks
- ✓ Pause/drain state management
- ✓ Per-domain settings models

**Phase 4: Plugin Protocol & Remote Artifacts** (✓ 80% Complete)
- ✓ Remote manifest fetch (HTTP/local)
- ✓ SHA256 digest verification
- ✓ Artifact caching
- ✓ Source metadata
- ✗ **MISSING: Signature verification** (spec requires but not implemented - CRITICAL SECURITY GAP)
- ✗ **MISSING: Entry-point discovery** (pluggy-style, spec line 88 in GRAND_IMPLEMENTATION_PLAN)
- ⚠ Wheel/zip installation mentioned in spec but not implemented (only sys.path prepend in samples)

**Phase 5: Observability & Resiliency** (✓ 70% Complete)
- ✓ OpenTelemetry tracing with spans
- ✓ Structured logging (structlog)
- ✓ Metrics (counters, histograms in remote/metrics.py)
- ✓ Health interfaces
- ✗ **MISSING: Backpressure/rate limiting** (spec line 62-63 in GRAND_IMPLEMENTATION_PLAN)
- ✗ **MISSING: Circuit breaker mixins** (spec line 86 in NEW_ARCH_SPEC)
- ✗ **MISSING: Retry/backoff standardization** (Phase 5 requirement)

**Phase 6: Lifecycle & Safety** (✓ 85% Complete)
- ✓ Lifecycle interface (init, health, cleanup)
- ✓ Cleanup on swap and shutdown
- ✓ Rollback on failed init
- ✓ Pause/resume for stateful components
- ⚠ Cancellation-safe utilities mentioned but not fully enforced (no shields, limited timeout usage)

**Phase 7: Tooling & UX** (✓ 90% Complete)
- ✓ CLI commands (list, explain, status, health, swap, pause, drain, remote-sync, orchestrate, activity)
- ✓ Sample manifest (docs/sample_remote_manifest.yaml)
- ✓ Per-domain tables with active/shadowed
- ⚠ Tests mentioned in Phase 7 but **completely absent**

### 3.2 Gap Analysis: Documented but Missing

**Documented in Specs, Not Implemented:**

1. **Signature Verification** (RESOLUTION_LAYER_SPEC.md line 84, NEW_ARCH_SPEC.md line 48)
   - Spec: "sha256, optional signature" and "signed manifest with uri + sha/signature"
   - Reality: Only SHA256 implemented (loader.py:272-275), no signature verification code found
   - **Impact:** HIGH - Remote manifests unverified, could be man-in-the-middle attacked

2. **Allowlist/Denylist for Sources** (RESOLUTION_LAYER_SPEC.md line 83)
   - Spec: "Enforce allowlist/denylist for sources"
   - Reality: No filtering mechanism in RemoteSourceConfig
   - **Impact:** MEDIUM - Cannot restrict which remote sources are trusted

3. **Wheel/Zip Installation** (NEW_ARCH_SPEC.md line 48, RESOLUTION_LAYER_SPEC.md line 63)
   - Spec: "download wheel/zip to cache; install or sys.path prepend"
   - Reality: Only factories are called (loader.py:249-269), no actual wheel installation
   - **Impact:** LOW - Current design may be intentional (lightweight), but spec mismatch

4. **Entry Point Discovery** (RESOLUTION_LAYER_SPEC.md line 41, GRAND_IMPLEMENTATION_PLAN.md line 49)
   - Spec: "discover_from_entry_points(group)" and "entry-point style discovery"
   - Reality: `CandidateSource.ENTRY_POINT` enum exists but no implementation
   - **Impact:** LOW - Phase 4 optional feature, but mentioned as future work

5. **Capability Tags** (NEW_ARCH_SPEC.md line 89)
   - Spec: "Capability tags and negotiation in resolver"
   - Reality: Metadata dict exists but no resolver logic for capability matching
   - **Impact:** LOW - Optional early add, deferred to future

### 3.3 Implemented but Not Documented

**Found in Code, Missing from Specs/Docs:**

1. **Activity State Management** (BUILD_PROGRESS.md lines 47-49 mention, but specs don't)
   - `DomainActivityStore` in runtime/activity.py
   - Pause/drain state persistence to `.oneiric_cache/domain_activity.json`
   - CLI `activity` command
   - **Good Addition:** Fills operational gap

2. **Runtime Health Snapshots** (BUILD_PROGRESS.md mentions, not in original specs)
   - `RuntimeHealthSnapshot` in runtime/health.py
   - Orchestrator PID tracking
   - Watcher status monitoring
   - **Good Addition:** Critical for production diagnostics

3. **Telemetry Caching** (remote/telemetry.py)
   - Per-domain sync metrics cached to JSON
   - Remote status persistence separate from lifecycle
   - **Good Addition:** Enables offline diagnostics

4. **Comprehensive CLI** (Goes beyond spec requirements)
   - Spec mentions basic list/explain/swap
   - Reality: 15+ commands with JSON output, filtering, probing
   - **Good Addition:** Production-ready CLI

---

## 4. Testing & Quality Assurance (Score: 10/100)

### 4.1 Test Coverage (CRITICAL FAILURE)

**Current State:**
- **Zero test files found** in project (only .venv test_cases.py from dependency)
- No `tests/` directory
- No `pytest.ini` or test configuration
- No CI/CD pipeline configuration

**Expected for Alpha:**
- Unit tests for core resolver precedence logic
- Lifecycle swap/rollback test cases
- Remote manifest parsing and validation tests
- Config loading and override tests
- Mock-based tests for HTTP fetching

**Missing Critical Test Categories:**

1. **Precedence Rules** (Should have ~15 test cases)
   - Override beats priority
   - Priority beats stack_level
   - Stack_level beats registration order
   - Registration order as tiebreaker
   - Edge case: equal priorities, different sources

2. **Lifecycle Swap Logic** (Should have ~20 test cases)
   - Successful swap with health check
   - Failed health check triggers rollback
   - Cleanup called on old instance
   - Pre/post hooks executed in order
   - Force flag bypasses health check
   - Exception during swap handled correctly

3. **Remote Manifest Security** (Should have ~10 test cases)
   - SHA256 mismatch raises exception
   - Invalid factory format rejected
   - Malicious domain names rejected
   - Factory import errors handled gracefully
   - Network timeout scenarios

4. **Config Watchers** (Should have ~8 test cases)
   - Detects selection changes
   - Triggers swap on config update
   - Respects pause state (skips swap)
   - Respects drain state (delays swap)
   - Poll interval works correctly

**Test Framework Recommendation:**
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
asyncio_mode = "auto"

[project.optional-dependencies]
test = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-cov>=4.1",
    "pytest-mock>=3.12",
]
```

### 4.2 Runtime Verification Needed

**Manual Testing Performed (via audit):**
- ✓ `main.py` runs successfully
- ✓ CLI commands work (list, health)
- ✓ Demo adapters register and activate
- ✓ Lifecycle snapshots persist

**Gaps Requiring Testing:**
1. Config hot-reload under concurrent load
2. Remote manifest refresh with network failures
3. Health check failures during production swap
4. Pause/drain state transitions during active swaps
5. Memory leaks from instance caching
6. Concurrent resolver access (thread safety unclear)

---

## 5. Security & Robustness (Score: 45/100)

### 5.1 Input Validation (CRITICAL GAPS)

**Vulnerabilities Found:**

#### 1. **Arbitrary Code Execution via Factory Resolution** (CRITICAL - CVE-worthy)
```python
# lifecycle.py:44-53
def resolve_factory(factory: str | FactoryCallable) -> FactoryCallable:
    module_path, _, attr = factory.partition(":")
    module = importlib.import_module(module_path)  # No validation!
    return getattr(module, attr)
```
**Attack Vector:**
```yaml
# Malicious manifest
entries:
  - domain: adapter
    key: evil
    provider: hacker
    factory: "os:system"  # Imports os module, returns os.system function
    # When activated, could execute: os.system("rm -rf /")
```
**Fix Required:** Implement factory allowlist/denylist, validate module paths against safe patterns

#### 2. **Path Traversal in Cache Dir** (HIGH)
```python
# loader.py:52-54
filename = sha256 or Path(uri).name  # If sha256 is None, uses uri filename
destination = self.cache_dir / filename  # No path sanitization!
```
**Attack Vector:** `uri: "../../etc/passwd"` could write outside cache dir
**Fix Required:** Use `destination.resolve()` and verify it's under `cache_dir.resolve()`

#### 3. **Unbounded Priority Values** (MEDIUM)
```python
# resolution.py:191-198
priority = cand.priority or self.settings.default_priority
score = (override_score, priority, stack, sequence)
```
**Attack Vector:** Remote manifest sets `priority: 999999999`, causing integer overflow or starving legitimate candidates
**Fix Required:** Enforce priority bounds (e.g., -1000 to 1000)

### 5.2 Missing Security Features

**From Spec, Not Implemented:**

1. **Signature Verification** (CRITICAL)
   - Spec requires "optional signature" checking
   - Current implementation only verifies SHA256
   - **Risk:** Man-in-the-middle can replace manifest if HTTPS is compromised

2. **Source Allowlist/Denylist** (HIGH)
   - No filtering of remote manifest URLs
   - No per-domain source restrictions
   - **Risk:** Malicious operator could add untrusted remote source

3. **TLS Certificate Pinning** (MEDIUM)
   - `RemoteSourceConfig.verify_tls` can be disabled
   - No certificate pinning for known sources
   - **Risk:** Downgrade attack possible

### 5.3 Error Handling Edge Cases

**Insufficiently Handled:**

1. **Disk Full During Snapshot Persistence**
```python
# lifecycle.py:357-359
tmp_path.write_text(json.dumps(payload))  # Could fail
tmp_path.replace(path)  # Atomic, but exception not caught
```
**Impact:** Snapshot corruption if disk full mid-write

2. **Concurrent Registry Modifications**
```python
# resolution.py:118-135
def register_candidate(self, candidate: Candidate) -> None:
    # No locking mechanism
    self._candidates[key].append(stored)
    self._recompute(stored.domain, stored.key)
```
**Impact:** Race condition if two threads register for same domain/key

3. **Infinite Recursion in Config Watchers**
```python
# watchers.py:85-88
for key, provider in added_or_changed.items():
    await self._trigger_swap(key, provider)
    # If swap modifies config, could trigger another swap
```
**Impact:** Stack overflow if config changes trigger recursive swaps

### 5.4 Secrets Handling (Score: 70/100)

**Good Practices:**
- Secrets not hardcoded (uses SecretsHook with adapter pattern)
- Inline secrets in config marked explicitly
- Auth tokens passed via headers, not URL params

**Concerns:**
- No secrets rotation mechanism
- Secrets cached in `_settings_cache` indefinitely (bridge.py:44, 59)
- No audit logging when secrets accessed

---

## 6. Observability & Operations (Score: 80/100)

### 6.1 Logging Strategy (Score: 85/100)

**Strengths:**
- Structured logging with structlog throughout
- Consistent field names (domain, key, provider, source, priority)
- Log levels appropriately used (debug/info/warning/error)
- Logger namespacing by component (e.g., "adapter.bridge", "lifecycle", "remote")

**Example:**
```python
# lifecycle.py:191-196
self._logger.info(
    "swap-complete",
    domain=candidate.domain,
    key=candidate.key,
    provider=candidate.provider,
)
```

**Minor Issues:**
- No correlation IDs for tracing swap chains
- Log volume could be high with verbose debug (no sampling)
- No log level configuration via environment

### 6.2 OpenTelemetry Integration (Score: 80/100)

**Implemented Features:**
- Trace spans for lifecycle swaps (lifecycle.py:288-298)
- Trace spans for resolver decisions (observability.py:57-69)
- Counters for remote sync successes/failures (remote/metrics.py)
- Histograms for sync duration (remote/metrics.py)

**Code Example:**
```python
# observability.py:57-69
@contextmanager
def traced_decision(event: DecisionEvent) -> Iterator[Span]:
    tracer = get_tracer(f"resolver.{event.domain}")
    with tracer.start_as_current_span("resolver.decision") as span:
        span.set_attributes(event.as_attributes())
        yield span
```

**Gaps:**
- No span context propagation across async tasks
- No custom metrics for lifecycle states (ready/failed counts)
- No trace sampling configuration
- OTLP exporter not configured (tracing works but goes nowhere by default)

### 6.3 Health Check Implementation (Score: 75/100)

**Implemented:**
- Generic health check interface (`candidate.health`, instance methods)
- CLI `health` command with live probing (`--probe`)
- Lifecycle status snapshots with timestamps
- Runtime health file with orchestrator PID

**Example:**
```python
# lifecycle.py:241-250
def _collect_health_checks(self, candidate: Candidate, instance: Any) -> List[Callable[[], Any]]:
    health_checks: List[Callable[[], Any]] = []
    if candidate.health:
        health_checks.append(candidate.health)
    for attr in ("health", "check_health", "ready", "is_healthy"):
        method = getattr(instance, attr, None)
        if callable(method):
            health_checks.append(method)
            break
```

**Gaps:**
- No readiness vs liveness distinction
- No health check timeouts (could hang on slow check)
- No aggregated health status API endpoint
- No health check scheduling (passive, only on swap or manual probe)

### 6.4 Runtime Diagnostics (Score: 85/100)

**Excellent Features:**
- Lifecycle state persistence (`.oneiric_cache/lifecycle_status.json`)
- Runtime health snapshots (`.oneiric_cache/runtime_health.json`)
- Domain activity tracking (`.oneiric_cache/domain_activity.json`)
- Remote telemetry caching (`.oneiric_cache/remote_status.json`)
- CLI access to all snapshots

**Example Snapshot:**
```json
{
  "domain": "adapter",
  "key": "demo",
  "state": "ready",
  "current_provider": "builtin",
  "last_activated_at": "2025-11-25T19:08:53.248592+00:00"
}
```

**Minor Issues:**
- Snapshot files could grow unbounded (no rotation)
- No snapshot compression for large registries
- No metrics export from snapshots (must parse JSON manually)

---

## 7. Technical Debt & Risks (Score: 60/100)

### 7.1 TODO/FIXME Analysis

**Result:** **Zero TODOs/FIXMEs found** in codebase (grep search performed)

**Assessment:** Either:
1. Code is truly complete (unlikely for alpha)
2. Technical debt not being tracked inline (risky)
3. Issues externalized to docs/issues (unknown)

**Recommendation:** Start tracking known issues as inline comments for visibility

### 7.2 Known Issues & Workarounds

**From Code Review:**

1. **Duplicate `_maybe_await` Implementation**
   - Found in `lifecycle.py:56` and `config.py:205`
   - Should extract to shared utility module
   - **Impact:** Maintenance burden, potential divergence

2. **Circular Import Risk**
   - `core.config` imports `oneiric.runtime.health` (line 16)
   - `runtime.health` likely imports from `core.config`
   - **Mitigation:** Currently works due to lazy imports, but fragile

3. **TaskGroup Result Collection Assumes Success**
```python
# runtime.py:66-67
def results(self) -> List[Any]:
    return [task.result() for task in self._tasks if task.done() and not task.cancelled()]
```
**Issue:** Calling `.result()` on failed task raises exception - should catch and return Result type

4. **Config Deep Merge Doesn't Handle Lists**
```python
# config.py:191-202
def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> Dict[str, Any]:
    # Only merges dicts, lists are overwritten entirely
```
**Issue:** Can't append to list configs, only replace

### 7.3 Scalability Concerns

**Identified Bottlenecks:**

1. **In-Memory Registry**
   - All candidates stored in `defaultdict[Tuple[str, str], List[Candidate]]`
   - No persistence layer (resets on restart)
   - **Impact:** At 1000+ candidates, memory usage ~10-50MB (acceptable for now)
   - **Future Risk:** Multi-process deployments have separate registries

2. **Sequential Remote Entry Registration**
```python
# loader.py:161-181
for entry in manifest.entries:
    # Each entry processed serially
    artifact_path = artifact_manager.fetch(...)  # Blocking I/O
    resolver.register(candidate)
```
**Impact:** Manifest with 100 entries takes 100× single-fetch latency
**Fix:** Parallelize with `asyncio.gather()`

3. **Snapshot Persistence on Every State Change**
```python
# lifecycle.py:329, called on every _update_status
self._persist_status_snapshot()
```
**Impact:** High I/O if many swaps per second
**Fix:** Batch writes or use async queue

4. **Config Watcher Polls Entire Config**
```python
# watchers.py:69-88
async def _tick(self) -> None:
    settings = self.settings_loader()  # Reloads entire config
    layer = self.layer_selector(settings)
```
**Impact:** At 5s poll interval with large configs, CPU usage increases
**Fix:** File modification timestamp check before full load

### 7.4 Maintenance Burden Areas

**High Churn Risk:**

1. **CLI Command Proliferation**
   - 15+ commands in single 1000-line file
   - Adding features requires modifying monolithic cli.py
   - **Recommendation:** Split into cli/commands/ package

2. **Bridge Pattern Duplication**
   - `AdapterBridge` (162 lines) vs `DomainBridge` (165 lines) - 90% duplicate code
   - Should have one base class with minimal domain-specific overrides
   - **Impact:** Bug fixes must be applied to both

3. **Pydantic Model Sprawl**
   - 15+ models across config/remote/resolution
   - No shared base class with common validation
   - **Risk:** Inconsistent validation patterns

---

## 8. Critical Issues (Blockers/High-Priority)

### 8.1 Blockers for Production (Must Fix)

#### 1. **SECURITY: Arbitrary Code Execution in Factory Resolution** (CRITICAL)
- **File:** `oneiric/core/lifecycle.py:44-53`
- **Issue:** No validation on `importlib.import_module(module_path)`
- **Attack:** Remote manifest specifies `factory: "os:system"`
- **Fix:**
  ```python
  ALLOWED_MODULE_PREFIXES = ["oneiric.", "myapp."]
  def resolve_factory(factory: str | FactoryCallable) -> FactoryCallable:
      if callable(factory):
          return factory
      module_path, _, attr = factory.partition(":")
      if not any(module_path.startswith(prefix) for prefix in ALLOWED_MODULE_PREFIXES):
          raise SecurityError(f"Factory module '{module_path}' not in allowlist")
      # ... rest of implementation
  ```

#### 2. **SECURITY: Missing Signature Verification** (CRITICAL)
- **Files:** `oneiric/remote/loader.py`, `oneiric/remote/models.py`
- **Issue:** Spec requires signature verification, not implemented
- **Attack:** MITM replaces manifest with malicious version (even with HTTPS compromise)
- **Fix:** Add `signature: str` and `public_key: str` to RemoteManifest, use `cryptography` library to verify

#### 3. **RELIABILITY: Zero Test Coverage** (BLOCKER)
- **Issue:** Cannot verify correctness, refactoring is risky
- **Fix:** Minimum 60% coverage required before production:
  - 20 tests for resolver precedence
  - 15 tests for lifecycle swaps
  - 10 tests for remote loading
  - 10 tests for config watchers

#### 4. **SECURITY: Path Traversal in Cache Dir** (HIGH)
- **File:** `oneiric/remote/loader.py:52-54`
- **Issue:** Unsanitized filenames could escape cache directory
- **Fix:**
  ```python
  filename = sha256 or Path(uri).name
  destination = (self.cache_dir / filename).resolve()
  if not destination.is_relative_to(self.cache_dir.resolve()):
      raise ValueError(f"Path traversal attempt: {filename}")
  ```

#### 5. **RELIABILITY: No Timeout on Remote Fetches** (HIGH)
- **File:** `oneiric/remote/loader.py:73, 234`
- **Issue:** `urllib.request.urlopen()` has no timeout
- **Fix:**
  ```python
  with urllib.request.urlopen(request, context=context, timeout=30.0) as response:
  ```

### 8.2 High Priority (Should Fix Soon)

#### 6. **Race Condition in Candidate Registration** (HIGH)
- **File:** `oneiric/core/resolution.py:118-135`
- **Issue:** No thread safety, concurrent registrations could corrupt registry
- **Fix:** Add `threading.Lock()` or document "single-threaded only"

#### 7. **Memory Leak: Unbounded Instance Cache** (MEDIUM)
- **File:** `oneiric/core/lifecycle.py:113`
- **Issue:** `self._instances` grows indefinitely, old instances never removed except on swap
- **Fix:** Add LRU cache or TTL-based eviction

#### 8. **Secrets Cache Never Invalidated** (MEDIUM)
- **File:** `oneiric/adapters/bridge.py:44, 59`, `oneiric/domains/base.py:44, 62`
- **Issue:** Settings cached in `_settings_cache` forever, no rotation
- **Fix:** Add TTL or invalidate on config reload

#### 9. **Unclear Error Messages** (MEDIUM)
- **File:** `oneiric/core/lifecycle.py:162`
- **Example:** `No candidate registered for adapter:demo`
- **Issue:** Doesn't explain why (no matching provider? wrong domain?)
- **Fix:** Include resolver decision trace in error message

### 8.3 Missing Core Functionality

**From Spec Analysis:**

1. **Entry Point Discovery** (MEDIUM - Phase 4 deferred)
   - Spec mentions pluggy-style discovery
   - `CandidateSource.ENTRY_POINT` exists but unused
   - **Impact:** Can't use Python packaging entry points for plugins

2. **Circuit Breaker for Remote Sync** (MEDIUM - Phase 5 deferred)
   - Spec requires backpressure/circuit breakers
   - Current: Infinite retry in remote loop
   - **Impact:** Cascading failures if remote service degrades

3. **Retry Logic with Exponential Backoff** (LOW - Phase 5 deferred)
   - Remote sync failures log and continue
   - No backoff, retries immediately on next interval
   - **Impact:** Thundering herd on remote service recovery

---

## 9. Overall Assessment

### 9.1 Project Maturity Score: 68/100

**Category Breakdown:**
- Architecture & Design: 85/100 (Strong foundation)
- Code Quality: 75/100 (Good idioms, missing docs)
- Implementation Completeness: 75/100 (Phase 1-4 mostly done)
- Testing: 10/100 (CRITICAL GAP)
- Security: 45/100 (CRITICAL VULNERABILITIES)
- Observability: 80/100 (Well-instrumented)
- Technical Debt: 60/100 (Manageable but growing)

**Grade:** D+ (Alpha Quality - Not Production Ready)

### 9.2 Production Readiness: NOT READY

**Blockers:**
1. Zero test coverage
2. Arbitrary code execution vulnerability
3. Missing signature verification
4. No input validation on remote manifests
5. Thread safety unknown (no tests, no documentation)

**Minimum Requirements for Beta:**
- [ ] 60% test coverage (focus on security and core logic)
- [ ] Factory allowlist implemented
- [ ] Signature verification (or explicitly documented as "trusted network only")
- [ ] Path sanitization in cache operations
- [ ] HTTP timeouts configured
- [ ] Thread safety documented or enforced

**Minimum Requirements for Production:**
- [ ] 80% test coverage
- [ ] Security audit passed
- [ ] Load testing completed (1000+ concurrent swaps)
- [ ] Circuit breaker implemented
- [ ] Retry with backoff implemented
- [ ] Secrets rotation mechanism
- [ ] Deployment documentation
- [ ] Incident response runbook

### 9.3 Top 5 Strengths

1. **Excellent Architecture**: Clean separation, extensible design, spec-aligned
2. **Comprehensive Feature Set**: 5 domains, remote manifests, CLI, observability all working
3. **Modern Python**: Strong type hints, async/await, Python 3.14 idioms
4. **Operational Tooling**: CLI with health checks, diagnostics, status snapshots
5. **Structured Observability**: OpenTelemetry spans, structured logs, metrics

### 9.4 Top 5 Weaknesses

1. **Zero Test Coverage**: Showstopper for production deployment
2. **Critical Security Vulnerabilities**: Arbitrary code execution, path traversal
3. **Missing Signature Verification**: Can't trust remote manifests in hostile networks
4. **Inadequate Input Validation**: Remote manifests trusted too much
5. **Insufficient Documentation**: No docstrings, unclear error messages, missing architecture docs

### 9.5 Recommended Next Steps

**Immediate (Week 1):**
1. **Add factory allowlist** (1 day, HIGH ROI) - Blocks arbitrary code execution
2. **Add HTTP timeouts** (2 hours, HIGH ROI) - Prevents hangs
3. **Fix path traversal** (2 hours, HIGH ROI) - Blocks directory escape
4. **Add thread safety docs** (1 day, MEDIUM ROI) - Clarifies usage constraints

**Short-term (Weeks 2-4):**
5. **Write 50 core tests** (2 weeks, CRITICAL) - Resolver precedence, lifecycle swaps, remote loading
6. **Implement signature verification** (3 days, HIGH) - Or document as roadmap item
7. **Add factory string validation** (1 day, MEDIUM) - Regex for module:attr format
8. **Document all public APIs** (3 days, MEDIUM) - Docstrings with examples

**Medium-term (Months 2-3):**
9. **Refactor bridge duplication** (1 week, MEDIUM) - Consolidate AdapterBridge/DomainBridge
10. **Add circuit breaker** (1 week, MEDIUM) - Protect remote sync
11. **Implement retry with backoff** (2 days, MEDIUM) - Resilient remote fetching
12. **Add entry point discovery** (3 days, LOW) - Complete Phase 4

**Long-term (Post-Beta):**
13. **Performance testing** (2 weeks) - Load test with 1000+ candidates
14. **Secrets rotation** (1 week) - TTL-based invalidation
15. **Monitoring dashboard** (1 week) - Grafana/Prometheus integration
16. **Production deployment guide** (3 days) - Helm charts, Docker, systemd units

---

## 10. Conclusion

Oneiric demonstrates **impressive architectural vision and execution** for a Python 3.14 alpha project. The resolver layer is well-designed, the multi-domain support is comprehensive, and the observability is better than most production systems.

However, the project is **fundamentally blocked from production deployment** due to:
1. **Security vulnerabilities** that allow arbitrary code execution
2. **Complete absence of testing**, making correctness unverifiable
3. **Missing spec-required features** like signature verification

**Verdict:** This is a **solid alpha-stage framework** that needs 4-6 weeks of hardening before beta. The architecture is sound, but the implementation needs security review, comprehensive testing, and production-readiness hardening.

**Recommendation:** Focus on security fixes (factory allowlist, path sanitization, timeouts) and core testing (resolver, lifecycle, remote loading) before adding new features. Once test coverage hits 60% and security gaps are closed, this will be a production-grade universal resolution layer.

---

**Audit Completed By:** Claude Code (Critical Audit Specialist)
**Audit Duration:** 45 minutes
**Files Reviewed:** 30 Python files (3,795 lines)
**Documentation Reviewed:** 11 spec/plan markdown files
**Runtime Tests Performed:** 5 (main.py, CLI commands)
