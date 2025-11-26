# Oneiric Roadmap - Executive Summary

**Version:** 0.1.0 (Alpha) → 1.0.0 (Production)
**Timeline:** 16 weeks
**Current Score:** 68/100 → Target: 92/100

---

## TL;DR: The Critical Path

```
🔴 Weeks 1-2:  Security (Factory allowlist, timeouts, path sanitization)
🟡 Weeks 3-6:  Tests (60 tests minimum, 60% coverage)
🟢 Weeks 7-9:  Documentation (API docs, examples, guides)
🔵 Weeks 10-12: Production Hardening (Circuit breaker, retry, performance)
⚪ Weeks 13-16: Polish & Launch (Entry points, deployment, v1.0.0)
```

---

## The 5 Critical Blockers (Week 1-2)

| # | Issue | File | Fix Time | Blocker For |
|---|-------|------|----------|-------------|
| 1 | **Arbitrary code execution** | `lifecycle.py:44-53` | 4 hours | Production |
| 2 | **No HTTP timeouts** | `loader.py:73` | 2 hours | Availability |
| 3 | **Path traversal** | `loader.py:52-54` | 2 hours | File system |
| 4 | **Missing signature verification** | `loader.py` | 3 days | Remote trust |
| 5 | **Zero test coverage** | `tests/` missing | 2 weeks | Confidence |

**Action:** Fix 1-3 in Day 1, fix 4-5 over Weeks 1-6.

---

## Quality Score Progression

| Milestone | Week | Score | Key Improvements |
|-----------|------|-------|------------------|
| **Current (Alpha)** | 0 | 68/100 | Good architecture, poor testing/security |
| **Beta (v0.5.0)** | 6 | 78/100 | Blockers fixed, 60% coverage |
| **RC (v0.9.0)** | 12 | 85/100 | Circuit breaker, 80% docs, benchmarks |
| **Production (v1.0.0)** | 16 | 92/100 | 80% coverage, load tested, deployed |

---

## What Gets Built When

### Weeks 1-2: Security Hardening
- Day 1: Factory allowlist (4h) + Path sanitization (2h) + HTTP timeouts (2h)
- Days 2-5: Signature verification with `cryptography` library
- Days 6-8: Input validation (domain/key/priority/stack bounds)
- Days 9-10: Security audit, documentation

### Weeks 3-6: Test Coverage
- Week 3: Test infrastructure + 20 core tests (resolver, lifecycle)
- Week 4: 15 security/remote tests (attack vectors, integrity)
- Week 5: 15 integration tests (watchers, bridges, config)
- Week 6: 10 CLI/concurrency tests

**Goal:** 60 tests, 60%+ coverage, CI/CD pipeline

### Weeks 7-9: Documentation
- Week 7: Docstrings (80% coverage) + architecture docs
- Week 8: 10 example projects (basic → advanced)
- Week 9: API stability review, deprecation policy, type stubs

### Weeks 10-12: Production Hardening
- Week 10: Circuit breaker + exponential backoff with jitter
- Week 11: Performance profiling, optimization, benchmarking
- Week 12: Metrics expansion, structured logging, monitoring guide

### Weeks 13-16: Final Polish
- Week 13: Entry point discovery, capability negotiation
- Week 14: Docker/K8s, CI/CD, deployment docs
- Week 15: Community (CONTRIBUTING.md, 3 reference plugins)
- Week 16: Security audit, load testing, v1.0.0 release

---

## The Test Coverage Plan (60 Tests Minimum)

| Category | Tests | Files |
|----------|-------|-------|
| **Resolver Precedence** | 10 | `tests/core/test_resolution.py` |
| **Lifecycle Swaps** | 10 | `tests/core/test_lifecycle.py` |
| **Security** | 8 | `tests/security/test_factory_validation.py` |
| **Remote Loading** | 7 | `tests/remote/test_loader.py` |
| **Config Watchers** | 8 | `tests/runtime/test_watchers.py` |
| **Domain Bridges** | 7 | `tests/domains/test_bridges.py` |
| **CLI Commands** | 5 | `tests/test_cli.py` |
| **Concurrency** | 5 | `tests/core/test_concurrency.py` |
| **Total** | **60** | **8 test modules** |

**Coverage Target:** 60% minimum, 70% goal, 80% for v1.0.0

---

## Technical Debt to Pay Down

### High Priority (Weeks 7-9)
1. **Consolidate Bridge Duplication** - `AdapterBridge` vs `DomainBridge` share 90% code
2. **Split CLI Monolith** - 1000-line `cli.py` needs modularization
3. **Extract Shared Utilities** - Duplicate `_maybe_await()` in 2 files
4. **Protocol-Based Interfaces** - Replace concrete class coupling with protocols

### Medium Priority (Weeks 10-12)
5. **Race Condition in Registry** - Add `threading.Lock()` or document single-threaded
6. **Unbounded Instance Cache** - Implement LRU eviction
7. **Secrets Cache Invalidation** - Add TTL or config reload hook
8. **Sequential Remote Registration** - Parallelize with `asyncio.gather()`

---

## What Makes v1.0.0 "Production Ready"

✅ **Security Checklist:**
- Factory allowlist enforced (arbitrary code execution blocked)
- Signature verification implemented (remote manifests trusted)
- Path traversal sanitized (file system protected)
- HTTP timeouts configured (availability protected)
- Input validation comprehensive (bounds checked)

✅ **Testing Checklist:**
- 80% code coverage (comprehensive verification)
- 60+ tests across core, security, integration
- CI/CD with automated testing on 3.13 and 3.14
- Load testing completed (1000+ candidates, 1000 swaps/sec)
- Memory leak testing (24-hour soak test)

✅ **Documentation Checklist:**
- 80% docstring coverage (API documented)
- Architecture diagrams (data flow, component interaction)
- 10 example projects (basic → advanced)
- Deployment guides (Docker, K8s, systemd)
- Migration guide from ACB

✅ **Production Hardening Checklist:**
- Circuit breaker protecting remote sync
- Exponential backoff with jitter
- Performance benchmarks established
- Monitoring integration (Prometheus, Grafana)
- Deployment infrastructure (Docker, K8s, CI/CD)

---

## Effort by Category

| Category | Weeks | % of Total | Priority |
|----------|-------|------------|----------|
| Security Hardening | 2 | 12.5% | 🔴 Critical |
| Test Coverage | 4 | 25% | 🔴 Critical |
| Documentation | 3 | 18.75% | 🟡 High |
| Production Hardening | 3 | 18.75% | 🟡 High |
| Final Polish | 4 | 25% | 🟢 Medium |
| **Total** | **16** | **100%** | - |

---

## Risk Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Security vuln post-release** | HIGH | Comprehensive audit Week 16, bug bounty |
| **Performance at scale** | HIGH | Load testing Week 15, benchmarks Week 11 |
| **API instability** | HIGH | API review Week 9, SemVer commitment |
| **Test coverage missed** | MEDIUM | Daily tracking, block merge if drops |
| **Timeline slippage** | MEDIUM | 2-week buffer, prioritize P0 items |

---

## Resource Allocation

**Solo Developer:**
- 16 weeks full-time (realistic alpha → production)
- Focus: P0 items first, defer P2 if constrained

**Small Team (2-3 developers):**
- 8-10 weeks with parallel workstreams
  - Dev 1: Security + core testing
  - Dev 2: Documentation + examples
  - Dev 3: Production hardening + deployment

**Large Team (4+ developers):**
- 6-8 weeks with specialized roles
  - Security Engineer
  - Backend Engineer
  - DevOps Engineer
  - Technical Writer

---

## Comparison with ACB (Post-Roadmap)

### Oneiric Advantages
1. 4-tier precedence (vs ACB's 2-tier)
2. First-class hot-swapping (vs manual reload)
3. Explain API (vs implicit resolution)
4. CLI diagnostics (vs none)
5. Remote-native design

### ACB Still Better
1. Production maturity (31 releases vs greenfield)
2. Adapter ecosystem (60+ vs 3 reference plugins)
3. Full platform (implementations vs bridges)
4. Established community
5. FastBlocks + MCP integration

### Convergence Path
- **Option 1:** Oneiric as ACB v2.0 foundation (12-18 months post-1.0)
- **Option 2:** Parallel evolution with idea cross-pollination (immediate)
- **Recommendation:** Option 2 initially, reassess after 6-12 months production

---

## Next Actions (Week 1, Day 1)

### Morning (4 hours)
1. **Factory Allowlist** (`lifecycle.py:44-53`)
   ```python
   ALLOWED_MODULE_PREFIXES = ["oneiric.", "myapp.", "builtins."]
   # Raise SecurityError if module_path not in allowlist
   ```

2. **Path Sanitization** (`loader.py:52-54`)
   ```python
   destination = (self.cache_dir / filename).resolve()
   if not destination.is_relative_to(self.cache_dir.resolve()):
       raise ValueError(f"Path traversal blocked: {filename}")
   ```

3. **HTTP Timeouts** (`loader.py:73, 234`)
   ```python
   timeout = self.settings.http_timeout or 30.0
   with urllib.request.urlopen(request, context=context, timeout=timeout):
   ```

### Afternoon (4 hours)
4. **Add Security Tests**
   - Create `tests/security/test_factory_validation.py`
   - Test malicious factory blocked: `"os:system"` raises `SecurityError`
   - Test path traversal blocked: `"../../etc/passwd"` raises `ValueError`
   - Test timeout works: Mock slow server, verify timeout

5. **Run Security Scanners**
   ```bash
   uv add --dev bandit safety
   uv run bandit -r oneiric/
   uv run safety check
   ```

### End of Day
- ✅ Critical security holes patched
- ✅ Basic security tests passing
- ✅ Confidence to start test coverage sprint

---

## Success Metrics

| Metric | Current | Beta (Week 6) | RC (Week 12) | v1.0 (Week 16) |
|--------|---------|---------------|--------------|----------------|
| **Overall Score** | 68/100 | 78/100 | 85/100 | 92/100 |
| **Security Score** | 45/100 | 80/100 | 90/100 | 95/100 |
| **Test Coverage** | 0% | 60% | 70% | 80% |
| **Docstring Coverage** | 15% | 50% | 80% | 90% |
| **Performance** | Unknown | Baseline | Optimized | Load tested |

---

## Conclusion

Oneiric has **world-class architecture** but **alpha implementation**. The path to production:

1. **Secure the foundation** (Weeks 1-2)
2. **Verify with tests** (Weeks 3-6)
3. **Document for users** (Weeks 7-9)
4. **Harden for production** (Weeks 10-12)
5. **Launch with confidence** (Weeks 13-16)

**Key Philosophy:** Resist feature creep. **Every line is a liability** until tested and hardened.

**Timeline:** 16 weeks to production-ready v1.0.0 matching ACB's 92/100 quality score.

**Next Step:** Start Day 1 with factory allowlist, path sanitization, and HTTP timeouts (8 hours of work, infinite security ROI).

---

**For Full Details:** See `docs/UNIFIED_ROADMAP.md`
**For Current Issues:** See `docs/CRITICAL_AUDIT_REPORT.md`
**For Architecture:** See `docs/NEW_ARCH_SPEC.md`
