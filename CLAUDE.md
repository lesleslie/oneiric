# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Oneiric is a **universal resolution layer** for pluggable components with hot-swapping, multi-domain support, and remote manifest delivery. It extracts and modernizes the component discovery and lifecycle patterns into a standalone infrastructure layer.

**Status:** Production Ready (0.2.0) - Hardened for controlled deployment. See `docs/implementation/STAGE5_FINAL_AUDIT_REPORT.md` for comprehensive audit (score: 95/100, 526 tests, 83% coverage) and `docs/ONEIRIC_VS_ACB.md` for comparison with ACB and migration strategy.

**Python Version:** 3.14+ (async-first, modern type hints)

## Architecture

### Core Philosophy

Oneiric provides **resolver + lifecycle + remote loading** as infrastructure, not as an application framework. It's domain-agnostic: the same resolution semantics work for adapters, services, tasks, events, workflows, or any custom domain.

### Key Components

```
oneiric/
├── core/
│   ├── resolution.py      # Candidate registry, 4-tier precedence, explain API
│   ├── lifecycle.py       # Hot-swap with health checks, rollback, cleanup
│   ├── config.py          # Pydantic settings with secrets hook
│   ├── logging.py         # Structured logging (structlog)
│   ├── observability.py   # OpenTelemetry integration
│   └── runtime.py         # Async runtime helpers (TaskGroup)
├── adapters/              # Adapter domain bridge
│   ├── metadata.py        # Adapter registration helpers
│   ├── bridge.py          # AdapterBridge for lifecycle activation
│   └── watcher.py         # Config file watcher for hot-swapping
├── domains/               # Generic domain bridges
│   ├── base.py            # DomainBridge base class
│   ├── services.py        # ServiceBridge
│   ├── tasks.py           # TaskBridge
│   ├── events.py          # EventBridge
│   └── workflows.py       # WorkflowBridge
├── remote/                # Remote manifest pipeline
│   ├── models.py          # Manifest models (Pydantic)
│   ├── loader.py          # Remote sync with cache/digest verification
│   ├── samples.py         # Demo remote providers
│   ├── metrics.py         # Remote sync metrics
│   └── telemetry.py       # Remote sync telemetry
├── runtime/               # Runtime orchestration
│   ├── orchestrator.py    # RuntimeOrchestrator (watchers + remote loop)
│   ├── watchers.py        # Domain selection watchers
│   ├── activity.py        # Pause/drain state persistence
│   └── health.py          # Runtime health snapshots
└── cli.py                 # Typer-based CLI (11 commands)
```

### Resolution Precedence (4-tier)

Components are resolved with this priority order (highest wins):

1. **Explicit override** - `selections` in config (`adapters.yml`, `services.yml`, etc.)
1. **Inferred priority** - From `ONEIRIC_STACK_ORDER` env var or path heuristics
1. **Stack level** - Z-index style layering (candidate metadata `stack_level`)
1. **Registration order** - Last registered wins (tie-breaker)

### Lifecycle Flow

```
resolve → instantiate → health_check → pre_swap_hook →
bind_instance → cleanup_old → post_swap_hook
```

Rollback occurs if instantiation or health check fails (unless `force=True`).

### Domain Bridges

All domains (adapters, services, tasks, events, workflows) use the same `DomainBridge` pattern:

- Registry-backed resolution via `Resolver`
- Lifecycle activation via `LifecycleManager`
- Config watchers trigger automatic swaps
- Pause/drain state management
- Health probes and status snapshots

## Development Commands

### Running the Application

```bash
# Quick demo (uses main.py)
uv run python main.py

# CLI commands (with demo providers)
uv run python -m oneiric.cli --demo list --domain adapter
uv run python -m oneiric.cli --demo explain status --domain service
uv run python -m oneiric.cli --demo status --domain service --key status
uv run python -m oneiric.cli --demo health --probe

# Remote manifest sync
uv run python -m oneiric.cli remote-sync --manifest docs/sample_remote_manifest.yaml
uv run python -m oneiric.cli remote-sync --manifest docs/sample_remote_manifest.yaml --watch --refresh-interval 60
uv run python -m oneiric.cli remote-status

# Runtime orchestrator (long-running)
uv run python -m oneiric.cli orchestrate --manifest docs/sample_remote_manifest.yaml --refresh-interval 120

# Domain activity controls
uv run python -m oneiric.cli pause --domain service status --note "maintenance window"
uv run python -m oneiric.cli drain --domain service status --note "draining queue"
uv run python -m oneiric.cli pause --resume --domain service status
```

### Shell Completions

```bash
# Install Typer shell completions (one-time setup)
uv run python -m oneiric.cli --install-completion
```

### Quality Control with Crackerjack

**Philosophy:** This project uses [Crackerjack](./.crackerjack) as the single source of truth for all quality control. Crackerjack orchestrates formatters, linters, type checkers, security analysis, and complexity checking through a unified interface. **Use crackerjack directly** - no custom CI scripts or separate quality pipelines needed.

```bash
# Quality checks only (fast feedback: ~8 minutes)
python -m crackerjack run

# Quality checks + test suite (full validation: ~16 minutes)
python -m crackerjack run -t

# Quick format and lint (fastest)
python -m crackerjack run -x

# Full automation with version bump and commit
python -m crackerjack run -a patch   # Bump patch version
python -m crackerjack run -a minor   # Bump minor version
python -m crackerjack run -a major   # Bump major version
```

**What Crackerjack Runs:**

**Fast Hooks (15):**

- Formatters: ruff-format, mdformat, trailing-whitespace, end-of-file-fixer, format-json
- Linters: ruff-check, check-toml, check-yaml, check-json, check-ast
- Validation: validate-regex-patterns, uv-lock, check-added-large-files, check-local-links, codespell

**Comprehensive Hooks (11):**

- Type checking: zuban (mypy wrapper, configured in `mypy.ini`)
- Security: gitleaks, semgrep, pip-audit, pyscn
- Complexity: complexipy (max complexity: 15)
- Dead code: skylos (excludes `adapters/` directory - focuses on core framework logic)
- Modernization: refurb
- Dependencies: creosote (excludes optional adapter dependencies)
- Validation: check-jsonschema, linkcheckmd

**Type Checking Configuration:**

This project uses **Zuban** (via Crackerjack) for ultra-fast type checking. Due to a known Zuban parsing bug with `[tool.mypy]` in `pyproject.toml`, type checking configuration is in `mypy.ini` instead:

- **Configuration file**: `mypy.ini` (not `pyproject.toml`)
- **Python version**: 3.14
- **Excluded directories**: `.venv`, `build`, `dist`, `tests`, `scripts/`
- **Module-level suppressions**: See `mypy.ini` for per-module `ignore_errors` settings

**Important**: Do NOT add `[tool.zuban]` or `[tool.mypy]` to `pyproject.toml` - this will cause parsing errors. All type checking config must be in `mypy.ini`.

**Note:** Comprehensive test suite with 526 passing tests and 83% coverage. Security hardening complete (all P0 vulnerabilities resolved). See `docs/implementation/STAGE5_FINAL_AUDIT_REPORT.md` for detailed quality assessment.

### Testing

**Test Suite Overview:**

- **Total:** 716 tests across 94 test files in 10 categories
- **Coverage:** 83% (target: 60%, achieved: 138% of target)
- **Test Categories:** Core (68), Adapters (60), Domains (44), Security (100), Remote/Runtime/CLI (117), Integration (39), E2E (8)
- **Timeout:** 600s (10 minutes) configured in `[tool.crackerjack]`

**Quick Start with Makefile:**

```bash
# Show all available test targets
make help

# Quick test patterns
make test              # Run all tests (default)
make test-fast         # Run only fast tests (<1s per test)
make test-not-slow     # Run all except slow tests (good for CI)
make test-unit         # Run only unit tests (isolated, no I/O)
make test-integration  # Run integration and e2e tests
make test-security     # Run security-related tests
make test-analyze      # Run tests and analyze timing distribution
```

**Direct pytest Commands:**

```bash
# Run all tests
uv run pytest

# Run with coverage report
uv run pytest --cov=oneiric --cov-report=term

# Run specific test module
uv run pytest tests/core/test_resolution.py -v

# Run tests by marker
uv run pytest -m "fast" -v              # Only fast tests
uv run pytest -m "not slow" -v          # Skip slow tests
uv run pytest -m "security" -v          # Security tests only
uv run pytest -m "integration or e2e"   # Integration and e2e tests

# Parallel execution
uv run pytest -n auto -v                # Auto-detect workers

# Timing analysis
uv run pytest --durations=20            # Show 20 slowest tests
```

**Test Markers:**

Tests can be marked with the following markers to enable selective execution:

- `@pytest.mark.fast` - Fast tests (\<1s per test)
- `@pytest.mark.slow` - Slow tests (>5s per test)
- `@pytest.mark.unit` - Unit tests (isolated, no I/O)
- `@pytest.mark.integration` - Integration tests
- `@pytest.mark.e2e` - End-to-end tests (full system)
- `@pytest.mark.security` - Security-related tests
- `@pytest.mark.adapter` - Adapter-specific tests
- `@pytest.mark.remote` - Remote manifest tests
- `@pytest.mark.runtime` - Runtime orchestration tests

**Test Execution Strategies:**

1. **Fast CI Pipeline** (< 2 minutes):

   ```bash
   make test-not-slow    # Skip slow tests
   ```

1. **Full Test Suite** (10 minutes):

   ```bash
   make test             # Run all 716 tests
   ```

1. **Development Workflow** (iterative):

   ```bash
   # Quick feedback loop
   make test-fast        # Fast tests only

   # Module-specific testing
   uv run pytest tests/core/ -v

   # Full validation before commit
   python -m crackerjack -t
   ```

1. **Performance Analysis**:

   ```bash
   make test-analyze     # Run tests and analyze timing distribution
   ```

**CI/CD Recommendations:**

- **Pull Request Checks:** `make test-not-slow` (fast feedback)
- **Pre-merge Validation:** `python -m crackerjack -t` (full quality suite)
- **Nightly Builds:** `make test-all` (comprehensive with timing)
- **Release Validation:** `make test-coverage` (with HTML report)

## Configuration

### Settings Structure

```
settings/
├── app.yml         # Application metadata (not required)
├── adapters.yml    # Adapter selections: {category: provider}
├── services.yml    # Service selections: {service_id: provider}
├── tasks.yml       # Task selections: {task_type: provider}
├── events.yml      # Event selections: {event_name: provider}
└── workflows.yml   # Workflow selections: {workflow_id: provider}
```

### Environment Variables

- `ONEIRIC_CONFIG` - Path to config directory
- `ONEIRIC_STACK_ORDER` - Stack priority override (e.g., `sites,splashstand,fastblocks,oneiric`)
  - Format: `name1:priority1,name2:priority2` or `name1,name2` (auto-assigns 0, 10, 20...)

### Cache Directory

- Default: `.oneiric_cache/`
- Contains:
  - `lifecycle_status.json` - Per-domain lifecycle state
  - `runtime_health.json` - Orchestrator health snapshot
  - `domain_activity.sqlite` - Pause/drain state
  - `remote_status.json` - Remote sync telemetry

## Implementation Patterns

### Registering Components

```python
from oneiric.adapters import AdapterMetadata, register_adapter_metadata
from oneiric.core.resolution import Resolver, Candidate

resolver = Resolver()

# Via metadata helper (adapters)
register_adapter_metadata(
    resolver,
    package_name="myapp",
    package_path=__file__,
    adapters=[
        AdapterMetadata(
            category="cache",
            provider="redis",
            stack_level=10,
            factory=lambda: RedisCache(),
            description="Production Redis cache",
        )
    ],
)

# Direct registration (services/tasks/events/workflows)
resolver.register(
    Candidate(
        domain="service",
        key="payment-processor",
        provider="stripe",
        stack_level=5,
        factory=lambda: StripePaymentService(),
    )
)
```

### Using Lifecycle Manager

```python
from oneiric.core.lifecycle import LifecycleManager

lifecycle = LifecycleManager(
    resolver, status_snapshot_path=".oneiric_cache/lifecycle_status.json"
)

# Activate component
instance = await lifecycle.activate("adapter", "cache")

# Hot-swap to different provider
instance = await lifecycle.swap("adapter", "cache", provider="memcached")

# Check health of active instance
is_healthy = await lifecycle.probe_instance_health("adapter", "cache")

# Get lifecycle status
status = lifecycle.get_status("adapter", "cache")
print(status.state)  # "ready", "failed", "activating"
```

### Domain Bridges

```python
from oneiric.domains import ServiceBridge

service_bridge = ServiceBridge(
    resolver=resolver, lifecycle=lifecycle, settings=settings.services
)

# Activate service
handle = await service_bridge.use("payment-processor")
result = await handle.instance.process_payment(amount=100)
```

### Config Watchers (Hot-Swapping)

```python
from oneiric.runtime.watchers import SelectionWatcher

watcher = SelectionWatcher(
    domain="adapter",
    config_path="settings/adapters.yml",
    bridge=adapter_bridge,
    poll_interval=5.0,
)

# Watcher monitors config file and triggers swaps automatically
async with watcher:
    await asyncio.sleep(3600)  # Run for 1 hour
```

## Security Hardening ✅ COMPLETE

**All P0 security vulnerabilities have been resolved** (see `docs/implementation/STAGE5_FINAL_AUDIT_REPORT.md`):

1. ✅ **Arbitrary code execution** - **RESOLVED**

   - Factory allowlist implemented in `core/security.py`
   - Module import restrictions enforced

1. ✅ **Missing signature verification** - **RESOLVED**

   - ED25519 signature verification in `remote/security.py`
   - Configurable trusted public keys

1. ✅ **Path traversal** - **RESOLVED**

   - Path sanitization function in `remote/security.py`
   - Cache directory boundary enforcement

1. ✅ **No HTTP timeouts** - **RESOLVED**

   - Configurable timeouts in `remote/loader.py` (default: 30s)
   - Circuit breaker + retry logic in `core/resiliency.py`

1. ✅ **Thread safety** - **RESOLVED**

   - RLock added to resolver registry
   - Concurrent registration tests passing

**Security Test Coverage:** 100 security tests (99 passing, 1 edge case)

## Documentation

The `docs/` directory contains comprehensive documentation organized by purpose:

**Essential Reference (Start Here):**

- **`ONEIRIC_VS_ACB.md`** - Complete comparison, migration guide, hybrid strategy ⭐
- **`UNCOMPLETED_TASKS.md`** - Future enhancements, known issues (zero blockers)
- **`implementation/STAGE5_FINAL_AUDIT_REPORT.md`** - Production readiness audit (95/100 score) ⭐
- `NEW_ARCH_SPEC.md` - Complete architecture specification
- `RESOLUTION_LAYER_SPEC.md` - Detailed resolution layer design

**Implementation & Status:**

- `STRATEGIC_ROADMAP.md` - Current priorities + execution tracks
- `implementation/SERVERLESS_AND_PARITY_EXECUTION_PLAN.md` - Serverless + parity workstreams
- `implementation/ADAPTER_REMEDIATION_PLAN.md` & `implementation/ADAPTER_REMEDIATION_EXECUTION.md` - Adapter backlog + evidence
- `archive/implementation/BUILD_PROGRESS.md` - Historical phase log (read-only)

**Analysis & Quality:**

- `analysis/QUALITY_AUDITS.md` - Quality audit summary (replaces older audit reports)
- `analysis/ACB_ADAPTER_ACTION_IMPLEMENTATION.md` - Adapter porting guide
- `analysis/` - Adapter strategies and technical deep-dives

**Operational Documentation:**

- `deployment/` - Docker, Kubernetes, systemd guides (2,514 lines)
- `monitoring/` - Prometheus, Grafana, Loki, AlertManager (3,336 lines)
- `runbooks/` - Incident response, maintenance, troubleshooting (3,232 lines)

**Archive:**

- `archive/` - Historical comparison docs (superseded by ONEIRIC_VS_ACB.md)

**Complete Index:** See `docs/README.md` for full documentation structure.

**Current Status:** Phase 7 complete, Stage 5 hardening complete. **Production ready for controlled deployment.**

## Design Principles

1. **Single Responsibility** - Oneiric only does resolution + lifecycle + remote loading
1. **Domain Agnostic** - Same semantics work for any pluggable domain
1. **Explicit Over Implicit** - Stack levels, priorities, and selection are transparent
1. **Explain Everything** - Every resolution has a traceable decision path
1. **Hot-Swap First** - Runtime changes without restarts
1. **Remote Native** - Built for distributed component delivery
1. **Type Safe** - Full Pydantic + type hints throughout
1. **Async First** - All I/O is async, structured concurrency ready

## Observability

### Structured Logging

Uses `structlog` with domain/key/provider context:

```python
logger.info("swap-complete", domain="adapter", key="cache", provider="redis")
```

### OpenTelemetry

Automatic spans for:

- `resolver.resolve` - Component resolution
- `lifecycle.swap` - Hot-swap operations
- `remote.sync` - Remote manifest fetches

### CLI Diagnostics

```bash
# Show active vs shadowed components
uv run python -m oneiric.cli --demo list --domain adapter

# Explain why a component was chosen
uv run python -m oneiric.cli --demo explain status --domain service

# Show lifecycle state
uv run python -m oneiric.cli --demo status --domain service --key status --json

# Check runtime health
uv run python -m oneiric.cli --demo health --probe --json

# View activity (paused/draining)
uv run python -m oneiric.cli activity --json
```

## Future Enhancements (from docs)

- Plugin protocol with entry points
- Capability negotiation (select by features + priority)
- Middleware/pipeline adapters
- Structured concurrency helpers (nursery patterns)
- Durable execution hooks for workflows
- Rate limiting & circuit breaker mixins
- State machine DSL for workflows

## Relationship to ACB

Oneiric extracts ACB's adapter resolution pattern into a universal layer. See `docs/ACB_COMPARISON.md` for detailed comparison:

- **ACB:** Production-ready full platform (v0.31.10, 92/100 score)
- **Oneiric:** Alpha resolution layer (v0.1.0, 68/100 score)

Oneiric is **not competing** with ACB—it's formalizing one of ACB's core patterns for potential future adoption once production-hardened.
