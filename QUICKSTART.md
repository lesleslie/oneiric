# Oneiric Quickstart (5 minutes)

Oneiric is the configuration management and component resolution system for the ecosystem. It provides explainable component resolution, lifecycle management, and remote delivery for Python 3.13+ runtimes.

## Level 1: Basic Configuration (1 minute) ✅

```bash
# Install Oneiric
pip install oneiric

# Or with uv (recommended)
uv add oneiric

# Initialize configuration
oneiric init

# Load configuration
oneiric load config.yaml

# Resolve components
oneiric resolve

# List available components
oneiric list --domain adapter
oneiric list --domain service
```

**What you learned**: Basic installation, configuration loading, and component listing.

______________________________________________________________________

## Level 2: Adapter Lifecycle (2 minutes) 🔧

```bash
# List available adapters
oneiric list --domain adapter --shadowed

# Install adapter from local registry
oneiric activate adapter postgresql --provider pgvector

# Check adapter status
oneiric status --domain adapter --key postgresql

# Explain resolution (why this adapter was chosen)
oneiric explain adapter --key postgresql

# Swap to different adapter
oneiric swap adapter postgresql --provider sqlite

# Pause adapter (stop accepting work)
oneiric pause adapter postgresql --note "Upgrading database"

# Resume adapter
oneiric resume adapter postgresql

# Drain adapter (graceful shutdown)
oneiric drain adapter postgresql --note "Maintenance window"
```

**What you learned**: Adapter activation, resolution explanation, lifecycle management (pause/resume/drain).

______________________________________________________________________

## Level 3: Advanced Resolution (2 minutes) 🎯

```bash
# Enable remote resolution
oneiric enable-remote --url http://localhost:8683/mcp

# Sync from remote manifest
oneiric remote-sync --manifest docs/sample_remote_manifest.yaml

# Resolve with dependencies
oneiric resolve --with-dependencies

# Export resolved configuration
oneiric export --output resolved.yaml

# Inspect workflow DAG plan
oneiric workflow plan \
  --workflow fastblocks.workflows.fulfillment \
  --json

# Run workflow once
oneiric workflow run \
  --workflow fastblocks.workflows.fulfillment \
  --context '{"order_id":"demo-123"}' \
  --json

# Emit events (with fan-out and filters)
oneiric event emit \
  --topic fastblocks.order.created \
  --payload '{"order_id":"demo-123","region":"us"}' \
  --json
```

**What you learned**: Remote resolution, dependency management, workflow execution, event dispatch.

______________________________________________________________________

## Operational Modes

Oneiric supports two operational modes:

### Lite Mode (Development)

**Setup Time**: < 2 minutes

```bash
export ONEIRIC_MODE=lite
oneiric start
```

**Features**:

- Local configuration only
- File-based persistence
- No remote resolution
- Perfect for development and testing

### Standard Mode (Production)

**Setup Time**: ~ 5 minutes

```bash
export ONEIRIC_MODE=standard
oneiric start --remote-url http://dhruva:8683/mcp
```

**Features**:

- Remote resolution enabled
- Distributed configuration
- Adapter distribution via Dhruva
- Cloud backup support
- Production-ready scaling

______________________________________________________________________

## Service Dependencies

### Required Services

- **None** - Oneiric is fully standalone and can operate without any external services

### Optional Integrations

**Mahavishnu (Orchestrator)**

- **Purpose**: Component resolution for workflows
- **Protocol**: MCP
- **URL**: http://localhost:8680/mcp

**Dhruva (Curator)**

- **Purpose**: Adapter distribution and remote manifests
- **Protocol**: MCP
- **URL**: http://localhost:8683/mcp

**Cloud Storage**

- **Purpose**: Remote configuration backup
- **Providers**: AWS S3, Azure Blob, GCS
- **Required**: Optional

______________________________________________________________________

## Quick Reference

### Domain Management

| Domain | Purpose | Example |
|--------|---------|---------|
| **Adapters** | External integrations (DBs, queues, APIs) | `oneiric list --domain adapter` |
| **Services** | Business services with lifecycle | `oneiric list --domain service` |
| **Tasks** | Async job runners | `oneiric list --domain task` |
| **Events** | Event dispatcher with filters | `oneiric list --domain event` |
| **Workflows** | DAG execution and orchestration | `oneiric list --domain workflow` |
| **Actions** | Reusable action kits | `oneiric list --domain action` |

### Lifecycle States

| State | Meaning | Command |
|-------|---------|---------|
| **Active** | Normal operation | `oneiric resume <domain> <key>` |
| **Paused** | Not accepting new work | `oneiric pause <domain> <key>` |
| **Draining** | Graceful shutdown | `oneiric drain <domain> <key>` |

### Observability

```bash
# Health check
oneiric health --probe --json

# Runtime status
oneiric status --json

# Activity log
oneiric activity --domain adapter --json

# Remote sync status
oneiric remote-status --json
```

______________________________________________________________________

## Next Steps

### Documentation

- [Configuration Reference](docs/reference/config.md) - Complete configuration options
- [Adapter Guide](docs/guides/adapters.md) - Creating and using adapters
- [MCP Integration](docs/integration/mcp.md) - MCP server setup
- [Service Dependencies](docs/reference/service-dependencies.md) - Ecosystem integration
- [Operational Modes](docs/guides/operational-modes.md) - Mode comparison and setup

### Examples

- [Local CLI Demo](docs/examples/LOCAL_CLI_DEMO.md) - Interactive examples
- [FastBlocks Parity](docs/examples/FASTBLOCKS_PARITY_FIXTURE.yaml) - Production fixture
- [Observability Guide](docs/OBSERVABILITY_GUIDE.md) - Monitoring and telemetry

### Advanced Features

- [Remote Manifests](docs/REMOTE_MANIFEST_SCHEMA.md) - Signed remote delivery
- [Event System](docs/CLI_REFERENCE.md#events) - Event dispatch and fan-out
- [Workflow Orchestration](docs/CLI_REFERENCE.md#workflows) - DAG execution
- [Admin Shell](docs/ONEIRIC_ADMIN_SHELL.md) - Interactive debugging

______________________________________________________________________

## Troubleshooting

### "Cannot resolve adapter"

```bash
# Check adapter registry
oneiric list --domain adapter --shadowed

# Enable remote resolution
oneiric enable-remote --url http://localhost:8683/mcp

# Verify Dhruva connection
oneiric health --probe
```

### "Remote sync failed"

```bash
# Check manifest URL
oneiric remote-sync --manifest /path/to/manifest.yaml --verify-only

# Verify signature
oneiric manifest verify --input manifest.json

# Check remote status
oneiric remote-status --json
```

### "Component not responding"

```bash
# Check activity state
oneiric activity --domain adapter --key postgresql

# Force resume
oneiric resume adapter postgresql

# Check health
oneiric health --probe --json
```

______________________________________________________________________

## Ecosystem Role

Oneiric is the **Resolver** in the ecosystem architecture:

- **Resolves**: Components, dependencies, and lifecycle management
- **Activates**: Adapters, services, and tasks
- **Swaps**: Hot-swappable providers with zero downtime
- **Explains**: Full resolution transparency with decision tracking
- **Orchestrates**: Workflow DAGs and event dispatch

**Role Taxonomy**: `resolver` - Manages configuration, components, and lifecycle

______________________________________________________________________

## Getting Help

- **Documentation**: Start with [docs/README.md](docs/README.md)
- **Issues**: https://github.com/lesleslie/oneiric/issues
- **Audit Report**: [docs/implementation/STAGE5_FINAL_AUDIT_REPORT.md](docs/implementation/STAGE5_FINAL_AUDIT_REPORT.md)
- **Migration Guide**: [docs/ONEIRIC_VS_ACB.md](docs/ONEIRIC_VS_ACB.md) - migrating from ACB

______________________________________________________________________

**Production Ready**: Oneiric is production-ready with 79.4% coverage, comprehensive testing, and zero critical issues. See the [Stage 5 Audit Report](docs/implementation/STAGE5_FINAL_AUDIT_REPORT.md) for complete metrics.
