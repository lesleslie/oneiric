# Oneiric

![Coverage](https://img.shields.io/badge/coverage-75.5%25-yellow)
**Explainable component resolution with hot-swapping for Python 3.14+**

> **Status:** Production Ready (v0.2.0) | [Audit Report](docs/STAGE5_FINAL_AUDIT_REPORT.md): 95/100, 526 tests, 83% coverage

Oneiric is a next-generation platform for building production-ready Python applications with **pluggable components**, **deterministic selection**, and **runtime flexibility**. It extracts and modernizes the component resolution patterns from [ACB](https://github.com/lesleslie/acb) into a universal infrastructure layer.

## What is Oneiric?

Oneiric provides **resolver + lifecycle + remote loading** as infrastructure for:

- **30+ Adapter implementations** (databases, caching, queues, storage, auth, secrets, monitoring, AI/LLM)
- **14+ Action kits** (workflows, tasks, events, compression, security, data transformation)
- **5 domain bridges** (adapters, services, tasks, events, workflows)
- **Hot-swapping** components without restarting your application
- **Explainable decisions** - trace why each component was selected
- **Remote manifests** - deliver components via CDN with cryptographic verification

______________________________________________________________________

## Why Oneiric?

### The Problem with Traditional DI

Most dependency injection frameworks:

- ❌ Can't explain WHY a component was selected
- ❌ Require restarts to swap implementations
- ❌ Hide component selection in opaque wiring
- ❌ Don't support multi-tenant component selection
- ❌ Lack structured lifecycle management

### The Oneiric Solution

```python
# Resolve with explainability
cache = await resolver.resolve("adapter", "cache")
explanation = resolver.explain("adapter", "cache")
print(explanation.why)
# Output: "RedisCache selected: priority=10, stack_level=5,
#          shadowing MemcachedCache (priority=5)"

# Hot-swap without restart
await lifecycle.swap("adapter", "cache", provider="memcached")
# Switched from Redis to Memcached, health checked, old instance cleaned up

# Multi-domain resolution
database = await resolver.resolve("adapter", "database")
task_scheduler = await resolver.resolve("action", "task.schedule")
workflow_runner = await resolver.resolve("action", "workflow.orchestrate")
```

______________________________________________________________________

## Quick Start

```bash
# Install
uv add oneiric

# Run demo
uv run python main.py

# Or use the CLI
uv run python -m oneiric.cli --demo list --domain adapter
uv run python -m oneiric.cli --demo explain status --domain service
```

______________________________________________________________________

## Architecture

Oneiric follows a **layered architecture** with deterministic component resolution:

```
┌─────────────────────────────────────────────┐
│         APPLICATION LAYER                   │
│      (Your Code / Other Frameworks)         │
└─────────────────────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────┐
│      ONEIRIC RESOLUTION LAYER               │
│  ┌─────────┐  ┌──────────┐  ┌───────────┐  │
│  │Resolver │  │Lifecycle │  │  Remote   │  │
│  │Registry │  │ Manager  │  │Manifests  │  │
│  └─────────┘  └──────────┘  └───────────┘  │
└─────────────────────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────┐
│        PLUGGABLE DOMAINS                    │
│  Adapters • Services • Tasks • Events •     │
│  Workflows • Actions • Your Custom Domains  │
└─────────────────────────────────────────────┘
```

### Resolution Precedence (4-tier)

Components are resolved with this priority order (highest wins):

1. **Explicit override** - `selections` in config (`adapters.yml`)
1. **Inferred priority** - From `ONEIRIC_STACK_ORDER` env var or path heuristics
1. **Stack level** - Z-index style layering (candidate metadata `stack_level`)
1. **Registration order** - Last registered wins (tie-breaker)

### Lifecycle Flow

```
resolve → instantiate → health_check → pre_swap_hook →
bind_instance → cleanup_old → post_swap_hook
```

Rollback occurs if instantiation or health check fails (unless `force=True`).

______________________________________________________________________

## Built-in Components

### 30+ Adapters (Stage 2 Complete)

| Category | Providers | Status |
|----------|-----------|--------|
| **Cache** | Redis, Memory | ✅ Complete |
| **Queue/Pub-Sub** | Redis Streams, NATS | ✅ Complete |
| **HTTP** | httpx, aiohttp | ✅ Complete |
| **Storage** | S3, GCS, Azure Blob, Local | ✅ Complete |
| **Database** | PostgreSQL, MySQL, SQLite, DuckDB | ✅ Complete |
| **Secrets** | Env, File, Infisical, GCP Secret Manager, AWS Secrets Manager | ✅ Complete |
| **Auth/Identity** | Auth0, Cloudflare | ✅ Complete |
| **Monitoring** | Logfire, Sentry, OTLP | ✅ Complete |
| **AI/LLM** | Anthropic, OpenAI, Ollama | ✅ Complete |
| **Embedding** | OpenAI, Sentence Transformers, ONNX | ✅ Complete |
| **Vector** | Pinecone, Qdrant | ✅ Complete |
| **NoSQL** | MongoDB, Firestore | ✅ In Progress |

### 14+ Action Kits (Stage 3 Complete)

| Domain | Action Kits | Capabilities |
|--------|-------------|--------------|
| **Workflow** | `workflow.audit`, `workflow.notify`, `workflow.retry`, `workflow.orchestrate` | Audit logging, notifications, retry policies, multi-step orchestration |
| **Task** | `task.schedule` | Cron/interval scheduling, queue metadata, preview runs |
| **Event** | `event.dispatch` | Structured events, webhook delivery, concurrent invocations |
| **Automation** | `automation.trigger` | Declarative rule engine, downstream action routing |
| **Compression** | `compression.encode`, `compression.hash` | Brotli/gzip compression, Blake3/SHA hashing |
| **Serialization** | `serialization.encode` | JSON/YAML/Pickle helpers |
| **HTTP** | `http.fetch` | httpx-backed requests, retry logic, timeout controls |
| **Security** | `security.signature`, `security.secure` | HMAC signing, token generation, password hashing |
| **Data** | `data.transform`, `data.sanitize` | Field selection/renaming, masking/scrubbing |
| **Validation** | `validation.schema` | Field-type enforcement, Pydantic integration |
| **Debug** | `debug.console` | Structured logging, echo helpers, secret scrubbing |

______________________________________________________________________

## Key Features

### 1. Explainable Component Selection

Every resolution decision is traceable:

```bash
$ uv run python -m oneiric.cli --demo explain status --domain adapter

Resolver Decision for adapter:cache
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Provider: redis
Reasons:
  • priority=10 (explicitly configured)
  • stack_level=5 (production tier)
  • registration_order=2

Shadowed Candidates:
  • memcached (priority=5, stack_level=3)
  • memory (priority=0, stack_level=1)
```

### 2. Hot-Swapping Without Restart

Change components at runtime with health checks and rollback:

```python
from oneiric.core.lifecycle import LifecycleManager

lifecycle = LifecycleManager(resolver)

# Swap cache implementation
await lifecycle.swap("adapter", "cache", provider="memcached")
# Old Redis instance cleaned up, new Memcached instance health-checked

# Rollback on failure
await lifecycle.swap("adapter", "cache", provider="broken")
# Health check fails, automatically rolls back to previous working instance
```

### 3. Remote Manifest Delivery

Deliver components via CDN with cryptographic verification:

```bash
$ uv run python -m oneiric.cli remote-sync \
    --manifest https://cdn.example.com/manifests/v1.yaml \
    --watch --refresh-interval 300

Remote Manifest Sync
━━━━━━━━━━━━━━━━━━━━
✓ Fetched manifest (SHA256: abc123...)
✓ Signature verified (ED25519)
✓ Registered 15 adapters, 8 actions
✓ Cache: 5 entries
✓ Watching for updates every 300s
```

### 4. Comprehensive Observability

- **Structured logging** (structlog + Logly)
- **OpenTelemetry integration** (traces + metrics)
- **Health probes** (per-component health checks)
- **Lifecycle snapshots** (persisted state for debugging)
- **Activity controls** (pause/drain for maintenance)

### 5. Multi-Domain Support

Same resolution semantics for all domains:

```python
# Adapters (infrastructure)
cache = await resolver.resolve("adapter", "cache")
database = await resolver.resolve("adapter", "database")

# Services (business logic)
payment_service = await resolver.resolve("service", "payment-processor")

# Tasks (background jobs)
task_scheduler = await resolver.resolve("action", "task.schedule")

# Events (pub/sub)
event_dispatcher = await resolver.resolve("action", "event.dispatch")

# Workflows (orchestration)
workflow_runner = await resolver.resolve("action", "workflow.orchestrate")
```

______________________________________________________________________

## Relationship to ACB

Oneiric is the **next-generation successor** to [ACB](https://github.com/lesleslie/acb) (Asynchronous Component Base):

| Aspect | ACB | Oneiric |
|--------|-----|---------|
| **Philosophy** | Batteries-included platform | Universal resolution layer |
| **DI Approach** | Bevy-based container | Deterministic registry |
| **Explainability** | Opaque (last registration wins) | Full trace (4-tier precedence) |
| **Hot-Swapping** | Limited (manual re-registration) | Built-in (lifecycle-managed) |
| **Remote Loading** | Not supported | Core feature |
| **Maturity** | v0.31.10 (Production) | v0.2.0 (Production-ready) |

### Migration Path

Oneiric is designed to **replace ACB's adapter and action functionality** with better architecture:

- **ACB → Oneiric migration** planned for: `crackerjack`, `fastblocks`, `session-mgmt-mcp`
- **Stage 2** (Adapters): ✅ Complete
- **Stage 3** (Actions): ✅ Complete
- **Stage 4** (Remote Packaging): ✅ Complete
- **Stage 5** (Hardening): 🔄 In Progress

See \[[ACB_ADAPTER_ACTION_IMPLEMENTATION|ACB_ADAPTER_ACTION_IMPLEMENTATION.md]\] for full migration plan.

______________________________________________________________________

## Why Registry Over Dependency Injection?

From \[[ACB_ADAPTER_ACTION_IMPLEMENTATION#why-no-dependency-injection-container|ACB_ADAPTER_ACTION_IMPLEMENTATION.md]\]:

> Oneiric relies on deterministic resolver registries and lifecycle managers instead of a general-purpose DI container. **Advantages:**
>
> - **Deterministic selection**: candidates declare domain, key, provider, priority, and stack level; the resolver can explain why a provider was selected, which is harder with opaque DI wiring.
> - **Hot swap support**: lifecycle orchestration (init → health → bind → cleanup) can swap providers at runtime; DI containers typically assume static wiring.
> - **Better observability**: registrations, selections, and swaps emit structured events with full metadata; DI usually hides instantiation details.
> - **Reduced coupling**: modules register themselves with metadata rather than importing container bindings everywhere; this isolates adapter code from framework plumbing.
> - **Async-first lifecycle**: resolver + lifecycle manage async init/health/cleanup which many DI frameworks treat as afterthoughts.

**Performance note:** Registry resolution is ~2-5x slower than DI hash lookups (~0.7µs vs ~0.3µs per lookup), but this difference is **completely irrelevant** in practice (\<0.004% of request time for typical web apps).

______________________________________________________________________

## Installation

```bash
# Base install (resolver + runtime)
uv add oneiric

# Common adapter bundles (cache/db/storage)
uv add oneiric[cache,database,storage]

# Add optional providers (HTTP + observability, etc.)
uv add oneiric[http-aiohttp,monitoring]

# Development install
git clone https://github.com/lesleslie/oneiric
cd oneiric
uv sync --group dev
```

______________________________________________________________________

## Configuration

### Settings Structure

```
settings/
├── app.yml         # Application metadata (optional)
├── adapters.yml    # Adapter selections: {category: provider}
├── services.yml    # Service selections: {service_id: provider}
├── tasks.yml       # Task selections: {task_type: provider}
├── events.yml      # Event selections: {event_name: provider}
└── workflows.yml   # Workflow selections: {workflow_id: provider}
```

### Example: `adapters.yml`

```yaml
selections:
  cache: redis
  database: postgres
  storage: gcs
  secrets: gcp-secret-manager
  monitoring: logfire

provider_settings:
  redis:
    url: redis://localhost:6379/0
    key_prefix: "oneiric:"
    enable_client_cache: true

  postgres:
    host: localhost
    port: 5432
    database: oneiric
    user: oneiric
    password: ${ONEIRIC_SECRET_DB_PASSWORD}
    max_size: 10

  gcs:
    bucket: oneiric-storage
    project: my-gcp-project

  logfire:
    service_name: oneiric-production
    token: ${ONEIRIC_SECRET_LOGFIRE_TOKEN}
```

### Environment Variables

- `ONEIRIC_CONFIG` - Path to config directory
- `ONEIRIC_STACK_ORDER` - Stack priority override (e.g., `sites:100,splashstand:50,oneiric:10`)
- `ONEIRIC_SECRET_*` - Secrets (when using env secrets adapter)

______________________________________________________________________

## CLI Commands

```bash
# List components
uv run python -m oneiric.cli --demo list --domain adapter
uv run python -m oneiric.cli --demo list --domain action

# Explain selection
uv run python -m oneiric.cli --demo explain status --domain service

# Check status
uv run python -m oneiric.cli --demo status --domain adapter --key cache
uv run python -m oneiric.cli health --probe

# Invoke actions
uv run python -m oneiric.cli --demo action-invoke compression.encode \
    --payload '{"text":"hello"}' --json

# Emit manifest-driven events
uv run python -m oneiric.cli --demo event emit cli.event \
    --payload '{"text":"cli"}'

# Execute workflow DAGs
uv run python -m oneiric.cli --demo workflow run demo-workflow --json

# Queue workflow runs via configured adapter
uv run python -m oneiric.cli --demo workflow enqueue demo-workflow --json

# Remote manifest sync
uv run python -m oneiric.cli remote-sync \
    --manifest docs/sample_remote_manifest.yaml

uv run python -m oneiric.cli remote-sync \
    --manifest https://cdn.example.com/v1.yaml \
    --watch --refresh-interval 60

uv run python -m oneiric.cli remote-status

# Runtime orchestrator (long-running)
uv run python -m oneiric.cli orchestrate \
    --manifest docs/sample_remote_manifest.yaml \
    --refresh-interval 120

# Override/disable workflow checkpoints for orchestrator runs
uv run python -m oneiric.cli orchestrate --workflow-checkpoints /tmp/my-checkpoints.sqlite
uv run python -m oneiric.cli orchestrate --no-workflow-checkpoints

# Activity controls
uv run python -m oneiric.cli pause --domain service status --note "maintenance window"
uv run python -m oneiric.cli drain --domain service status --note "draining queue"
uv run python -m oneiric.cli pause --resume --domain service status

# Shell completions
uv run python -m oneiric.cli --install-completion
```

______________________________________________________________________

## Usage Patterns

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

______________________________________________________________________

## Security Hardening ✅ COMPLETE

**All P0 security vulnerabilities have been resolved** (see \[[STAGE5_FINAL_AUDIT_REPORT|STAGE5_FINAL_AUDIT_REPORT.md]\]):

1. ✅ **Arbitrary code execution** - Factory allowlist implemented
1. ✅ **Missing signature verification** - ED25519 signing enforced
1. ✅ **Path traversal** - Path sanitization + boundary enforcement
1. ✅ **No HTTP timeouts** - Configurable timeouts + circuit breaker
1. ✅ **Thread safety** - RLock added to resolver registry

**Security Test Coverage:** 100 tests (99 passing, 1 edge case)

______________________________________________________________________

## Testing

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=oneiric --cov-report=term

# Security tests
uv run pytest tests/security/ -v
```

**Test Statistics:**

- Total: 546 tests (526 passing, 18 failing, 2 skipped)
- Coverage: 83% (target: 60%)
- Pass Rate: 96.3%

______________________________________________________________________

## Quality Control

This project uses [Crackerjack](https://github.com/lesleslie/crackerjack) for quality control:

```bash
# Full quality suite
python -m crackerjack

# With tests
python -m crackerjack -t

# Full automation (format, lint, test, bump, commit)
python -m crackerjack -a patch
```

______________________________________________________________________

## Documentation

**Essential Reading:**

- **\[[ONEIRIC_VS_ACB|ONEIRIC_VS_ACB.md]\]** - Complete comparison, migration guide, hybrid strategy ⭐
- **\[[UNCOMPLETED_TASKS|UNCOMPLETED_TASKS.md]\]** - Future work, known issues (zero blockers)
- **\[[STAGE5_FINAL_AUDIT_REPORT|STAGE5_FINAL_AUDIT_REPORT.md]\]** - Production audit (95/100) ⭐

**Architecture & Design:**

- \[[NEW_ARCH_SPEC|Architecture Specification]\] - Core system design
- \[[RESOLUTION_LAYER_SPEC|Resolution Layer]\] - Detailed resolution design
- \[[REBUILD_VS_REFACTOR|Design Rationale]\] - Why we rebuilt

**Implementation & Status:**

- \[[STRATEGIC_ROADMAP|Strategic Roadmap]\] - Vision + execution tracks
- \[[SERVERLESS_AND_PARITY_EXECUTION_PLAN|Serverless & Parity Plan]\] - Cloud Run + parity workstreams
- \[[ORCHESTRATION_PARITY_PLAN|Orchestration Parity Plan]\] - Events, DAGs, supervisors
- \[[ADAPTER_REMEDIATION_PLAN|Adapter Remediation Plan]\] - Remaining adapter/extra work
- \[[MESSAGING_AND_SCHEDULER_ADAPTER_PLAN|Messaging & Scheduler Adapter Plan]\] - SendGrid/Mailgun/Twilio + Cloud Tasks/Pub/Sub delivery
- \[[BUILD_PROGRESS|Build Progress (Archive)]\] - Historical phase log
- \[[ACB_ADAPTER_ACTION_IMPLEMENTATION|ACB Migration]\] - Adapter porting guide

**Operations:**

- [Deployment Guides](docs/deployment/) - Docker, Kubernetes, systemd (2,514 lines)
- Cloud Run / buildpack deployment is the default target: ship the new `Procfile`, prefer `pack build` or `gcloud run deploy --source .`, and keep Docker images optional.
- Docker/Kubernetes docs in `docs/deployment/` are now marked as legacy references; new services should follow `docs/deployment/CLOUD_RUN_BUILD.md`.
- [Monitoring Setup](docs/monitoring/) - Prometheus, Grafana, Loki, Alerts (3,336 lines)
- [Runbooks](docs/runbooks/) - Incident response, troubleshooting (3,232 lines)

**Complete Index:** See \[[docs/README|docs/README.md]\] for full documentation structure

______________________________________________________________________

## Design Principles

1. **Single Responsibility** - Oneiric only does resolution + lifecycle + remote loading
1. **Domain Agnostic** - Same semantics work for any pluggable domain
1. **Explicit Over Implicit** - Stack levels, priorities, and selection are transparent
1. **Explain Everything** - Every resolution has a traceable decision path
1. **Hot-Swap First** - Runtime changes without restarts
1. **Remote Native** - Built for distributed component delivery
1. **Type Safe** - Full Pydantic + type hints throughout
1. **Async First** - All I/O is async, structured concurrency ready

______________________________________________________________________

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
```

______________________________________________________________________

## Use Cases

### 1. Multi-Tenant SaaS

Different components per tenant:

```python
# Tenant A gets Redis, Tenant B gets Memcached
cache_a = await resolver.resolve("adapter", "cache", tenant="tenant_a")
cache_b = await resolver.resolve("adapter", "cache", tenant="tenant_b")
```

### 2. Plugin Marketplaces

Remote component delivery with signatures:

```python
# Fetch signed manifest from CDN
await remote_loader.sync(
    manifest_url="https://cdn.example.com/plugins/v1.yaml", verify_signature=True
)

# Components automatically registered
plugin = await resolver.resolve("adapter", "custom-plugin")
```

### 3. Hot-Swapping in Production

Change implementations without downtime:

```python
# Swap database from PostgreSQL to MySQL
await lifecycle.swap("adapter", "database", provider="mysql")
# Old connections drained, new pool initialized, health checked
```

### 4. Explainable Component Selection

Debug why components were selected:

```python
explanation = resolver.explain("adapter", "cache")
print(f"Selected: {explanation.selected}")
print(f"Reasons: {explanation.reasons}")
print(f"Shadowed: {explanation.shadowed}")
```

______________________________________________________________________

## Performance

Registry resolution is **2-5x slower** than DI hash lookups (~0.7µs vs ~0.3µs per lookup).

**Is this relevant?** No. For a typical web application:

- Component resolution: 0.007ms (Oneiric) vs 0.003ms (DI)
- Network I/O: 10-50ms
- Database query: 5-30ms

**Difference: 0.004ms** (0.004% of request time)

See \[[PERFORMANCE_ANALYSIS|PERFORMANCE_ANALYSIS.md]\] for detailed benchmarks (archived - see ONEIRIC_VS_ACB.md for updated analysis).

______________________________________________________________________

## Future Enhancements

- Plugin protocol with entry points ✅ (Complete)
- Capability negotiation (select by features + priority)
- Middleware/pipeline adapters
- Structured concurrency helpers (nursery patterns)
- Durable execution hooks for workflows
- Rate limiting & circuit breaker mixins
- State machine DSL for workflows

______________________________________________________________________

## Projects Using Oneiric

**Planned migrations:**

- [Crackerjack](https://github.com/lesleslie/crackerjack) - Quality control framework
- [FastBlocks](https://github.com/lesleslie/fastblocks) - HTMX web framework
- [Session Management MCP](https://github.com/lesleslie/session-mgmt-mcp) - MCP server

______________________________________________________________________

## Contributing

Contributions welcome! Please:

1. Follow [ACB + Crackerjack guidelines](https://github.com/lesleslie/acb)
1. Run quality gates: `python -m crackerjack -t`
1. Update docs and tests
1. Follow the resolver/lifecycle architecture

______________________________________________________________________

## License

MIT License - see [LICENSE](LICENSE) file.

______________________________________________________________________

## Acknowledgements

Oneiric builds on patterns from:

- [ACB](https://github.com/lesleslie/acb) - Component base platform
- [Crackerjack](https://github.com/lesleslie/crackerjack) - Quality control
- [FastBlocks](https://github.com/lesleslie/fastblocks) - Web framework

______________________________________________________________________

## Support

- GitHub Issues: https://github.com/lesleslie/oneiric/issues
- Documentation: [docs/](docs/)
- Audit Report: \[[STAGE5_FINAL_AUDIT_REPORT|STAGE5_FINAL_AUDIT_REPORT.md]\]
