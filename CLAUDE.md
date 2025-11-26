# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Oneiric is a **universal resolution layer** for pluggable components with hot-swapping, multi-domain support, and remote manifest delivery. It extracts and modernizes the component discovery and lifecycle patterns into a standalone infrastructure layer.

**Status:** Alpha (0.1.0) - Not production ready. See `docs/CRITICAL_AUDIT_REPORT.md` for security issues and `docs/ACB_COMPARISON.md` for comparison with the mature ACB framework.

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
2. **Inferred priority** - From `ONEIRIC_STACK_ORDER` env var or path heuristics
3. **Stack level** - Z-index style layering (candidate metadata `stack_level`)
4. **Registration order** - Last registered wins (tie-breaker)

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

**Important:** This project uses [Crackerjack](../crackerjack) for quality control, following the same patterns as the ACB project.

```bash
# Run full quality suite (formatting, linting, type checking, security)
python -m crackerjack

# Run with tests
python -m crackerjack -t

# Run with specific checks
python -m crackerjack -x  # Format and lint only
python -m crackerjack -c  # Just clean/format

# Full automation (format, lint, test, bump version, commit)
python -m crackerjack -a patch   # Bump patch version
python -m crackerjack -a minor   # Bump minor version
python -m crackerjack -a major   # Bump major version
```

**Note:** Currently, test coverage is critical gap (only 1 test file exists). Security issues documented in `docs/CRITICAL_AUDIT_REPORT.md` must be fixed before production use.

### Testing (Placeholder - Needs Implementation)

```bash
# When tests are written, use:
uv run pytest
uv run pytest tests/core/test_resolution.py -v
uv run pytest --cov=oneiric --cov-report=term
```

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
  - `domain_activity.json` - Pause/drain state
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
            description="Production Redis cache"
        )
    ]
)

# Direct registration (services/tasks/events/workflows)
resolver.register(
    Candidate(
        domain="service",
        key="payment-processor",
        provider="stripe",
        stack_level=5,
        factory=lambda: StripePaymentService()
    )
)
```

### Using Lifecycle Manager

```python
from oneiric.core.lifecycle import LifecycleManager

lifecycle = LifecycleManager(
    resolver,
    status_snapshot_path=".oneiric_cache/lifecycle_status.json"
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
    resolver=resolver,
    lifecycle=lifecycle,
    settings=settings.services
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
    poll_interval=5.0
)

# Watcher monitors config file and triggers swaps automatically
async with watcher:
    await asyncio.sleep(3600)  # Run for 1 hour
```

## Critical Security Issues

**DO NOT USE IN PRODUCTION** until these are fixed (see `docs/CRITICAL_AUDIT_REPORT.md`):

1. **Arbitrary code execution** - `lifecycle.py:resolve_factory()` allows importing any module
2. **Missing signature verification** - Remote manifests only check SHA256, no signatures
3. **Path traversal** - Cache directory operations need path sanitization
4. **No HTTP timeouts** - Remote fetches can hang indefinitely

**Immediate fixes required:**
- Add factory allowlist (whitelist permitted modules/functions)
- Implement manifest signature verification
- Add path sanitization for all cache file operations
- Add configurable HTTP timeouts

## Planning Documents

The `docs/` directory contains comprehensive architecture and planning:

- `NEW_ARCH_SPEC.md` - Complete architecture specification
- `GRAND_IMPLEMENTATION_PLAN.md` - 7-phase implementation plan
- `RESOLUTION_LAYER_SPEC.md` - Detailed resolution layer design
- `PHASES_SUMMARY.md` - Quick reference for phases
- `BUILD_PROGRESS.md` - Current implementation status
- `REBUILD_VS_REFACTOR.md` - Design decision rationale
- `CRITICAL_AUDIT_REPORT.md` - Security audit findings (68/100 score)
- `ACB_COMPARISON.md` - Comparison with mature ACB framework

**Current Phase:** Phase 7 complete (activity state persistence). Security hardening needed before production use.

## Design Principles

1. **Single Responsibility** - Oneiric only does resolution + lifecycle + remote loading
2. **Domain Agnostic** - Same semantics work for any pluggable domain
3. **Explicit Over Implicit** - Stack levels, priorities, and selection are transparent
4. **Explain Everything** - Every resolution has a traceable decision path
5. **Hot-Swap First** - Runtime changes without restarts
6. **Remote Native** - Built for distributed component delivery
7. **Type Safe** - Full Pydantic + type hints throughout
8. **Async First** - All I/O is async, structured concurrency ready

## Observability

### Structured Logging
Uses `structlog` with domain/key/provider context:
```python
logger.info(
    "swap-complete",
    domain="adapter",
    key="cache",
    provider="redis"
)
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
